"""
TaskManager - 태스크 라이프사이클 관리

태스크 기반 아키텍처의 핵심 컴포넌트.
클라이언트(dorothy_bot 등)의 실행 요청을 태스크로 관리하고,
결과를 영속화하여 클라이언트 재시작 시에도 복구 가능하게 합니다.
"""

import asyncio
import json
import logging
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field
from enum import Enum

from src.service.discord_notifier import discord_notifier

logger = logging.getLogger(__name__)


class TaskStatus(str, Enum):
    """태스크 상태"""
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"


class TaskConflictError(Exception):
    """태스크 충돌 오류 (같은 키로 running 태스크 존재)"""
    pass


class TaskNotFoundError(Exception):
    """태스크 없음 오류"""
    pass


class TaskNotRunningError(Exception):
    """태스크가 running 상태가 아님"""
    pass


def utc_now() -> datetime:
    """현재 UTC 시간 반환"""
    return datetime.now(timezone.utc)


def datetime_to_str(dt: datetime) -> str:
    """datetime을 ISO 문자열로 변환"""
    return dt.isoformat()


def str_to_datetime(s: str) -> datetime:
    """ISO 문자열을 datetime으로 변환"""
    return datetime.fromisoformat(s)


@dataclass
class Task:
    """태스크 데이터"""
    client_id: str
    request_id: str
    prompt: str
    status: TaskStatus = TaskStatus.RUNNING

    # Claude Code 관련
    resume_session_id: Optional[str] = None
    claude_session_id: Optional[str] = None

    # 결과
    result: Optional[str] = None
    error: Optional[str] = None
    result_delivered: bool = False

    # 타임스탬프
    created_at: datetime = field(default_factory=utc_now)
    completed_at: Optional[datetime] = None

    # 런타임 전용 (영속화 안 됨)
    listeners: List[asyncio.Queue] = field(default_factory=list, repr=False)
    intervention_queue: asyncio.Queue = field(default_factory=asyncio.Queue, repr=False)
    execution_task: Optional[asyncio.Task] = field(default=None, repr=False)  # 백그라운드 실행 태스크
    last_progress_text: Optional[str] = field(default=None, repr=False)  # 마지막 진행 상황 (재연결용)

    @property
    def key(self) -> str:
        """태스크 키"""
        return f"{self.client_id}:{self.request_id}"

    def to_dict(self) -> dict:
        """영속화용 dict 변환"""
        return {
            "client_id": self.client_id,
            "request_id": self.request_id,
            "prompt": self.prompt,
            "status": self.status.value,
            "resume_session_id": self.resume_session_id,
            "claude_session_id": self.claude_session_id,
            "result": self.result,
            "error": self.error,
            "result_delivered": self.result_delivered,
            "created_at": datetime_to_str(self.created_at),
            "completed_at": datetime_to_str(self.completed_at) if self.completed_at else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Task":
        """dict에서 복원"""
        return cls(
            client_id=data["client_id"],
            request_id=data["request_id"],
            prompt=data["prompt"],
            status=TaskStatus(data["status"]),
            resume_session_id=data.get("resume_session_id"),
            claude_session_id=data.get("claude_session_id"),
            result=data.get("result"),
            error=data.get("error"),
            result_delivered=data.get("result_delivered", False),
            created_at=str_to_datetime(data["created_at"]),
            completed_at=str_to_datetime(data["completed_at"]) if data.get("completed_at") else None,
        )


class TaskManager:
    """
    태스크 라이프사이클 관리자

    역할:
    1. 태스크 생성/조회/삭제
    2. {client_id, request_id}로 활성 태스크 추적 (중복 방지)
    3. 태스크 상태 업데이트 및 결과 저장
    4. SSE 리스너 관리
    5. 개입 메시지 큐 관리
    6. JSON 파일 영속화
    """

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Args:
            storage_path: 태스크 저장 파일 경로 (None이면 영속화 안 함)
        """
        # task_key -> Task
        self._tasks: Dict[str, Task] = {}
        # 영속화 경로
        self._storage_path = storage_path
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()
        # 저장 예약 플래그 (debounce용)
        self._save_scheduled = False

    async def load(self) -> int:
        """
        파일에서 태스크 로드

        서비스 시작 시 호출. running 상태의 태스크는 error로 마킹.

        Returns:
            로드된 태스크 수
        """
        if not self._storage_path or not self._storage_path.exists():
            logger.info("No existing tasks file to load")
            return 0

        try:
            data = json.loads(self._storage_path.read_text())
            tasks_data = data.get("tasks", {})

            loaded = 0
            for key, task_data in tasks_data.items():
                try:
                    task = Task.from_dict(task_data)

                    # running 상태의 태스크는 서비스 재시작으로 중단된 것
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.ERROR
                        task.error = "서비스 재시작으로 중단됨"
                        task.completed_at = utc_now()
                        logger.warning(f"Marked interrupted task as error: {key}")

                    self._tasks[key] = task
                    loaded += 1
                except Exception as e:
                    logger.error(f"Failed to load task {key}: {e}")

            logger.info(f"Loaded {loaded} tasks from storage")

            # running → error 변경사항 저장
            await self._save()

            return loaded

        except Exception as e:
            logger.error(f"Failed to load tasks file: {e}")
            return 0

    async def _save(self) -> None:
        """태스크를 파일에 저장"""
        if not self._storage_path:
            return

        try:
            data = {
                "tasks": {key: task.to_dict() for key, task in self._tasks.items()},
                "last_saved": datetime_to_str(utc_now()),
            }

            # 디렉토리 생성
            self._storage_path.parent.mkdir(parents=True, exist_ok=True)

            # 임시 파일에 먼저 쓰고 rename (atomic write)
            temp_path = self._storage_path.with_suffix(".tmp")
            temp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            temp_path.rename(self._storage_path)

            logger.debug(f"Saved {len(self._tasks)} tasks to storage")

        except Exception as e:
            logger.error(f"Failed to save tasks: {e}")

    async def save(self) -> None:
        """태스크 상태 저장 (public interface)"""
        await self._save()

    def get_running_tasks(self) -> List[Task]:
        """실행 중인 태스크 목록 반환"""
        return [t for t in self._tasks.values() if t.status == TaskStatus.RUNNING]

    async def _schedule_save(self) -> None:
        """저장 예약 (debounce)"""
        if self._save_scheduled:
            return

        self._save_scheduled = True

        async def do_save():
            await asyncio.sleep(0.5)  # 500ms debounce
            self._save_scheduled = False
            await self._save()

        asyncio.create_task(do_save())

    async def create_task(
        self,
        client_id: str,
        request_id: str,
        prompt: str,
        resume_session_id: Optional[str] = None,
    ) -> Task:
        """
        새 태스크 생성

        Args:
            client_id: 클라이언트 ID (e.g., "dorothy_bot")
            request_id: 요청 ID (e.g., Discord thread ID)
            prompt: 실행할 프롬프트
            resume_session_id: 이전 세션 ID (대화 연속성용)

        Returns:
            Task: 생성된 태스크

        Raises:
            TaskConflictError: 같은 키로 running 태스크가 존재
        """
        key = f"{client_id}:{request_id}"

        async with self._lock:
            # 기존 태스크 확인
            existing = self._tasks.get(key)
            if existing:
                if existing.status == TaskStatus.RUNNING:
                    raise TaskConflictError(f"Task already running: {key}")
                # 완료된 태스크가 있으면 덮어쓰기
                logger.info(f"Overwriting existing task: {key}")

            task = Task(
                client_id=client_id,
                request_id=request_id,
                prompt=prompt,
                resume_session_id=resume_session_id,
            )

            self._tasks[key] = task
            logger.info(f"Created task: {key}")

        await self._schedule_save()
        return task

    async def get_task(self, client_id: str, request_id: str) -> Optional[Task]:
        """태스크 조회"""
        key = f"{client_id}:{request_id}"
        return self._tasks.get(key)

    async def get_tasks_by_client(self, client_id: str) -> List[Task]:
        """클라이언트별 태스크 목록 조회"""
        return [
            task for task in self._tasks.values()
            if task.client_id == client_id
        ]

    async def complete_task(
        self,
        client_id: str,
        request_id: str,
        result: str,
        claude_session_id: Optional[str] = None,
    ) -> Optional[Task]:
        """
        태스크 완료 처리

        Args:
            client_id: 클라이언트 ID
            request_id: 요청 ID
            result: 실행 결과
            claude_session_id: Claude Code 세션 ID

        Returns:
            업데이트된 태스크 (없으면 None)
        """
        key = f"{client_id}:{request_id}"

        async with self._lock:
            task = self._tasks.get(key)
            if not task:
                logger.warning(f"Task not found for complete: {key}")
                return None

            task.status = TaskStatus.COMPLETED
            task.result = result
            task.claude_session_id = claude_session_id
            task.completed_at = utc_now()

            # 소요 시간 계산
            duration_seconds = (task.completed_at - task.created_at).total_seconds()

            logger.info(f"Completed task: {key}")

        # Discord 알림 (fire-and-forget)
        asyncio.create_task(discord_notifier.notify_task_completed(
            client_id, request_id, duration_seconds
        ))

        await self._schedule_save()
        return task

    async def error_task(
        self,
        client_id: str,
        request_id: str,
        error: str,
    ) -> Optional[Task]:
        """
        태스크 에러 처리

        Args:
            client_id: 클라이언트 ID
            request_id: 요청 ID
            error: 에러 메시지

        Returns:
            업데이트된 태스크 (없으면 None)
        """
        key = f"{client_id}:{request_id}"

        async with self._lock:
            task = self._tasks.get(key)
            if not task:
                logger.warning(f"Task not found for error: {key}")
                return None

            task.status = TaskStatus.ERROR
            task.error = error
            task.completed_at = utc_now()

            logger.info(f"Error task: {key} - {error}")

        # Discord 알림 (fire-and-forget)
        asyncio.create_task(discord_notifier.notify_task_error(client_id, request_id, error))

        await self._schedule_save()
        return task

    async def ack_task(self, client_id: str, request_id: str) -> bool:
        """
        결과 수신 확인 (태스크 삭제)

        Args:
            client_id: 클라이언트 ID
            request_id: 요청 ID

        Returns:
            성공 여부
        """
        key = f"{client_id}:{request_id}"

        async with self._lock:
            task = self._tasks.pop(key, None)
            if not task:
                logger.warning(f"Task not found for ack: {key}")
                return False

            # intervention_queue 정리 (메모리 릭 방지)
            self._clear_queue(task.intervention_queue)
            # listeners 정리
            task.listeners.clear()

            logger.info(f"Acked task: {key}")

        await self._schedule_save()
        return True

    async def mark_delivered(self, client_id: str, request_id: str) -> bool:
        """
        결과 전달 완료 마킹

        ack 전에 결과가 전달되었음을 표시.
        서비스 재시작 시 이미 전달된 결과는 재전송하지 않음.

        Returns:
            성공 여부
        """
        key = f"{client_id}:{request_id}"

        async with self._lock:
            task = self._tasks.get(key)
            if not task:
                return False

            task.result_delivered = True

        await self._schedule_save()
        return True

    # === SSE 리스너 관리 ===

    async def add_listener(self, client_id: str, request_id: str, queue: asyncio.Queue) -> bool:
        """
        SSE 리스너 추가

        Returns:
            성공 여부 (태스크 존재 여부)
        """
        key = f"{client_id}:{request_id}"
        async with self._lock:
            task = self._tasks.get(key)
            if not task:
                return False

            task.listeners.append(queue)
            logger.info(f"[LISTENER] Added listener to task {key}, total: {len(task.listeners)}")
        return True

    async def remove_listener(self, client_id: str, request_id: str, queue: asyncio.Queue) -> None:
        """SSE 리스너 제거"""
        key = f"{client_id}:{request_id}"
        async with self._lock:
            task = self._tasks.get(key)
            if task and queue in task.listeners:
                task.listeners.remove(queue)
                logger.info(f"[LISTENER] Removed listener from task {key}, remaining: {len(task.listeners)}")

    async def broadcast(self, client_id: str, request_id: str, event: dict) -> int:
        """
        모든 리스너에게 이벤트 브로드캐스트

        Returns:
            전송된 리스너 수
        """
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)
        if not task:
            return 0

        count = 0
        for queue in task.listeners:
            try:
                await queue.put(event)
                count += 1
            except Exception as e:
                logger.warning(f"Failed to broadcast to listener: {e}")

        if count > 0:
            event_type = event.get("type", "unknown")
            logger.info(f"[BROADCAST] {key} -> {count} listener(s), event={event_type}")

        return count

    # === 개입 메시지 관리 ===

    async def add_intervention(
        self,
        client_id: str,
        request_id: str,
        text: str,
        user: str,
        attachment_paths: Optional[List[str]] = None,
    ) -> int:
        """
        개입 메시지 추가

        Args:
            client_id: 클라이언트 ID
            request_id: 요청 ID
            text: 메시지 텍스트
            user: 사용자
            attachment_paths: 첨부 파일 경로

        Returns:
            큐 내 위치 (queue position)

        Raises:
            TaskNotFoundError: 태스크 없음
            TaskNotRunningError: 태스크가 running 상태가 아님
        """
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)

        if not task:
            raise TaskNotFoundError(f"Task not found: {key}")

        if task.status != TaskStatus.RUNNING:
            raise TaskNotRunningError(f"Task is not running: {key}")

        message = {
            "text": text,
            "user": user,
            "attachment_paths": attachment_paths or [],
        }
        await task.intervention_queue.put(message)

        return task.intervention_queue.qsize()

    async def get_intervention(self, client_id: str, request_id: str) -> Optional[dict]:
        """
        개입 메시지 가져오기 (non-blocking)

        Returns:
            메시지 dict 또는 None
        """
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)
        if not task:
            return None

        try:
            return task.intervention_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    # === 백그라운드 실행 관리 ===

    async def start_execution(
        self,
        client_id: str,
        request_id: str,
        claude_runner,
        resource_manager,
    ) -> bool:
        """
        태스크의 Claude 실행을 백그라운드에서 시작

        SSE 연결과 독립적으로 실행되어, 클라이언트 재연결 시에도
        실행이 계속됩니다.

        Args:
            client_id: 클라이언트 ID
            request_id: 요청 ID
            claude_runner: ClaudeCodeRunner 인스턴스
            resource_manager: ResourceManager 인스턴스

        Returns:
            bool: 성공 여부
        """
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)
        if not task:
            logger.warning(f"Task not found for execution: {key}")
            return False

        if task.execution_task is not None:
            logger.warning(f"Task already executing: {key}")
            return False

        # 백그라운드 태스크 생성
        task.execution_task = asyncio.create_task(
            self._run_execution(
                task=task,
                claude_runner=claude_runner,
                resource_manager=resource_manager,
            )
        )
        logger.info(f"Started background execution for task: {key}")

        # Discord 알림 (fire-and-forget)
        asyncio.create_task(discord_notifier.notify_task_started(client_id, request_id))

        return True

    async def _run_execution(
        self,
        task: Task,
        claude_runner,
        resource_manager,
    ) -> None:
        """백그라운드에서 Claude 실행 및 이벤트 브로드캐스트"""
        key = task.key

        try:
            async with resource_manager.acquire(timeout=5.0):
                # 개입 메시지 가져오기 함수
                async def get_intervention():
                    return await self.get_intervention(task.client_id, task.request_id)

                # 개입 메시지 전송 콜백
                async def on_intervention_sent(user: str, text: str):
                    event = {"type": "intervention_sent", "user": user, "text": text}
                    await self.broadcast(task.client_id, task.request_id, event)

                # Claude Code 실행
                async for event in claude_runner.execute(
                    prompt=task.prompt,
                    resume_session_id=task.resume_session_id,
                    get_intervention=get_intervention,
                    on_intervention_sent=on_intervention_sent,
                ):
                    event_dict = event.model_dump()

                    # 진행 상황 저장 (재연결용)
                    if event.type == "progress":
                        task.last_progress_text = event_dict.get("text", "")

                    # 리스너들에게 브로드캐스트
                    await self.broadcast(task.client_id, task.request_id, event_dict)

                    # 완료 또는 오류 시 태스크 상태 업데이트
                    if event.type == "complete":
                        await self.complete_task(
                            task.client_id,
                            task.request_id,
                            result=event.result,
                            claude_session_id=event.claude_session_id,
                        )
                    elif event.type == "error":
                        await self.error_task(
                            task.client_id,
                            task.request_id,
                            error=event.message,
                        )

        except RuntimeError as e:
            # 리소스 획득 실패
            error_msg = str(e)
            logger.error(f"Resource acquisition failed for task {key}: {error_msg}")
            await self.error_task(task.client_id, task.request_id, error=error_msg)
            # 에러 이벤트 브로드캐스트
            await self.broadcast(
                task.client_id, task.request_id,
                {"type": "error", "message": error_msg}
            )

        except asyncio.CancelledError:
            logger.info(f"Task execution cancelled: {key}")
            raise

        except Exception as e:
            logger.exception(f"Task execution error for {key}: {e}")
            error_msg = f"실행 오류: {str(e)}"
            await self.error_task(task.client_id, task.request_id, error=error_msg)
            # 에러 이벤트 브로드캐스트
            await self.broadcast(
                task.client_id, task.request_id,
                {"type": "error", "message": error_msg}
            )

        finally:
            task.execution_task = None
            logger.info(f"Background execution finished for task: {key}")

    def is_execution_running(self, client_id: str, request_id: str) -> bool:
        """태스크 실행이 진행 중인지 확인"""
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)
        return task is not None and task.execution_task is not None

    async def send_reconnect_status(self, client_id: str, request_id: str, queue: asyncio.Queue) -> None:
        """
        재연결 시 현재 상태 이벤트 전송

        새로 연결된 리스너에게 현재 태스크 상태를 알려줍니다.
        """
        key = f"{client_id}:{request_id}"
        task = self._tasks.get(key)
        if not task:
            return

        # 재연결 알림 이벤트
        reconnect_event = {
            "type": "reconnected",
            "status": task.status.value,
            "has_execution": task.execution_task is not None,
        }

        # 마지막 진행 상황이 있으면 포함
        if task.last_progress_text:
            reconnect_event["last_progress"] = task.last_progress_text

        try:
            await queue.put(reconnect_event)
            logger.debug(f"Sent reconnect status to listener for task {key}")

            # Discord 알림 (fire-and-forget)
            asyncio.create_task(discord_notifier.notify_reconnect(
                client_id, request_id,
                task_status=task.status.value,
                has_execution=task.execution_task is not None
            ))

        except Exception as e:
            logger.warning(f"Failed to send reconnect status: {e}")

    # === 정리 ===

    async def cancel_running_tasks(self, timeout: float = 5.0) -> int:
        """
        실행 중인 모든 태스크 취소

        서비스 shutdown 시 호출하여 고아 프로세스 방지.

        Args:
            timeout: 취소 대기 시간 (초)

        Returns:
            취소된 태스크 수
        """
        tasks_to_cancel = []

        async with self._lock:
            for key, task in self._tasks.items():
                if task.execution_task and not task.execution_task.done():
                    task.execution_task.cancel()
                    tasks_to_cancel.append((key, task.execution_task))
                    logger.info(f"Cancelling execution for task: {key}")

        if not tasks_to_cancel:
            return 0

        # 모든 취소된 태스크 완료 대기 (gather로 병렬 대기)
        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *[t for _, t in tasks_to_cancel],
                    return_exceptions=True
                ),
                timeout=timeout
            )
        except asyncio.TimeoutError:
            logger.warning(f"Task cancellation timeout after {timeout}s")

        # 취소된 태스크 수 카운트
        cancelled_count = sum(1 for _, t in tasks_to_cancel if t.done())
        logger.info(f"Cancelled {cancelled_count}/{len(tasks_to_cancel)} running tasks")
        return cancelled_count

    async def cleanup_old_tasks(self, max_age_hours: int = 24) -> int:
        """
        오래된 태스크 정리

        Args:
            max_age_hours: 최대 보관 시간

        Returns:
            정리된 태스크 수
        """
        cutoff = utc_now() - timedelta(hours=max_age_hours)
        cleaned = 0

        async with self._lock:
            keys_to_remove = []
            for key, task in self._tasks.items():
                # RUNNING 상태 태스크 처리
                if task.status == TaskStatus.RUNNING:
                    # execution_task가 없거나 완료된 경우 (orphaned task)
                    if task.execution_task is None or task.execution_task.done():
                        # 오래된 orphaned task는 에러로 전환 후 정리 대상
                        if task.created_at < cutoff:
                            task.status = TaskStatus.ERROR
                            task.error = "실행 태스크 없이 오래된 running 상태 (orphaned)"
                            task.completed_at = utc_now()
                            keys_to_remove.append(key)
                            logger.warning(f"Cleaning up orphaned running task: {key}")
                    # 활성 실행 중인 태스크는 정리하지 않음
                    continue

                # 오래된 태스크 정리
                if task.created_at < cutoff:
                    keys_to_remove.append(key)

            for key in keys_to_remove:
                task = self._tasks[key]
                # intervention_queue 정리 (메모리 릭 방지)
                self._clear_queue(task.intervention_queue)
                # listeners 정리
                task.listeners.clear()
                del self._tasks[key]
                cleaned += 1

        if cleaned > 0:
            logger.info(f"Cleaned up {cleaned} old tasks")
            await self._schedule_save()

        return cleaned

    def _clear_queue(self, queue: asyncio.Queue) -> None:
        """큐 내 모든 항목 제거"""
        try:
            while True:
                queue.get_nowait()
        except asyncio.QueueEmpty:
            pass

    def get_stats(self) -> dict:
        """통계 반환"""
        running = sum(1 for t in self._tasks.values() if t.status == TaskStatus.RUNNING)
        completed = sum(1 for t in self._tasks.values() if t.status == TaskStatus.COMPLETED)
        error = sum(1 for t in self._tasks.values() if t.status == TaskStatus.ERROR)

        return {
            "total": len(self._tasks),
            "running": running,
            "completed": completed,
            "error": error,
        }


# 싱글톤 인스턴스는 main.py에서 초기화
task_manager: Optional[TaskManager] = None


def get_task_manager() -> TaskManager:
    """TaskManager 싱글톤 반환"""
    global task_manager
    if task_manager is None:
        raise RuntimeError("TaskManager not initialized. Call init_task_manager first.")
    return task_manager


def init_task_manager(storage_path: Optional[Path] = None) -> TaskManager:
    """TaskManager 초기화"""
    global task_manager
    task_manager = TaskManager(storage_path=storage_path)
    return task_manager


def set_task_manager(manager: Optional[TaskManager]) -> None:
    """TaskManager 인스턴스 설정 (테스트용)"""
    global task_manager
    task_manager = manager
