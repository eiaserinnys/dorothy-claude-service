"""
Test fixtures and configuration
"""

import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def reset_settings():
    """각 테스트 전에 설정 캐시 클리어"""
    # 테스트 환경에서는 개발 모드로 설정 (프로덕션 인증 우회)
    original_env = os.environ.get('ENVIRONMENT')
    os.environ['ENVIRONMENT'] = 'development'

    from src.config import get_settings
    get_settings.cache_clear()

    yield

    # 테스트 후에 원래 환경 복원
    if original_env is not None:
        os.environ['ENVIRONMENT'] = original_env
    elif 'ENVIRONMENT' in os.environ:
        del os.environ['ENVIRONMENT']

    get_settings.cache_clear()


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트"""
    from src.main import app

    with TestClient(app) as client:
        yield client


@pytest.fixture
def mock_session():
    """Mock 세션 데이터"""
    return {
        "session_id": "ses_test123",
        "thread_id": 123456789,
        "user": "testuser#1234",
        "status": "ready",
    }


@pytest.fixture
def mock_claude_response():
    """Mock Claude 응답"""
    return {
        "result": "테스트 응답입니다.",
        "session_id": "abc123",
    }


@pytest.fixture
def auth_headers():
    """인증 헤더"""
    return {"Authorization": "Bearer test-token"}


@pytest.fixture
def test_file(tmp_path):
    """테스트용 파일"""
    file = tmp_path / "test.txt"
    file.write_text("테스트 내용입니다.")
    return file
