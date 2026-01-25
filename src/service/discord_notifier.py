"""
Discord Webhook Notifier

서비스 이벤트를 Discord 웹훅으로 발송합니다.
환경변수 DISCORD_WEBHOOK_URL이 설정된 경우에만 활성화됩니다.
"""

import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from src.config import get_settings

logger = logging.getLogger(__name__)

# 웹훅 발송 타임아웃 (초)
WEBHOOK_TIMEOUT = 5


class DiscordNotifier:
    """
    Discord 웹훅 알림 발송기

    주요 이벤트:
    - 서버 기동/종료
    - 태스크 시작/완료/에러
    - 재연결
    """

    def __init__(self):
        self._session: Optional[aiohttp.ClientSession] = None
        self._settings = get_settings()

    @property
    def is_enabled(self) -> bool:
        """웹훅이 설정되었고 프로덕션 환경인지 확인

        개발 환경에서는 웹훅을 발송하지 않음.
        """
        return bool(self._settings.discord_webhook_url) and self._settings.is_production

    @property
    def webhook_url(self) -> str:
        return self._settings.discord_webhook_url

    async def _get_session(self) -> aiohttp.ClientSession:
        """aiohttp 세션 반환 (lazy 초기화)"""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=WEBHOOK_TIMEOUT)
            self._session = aiohttp.ClientSession(timeout=timeout)
        return self._session

    async def close(self) -> None:
        """세션 종료"""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    async def _send(self, content: str, embeds: Optional[list] = None) -> bool:
        """
        웹훅 메시지 발송 (fire-and-forget)

        실패해도 서비스에 영향 없음.
        """
        if not self.is_enabled:
            return False

        try:
            session = await self._get_session()
            payload = {}

            if content:
                payload["content"] = content
            if embeds:
                payload["embeds"] = embeds

            async with session.post(self.webhook_url, json=payload) as response:
                if response.status in (200, 204):
                    return True
                else:
                    logger.warning(f"Discord webhook failed: HTTP {response.status}")
                    return False

        except asyncio.TimeoutError:
            logger.warning("Discord webhook timeout")
            return False
        except Exception as e:
            logger.warning(f"Discord webhook error: {e}")
            return False

    def _timestamp(self) -> str:
        """현재 시간 포맷"""
        return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    # === 서버 이벤트 ===

    async def notify_startup(self, version: str, environment: str, loaded_tasks: int) -> bool:
        """서버 기동 알림"""
        embed = {
            "title": "Claude Code Service Started",
            "color": 0x00FF00,  # 초록
            "fields": [
                {"name": "Version", "value": version, "inline": True},
                {"name": "Environment", "value": environment, "inline": True},
                {"name": "Loaded Tasks", "value": str(loaded_tasks), "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])

    async def notify_shutdown(self, uptime_seconds: int) -> bool:
        """서버 종료 알림"""
        hours = uptime_seconds // 3600
        minutes = (uptime_seconds % 3600) // 60
        uptime_str = f"{hours}h {minutes}m"

        embed = {
            "title": "Claude Code Service Stopping",
            "color": 0xFFA500,  # 주황
            "fields": [
                {"name": "Uptime", "value": uptime_str, "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])

    # === 태스크 이벤트 ===

    async def notify_task_started(self, client_id: str, request_id: str) -> bool:
        """태스크 시작 알림"""
        embed = {
            "title": "Task Started",
            "color": 0x3498DB,  # 파랑
            "fields": [
                {"name": "Client", "value": client_id, "inline": True},
                {"name": "Request", "value": request_id, "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])

    async def notify_task_completed(
        self,
        client_id: str,
        request_id: str,
        duration_seconds: Optional[float] = None
    ) -> bool:
        """태스크 완료 알림"""
        fields = [
            {"name": "Client", "value": client_id, "inline": True},
            {"name": "Request", "value": request_id, "inline": True},
        ]

        if duration_seconds is not None:
            if duration_seconds >= 60:
                duration_str = f"{duration_seconds / 60:.1f}m"
            else:
                duration_str = f"{duration_seconds:.1f}s"
            fields.append({"name": "Duration", "value": duration_str, "inline": True})

        embed = {
            "title": "Task Completed",
            "color": 0x00FF00,  # 초록
            "fields": fields,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])

    async def notify_task_error(
        self,
        client_id: str,
        request_id: str,
        error: str
    ) -> bool:
        """태스크 에러 알림"""
        # 에러 메시지 truncate (Discord embed field 제한)
        if len(error) > 200:
            error = error[:197] + "..."

        embed = {
            "title": "Task Error",
            "color": 0xFF0000,  # 빨강
            "fields": [
                {"name": "Client", "value": client_id, "inline": True},
                {"name": "Request", "value": request_id, "inline": True},
                {"name": "Error", "value": error, "inline": False},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])

    # === 재연결 이벤트 ===

    async def notify_reconnect(
        self,
        client_id: str,
        request_id: str,
        task_status: str,
        has_execution: bool
    ) -> bool:
        """재연결 알림"""
        embed = {
            "title": "Client Reconnected",
            "color": 0x9B59B6,  # 보라
            "fields": [
                {"name": "Client", "value": client_id, "inline": True},
                {"name": "Request", "value": request_id, "inline": True},
                {"name": "Task Status", "value": task_status, "inline": True},
                {"name": "Execution Active", "value": "Yes" if has_execution else "No", "inline": True},
            ],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        return await self._send(content=None, embeds=[embed])


# 싱글톤 인스턴스
discord_notifier = DiscordNotifier()
