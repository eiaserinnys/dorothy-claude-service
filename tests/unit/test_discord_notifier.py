"""
DiscordNotifier 단위 테스트

Discord 웹훅 알림 테스트 (실제 웹훅 호출 없이)
"""

import pytest
from unittest.mock import patch, AsyncMock, MagicMock
import aiohttp


@pytest.fixture
def mock_settings():
    """Mock settings"""
    settings = MagicMock()
    settings.discord_webhook_url = ""
    return settings


@pytest.fixture
def notifier_disabled(mock_settings):
    """웹훅 비활성화된 notifier"""
    mock_settings.discord_webhook_url = ""

    with patch('src.service.discord_notifier.get_settings', return_value=mock_settings):
        from src.service.discord_notifier import DiscordNotifier
        return DiscordNotifier()


@pytest.fixture
def notifier_enabled(mock_settings):
    """웹훅 활성화된 notifier"""
    mock_settings.discord_webhook_url = "https://discord.com/api/webhooks/123/abc"

    with patch('src.service.discord_notifier.get_settings', return_value=mock_settings):
        from src.service.discord_notifier import DiscordNotifier
        return DiscordNotifier()


class TestIsEnabled:
    """is_enabled 프로퍼티 테스트"""

    def test_disabled_when_url_empty(self, notifier_disabled):
        """URL이 비어있으면 비활성화"""
        assert notifier_disabled.is_enabled is False

    def test_enabled_when_url_set(self, notifier_enabled):
        """URL이 설정되면 활성화"""
        assert notifier_enabled.is_enabled is True


class TestSendDisabled:
    """웹훅 비활성화 시 _send 테스트"""

    @pytest.mark.asyncio
    async def test_send_returns_false_when_disabled(self, notifier_disabled):
        """비활성화 시 False 반환"""
        result = await notifier_disabled._send("test message")
        assert result is False


class TestNotifyMethods:
    """각 notify_* 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_notify_startup_disabled(self, notifier_disabled):
        """startup 알림 - 비활성화"""
        result = await notifier_disabled.notify_startup(
            version="1.0.0",
            environment="production",
            loaded_tasks=5,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_shutdown_disabled(self, notifier_disabled):
        """shutdown 알림 - 비활성화"""
        result = await notifier_disabled.notify_shutdown(uptime_seconds=3600)
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_task_started_disabled(self, notifier_disabled):
        """태스크 시작 알림 - 비활성화"""
        result = await notifier_disabled.notify_task_started(
            client_id="dorothy_bot",
            request_id="123",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_task_completed_disabled(self, notifier_disabled):
        """태스크 완료 알림 - 비활성화"""
        result = await notifier_disabled.notify_task_completed(
            client_id="dorothy_bot",
            request_id="123",
            duration_seconds=45.5,
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_task_error_disabled(self, notifier_disabled):
        """태스크 에러 알림 - 비활성화"""
        result = await notifier_disabled.notify_task_error(
            client_id="dorothy_bot",
            request_id="123",
            error="Something went wrong",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_reconnect_disabled(self, notifier_disabled):
        """재연결 알림 - 비활성화"""
        result = await notifier_disabled.notify_reconnect(
            client_id="dorothy_bot",
            request_id="123",
            task_status="running",
            has_execution=True,
        )
        assert result is False


class TestSendEnabled:
    """웹훅 활성화 시 _send 테스트"""

    @pytest.mark.asyncio
    async def test_send_success(self, notifier_enabled):
        """성공적인 전송"""
        mock_response = AsyncMock()
        mock_response.status = 204

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        result = await notifier_enabled._send("test message")
        assert result is True

    @pytest.mark.asyncio
    async def test_send_with_embeds(self, notifier_enabled):
        """embed와 함께 전송"""
        mock_response = AsyncMock()
        mock_response.status = 200

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        embeds = [{"title": "Test", "color": 0x00FF00}]
        result = await notifier_enabled._send(content=None, embeds=embeds)
        assert result is True

    @pytest.mark.asyncio
    async def test_send_http_error(self, notifier_enabled):
        """HTTP 에러 처리"""
        mock_response = AsyncMock()
        mock_response.status = 500

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        result = await notifier_enabled._send("test message")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_timeout_error(self, notifier_enabled):
        """타임아웃 에러 처리"""
        import asyncio

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.side_effect = asyncio.TimeoutError()
        mock_session.closed = False

        notifier_enabled._session = mock_session

        result = await notifier_enabled._send("test message")
        assert result is False

    @pytest.mark.asyncio
    async def test_send_generic_error(self, notifier_enabled):
        """일반 에러 처리"""
        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.side_effect = Exception("Network error")
        mock_session.closed = False

        notifier_enabled._session = mock_session

        result = await notifier_enabled._send("test message")
        assert result is False


class TestEmbedFormatting:
    """embed 포맷팅 테스트"""

    @pytest.mark.asyncio
    async def test_notify_shutdown_uptime_formatting(self, notifier_enabled):
        """shutdown 알림의 uptime 포맷팅"""
        mock_response = AsyncMock()
        mock_response.status = 204

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        # 3시간 30분
        await notifier_enabled.notify_shutdown(uptime_seconds=12600)

        # post 호출 확인
        mock_session.post.assert_called_once()
        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')

        # embed에서 uptime 확인
        uptime_field = None
        for field in payload['embeds'][0]['fields']:
            if field['name'] == 'Uptime':
                uptime_field = field['value']
                break

        assert uptime_field == "3h 30m"

    @pytest.mark.asyncio
    async def test_notify_task_completed_duration_formatting(self, notifier_enabled):
        """태스크 완료 알림의 duration 포맷팅"""
        mock_response = AsyncMock()
        mock_response.status = 204

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        # 90초 = 1.5분
        await notifier_enabled.notify_task_completed(
            client_id="test",
            request_id="123",
            duration_seconds=90.0,
        )

        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')

        duration_field = None
        for field in payload['embeds'][0]['fields']:
            if field['name'] == 'Duration':
                duration_field = field['value']
                break

        assert duration_field == "1.5m"

    @pytest.mark.asyncio
    async def test_notify_task_error_truncates_long_error(self, notifier_enabled):
        """에러 메시지 truncate 확인"""
        mock_response = AsyncMock()
        mock_response.status = 204

        mock_session = AsyncMock(spec=aiohttp.ClientSession)
        mock_session.post.return_value.__aenter__.return_value = mock_response
        mock_session.closed = False

        notifier_enabled._session = mock_session

        long_error = "x" * 300  # 200자 초과

        await notifier_enabled.notify_task_error(
            client_id="test",
            request_id="123",
            error=long_error,
        )

        call_args = mock_session.post.call_args
        payload = call_args.kwargs.get('json') or call_args[1].get('json')

        error_field = None
        for field in payload['embeds'][0]['fields']:
            if field['name'] == 'Error':
                error_field = field['value']
                break

        assert len(error_field) <= 200
        assert error_field.endswith("...")


class TestSessionManagement:
    """aiohttp 세션 관리 테스트"""

    @pytest.mark.asyncio
    async def test_get_session_creates_new(self, notifier_enabled):
        """세션이 없으면 새로 생성"""
        notifier_enabled._session = None

        session = await notifier_enabled._get_session()

        assert session is not None
        assert isinstance(session, aiohttp.ClientSession)

        # 정리
        await session.close()

    @pytest.mark.asyncio
    async def test_close_session(self, notifier_enabled):
        """세션 종료"""
        # 세션 생성
        session = await notifier_enabled._get_session()
        assert notifier_enabled._session is not None

        # 종료
        await notifier_enabled.close()

        assert notifier_enabled._session is None
