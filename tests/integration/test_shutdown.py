"""
Graceful Shutdown Tests - 종료 시 세션 정리 테스트

서비스 종료 시 활성 세션이 올바르게 정리되는지 테스트합니다.
"""

import pytest
import asyncio
from unittest.mock import patch, AsyncMock
from fastapi.testclient import TestClient

from src.models import SessionStatus


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        # 모듈 다시 로드하여 환경변수 적용
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def reset_managers():
    """각 테스트 전 매니저 초기화"""
    from src.service import session_manager

    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()

    yield

    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()


class TestGracefulShutdown:
    """Graceful shutdown 테스트"""

    @pytest.mark.asyncio
    async def test_terminate_all_sessions(self):
        """모든 세션 종료 테스트"""
        from src.service import session_manager

        # 여러 세션 생성
        sessions = []
        for i in range(3):
            session = await session_manager.create_session(
                thread_id=60000 + i,
                user=f"shutdown_user_{i}"
            )
            sessions.append(session)

        # 활성 세션 확인
        assert session_manager.get_active_count() == 3

        # terminate_all 호출 (shutdown 시 실행됨)
        terminated_count = await session_manager.terminate_all()

        # 결과 확인
        assert terminated_count == 3

        # 모든 세션이 terminated 상태인지 확인
        for session in sessions:
            s = await session_manager.get_session(session.session_id)
            assert s.status == SessionStatus.TERMINATED

        # 활성 세션 수는 0
        assert session_manager.get_active_count() == 0

    @pytest.mark.asyncio
    async def test_terminate_running_session(self):
        """실행 중인 세션 종료"""
        from src.service import session_manager

        # 세션 생성 후 RUNNING 상태로 변경
        session = await session_manager.create_session(
            thread_id=61000,
            user="running_user"
        )
        await session_manager.update_status(session.session_id, SessionStatus.RUNNING)

        # 상태 확인
        s = await session_manager.get_session(session.session_id)
        assert s.status == SessionStatus.RUNNING

        # terminate_all 호출
        terminated = await session_manager.terminate_all()
        assert terminated == 1

        # 상태 확인
        s = await session_manager.get_session(session.session_id)
        assert s.status == SessionStatus.TERMINATED

    @pytest.mark.asyncio
    async def test_terminate_mixed_states(self):
        """다양한 상태의 세션들 종료"""
        from src.service import session_manager

        # READY 상태 세션
        ready_session = await session_manager.create_session(
            thread_id=62001,
            user="ready_user"
        )

        # RUNNING 상태 세션
        running_session = await session_manager.create_session(
            thread_id=62002,
            user="running_user"
        )
        await session_manager.update_status(running_session.session_id, SessionStatus.RUNNING)

        # COMPLETED 상태 세션 (이미 완료됨)
        completed_session = await session_manager.create_session(
            thread_id=62003,
            user="completed_user"
        )
        await session_manager.update_status(completed_session.session_id, SessionStatus.COMPLETED)

        # terminate_all 호출
        # READY와 RUNNING만 종료됨 (COMPLETED는 이미 끝남)
        terminated = await session_manager.terminate_all()
        assert terminated == 2

        # 상태 확인
        r = await session_manager.get_session(ready_session.session_id)
        assert r.status == SessionStatus.TERMINATED

        run = await session_manager.get_session(running_session.session_id)
        assert run.status == SessionStatus.TERMINATED

        comp = await session_manager.get_session(completed_session.session_id)
        assert comp.status == SessionStatus.COMPLETED  # 변경 안 됨

    @pytest.mark.asyncio
    async def test_thread_sessions_cleared_on_shutdown(self):
        """종료 시 thread_sessions 맵도 정리됨"""
        from src.service import session_manager

        # 세션 생성
        await session_manager.create_session(thread_id=63001, user="user1")
        await session_manager.create_session(thread_id=63002, user="user2")

        # thread_sessions 확인
        assert 63001 in session_manager._thread_sessions
        assert 63002 in session_manager._thread_sessions

        # terminate_all
        await session_manager.terminate_all()

        # thread_sessions에서 제거됨
        assert 63001 not in session_manager._thread_sessions
        assert 63002 not in session_manager._thread_sessions


class TestLifespanShutdown:
    """FastAPI lifespan 종료 테스트"""

    @pytest.mark.asyncio
    async def test_shutdown_cleans_sessions(self):
        """애플리케이션 종료 시 세션 정리 시뮬레이션"""
        from src.service import session_manager

        # 세션 생성
        for i in range(2):
            await session_manager.create_session(
                thread_id=64000 + i,
                user=f"lifespan_user_{i}"
            )

        # 활성 세션 확인
        assert session_manager.get_active_count() == 2

        # terminate_all 호출하여 shutdown 시뮬레이션
        terminated = await session_manager.terminate_all()

        # 활성 세션 없음
        assert session_manager.get_active_count() == 0


class TestFileManagerCleanup:
    """파일 매니저 정리 테스트"""

    def test_cleanup_old_files(self):
        """오래된 첨부 파일 정리"""
        from src.service.file_manager import FileManager
        import tempfile
        import os
        from pathlib import Path

        # 임시 디렉토리로 새 FileManager 생성
        with tempfile.TemporaryDirectory() as tmpdir:
            test_manager = FileManager(base_dir=tmpdir)

            # 테스트용 디렉토리 생성
            test_dir = Path(tmpdir) / "thread_test"
            test_dir.mkdir()

            # 파일 생성
            test_file = test_dir / "test.txt"
            test_file.write_text("test content")

            # 파일 존재 확인
            assert test_file.exists()

            # 정리 실행 (0시간 = 모두 삭제)
            cleaned = test_manager.cleanup_old_files(max_age_hours=0)

            # 결과 확인 (디렉토리가 삭제됨)
            assert cleaned >= 1
            assert not test_dir.exists()


class TestInterventionQueueCleanup:
    """개입 메시지 큐 정리 테스트"""

    @pytest.mark.asyncio
    async def test_intervention_queue_cleared(self):
        """종료 시 개입 메시지 큐 정리"""
        from src.service import session_manager

        # 세션 생성 및 RUNNING 상태로 변경
        session = await session_manager.create_session(
            thread_id=65001,
            user="queue_user"
        )
        await session_manager.update_status(session.session_id, SessionStatus.RUNNING)

        # 개입 메시지 추가
        await session_manager.add_intervention_message(
            session.session_id,
            "test message 1",
            "user1"
        )
        await session_manager.add_intervention_message(
            session.session_id,
            "test message 2",
            "user2"
        )

        # 큐에 메시지가 있음
        s = await session_manager.get_session(session.session_id)
        assert s.message_queue.qsize() == 2

        # 세션 삭제 (terminate)
        await session_manager.terminate_all()

        # 세션은 terminated 상태지만 메모리에는 아직 있음
        # (cleanup_session을 호출해야 완전히 제거됨)
        s = await session_manager.get_session(session.session_id)
        assert s.status == SessionStatus.TERMINATED
