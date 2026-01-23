"""
Integration Tests - API 전체 흐름 테스트

봇과 서비스 간의 전체 API 흐름을 테스트합니다.
"""

import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


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

    def test_status_returns_task_info(self, client):
        """상태 엔드포인트가 태스크 정보를 반환"""
        response = client.get("/status")
        assert response.status_code == 200

        data = response.json()
        assert "active_tasks" in data
        assert "max_concurrent" in data
        assert isinstance(data["tasks"], list)
        assert data["max_concurrent"] > 0


# === Authentication Tests ===

class TestAuthentication:
    """인증 테스트"""

    def test_no_auth_in_dev_mode(self, client):
        """개발 모드에서는 인증 없이 접근 가능"""
        # CLAUDE_SERVICE_TOKEN이 비어있으면 인증 우회
        response = client.get("/status")
        assert response.status_code == 200

    def test_missing_auth_header_fails(self, auth_client):
        """인증 헤더 없으면 실패 (인증이 활성화된 경우)"""
        response = auth_client.get("/tasks/test_client")
        assert response.status_code == 401

    def test_invalid_token_fails(self, auth_client):
        """잘못된 토큰으로 실패"""
        response = auth_client.get(
            "/tasks/test_client",
            headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401

    def test_valid_token_succeeds(self, auth_client):
        """올바른 토큰으로 성공"""
        response = auth_client.get(
            "/tasks/test_client",
            headers={"Authorization": "Bearer test-secret-token"}
        )
        # 태스크가 없으면 빈 리스트 반환 (200)
        assert response.status_code == 200


# === Resource Limit Tests ===

class TestResourceLimits:
    """리소스 제한 테스트"""

    def test_rate_limit_check(self, client):
        """동시 실행 제한 확인"""
        from src.service import resource_manager

        # can_acquire 확인
        assert resource_manager.can_acquire() is True

        # 상태 확인
        stats = resource_manager.get_stats()
        assert stats["max_concurrent"] >= 1
        assert stats["available_slots"] >= 1
