"""
Auth 모듈 단위 테스트

Bearer 토큰 인증 검증 테스트
"""

import pytest
from unittest.mock import patch
from fastapi import HTTPException


class TestVerifyToken:
    """verify_token 함수 테스트"""

    @pytest.mark.asyncio
    async def test_dev_mode_no_token_configured(self):
        """개발 모드: 토큰이 설정되지 않으면 인증 우회"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': '', 'ENVIRONMENT': 'development'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            import src.config as config_module
            # 캐시된 설정을 클리어
            config_module.get_settings.cache_clear()
            importlib.reload(auth_module)

            result = await auth_module.verify_token(None)
            assert result == ""

    @pytest.mark.asyncio
    async def test_missing_authorization_header(self):
        """인증 헤더 없으면 401"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            with pytest.raises(HTTPException) as exc_info:
                await auth_module.verify_token(None)

            assert exc_info.value.status_code == 401
            assert "Authorization 헤더가 필요합니다" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_bearer_format_no_bearer_prefix(self):
        """Bearer 접두사 없으면 401"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            with pytest.raises(HTTPException) as exc_info:
                await auth_module.verify_token("secret-token")  # Bearer 없음

            assert exc_info.value.status_code == 401
            assert "Bearer 토큰 형식" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_invalid_bearer_format_wrong_prefix(self):
        """잘못된 접두사면 401"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            with pytest.raises(HTTPException) as exc_info:
                await auth_module.verify_token("Basic secret-token")

            assert exc_info.value.status_code == 401

    @pytest.mark.asyncio
    async def test_invalid_token_value(self):
        """토큰 값이 틀리면 401"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            with pytest.raises(HTTPException) as exc_info:
                await auth_module.verify_token("Bearer wrong-token")

            assert exc_info.value.status_code == 401
            assert "유효하지 않은 토큰" in str(exc_info.value.detail)

    @pytest.mark.asyncio
    async def test_valid_token(self):
        """올바른 토큰이면 성공"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            result = await auth_module.verify_token("Bearer secret-token")
            assert result == "secret-token"

    @pytest.mark.asyncio
    async def test_bearer_case_insensitive(self):
        """Bearer는 대소문자 구분 안 함"""
        with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'secret-token'}, clear=False):
            import importlib
            import src.api.auth as auth_module
            importlib.reload(auth_module)

            result = await auth_module.verify_token("bearer secret-token")
            assert result == "secret-token"
