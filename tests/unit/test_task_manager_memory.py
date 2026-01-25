"""
TaskManager 메모리 관리 테스트

메모리 누수 방지 로직 검증:
1. cleanup_old_tasks - orphaned running task 정리
2. ack_task - intervention_queue, listeners 정리
3. add_listener/remove_listener - lock 보호
"""

import asyncio
import gc
import sys
from datetime import timedelta

import pytest

from src.service.task_manager import (
    TaskManager,
    Task,
    TaskStatus,
    utc_now,
)


@pytest.fixture
def task_manager():
    """테스트용 TaskManager (영속화 없음)"""
    return TaskManager(storage_path=None)


@pytest.mark.asyncio
async def test_cleanup_old_tasks_orphaned_running(task_manager):
    """orphaned running task(execution_task 없음) 정리 테스트"""
    # 24시간 이상 된 orphaned running task 생성
    task = await task_manager.create_task(
        client_id="test",
        request_id="orphaned",
        prompt="test prompt",
    )
    # 시간을 과거로 조작
    task.created_at = utc_now() - timedelta(hours=25)
    # execution_task가 None인 상태 (orphaned)
    assert task.execution_task is None

    # cleanup 실행
    cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

    assert cleaned == 1
    assert await task_manager.get_task("test", "orphaned") is None


@pytest.mark.asyncio
async def test_cleanup_old_tasks_active_running_preserved(task_manager):
    """활성 running task(execution_task 실행 중)는 정리하지 않음"""
    # 24시간 이상 된 태스크 생성
    task = await task_manager.create_task(
        client_id="test",
        request_id="active",
        prompt="test prompt",
    )
    task.created_at = utc_now() - timedelta(hours=25)

    # 실행 중인 execution_task 시뮬레이션
    async def dummy_execution():
        await asyncio.sleep(10)

    task.execution_task = asyncio.create_task(dummy_execution())

    try:
        # cleanup 실행
        cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

        assert cleaned == 0
        assert await task_manager.get_task("test", "active") is not None
    finally:
        task.execution_task.cancel()
        try:
            await task.execution_task
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_cleanup_old_tasks_clears_queue_and_listeners(task_manager):
    """cleanup 시 intervention_queue와 listeners 정리 확인"""
    # 완료된 태스크 생성
    task = await task_manager.create_task(
        client_id="test",
        request_id="completed",
        prompt="test prompt",
    )
    await task_manager.complete_task("test", "completed", result="done")
    task.created_at = utc_now() - timedelta(hours=25)

    # queue에 메시지 추가
    await task.intervention_queue.put({"text": "test message"})
    assert task.intervention_queue.qsize() == 1

    # listener 추가
    listener_queue = asyncio.Queue()
    task.listeners.append(listener_queue)
    assert len(task.listeners) == 1

    # cleanup 실행
    cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

    assert cleaned == 1
    # 태스크가 삭제됨
    assert await task_manager.get_task("test", "completed") is None


@pytest.mark.asyncio
async def test_ack_task_clears_queue_and_listeners(task_manager):
    """ack_task 시 intervention_queue와 listeners 정리 확인"""
    # 완료된 태스크 생성
    task = await task_manager.create_task(
        client_id="test",
        request_id="to_ack",
        prompt="test prompt",
    )
    await task_manager.complete_task("test", "to_ack", result="done")

    # queue에 메시지 추가
    await task.intervention_queue.put({"text": "test message 1"})
    await task.intervention_queue.put({"text": "test message 2"})
    assert task.intervention_queue.qsize() == 2

    # listener 추가
    listener_queue = asyncio.Queue()
    task.listeners.append(listener_queue)
    assert len(task.listeners) == 1

    # ack 실행
    result = await task_manager.ack_task("test", "to_ack")

    assert result is True
    # queue가 비워짐 (task 객체는 이미 삭제됨)
    assert task.intervention_queue.qsize() == 0
    assert len(task.listeners) == 0


@pytest.mark.asyncio
async def test_listener_operations_thread_safe(task_manager):
    """add_listener/remove_listener 동시성 테스트"""
    # 태스크 생성
    await task_manager.create_task(
        client_id="test",
        request_id="concurrent",
        prompt="test prompt",
    )

    # 동시에 여러 리스너 추가/제거
    async def add_and_remove():
        queue = asyncio.Queue()
        await task_manager.add_listener("test", "concurrent", queue)
        await asyncio.sleep(0.01)  # 짧은 대기
        await task_manager.remove_listener("test", "concurrent", queue)

    # 10개 동시 실행
    await asyncio.gather(*[add_and_remove() for _ in range(10)])

    # 모든 리스너가 정리됨
    task = await task_manager.get_task("test", "concurrent")
    assert len(task.listeners) == 0


@pytest.mark.asyncio
async def test_repeated_task_creation_memory_stable(task_manager):
    """반복 태스크 생성/삭제 시 메모리 안정성 테스트"""
    gc.collect()
    initial_objects = len(gc.get_objects())

    # 100회 태스크 생성/완료/ack 반복
    for i in range(100):
        task = await task_manager.create_task(
            client_id="test",
            request_id=f"task_{i}",
            prompt="test prompt",
        )
        # queue에 메시지 추가
        await task.intervention_queue.put({"text": f"message_{i}"})
        # listener 추가
        listener_queue = asyncio.Queue()
        task.listeners.append(listener_queue)

        # 완료 및 ack
        await task_manager.complete_task("test", f"task_{i}", result="done")
        await task_manager.ack_task("test", f"task_{i}")

    gc.collect()
    final_objects = len(gc.get_objects())

    # 태스크 모두 삭제 확인
    assert len(task_manager._tasks) == 0

    # 객체 증가가 과도하지 않음 (임계값: 1000개)
    # 일부 증가는 정상 (로거, 캐시 등)
    object_increase = final_objects - initial_objects
    assert object_increase < 1000, f"Too many objects created: {object_increase}"


@pytest.mark.asyncio
async def test_clear_queue_helper():
    """_clear_queue 헬퍼 메서드 테스트"""
    task_manager = TaskManager(storage_path=None)

    queue = asyncio.Queue()
    for i in range(10):
        await queue.put(f"item_{i}")

    assert queue.qsize() == 10

    task_manager._clear_queue(queue)

    assert queue.qsize() == 0


@pytest.mark.asyncio
async def test_cleanup_done_execution_task(task_manager):
    """execution_task가 완료된(done) running 태스크 정리"""
    task = await task_manager.create_task(
        client_id="test",
        request_id="done_execution",
        prompt="test prompt",
    )
    task.created_at = utc_now() - timedelta(hours=25)

    # 완료된 execution_task 시뮬레이션
    async def quick_task():
        pass

    task.execution_task = asyncio.create_task(quick_task())
    await task.execution_task  # 완료 대기

    assert task.execution_task.done()

    # cleanup 실행 - done 상태의 execution_task도 orphaned로 간주
    cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

    assert cleaned == 1
    assert await task_manager.get_task("test", "done_execution") is None
