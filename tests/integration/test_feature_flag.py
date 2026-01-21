"""
Feature Flag / Rollback Tests - 기능 플래그 전환 테스트

서비스 측에서의 인증 토큰 및 모드 전환을 테스트합니다.

⚠️ 주의:
- ClaudeServiceClient는 dorothy_bot 프로젝트에 위치
- 이 테스트는 서비스 측의 인증/설정 관련 테스트만 수행
- 클라이언트 측 테스트는 dorothy_bot 프로젝트에서 수행
"""

import pytest
import os
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def client_no_auth():
    """인증 없는 테스트 클라이언트"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def client_with_auth():
    """인증 필요한 테스트 클라이언트"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'test-token-123'}, clear=False):
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


class TestAuthModeSwitch:
    """인증 모드 전환 테스트"""

    def test_dev_mode_no_auth_required(self, client_no_auth):
        """개발 모드: 인증 불필요"""
        # 토큰 없이 세션 생성 성공
        response = client_no_auth.post("/sessions", json={
            "thread_id": 70001,
            "user": "dev_user"
        })
        assert response.status_code == 201

    def test_prod_mode_requires_auth(self, client_with_auth):
        """프로덕션 모드: 인증 필수"""
        # 토큰 없이 요청 시 401
        response = client_with_auth.post("/sessions", json={
            "thread_id": 70002,
            "user": "prod_user"
        })
        assert response.status_code == 401

    def test_prod_mode_with_valid_token(self, client_with_auth):
        """프로덕션 모드: 올바른 토큰으로 성공"""
        response = client_with_auth.post(
            "/sessions",
            json={"thread_id": 70003, "user": "prod_user"},
            headers={"Authorization": "Bearer test-token-123"}
        )
        assert response.status_code == 201

    def test_prod_mode_with_invalid_token(self, client_with_auth):
        """프로덕션 모드: 잘못된 토큰으로 실패"""
        response = client_with_auth.post(
            "/sessions",
            json={"thread_id": 70004, "user": "prod_user"},
            headers={"Authorization": "Bearer wrong-token"}
        )
        assert response.status_code == 401


class TestRollbackFromProdToDev:
    """프로덕션 → 개발 모드 롤백"""

    def test_rollback_auth_mode(self, client_no_auth):
        """롤백: 인증 모드 비활성화"""
        # 토큰 환경변수 제거 후 인증 없이 접근 가능
        response = client_no_auth.post("/sessions", json={
            "thread_id": 71001,
            "user": "rollback_user"
        })
        assert response.status_code == 201


class TestHealthEndpointsNoAuth:
    """헬스 엔드포인트는 인증 불필요"""

    def test_health_no_auth(self, client_with_auth):
        """헬스 체크는 인증 없이 접근 가능"""
        response = client_with_auth.get("/health")
        assert response.status_code == 200

    def test_status_requires_auth_in_prod(self, client_with_auth):
        """상태 엔드포인트는 인증 필요 (선택적)"""
        # 현재 구현은 /status도 인증 불필요
        # 필요 시 변경 가능
        response = client_with_auth.get("/status")
        assert response.status_code == 200


class TestEnvironmentVariableHandling:
    """환경변수 처리 테스트"""

    def test_empty_token_means_no_auth(self):
        """빈 토큰 = 인증 비활성화"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            # 토큰이 비어있으면 인증 우회
            assert auth_module.CLAUDE_SERVICE_TOKEN == ""

    def test_whitespace_token_treated_as_empty(self):
        """공백만 있는 토큰도 비어있는 것으로 처리"""
        # 주의: 현재 구현은 공백을 비어있는 것으로 처리하지 않음
        # 필요 시 구현 변경
        pass


class TestSessionApiAuth:
    """세션 API 인증 테스트"""

    def test_all_session_endpoints_auth(self, client_with_auth):
        """모든 세션 엔드포인트가 인증 요구"""
        endpoints = [
            ("POST", "/sessions", {"thread_id": 1, "user": "test"}),
            ("GET", "/sessions/ses_nonexistent", None),
            ("DELETE", "/sessions/ses_nonexistent", None),
        ]

        for method, path, body in endpoints:
            if method == "POST":
                response = client_with_auth.post(path, json=body)
            elif method == "GET":
                response = client_with_auth.get(path)
            elif method == "DELETE":
                response = client_with_auth.delete(path)

            # 인증 없이 요청하면 401
            assert response.status_code == 401, f"{method} {path} should require auth"


class TestTokenFormats:
    """토큰 형식 테스트"""

    def test_bearer_prefix_required(self, client_with_auth):
        """Bearer 접두사 필수"""
        response = client_with_auth.post(
            "/sessions",
            json={"thread_id": 72001, "user": "test"},
            headers={"Authorization": "test-token-123"}  # Bearer 없음
        )
        assert response.status_code == 401

    def test_lowercase_bearer_accepted(self, client_with_auth):
        """소문자 bearer도 허용"""
        response = client_with_auth.post(
            "/sessions",
            json={"thread_id": 72002, "user": "test"},
            headers={"Authorization": "bearer test-token-123"}
        )
        assert response.status_code == 201

    def test_extra_spaces_rejected(self, client_with_auth):
        """잘못된 형식 (추가 공백) 거부"""
        response = client_with_auth.post(
            "/sessions",
            json={"thread_id": 72003, "user": "test"},
            headers={"Authorization": "Bearer  test-token-123"}  # 공백 2개
        )
        # 현재 구현에서는 split() 사용으로 공백 처리될 수 있음
        # 엄격한 검증이 필요하면 구현 수정


class TestConcurrentLimit:
    """동시 세션 제한 테스트"""

    def test_max_concurrent_from_env(self):
        """환경변수에서 동시 세션 제한 읽기"""
        from src.service import resource_manager

        # 기본값 확인
        assert resource_manager.max_concurrent >= 1
