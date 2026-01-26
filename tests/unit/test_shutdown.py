"""
Shutdown 시 활성 태스크 정리 테스트

진단: 서비스 종료 시 실행 중인 태스크(execution_task)가 취소되지 않아
고아 프로세스가 남는 문제 검증.
"""

import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from src.service.task_manager import TaskManager, Task, TaskStatus


class TestShutdownTaskCleanup:
    """Shutdown 시 태스크 정리 테스트"""

    @pytest.fixture
    def task_manager(self, tmp_path):
        """테스트용 TaskManager"""
        return TaskManager(storage_path=tmp_path / "tasks.json")

    @pytest.fixture
    def running_task(self):
        """실행 중인 태스크"""
        task = Task(
            client_id="test_client",
            request_id="test_request",
            prompt="테스트 프롬프트",
            status=TaskStatus.RUNNING,
        )
        return task

    @pytest.mark.asyncio
    async def test_running_task_has_execution_task(self, task_manager, running_task):
        """실행 중인 태스크는 execution_task를 가짐"""
        # 태스크 생성
        task = await task_manager.create_task(
            client_id="test_client",
            request_id="test_request",
            prompt="테스트 프롬프트",
        )

        # 더미 execution_task 설정
        async def dummy_execution():
            await asyncio.sleep(100)

        task.execution_task = asyncio.create_task(dummy_execution())

        # execution_task가 있는지 확인
        assert task.execution_task is not None
        assert not task.execution_task.done()

        # 정리
        task.execution_task.cancel()
        try:
            await task.execution_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_shutdown_without_cleanup_leaves_execution_running(self, task_manager):
        """
        문제 재현: shutdown 시 execution_task 정리 로직이 없으면
        태스크가 계속 실행됨
        """
        execution_started = asyncio.Event()
        execution_cancelled = asyncio.Event()

        async def long_running_execution():
            execution_started.set()
            try:
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                execution_cancelled.set()
                raise

        # 태스크 생성 및 실행 시작
        task = await task_manager.create_task(
            client_id="test_client",
            request_id="test_request",
            prompt="테스트 프롬프트",
        )
        task.execution_task = asyncio.create_task(long_running_execution())

        # 실행 시작 대기
        await asyncio.wait_for(execution_started.wait(), timeout=1.0)

        # 현재 shutdown 로직 - execution_task를 취소하지 않음
        # (main.py lifespan의 현재 동작 시뮬레이션)
        await task_manager.save()

        # 문제: execution_task가 여전히 실행 중
        assert not task.execution_task.done()
        assert not execution_cancelled.is_set()

        # 정리
        task.execution_task.cancel()
        try:
            await task.execution_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_shutdown_with_cleanup_cancels_execution(self, task_manager):
        """
        해결책: shutdown 시 execution_task를 명시적으로 취소해야 함
        """
        execution_started = asyncio.Event()
        execution_cancelled = asyncio.Event()

        async def long_running_execution():
            try:
                execution_started.set()
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                execution_cancelled.set()
                raise

        # 태스크 생성 및 실행 시작
        task = await task_manager.create_task(
            client_id="test_client",
            request_id="test_request",
            prompt="테스트 프롬프트",
        )
        task.execution_task = asyncio.create_task(long_running_execution())

        # 태스크가 시작될 때까지 대기
        await asyncio.wait_for(execution_started.wait(), timeout=1.0)

        # 개선된 shutdown 로직 - cancel_running_tasks 호출
        await task_manager.cancel_running_tasks()

        # execution_task가 취소됨
        assert execution_cancelled.is_set()

    @pytest.mark.asyncio
    async def test_cancel_running_tasks_method(self, task_manager):
        """cancel_running_tasks 메서드가 모든 running 태스크를 취소함"""
        cancelled_tasks = []
        started_events = []

        async def make_execution(task_id, started_event):
            try:
                started_event.set()
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancelled_tasks.append(task_id)
                raise

        # 여러 태스크 생성
        for i in range(3):
            task = await task_manager.create_task(
                client_id="test_client",
                request_id=f"request_{i}",
                prompt=f"프롬프트 {i}",
            )
            started = asyncio.Event()
            started_events.append(started)
            task.execution_task = asyncio.create_task(make_execution(i, started))

        # 모든 태스크가 시작될 때까지 대기
        await asyncio.gather(*[e.wait() for e in started_events])

        # 실행 중인 태스크 확인
        running = [t for t in task_manager._tasks.values() if t.execution_task]
        assert len(running) == 3

        # 모든 running 태스크 취소
        await task_manager.cancel_running_tasks()

        # 모든 태스크가 취소됨
        assert len(cancelled_tasks) == 3
        assert set(cancelled_tasks) == {0, 1, 2}

    @pytest.mark.asyncio
    async def test_cancel_running_tasks_timeout(self, task_manager):
        """취소가 오래 걸리는 태스크도 timeout 내에 처리됨"""
        execution_started = asyncio.Event()
        cancellation_started = asyncio.Event()

        async def slow_cleanup_execution():
            try:
                execution_started.set()
                await asyncio.sleep(100)
            except asyncio.CancelledError:
                cancellation_started.set()
                # 느린 정리 작업 시뮬레이션
                await asyncio.sleep(0.5)
                raise

        task = await task_manager.create_task(
            client_id="test_client",
            request_id="test_request",
            prompt="테스트 프롬프트",
        )
        task.execution_task = asyncio.create_task(slow_cleanup_execution())

        # 태스크가 시작될 때까지 대기
        await asyncio.wait_for(execution_started.wait(), timeout=1.0)

        # timeout 지정하여 취소
        await task_manager.cancel_running_tasks(timeout=2.0)

        # 취소가 시작되었는지 확인
        assert cancellation_started.is_set()


class TestTaskManagerCancelMethod:
    """TaskManager.cancel_running_tasks() 메서드 존재 여부 테스트"""

    def test_cancel_running_tasks_method_exists(self):
        """cancel_running_tasks 메서드가 존재해야 함"""
        manager = TaskManager()
        assert hasattr(manager, 'cancel_running_tasks')
        assert callable(getattr(manager, 'cancel_running_tasks'))
