"""
ClaudeCodeRunner - Claude Code CLI 실행

Claude Agent SDK를 사용하여 Claude Code를 실행하고 결과를 스트리밍합니다.
"""

import os
import re
import asyncio
import logging
from pathlib import Path
from typing import Optional, AsyncIterator, Callable, Awaitable, List
from dataclasses import dataclass

try:
    from claude_agent_sdk import (
        ClaudeSDKClient,
        ClaudeAgentOptions,
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
        SystemMessage,
        ProcessError,
        CLINotFoundError,
    )
    from claude_agent_sdk.types import (
        HookMatcher,
        HookInput,
        HookContext,
        HookJSONOutput,
        SyncHookJSONOutput,
    )
    SDK_AVAILABLE = True
except ImportError:
    SDK_AVAILABLE = False
    # 테스트용 더미 클래스
    class ClaudeSDKClient:
        pass
    class ClaudeAgentOptions:
        pass
    class HookMatcher:
        pass
    class SystemMessage:
        pass

from src.models import (
    ProgressEvent,
    MemoryEvent,
    InterventionSentEvent,
    CompleteEvent,
    ErrorEvent,
    ContextUsageEvent,
    CompactEvent,
)
from src.service.resource_manager import resource_manager


# 세션 검증 관련 상수
SESSION_NOT_FOUND_CODE = "SESSION_NOT_FOUND"

logger = logging.getLogger(__name__)


# === 설정 ===
ALLOWED_TOOLS = ["Read", "Glob", "Grep", "Task", "WebFetch", "WebSearch", "Edit", "Write", "Bash"]
DISALLOWED_TOOLS = ["NotebookEdit", "TodoWrite"]
EXECUTION_TIMEOUT = 600  # 10분
STREAM_UPDATE_INTERVAL = 2.0  # 초
MEMORY_REPORT_INTERVAL = 10.0  # 초
MAX_ATTACHMENT_SIZE = 8 * 1024 * 1024  # 8MB
DANGEROUS_EXTENSIONS = ['.env', '.pem', '.key', '.crt', '.p12', '.pfx']

# 컨텍스트 관련 상수
DEFAULT_MAX_CONTEXT_TOKENS = 200000  # 기본 컨텍스트 윈도우 크기


@dataclass
class InterventionMessage:
    """개입 메시지 데이터"""
    text: str
    user: str
    attachment_paths: List[str]


class ClaudeCodeRunner:
    """
    Claude Code CLI 실행기

    역할:
    1. Claude Agent SDK를 사용하여 Claude Code 실행
    2. 진행 상황을 SSE 이벤트로 변환
    3. 출력 필터링 (비밀 마스킹)
    4. 첨부 파일 추출
    """

    def __init__(self, workspace_dir: Optional[str] = None):
        """
        Args:
            workspace_dir: Claude Code 작업 디렉토리
        """
        self._workspace_dir = workspace_dir or os.getenv(
            "WORKSPACE_DIR", "/workspace"
        )

    def _sanitize_output(self, text: str) -> str:
        """출력에서 민감 정보 마스킹"""
        patterns = [
            (r'sk-[a-zA-Z0-9-_]{20,}', 'sk-***REDACTED***'),
            (r'sk-ant-[a-zA-Z0-9-_]+', 'sk-ant-***REDACTED***'),
            (r'ghp_[a-zA-Z0-9]{30,}', 'ghp_***REDACTED***'),
            (r'gho_[a-zA-Z0-9]{30,}', 'gho_***REDACTED***'),
            (r'github_pat_[a-zA-Z0-9_]{20,}', 'github_pat_***REDACTED***'),
            (r'xoxb-[a-zA-Z0-9-]+', 'xoxb-***REDACTED***'),
            (r'xoxp-[a-zA-Z0-9-]+', 'xoxp-***REDACTED***'),
            (r'DISCORD_[A-Z_]*=\S+', 'DISCORD_***=REDACTED'),
            (r'[a-zA-Z_]*PASSWORD[a-zA-Z_]*=\S+', '***PASSWORD***=REDACTED'),
            (r'[a-zA-Z_]*SECRET[a-zA-Z_]*=\S+', '***SECRET***=REDACTED'),
            (r'[a-zA-Z_]*TOKEN[a-zA-Z_]*=\S+', '***TOKEN***=REDACTED'),
            (r'[a-zA-Z_]*KEY[a-zA-Z_]*=\S+', '***KEY***=REDACTED'),
        ]

        result = text
        for pattern, replacement in patterns:
            result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)

        return result

    def _extract_attachments(self, text: str) -> tuple[str, list[str]]:
        """출력에서 [ATTACH:path] 패턴 추출"""
        pattern = r'\[ATTACH:([^\]]+)\]'
        attachments = []

        for match in re.finditer(pattern, text):
            path = match.group(1).strip()
            if self._is_safe_attachment_path(path):
                attachments.append(path)

        cleaned = re.sub(pattern, '', text).strip()
        return cleaned, attachments

    def _is_safe_attachment_path(self, path: str) -> bool:
        """첨부 파일 경로 보안 검증"""
        try:
            resolved = Path(path).resolve()
            resolved_str = str(resolved)

            # 허용된 디렉토리
            allowed = False
            if resolved_str.startswith(self._workspace_dir):
                allowed = True
            if resolved_str.startswith('/tmp/claude-code-'):
                allowed = True

            if not allowed:
                return False

            if resolved.suffix.lower() in DANGEROUS_EXTENSIONS:
                return False

            if not resolved.exists():
                return False

            if resolved.is_dir():
                return False

            if resolved.stat().st_size > MAX_ATTACHMENT_SIZE:
                return False

            return True

        except Exception:
            return False

    def _find_session_file(self, session_id: str) -> Optional[Path]:
        """
        세션 파일을 찾습니다.

        세션 파일은 ~/.claude/projects/{project-path}/{session-id}.jsonl 형식으로 저장됩니다.
        여러 프로젝트 경로에서 검색합니다.

        Args:
            session_id: 세션 ID (UUID 형식)

        Returns:
            세션 파일 경로 또는 None
        """
        claude_dir = Path.home() / ".claude" / "projects"
        if not claude_dir.exists():
            return None

        # 모든 프로젝트 폴더에서 세션 파일 검색
        session_file_name = f"{session_id}.jsonl"
        for project_dir in claude_dir.iterdir():
            if project_dir.is_dir():
                session_file = project_dir / session_file_name
                if session_file.exists():
                    return session_file

        return None

    def _validate_session(self, session_id: str) -> Optional[str]:
        """
        세션 ID가 유효한지 검증합니다.

        Args:
            session_id: 세션 ID

        Returns:
            에러 메시지 (유효하면 None)
        """
        # 기본 형식 검증 (UUID 형식)
        import re
        uuid_pattern = re.compile(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            re.IGNORECASE
        )

        if not uuid_pattern.match(session_id):
            return f"유효하지 않은 세션 ID 형식입니다: {session_id}"

        # 세션 파일 존재 확인
        session_file = self._find_session_file(session_id)
        if session_file is None:
            return f"세션을 찾을 수 없습니다: {session_id}"

        return None

    def _create_options(self, resume_session_id: Optional[str] = None) -> "ClaudeAgentOptions":
        """ClaudeAgentOptions 생성"""
        if not SDK_AVAILABLE:
            raise RuntimeError("Claude Agent SDK not available")

        # 환경변수 설정 (민감 정보 및 서비스 전용 설정 제외)
        env = os.environ.copy()
        keys_to_remove = [
            'OPENAI_API_KEY', 'DISCORD_BOT_TOKEN', 'GH_TOKEN',
            'ROAM_PASSWORD', 'GOOGLE_API_KEY', 'CLAUDE_SERVICE_TOKEN',
            'DISCORD_WEBHOOK_URL',  # 개발 환경에서 프로덕션 웹훅 알림 방지
        ]
        for key in keys_to_remove:
            env.pop(key, None)

        options = ClaudeAgentOptions(
            allowed_tools=ALLOWED_TOOLS,
            disallowed_tools=DISALLOWED_TOOLS,
            permission_mode='bypassPermissions',
            cwd=self._workspace_dir,
            env=env,
            setting_sources=['project'],  # CLAUDE.md 로드
        )

        if resume_session_id:
            options.resume = resume_session_id

        return options

    def _build_intervention_prompt(self, msg: InterventionMessage) -> str:
        """개입 메시지를 Claude 프롬프트로 변환"""
        if msg.attachment_paths:
            attachment_info = "\n".join([f"- {p}" for p in msg.attachment_paths])
            return f"""[사용자 개입 메시지 from {msg.user}]
{msg.text}

첨부 파일 (Read 도구로 확인):
{attachment_info}"""
        else:
            return f"""[사용자 개입 메시지 from {msg.user}]
{msg.text}"""

    def _extract_context_usage(self, usage: Optional[dict]) -> Optional[ContextUsageEvent]:
        """
        ResultMessage.usage에서 컨텍스트 사용량 추출

        Claude Agent SDK의 usage 딕셔너리는 세션 전체의 누적 토큰을 포함할 수 있음.
        따라서 마지막 요청의 토큰만 추출하여 표시.

        Args:
            usage: ResultMessage.usage 딕셔너리

        Returns:
            ContextUsageEvent 또는 None
        """
        if not usage:
            return None

        # 디버그: 실제 usage 필드 구조 로깅
        logger.debug(f"Usage dict keys: {list(usage.keys())}")
        logger.debug(f"Usage dict: {usage}")

        # 입력 토큰 수 추출
        # Anthropic API usage 구조: input_tokens, output_tokens, cache_creation_input_tokens, cache_read_input_tokens
        input_tokens = usage.get("input_tokens", 0)

        # 캐시 토큰은 input_tokens에 포함되지 않으므로 별도 합산하지 않음
        # input_tokens가 이미 실제 "새로 처리된" 토큰 수임
        # cache_read_input_tokens는 캐시에서 읽은 토큰 (이미 처리됨)
        # cache_creation_input_tokens는 캐시 생성에 사용된 토큰

        # 현재 컨텍스트 사용량 = input_tokens (마지막 요청)
        # 컨텍스트 윈도우 제한에 대한 비율을 계산하려면 전체 대화의 토큰이 필요
        # SDK의 usage는 단일 요청의 usage일 수 있음

        if input_tokens <= 0:
            return None

        # 모델별 컨텍스트 윈도우 크기 (Claude 3.5/4 Sonnet은 200k)
        max_tokens = DEFAULT_MAX_CONTEXT_TOKENS

        # 사용 퍼센트 계산
        percent = (input_tokens / max_tokens) * 100 if max_tokens > 0 else 0

        logger.info(
            f"Context usage calculation: input_tokens={input_tokens}, "
            f"max_tokens={max_tokens}, percent={percent:.1f}%"
        )

        return ContextUsageEvent(
            used_tokens=input_tokens,
            max_tokens=max_tokens,
            percent=round(percent, 1)
        )

    async def execute(
        self,
        prompt: str,
        resume_session_id: Optional[str] = None,
        get_intervention: Optional[Callable[[], Awaitable[Optional[dict]]]] = None,
        on_intervention_sent: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> AsyncIterator:
        """
        Claude Code 실행 (SSE 이벤트 스트림)

        Args:
            prompt: 사용자 프롬프트
            resume_session_id: 이전 세션 ID
            get_intervention: 개입 메시지 가져오기 함수
            on_intervention_sent: 개입 메시지 전송 후 콜백

        Yields:
            ProgressEvent | MemoryEvent | InterventionSentEvent | ContextUsageEvent | CompleteEvent | ErrorEvent
        """
        if not SDK_AVAILABLE:
            yield ErrorEvent(message="Claude Agent SDK not available")
            return

        # 세션 ID 검증 (resume 시)
        if resume_session_id:
            validation_error = self._validate_session(resume_session_id)
            if validation_error:
                yield ErrorEvent(
                    message=validation_error,
                    error_code=SESSION_NOT_FOUND_CODE
                )
                return

        options = self._create_options(resume_session_id)

        accumulated_text = ""
        current_text = ""
        session_id = None
        context_usage_event = None
        compact_events = []  # 컴팩트 이벤트 저장
        last_update_time = asyncio.get_event_loop().time()
        memory_reported_since_progress = False

        try:
            async with ClaudeSDKClient(options=options) as client:
                # 쿼리 시작
                await client.query(prompt)

                # 응답 수신 및 스트리밍
                async for message in client.receive_messages():
                    # AssistantMessage에서 텍스트 추출
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                current_text = block.text
                            elif isinstance(block, ToolUseBlock):
                                logger.debug(f"Tool use: {block.name}")

                    # SystemMessage 처리 (컴팩트 이벤트 감지)
                    elif isinstance(message, SystemMessage):
                        logger.debug(f"SystemMessage: subtype={message.subtype}, data={message.data}")

                        # 컴팩트 관련 시스템 메시지 감지
                        if message.subtype == "compact" or "compact" in str(message.data).lower():
                            trigger = message.data.get("trigger", "auto")
                            compact_events.append(CompactEvent(
                                trigger=trigger,
                                message=f"컨텍스트 컴팩트 실행됨 (트리거: {trigger})"
                            ))
                            logger.info(f"Compact detected: trigger={trigger}")

                    # ResultMessage에서 세션 ID와 최종 결과 추출
                    elif isinstance(message, ResultMessage):
                        session_id = message.session_id
                        if message.result:
                            accumulated_text = message.result

                        # 컨텍스트 사용량 추출
                        context_usage_event = self._extract_context_usage(message.usage)
                        if context_usage_event:
                            logger.info(
                                f"Context usage: {context_usage_event.used_tokens}/{context_usage_event.max_tokens} "
                                f"({context_usage_event.percent}%)"
                            )
                        break

                    # 진행 상황 업데이트
                    current_time = asyncio.get_event_loop().time()
                    if current_time - last_update_time >= STREAM_UPDATE_INTERVAL:
                        display_text = current_text or accumulated_text
                        if display_text:
                            sanitized = self._sanitize_output(display_text)
                            yield ProgressEvent(text=sanitized)
                            last_update_time = current_time
                            memory_reported_since_progress = False

                    # 메모리 리포트
                    if not memory_reported_since_progress:
                        if current_time - last_update_time >= MEMORY_REPORT_INTERVAL:
                            used_gb, total_gb, percent = resource_manager.get_system_memory()
                            if total_gb > 0:
                                yield MemoryEvent(
                                    used_gb=used_gb,
                                    total_gb=total_gb,
                                    percent=percent
                                )
                            memory_reported_since_progress = True

                    # 개입 메시지 확인
                    if get_intervention:
                        intervention = await get_intervention()
                        if intervention:
                            msg = InterventionMessage(
                                text=intervention.get("text", ""),
                                user=intervention.get("user", ""),
                                attachment_paths=intervention.get("attachment_paths", [])
                            )
                            intervention_prompt = self._build_intervention_prompt(msg)
                            logger.info(f"[Intervention] Sending: {intervention_prompt[:100]}...")
                            await client.query(intervention_prompt)

                            if on_intervention_sent:
                                await on_intervention_sent(msg.user, msg.text)

                            yield InterventionSentEvent(
                                user=msg.user,
                                text=msg.text
                            )

            # 컴팩트 이벤트 전송 (먼저)
            for compact_event in compact_events:
                yield compact_event

            # 컨텍스트 사용량 이벤트 전송 (결과 전에)
            if context_usage_event:
                yield context_usage_event

            # 최종 결과
            final_text = accumulated_text or current_text
            if not final_text:
                final_text = "(결과 없음)"

            # 출력 필터링 및 첨부 파일 추출
            final_text = self._sanitize_output(final_text)
            final_text, attachments = self._extract_attachments(final_text)

            yield CompleteEvent(
                result=final_text,
                attachments=attachments,
                claude_session_id=session_id
            )

        except asyncio.TimeoutError:
            yield ErrorEvent(message=f"실행 시간 초과 ({EXECUTION_TIMEOUT}초)")

        except CLINotFoundError:
            yield ErrorEvent(message="Claude Code CLI가 설치되지 않았습니다")

        except ProcessError as e:
            yield ErrorEvent(message=f"실행 오류: {str(e)}")

        except Exception as e:
            logger.exception(f"Claude Code execution error: {e}")
            yield ErrorEvent(message=f"실행 오류: {str(e)}")

    async def generate_title(
        self,
        resume_session_id: str,
        timeout: int = 30
    ) -> Optional[str]:
        """
        세션 제목 생성

        Args:
            resume_session_id: 세션 ID
            timeout: 타임아웃 (초)

        Returns:
            생성된 제목 또는 None
        """
        if not SDK_AVAILABLE:
            return None

        from claude_agent_sdk import query

        prompt = (
            "이 세션에서 실제로 수행한 작업(코드 변경, 버그 수정, 기능 추가 등)을 "
            "50자 이내의 한글로 요약해서 제목을 붙여주세요. "
            "예: 'Discord 봇 에러 핸들링 개선', 'pytest 테스트 추가'. "
            "'세션 종료'나 '마무리' 같은 일반적인 제목은 피하세요. "
            "제목만 출력하세요. 따옴표 없이."
        )

        options = ClaudeAgentOptions(
            resume=resume_session_id,
            permission_mode='bypassPermissions',
            cwd=self._workspace_dir,
        )

        try:
            result_text = ""

            async def collect_result():
                nonlocal result_text
                async for message in query(prompt=prompt, options=options):
                    if isinstance(message, AssistantMessage):
                        for block in message.content:
                            if isinstance(block, TextBlock):
                                result_text = block.text
                    elif isinstance(message, ResultMessage):
                        if message.result:
                            result_text = message.result
                        break

            await asyncio.wait_for(collect_result(), timeout=timeout)

            if result_text:
                title = result_text.strip().split('\n')[0].strip()
                title = title.strip('"\'')
                return title[:50] if title else None

            return None

        except asyncio.TimeoutError:
            logger.warning(f"Title generation timeout for session {resume_session_id}")
            return None
        except Exception as e:
            logger.warning(f"Title generation error: {e}")
            return None


# 싱글톤 인스턴스
claude_runner = ClaudeCodeRunner()
