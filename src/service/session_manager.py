"""
SessionManager - 세션 라이프사이클 관리

Claude Code 세션의 생성, 조회, 삭제 및 상태 관리를 담당합니다.
"""

import asyncio
import uuid
from datetime import datetime, timezone
from typing import Optional, Dict
from dataclasses import dataclass, field

from src.models import SessionStatus


def utc_now() -> datetime:
    """현재 UTC 시간 반환"""
    return datetime.now(timezone.utc)


@dataclass
class Session:
    """세션 데이터"""
    session_id: str
    thread_id: int
    user: str
    status: SessionStatus
    resume_session_id: Optional[str] = None
    created_at: datetime = field(default_factory=utc_now)
    updated_at: datetime = field(default_factory=utc_now)
    # Claude Code 세션 ID (실행 후 할당)
    claude_session_id: Optional[str] = None
    # 실행 결과 (완료 시)
    result: Optional[str] = None
    # 메시지 큐 (개입 메시지용)
    message_queue: asyncio.Queue = field(default_factory=asyncio.Queue)


class SessionManager:
    """
    세션 라이프사이클 관리자

    역할:
    1. 세션 생성/조회/삭제
    2. thread_id로 활성 세션 추적 (중복 방지)
    3. 세션 상태 업데이트
    4. 개입 메시지 큐 관리
    """

    def __init__(self):
        # session_id -> Session
        self._sessions: Dict[str, Session] = {}
        # thread_id -> session_id (활성 세션만)
        self._thread_sessions: Dict[int, str] = {}
        # Lock for thread-safe operations
        self._lock = asyncio.Lock()

    def _generate_session_id(self) -> str:
        """세션 ID 생성"""
        return f"ses_{uuid.uuid4().hex[:12]}"

    async def create_session(
        self,
        thread_id: int,
        user: str,
        resume_session_id: Optional[str] = None
    ) -> Session:
        """
        새 세션 생성

        Args:
            thread_id: Discord 스레드 ID
            user: 요청한 사용자
            resume_session_id: 이전 세션 ID (대화 연속성용)

        Returns:
            Session: 생성된 세션

        Raises:
            ValueError: 해당 thread_id에 이미 활성 세션 존재
        """
        async with self._lock:
            # 중복 체크
            if thread_id in self._thread_sessions:
                existing_session_id = self._thread_sessions[thread_id]
                existing_session = self._sessions.get(existing_session_id)
                if existing_session and existing_session.status in [
                    SessionStatus.READY, SessionStatus.RUNNING
                ]:
                    raise ValueError(f"Thread {thread_id} already has an active session")

            session_id = self._generate_session_id()
            session = Session(
                session_id=session_id,
                thread_id=thread_id,
                user=user,
                status=SessionStatus.READY,
                resume_session_id=resume_session_id,
            )

            self._sessions[session_id] = session
            self._thread_sessions[thread_id] = session_id

            return session

    async def get_session(self, session_id: str) -> Optional[Session]:
        """세션 조회"""
        return self._sessions.get(session_id)

    async def get_session_by_thread(self, thread_id: int) -> Optional[Session]:
        """thread_id로 세션 조회"""
        session_id = self._thread_sessions.get(thread_id)
        if session_id:
            return self._sessions.get(session_id)
        return None

    async def update_status(
        self,
        session_id: str,
        status: SessionStatus,
        result: Optional[str] = None,
        claude_session_id: Optional[str] = None
    ) -> Optional[Session]:
        """
        세션 상태 업데이트

        Args:
            session_id: 세션 ID
            status: 새 상태
            result: 실행 결과 (선택)
            claude_session_id: Claude Code 세션 ID (선택)
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            session.status = status
            session.updated_at = utc_now()

            if result is not None:
                session.result = result
            if claude_session_id is not None:
                session.claude_session_id = claude_session_id

            # 완료/에러 상태면 thread_sessions에서 제거
            if status in [SessionStatus.COMPLETED, SessionStatus.ERROR, SessionStatus.TERMINATED]:
                self._thread_sessions.pop(session.thread_id, None)

            return session

    async def delete_session(self, session_id: str) -> Optional[Session]:
        """
        세션 삭제/종료

        Returns:
            삭제된 세션 (없으면 None)
        """
        async with self._lock:
            session = self._sessions.get(session_id)
            if not session:
                return None

            # 상태를 TERMINATED로 변경
            session.status = SessionStatus.TERMINATED
            session.updated_at = utc_now()

            # thread_sessions에서 제거
            self._thread_sessions.pop(session.thread_id, None)

            return session

    async def cleanup_session(self, session_id: str) -> None:
        """
        세션 완전 정리 (메모리에서 제거)

        완료된 세션을 일정 시간 후 정리할 때 사용
        """
        async with self._lock:
            session = self._sessions.pop(session_id, None)
            if session:
                self._thread_sessions.pop(session.thread_id, None)

    def get_active_sessions(self) -> list[Session]:
        """활성 세션 목록 반환"""
        return [
            s for s in self._sessions.values()
            if s.status in [SessionStatus.READY, SessionStatus.RUNNING]
        ]

    def get_active_count(self) -> int:
        """활성 세션 수 반환"""
        return len(self.get_active_sessions())

    async def add_intervention_message(
        self,
        session_id: str,
        text: str,
        user: str,
        attachment_paths: Optional[list[str]] = None
    ) -> int:
        """
        개입 메시지 추가

        Args:
            session_id: 세션 ID
            text: 메시지 텍스트
            user: 사용자
            attachment_paths: 첨부 파일 경로

        Returns:
            큐 내 위치 (queue position)

        Raises:
            ValueError: 세션 없음 또는 실행 중이 아님
        """
        session = self._sessions.get(session_id)
        if not session:
            raise ValueError(f"Session not found: {session_id}")

        if session.status != SessionStatus.RUNNING:
            raise ValueError(f"Session is not running: {session_id}")

        message = {
            "text": text,
            "user": user,
            "attachment_paths": attachment_paths or [],
        }
        await session.message_queue.put(message)

        return session.message_queue.qsize()

    async def get_intervention_message(self, session_id: str) -> Optional[dict]:
        """
        개입 메시지 가져오기 (non-blocking)

        Returns:
            메시지 dict 또는 None
        """
        session = self._sessions.get(session_id)
        if not session:
            return None

        try:
            return session.message_queue.get_nowait()
        except asyncio.QueueEmpty:
            return None

    async def terminate_all(self) -> int:
        """
        모든 활성 세션 종료 (shutdown용)

        Returns:
            종료된 세션 수
        """
        count = 0
        async with self._lock:
            for session in list(self._sessions.values()):
                if session.status in [SessionStatus.READY, SessionStatus.RUNNING]:
                    session.status = SessionStatus.TERMINATED
                    session.updated_at = utc_now()
                    self._thread_sessions.pop(session.thread_id, None)
                    count += 1
        return count


# 싱글톤 인스턴스
session_manager = SessionManager()
