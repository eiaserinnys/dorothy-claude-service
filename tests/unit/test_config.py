"""
Config 모듈 단위 테스트

환경변수 기반 설정 관리 테스트
"""

import pytest
import logging
from unittest.mock import patch


class TestSettings:
    """Settings 클래스 테스트"""

    def test_default_values(self):
        """기본값 확인"""
        from src.config import Settings

        settings = Settings()

        assert settings.service_name == "dorothy-claude-service"
        assert settings.environment == "development"
        assert settings.port == 8080
        assert settings.max_concurrent_sessions == 3
        assert settings.log_level == "INFO"

    def test_from_env(self):
        """환경변수에서 로드"""
        env = {
            'SERVICE_NAME': 'test-service',
            'ENVIRONMENT': 'production',
            'PORT': '9090',
            'MAX_CONCURRENT_SESSIONS': '5',
            'LOG_LEVEL': 'DEBUG',
            'WORKSPACE_DIR': '/custom/workspace',
            'DISCORD_WEBHOOK_URL': 'https://discord.webhook',
        }

        with patch.dict('os.environ', env, clear=False):
            from src.config import Settings
            settings = Settings.from_env()

            assert settings.service_name == 'test-service'
            assert settings.environment == 'production'
            assert settings.port == 9090
            assert settings.max_concurrent_sessions == 5
            assert settings.log_level == 'DEBUG'
            assert settings.workspace_dir == '/custom/workspace'
            assert settings.discord_webhook_url == 'https://discord.webhook'

    def test_is_production(self):
        """is_production 프로퍼티 테스트"""
        from src.config import Settings

        prod_settings = Settings(environment="production")
        assert prod_settings.is_production is True
        assert prod_settings.is_development is False

        dev_settings = Settings(environment="development")
        assert dev_settings.is_production is False
        assert dev_settings.is_development is True

        staging_settings = Settings(environment="staging")
        assert staging_settings.is_production is False
        assert staging_settings.is_development is False


class TestGetSettings:
    """get_settings 싱글톤 테스트"""

    def test_returns_same_instance(self):
        """같은 인스턴스 반환"""
        from src.config import get_settings

        # lru_cache 초기화를 위해 clear
        get_settings.cache_clear()

        settings1 = get_settings()
        settings2 = get_settings()

        assert settings1 is settings2


class TestSetupLogging:
    """setup_logging 함수 테스트"""

    def test_text_format_in_development(self):
        """개발 모드에서 텍스트 포맷"""
        from src.config import Settings, setup_logging

        settings = Settings(
            environment="development",
            log_level="DEBUG",
            log_format="text",
        )

        logger = setup_logging(settings)

        assert logger.level == logging.DEBUG
        # 핸들러가 설정되었는지 확인
        root_logger = logging.getLogger()
        assert len(root_logger.handlers) > 0

    def test_json_format_in_production(self):
        """프로덕션에서 JSON 포맷"""
        from src.config import Settings, setup_logging

        settings = Settings(
            environment="production",
            log_level="INFO",
            log_format="json",
        )

        logger = setup_logging(settings)

        assert logger.level == logging.INFO

    def test_log_level_mapping(self):
        """로그 레벨 문자열 매핑"""
        from src.config import Settings, setup_logging

        for level_name, level_value in [
            ("DEBUG", logging.DEBUG),
            ("INFO", logging.INFO),
            ("WARNING", logging.WARNING),
            ("ERROR", logging.ERROR),
        ]:
            settings = Settings(log_level=level_name)
            logger = setup_logging(settings)
            assert logger.level == level_value

    def test_invalid_log_level_defaults_to_info(self):
        """잘못된 로그 레벨은 INFO로 기본값"""
        from src.config import Settings, setup_logging

        settings = Settings(log_level="INVALID")
        logger = setup_logging(settings)

        assert logger.level == logging.INFO


class TestSettingsEdgeCases:
    """Settings 엣지 케이스 테스트"""

    def test_empty_token(self):
        """빈 토큰"""
        from src.config import Settings

        settings = Settings(claude_service_token="")
        assert settings.claude_service_token == ""

    def test_port_as_string_from_env(self):
        """환경변수에서 포트가 문자열로 오는 경우"""
        with patch.dict('os.environ', {'PORT': '8888'}, clear=False):
            from src.config import Settings
            settings = Settings.from_env()
            assert settings.port == 8888
            assert isinstance(settings.port, int)

    def test_session_timeout_from_env(self):
        """세션 타임아웃 환경변수"""
        with patch.dict('os.environ', {'SESSION_TIMEOUT_SECONDS': '3600'}, clear=False):
            from src.config import Settings
            settings = Settings.from_env()
            assert settings.session_timeout_seconds == 3600
