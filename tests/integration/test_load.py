"""
Load Tests - 부하 테스트

동시 세션 처리 능력을 테스트합니다.
⚠️ 사용자 지시: 서버 리소스 제한으로 동시 세션은 2개까지만 테스트
"""

import pytest
import asyncio
import time
from unittest.mock import patch, AsyncMock, MagicMock
from concurrent.futures import ThreadPoolExecutor
from fastapi.testclient import TestClient


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
    from src.service import session_manager, resource_manager

    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()

    # 리소스 매니저 초기화 (새 Semaphore 생성)
    resource_manager._semaphore = asyncio.Semaphore(resource_manager.max_concurrent)
    resource_manager._active_count = 0

    yield

    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()


class TestConcurrentSessions:
    """동시 세션 테스트 (2개 제한)"""

    def test_two_concurrent_sessions(self, client):
        """
        2개 동시 세션 생성 및 관리 테스트

        사용자 지시에 따라 부하 테스트는 2개까지만 실행.
        (서버 물리적 리소스 제한)
        """
        sessions = []
        thread_ids = [20001, 20002]  # 2개만 테스트

        # 세션 생성
        for thread_id in thread_ids:
            response = client.post("/sessions", json={
                "thread_id": thread_id,
                "user": f"load_test_user_{thread_id}"
            })
            assert response.status_code == 201, f"Failed to create session for thread {thread_id}"
            sessions.append(response.json())

        # 모든 세션이 ready 상태인지 확인
        for session in sessions:
            response = client.get(f"/sessions/{session['session_id']}")
            assert response.status_code == 200
            assert response.json()["status"] == "ready"

        # 상태 엔드포인트로 전체 확인
        status = client.get("/status").json()
        assert status["active_sessions"] == 2, "Should have exactly 2 active sessions"

        # 정리
        for session in sessions:
            response = client.delete(f"/sessions/{session['session_id']}")
            assert response.status_code == 200

        # 정리 후 확인
        status_after = client.get("/status").json()
        assert status_after["active_sessions"] == 0

    def test_session_creation_performance(self, client):
        """세션 생성 성능 측정"""
        creation_times = []
        sessions = []

        for i in range(2):  # 2개만 테스트
            start = time.time()
            response = client.post("/sessions", json={
                "thread_id": 30000 + i,
                "user": f"perf_user_{i}"
            })
            elapsed = time.time() - start
            creation_times.append(elapsed)

            assert response.status_code == 201
            sessions.append(response.json())

        # 세션 생성은 100ms 이내여야 함
        for ct in creation_times:
            assert ct < 0.1, f"Session creation took too long: {ct:.3f}s"

        # 평균 시간 출력 (디버깅용)
        avg_time = sum(creation_times) / len(creation_times)
        print(f"\nAverage session creation time: {avg_time:.4f}s")

        # 정리
        for session in sessions:
            client.delete(f"/sessions/{session['session_id']}")


class TestResourceManager:
    """리소스 매니저 동시성 테스트"""

    @pytest.mark.asyncio
    async def test_semaphore_limits_concurrent_execution(self):
        """세마포어가 동시 실행을 제한하는지 테스트"""
        from src.service.resource_manager import ResourceManager

        # 테스트용 새 ResourceManager 생성 (max_concurrent=2)
        test_manager = ResourceManager(max_concurrent=2)

        acquired_count = 0
        max_concurrent_observed = 0

        async def acquire_and_hold():
            nonlocal acquired_count, max_concurrent_observed

            async with test_manager.acquire(timeout=5.0):
                acquired_count += 1
                max_concurrent_observed = max(max_concurrent_observed, acquired_count)
                await asyncio.sleep(0.1)  # 약간 대기
                acquired_count -= 1

        # 3개 동시 실행 시도
        tasks = [acquire_and_hold() for _ in range(3)]
        await asyncio.gather(*tasks, return_exceptions=True)

        # 동시에 2개 이하만 실행되어야 함
        assert max_concurrent_observed <= 2


class TestSessionManagerConcurrency:
    """세션 매니저 동시성 테스트"""

    @pytest.mark.asyncio
    async def test_concurrent_create_same_thread(self):
        """동일 thread_id로 동시 생성 시 하나만 성공"""
        from src.service import session_manager

        results = []

        async def create_session():
            try:
                session = await session_manager.create_session(
                    thread_id=40001,
                    user="concurrent_user"
                )
                results.append(("success", session.session_id))
            except ValueError as e:
                results.append(("conflict", str(e)))

        # 동시에 2개 생성 시도
        await asyncio.gather(
            create_session(),
            create_session()
        )

        # 하나는 성공, 하나는 충돌
        success_count = sum(1 for r in results if r[0] == "success")
        conflict_count = sum(1 for r in results if r[0] == "conflict")

        assert success_count == 1, "Exactly one session should be created"
        assert conflict_count == 1, "One creation should fail with conflict"


class TestHealthUnderLoad:
    """부하 상황에서 헬스 체크"""

    def test_health_with_active_sessions(self, client):
        """활성 세션이 있을 때 헬스 체크"""
        # 세션 생성
        sessions = []
        for i in range(2):
            response = client.post("/sessions", json={
                "thread_id": 50000 + i,
                "user": f"health_test_{i}"
            })
            sessions.append(response.json())

        # 헬스 체크
        health_response = client.get("/health")
        assert health_response.status_code == 200
        assert health_response.json()["status"] == "healthy"

        # 상태 확인
        status_response = client.get("/status")
        assert status_response.status_code == 200
        status = status_response.json()
        assert status["active_sessions"] == 2

        # 정리
        for session in sessions:
            client.delete(f"/sessions/{session['session_id']}")
