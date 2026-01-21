"""
Integration Tests - API 전체 흐름 테스트

봇과 서비스 간의 전체 API 흐름을 테스트합니다.
Claude Code 실제 실행 없이 Mock을 사용합니다.
"""

import pytest
import asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
import json


# === Fixtures ===

@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트 (인증 비활성화)"""
    # 인증 토큰 비활성화 (테스트 모드)
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        # 모듈 다시 로드하여 환경변수 적용
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def auth_client():
    """인증이 필요한 테스트 클라이언트"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'test-secret-token'}, clear=False):
        # 모듈 다시 로드하여 환경변수 적용
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture(autouse=True)
def reset_session_manager():
    """각 테스트 전 세션 매니저 초기화"""
    from src.service import session_manager
    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()
    yield
    # 테스트 후 정리
    session_manager._sessions.clear()
    session_manager._thread_sessions.clear()


# === Health & Status Tests ===

class TestHealthEndpoints:
    """헬스 체크 엔드포인트 테스트"""

    def test_health_returns_healthy(self, client):
        """헬스 체크가 healthy 상태를 반환"""
        response = client.get("/health")
        assert response.status_code == 200

        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data
        assert data["uptime_seconds"] >= 0

    def test_status_returns_session_info(self, client):
        """상태 엔드포인트가 세션 정보를 반환"""
        response = client.get("/status")
        assert response.status_code == 200

        data = response.json()
        assert "active_sessions" in data
        assert "max_concurrent" in data
        assert isinstance(data["sessions"], list)
        assert data["max_concurrent"] > 0


# === Session CRUD Tests ===

class TestSessionLifecycle:
    """세션 생명주기 테스트"""

    def test_create_session_success(self, client):
        """세션 생성 성공"""
        response = client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#1234"
        })

        assert response.status_code == 201
        data = response.json()

        assert "session_id" in data
        assert data["session_id"].startswith("ses_")
        assert data["thread_id"] == 12345
        assert data["status"] == "ready"

    def test_create_session_with_resume(self, client):
        """이전 세션 ID로 세션 생성"""
        response = client.post("/sessions", json={
            "thread_id": 12346,
            "user": "testuser#1234",
            "resume_session_id": "abc123"
        })

        assert response.status_code == 201
        data = response.json()
        assert data["status"] == "ready"

    def test_create_duplicate_session_fails(self, client):
        """동일 thread_id로 중복 세션 생성 실패"""
        # 첫 번째 세션 생성
        client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#1234"
        })

        # 중복 시도
        response = client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#5678"
        })

        assert response.status_code == 409
        data = response.json()
        assert data["detail"]["error"]["code"] == "SESSION_CONFLICT"

    def test_get_session_success(self, client):
        """세션 조회 성공"""
        # 세션 생성
        create_response = client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#1234"
        })
        session_id = create_response.json()["session_id"]

        # 조회
        response = client.get(f"/sessions/{session_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == session_id
        assert data["thread_id"] == 12345
        assert data["user"] == "testuser#1234"

    def test_get_nonexistent_session_fails(self, client):
        """존재하지 않는 세션 조회 실패"""
        response = client.get("/sessions/ses_nonexistent")

        assert response.status_code == 404
        data = response.json()
        assert data["detail"]["error"]["code"] == "SESSION_NOT_FOUND"

    def test_delete_session_success(self, client):
        """세션 삭제 성공"""
        # 세션 생성
        create_response = client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#1234"
        })
        session_id = create_response.json()["session_id"]

        # 삭제
        response = client.delete(f"/sessions/{session_id}")
        assert response.status_code == 200

        data = response.json()
        assert data["session_id"] == session_id
        assert data["status"] == "terminated"

    def test_delete_nonexistent_session_fails(self, client):
        """존재하지 않는 세션 삭제 실패"""
        response = client.delete("/sessions/ses_nonexistent")

        assert response.status_code == 404


# === Authentication Tests ===

class TestAuthentication:
    """인증 테스트"""

    def test_no_auth_in_dev_mode(self, client):
        """개발 모드에서는 인증 없이 접근 가능"""
        # CLAUDE_SERVICE_TOKEN이 비어있으면 인증 우회
        response = client.get("/status")
        assert response.status_code == 200

    def test_missing_auth_header_fails(self, auth_client):
        """인증 헤더 없으면 실패"""
        response = auth_client.post("/sessions", json={
            "thread_id": 12345,
            "user": "testuser#1234"
        })

        assert response.status_code == 401

    def test_invalid_token_fails(self, auth_client):
        """잘못된 토큰으로 실패"""
        response = auth_client.post(
            "/sessions",
            json={"thread_id": 12345, "user": "testuser#1234"},
            headers={"Authorization": "Bearer wrong-token"}
        )

        assert response.status_code == 401

    def test_valid_token_succeeds(self, auth_client):
        """올바른 토큰으로 성공"""
        response = auth_client.post(
            "/sessions",
            json={"thread_id": 12345, "user": "testuser#1234"},
            headers={"Authorization": "Bearer test-secret-token"}
        )

        assert response.status_code == 201


# === Resource Limit Tests ===

class TestResourceLimits:
    """리소스 제한 테스트"""

    def test_rate_limit_check(self, client):
        """동시 세션 제한 확인"""
        from src.service import resource_manager

        # can_acquire 확인
        assert resource_manager.can_acquire() is True

        # 상태 확인
        stats = resource_manager.get_stats()
        assert stats["max_concurrent"] >= 1
        assert stats["available_slots"] >= 1

    def test_session_creates_regardless_of_query_limit(self, client):
        """세션 생성은 query 제한과 별개"""
        # 여러 세션 생성 가능 (query 실행 시점에서만 제한)
        sessions = []
        for i in range(3):
            response = client.post("/sessions", json={
                "thread_id": 12345 + i,
                "user": f"user{i}"
            })
            assert response.status_code == 201
            sessions.append(response.json())

        # 정리
        for session in sessions:
            client.delete(f"/sessions/{session['session_id']}")


# === Full Flow Integration Tests ===

class TestFullFlow:
    """전체 흐름 통합 테스트"""

    def test_session_lifecycle_complete(self, client):
        """세션의 전체 생명주기 테스트"""
        # 1. 세션 생성
        create_response = client.post("/sessions", json={
            "thread_id": 99999,
            "user": "integration_test_user"
        })
        assert create_response.status_code == 201
        session_id = create_response.json()["session_id"]

        # 2. 상태 확인
        status_response = client.get("/status")
        assert status_response.status_code == 200
        status_data = status_response.json()
        assert status_data["active_sessions"] >= 1

        # 3. 세션 조회
        get_response = client.get(f"/sessions/{session_id}")
        assert get_response.status_code == 200
        assert get_response.json()["status"] == "ready"

        # 4. 세션 삭제
        delete_response = client.delete(f"/sessions/{session_id}")
        assert delete_response.status_code == 200
        assert delete_response.json()["status"] == "terminated"

        # 5. 삭제 후 조회 - 아직 메모리에 있지만 terminated 상태
        get_after_delete = client.get(f"/sessions/{session_id}")
        assert get_after_delete.status_code == 200
        assert get_after_delete.json()["status"] == "terminated"

    def test_multiple_threads_independent(self, client):
        """여러 스레드가 독립적으로 동작"""
        thread_ids = [10001, 10002, 10003]
        session_ids = []

        # 여러 세션 생성
        for thread_id in thread_ids:
            response = client.post("/sessions", json={
                "thread_id": thread_id,
                "user": f"user_{thread_id}"
            })
            assert response.status_code == 201
            session_ids.append(response.json()["session_id"])

        # 상태 확인
        status = client.get("/status").json()
        assert status["active_sessions"] >= 3

        # 개별 삭제
        for session_id in session_ids:
            response = client.delete(f"/sessions/{session_id}")
            assert response.status_code == 200


# === Error Handling Tests ===

class TestErrorHandling:
    """에러 처리 테스트"""

    def test_invalid_json_body(self, client):
        """잘못된 JSON 요청 처리"""
        response = client.post(
            "/sessions",
            content="not valid json",
            headers={"Content-Type": "application/json"}
        )
        # FastAPI가 자동으로 422 반환
        assert response.status_code == 422

    def test_missing_required_field(self, client):
        """필수 필드 누락 시 422 반환"""
        response = client.post("/sessions", json={
            "thread_id": 12345
            # user 필드 누락
        })
        assert response.status_code == 422

    def test_invalid_session_id_format(self, client):
        """잘못된 세션 ID 형식"""
        response = client.get("/sessions/invalid-id-format")
        # 형식이 맞지 않아도 404 반환 (존재하지 않음)
        assert response.status_code == 404


# === Concurrent Access Tests ===

class TestConcurrentAccess:
    """동시 접근 테스트"""

    @pytest.mark.asyncio
    async def test_concurrent_session_creation(self, client):
        """동시 세션 생성 시 하나만 성공"""
        # 동일 thread_id로 동시 요청 시뮬레이션
        # (실제로는 동기 TestClient라 순차 실행됨)

        response1 = client.post("/sessions", json={
            "thread_id": 55555,
            "user": "user1"
        })
        response2 = client.post("/sessions", json={
            "thread_id": 55555,
            "user": "user2"
        })

        # 하나는 성공, 하나는 충돌
        statuses = [response1.status_code, response2.status_code]
        assert 201 in statuses
        assert 409 in statuses
