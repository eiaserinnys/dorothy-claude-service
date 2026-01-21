"""
ResourceManager 단위 테스트
"""

import pytest
import asyncio

from src.service.resource_manager import ResourceManager


@pytest.fixture
def resource_manager():
    """테스트용 ResourceManager (max_concurrent=2)"""
    return ResourceManager(max_concurrent=2)


def test_initial_state(resource_manager):
    """초기 상태 테스트"""
    assert resource_manager.max_concurrent == 2
    assert resource_manager.active_count == 0
    assert resource_manager.available_slots == 2
    assert resource_manager.can_acquire() is True


@pytest.mark.asyncio
async def test_acquire_and_release(resource_manager):
    """리소스 획득/해제 테스트"""
    async with resource_manager.acquire():
        assert resource_manager.active_count == 1
        assert resource_manager.available_slots == 1

    assert resource_manager.active_count == 0
    assert resource_manager.available_slots == 2


@pytest.mark.asyncio
async def test_concurrent_acquire(resource_manager):
    """동시 획득 테스트"""
    async def task(delay: float):
        async with resource_manager.acquire():
            await asyncio.sleep(delay)

    # 2개 동시 실행 가능
    tasks = [
        asyncio.create_task(task(0.1)),
        asyncio.create_task(task(0.1)),
    ]

    await asyncio.sleep(0.05)
    assert resource_manager.active_count == 2
    assert resource_manager.can_acquire() is False

    await asyncio.gather(*tasks)
    assert resource_manager.active_count == 0


@pytest.mark.asyncio
async def test_acquire_timeout(resource_manager):
    """리소스 획득 타임아웃 테스트"""
    # 2개 슬롯 점유
    async with resource_manager.acquire():
        async with resource_manager.acquire():
            # 3번째 획득 시도 - 타임아웃
            with pytest.raises(RuntimeError, match="동시 실행 제한"):
                async with resource_manager.acquire(timeout=0.1):
                    pass


def test_get_system_memory(resource_manager):
    """시스템 메모리 조회 테스트"""
    used_gb, total_gb, percent = resource_manager.get_system_memory()

    assert used_gb >= 0
    assert total_gb > 0
    assert 0 <= percent <= 100


def test_get_stats(resource_manager):
    """통계 조회 테스트"""
    stats = resource_manager.get_stats()

    assert "active_sessions" in stats
    assert "max_concurrent" in stats
    assert "available_slots" in stats
    assert "memory" in stats
    assert stats["max_concurrent"] == 2
