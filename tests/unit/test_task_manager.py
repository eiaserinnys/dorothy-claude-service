"""
TaskManager 유닛 테스트

태스크 기반 아키텍처의 핵심 컴포넌트 테스트
"""

import pytest
import asyncio
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock, AsyncMock

# TaskManager가 아직 없으므로 테스트 먼저 작성 (TDD)
# 실제 구현 후 import 경로 수정 필요


class TestTaskManagerUnit:
    """TaskManager 유닛 테스트"""

    # === 태스크 생성 ===

    @pytest.mark.asyncio
    async def test_create_task_success(self, task_manager):
        """태스크 생성 성공"""
        task = await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="테스트 프롬프트",
        )

        assert task.client_id == "dorothy_bot"
        assert task.request_id == "123456789"
        assert task.status == "running"
        assert task.claude_session_id is None  # 실행 시작 전
        assert task.result is None
        assert task.result_delivered is False

    @pytest.mark.asyncio
    async def test_create_task_with_resume_session(self, task_manager):
        """resume_session_id로 태스크 생성"""
        task = await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="테스트",
            resume_session_id="abc-123-def",
        )

        assert task.resume_session_id == "abc-123-def"

    @pytest.mark.asyncio
    async def test_create_task_duplicate_running_conflict(self, task_manager):
        """같은 키로 running 태스크가 있으면 충돌"""
        await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="첫 번째",
        )

        with pytest.raises(TaskConflictError):
            await task_manager.create_task(
                client_id="dorothy_bot",
                request_id="123456789",  # 같은 키
                prompt="두 번째",
            )

    @pytest.mark.asyncio
    async def test_create_task_after_completed_ok(self, task_manager):
        """완료된 태스크가 있으면 새로 생성 가능 (덮어쓰기)"""
        # 첫 번째 태스크 생성 및 완료
        task1 = await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="첫 번째",
        )
        await task_manager.complete_task(
            task1.client_id,
            task1.request_id,
            result="결과",
            claude_session_id="sess-1",
        )
        await task_manager.ack_task(task1.client_id, task1.request_id)

        # 같은 키로 새 태스크 생성
        task2 = await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="두 번째",
        )

        assert task2.status == "running"

    # === 태스크 조회 ===

    @pytest.mark.asyncio
    async def test_get_task_exists(self, task_manager):
        """존재하는 태스크 조회"""
        await task_manager.create_task(
            client_id="dorothy_bot",
            request_id="123456789",
            prompt="테스트",
        )

        task = await task_manager.get_task("dorothy_bot", "123456789")

        assert task is not None
        assert task.request_id == "123456789"

    @pytest.mark.asyncio
    async def test_get_task_not_exists(self, task_manager):
        """존재하지 않는 태스크 조회"""
        task = await task_manager.get_task("dorothy_bot", "nonexistent")

        assert task is None

    @pytest.mark.asyncio
    async def test_get_tasks_by_client(self, task_manager):
        """클라이언트별 태스크 목록 조회"""
        # 여러 클라이언트의 태스크 생성
        await task_manager.create_task("dorothy_bot", "111", "p1")
        await task_manager.create_task("dorothy_bot", "222", "p2")
        await task_manager.create_task("other_service", "333", "p3")

        tasks = await task_manager.get_tasks_by_client("dorothy_bot")

        assert len(tasks) == 2
        request_ids = {t.request_id for t in tasks}
        assert request_ids == {"111", "222"}

    @pytest.mark.asyncio
    async def test_get_tasks_by_client_empty(self, task_manager):
        """태스크가 없는 클라이언트 조회"""
        tasks = await task_manager.get_tasks_by_client("nonexistent")

        assert tasks == []

    # === 태스크 상태 변경 ===

    @pytest.mark.asyncio
    async def test_complete_task_success(self, task_manager):
        """태스크 완료 처리"""
        task = await task_manager.create_task("client", "req1", "prompt")

        await task_manager.complete_task(
            "client",
            "req1",
            result="실행 결과입니다",
            claude_session_id="sess-abc-123",
        )

        updated = await task_manager.get_task("client", "req1")
        assert updated.status == "completed"
        assert updated.result == "실행 결과입니다"
        assert updated.claude_session_id == "sess-abc-123"
        assert updated.completed_at is not None
        assert updated.result_delivered is False

    @pytest.mark.asyncio
    async def test_error_task_success(self, task_manager):
        """태스크 에러 처리"""
        task = await task_manager.create_task("client", "req1", "prompt")

        await task_manager.error_task(
            "client",
            "req1",
            error="실행 중 오류 발생",
        )

        updated = await task_manager.get_task("client", "req1")
        assert updated.status == "error"
        assert updated.error == "실행 중 오류 발생"
        assert updated.completed_at is not None

    @pytest.mark.asyncio
    async def test_ack_task_deletes(self, task_manager):
        """ack 호출 시 태스크 삭제"""
        task = await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess-1")

        result = await task_manager.ack_task("client", "req1")

        assert result is True
        assert await task_manager.get_task("client", "req1") is None

    @pytest.mark.asyncio
    async def test_ack_task_not_found(self, task_manager):
        """없는 태스크 ack"""
        result = await task_manager.ack_task("client", "nonexistent")

        assert result is False

    # === SSE 리스너 관리 ===

    @pytest.mark.asyncio
    async def test_add_listener(self, task_manager):
        """SSE 리스너 추가"""
        task = await task_manager.create_task("client", "req1", "prompt")
        queue = asyncio.Queue()

        await task_manager.add_listener("client", "req1", queue)

        assert len(task.listeners) == 1

    @pytest.mark.asyncio
    async def test_remove_listener(self, task_manager):
        """SSE 리스너 제거"""
        task = await task_manager.create_task("client", "req1", "prompt")
        queue = asyncio.Queue()
        await task_manager.add_listener("client", "req1", queue)

        await task_manager.remove_listener("client", "req1", queue)

        assert len(task.listeners) == 0

    @pytest.mark.asyncio
    async def test_broadcast_to_listeners(self, task_manager):
        """모든 리스너에게 이벤트 브로드캐스트"""
        task = await task_manager.create_task("client", "req1", "prompt")
        queue1 = asyncio.Queue()
        queue2 = asyncio.Queue()
        await task_manager.add_listener("client", "req1", queue1)
        await task_manager.add_listener("client", "req1", queue2)

        event = {"type": "progress", "text": "진행 중..."}
        await task_manager.broadcast("client", "req1", event)

        assert await queue1.get() == event
        assert await queue2.get() == event

    # === 개입 메시지 ===

    @pytest.mark.asyncio
    async def test_add_intervention(self, task_manager):
        """개입 메시지 추가"""
        task = await task_manager.create_task("client", "req1", "prompt")

        position = await task_manager.add_intervention(
            "client",
            "req1",
            text="이것도 확인해줘",
            user="user#1234",
        )

        assert position == 1

    @pytest.mark.asyncio
    async def test_get_intervention(self, task_manager):
        """개입 메시지 가져오기"""
        task = await task_manager.create_task("client", "req1", "prompt")
        await task_manager.add_intervention("client", "req1", "메시지1", "user")
        await task_manager.add_intervention("client", "req1", "메시지2", "user")

        msg1 = await task_manager.get_intervention("client", "req1")
        msg2 = await task_manager.get_intervention("client", "req1")
        msg3 = await task_manager.get_intervention("client", "req1")

        assert msg1["text"] == "메시지1"
        assert msg2["text"] == "메시지2"
        assert msg3 is None

    @pytest.mark.asyncio
    async def test_add_intervention_not_running(self, task_manager):
        """running이 아닌 태스크에 개입 시도"""
        task = await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess")

        with pytest.raises(TaskNotRunningError):
            await task_manager.add_intervention("client", "req1", "메시지", "user")


class TestTaskManagerPersistence:
    """TaskManager 영속화 테스트"""

    @pytest.mark.asyncio
    async def test_save_on_create(self, task_manager, tasks_file):
        """태스크 생성 시 파일 저장"""
        await task_manager.create_task("client", "req1", "prompt")

        # debounce 대기
        await asyncio.sleep(0.6)

        # 파일 확인
        assert tasks_file.exists()
        data = json.loads(tasks_file.read_text())
        assert "client:req1" in data["tasks"]

    @pytest.mark.asyncio
    async def test_save_on_complete(self, task_manager, tasks_file):
        """태스크 완료 시 파일 저장"""
        await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess")

        # debounce 대기
        await asyncio.sleep(0.6)

        data = json.loads(tasks_file.read_text())
        assert data["tasks"]["client:req1"]["status"] == "completed"

    @pytest.mark.asyncio
    async def test_load_on_startup(self, tmp_path):
        """서비스 시작 시 파일에서 로드"""
        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({
            "tasks": {
                "client:req1": {
                    "client_id": "client",
                    "request_id": "req1",
                    "prompt": "test prompt",
                    "status": "completed",
                    "result": "저장된 결과",
                    "claude_session_id": "sess-1",
                    "created_at": "2025-01-22T10:00:00+00:00",
                    "completed_at": "2025-01-22T10:05:00+00:00",
                    "result_delivered": False,
                }
            },
            "last_cleanup": "2025-01-22T09:00:00Z",
        }))

        # 새 TaskManager 생성 (로드)
        manager = TaskManager(storage_path=tasks_file)
        await manager.load()

        task = await manager.get_task("client", "req1")
        assert task is not None
        assert task.result == "저장된 결과"

    @pytest.mark.asyncio
    async def test_mark_running_as_error_on_startup(self, tmp_path):
        """시작 시 running 태스크를 error로 마킹"""
        from src.service.task_manager import TaskStatus

        tasks_file = tmp_path / "tasks.json"
        tasks_file.write_text(json.dumps({
            "tasks": {
                "client:req1": {
                    "client_id": "client",
                    "request_id": "req1",
                    "prompt": "test prompt",
                    "status": "running",  # 서비스 재시작 전 실행 중이던 태스크
                    "created_at": "2025-01-22T10:00:00+00:00",
                    "result_delivered": False,
                }
            },
        }))

        manager = TaskManager(storage_path=tasks_file)
        await manager.load()

        task = await manager.get_task("client", "req1")
        assert task.status == TaskStatus.ERROR
        assert "서비스 재시작" in task.error


class TestTaskManagerCleanup:
    """태스크 정리 테스트"""

    @pytest.mark.asyncio
    async def test_cleanup_old_tasks(self, task_manager):
        """오래된 태스크 정리"""
        from src.service.task_manager import utc_now

        # 오래된 완료 태스크 생성 (수동으로 시간 조작)
        task = await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess")

        # 생성 시간을 25시간 전으로 조작
        task = await task_manager.get_task("client", "req1")
        task.created_at = utc_now() - timedelta(hours=25)

        # 정리 실행
        cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

        assert cleaned == 1
        assert await task_manager.get_task("client", "req1") is None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_recent_tasks(self, task_manager):
        """최근 태스크는 정리 안 함"""
        task = await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess")

        cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

        assert cleaned == 0
        assert await task_manager.get_task("client", "req1") is not None

    @pytest.mark.asyncio
    async def test_cleanup_keeps_running_tasks(self, task_manager):
        """running 태스크는 시간이 지나도 정리 안 함"""
        from src.service.task_manager import utc_now

        task = await task_manager.create_task("client", "req1", "prompt")
        task.created_at = utc_now() - timedelta(hours=25)

        cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)

        assert cleaned == 0
        assert await task_manager.get_task("client", "req1") is not None


class TestTaskManagerAdditional:
    """추가 메서드 테스트"""

    @pytest.mark.asyncio
    async def test_mark_delivered(self, task_manager):
        """결과 전달 완료 마킹"""
        await task_manager.create_task("client", "req1", "prompt")
        await task_manager.complete_task("client", "req1", "결과", "sess")

        result = await task_manager.mark_delivered("client", "req1")

        assert result is True
        task = await task_manager.get_task("client", "req1")
        assert task.result_delivered is True

    @pytest.mark.asyncio
    async def test_mark_delivered_not_found(self, task_manager):
        """없는 태스크에 mark_delivered"""
        result = await task_manager.mark_delivered("client", "nonexistent")

        assert result is False

    @pytest.mark.asyncio
    async def test_get_stats(self, task_manager):
        """통계 조회"""
        # 여러 상태의 태스크 생성
        await task_manager.create_task("client", "req1", "p1")  # running
        await task_manager.create_task("client", "req2", "p2")  # running

        task3 = await task_manager.create_task("client", "req3", "p3")
        await task_manager.complete_task("client", "req3", "결과", "sess")  # completed

        task4 = await task_manager.create_task("client", "req4", "p4")
        await task_manager.error_task("client", "req4", "에러")  # error

        stats = task_manager.get_stats()

        assert stats["total"] == 4
        assert stats["running"] == 2
        assert stats["completed"] == 1
        assert stats["error"] == 1

    @pytest.mark.asyncio
    async def test_send_reconnect_status_running(self, task_manager):
        """재연결 시 running 태스크 상태 전송"""
        task = await task_manager.create_task("client", "req1", "prompt")
        task.last_progress_text = "진행 중..."

        queue = asyncio.Queue()
        await task_manager.add_listener("client", "req1", queue)

        await task_manager.send_reconnect_status("client", "req1", queue)

        event = await queue.get()
        assert event["type"] == "reconnected"
        assert event["status"] == "running"
        assert event["last_progress"] == "진행 중..."

    @pytest.mark.asyncio
    async def test_send_reconnect_status_no_task(self, task_manager):
        """없는 태스크에 재연결 상태 전송 (무시)"""
        queue = asyncio.Queue()

        # 에러 없이 완료되어야 함
        await task_manager.send_reconnect_status("client", "nonexistent", queue)

        assert queue.empty()

    @pytest.mark.asyncio
    async def test_is_execution_running(self, task_manager):
        """실행 중 여부 확인"""
        task = await task_manager.create_task("client", "req1", "prompt")

        # execution_task 없음
        assert task_manager.is_execution_running("client", "req1") is False

        # execution_task 설정
        async def dummy_execution():
            await asyncio.sleep(100)

        task.execution_task = asyncio.create_task(dummy_execution())

        assert task_manager.is_execution_running("client", "req1") is True

        # 정리
        task.execution_task.cancel()
        try:
            await task.execution_task
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_add_intervention_with_attachments(self, task_manager):
        """첨부 파일이 있는 개입 메시지"""
        task = await task_manager.create_task("client", "req1", "prompt")

        position = await task_manager.add_intervention(
            "client",
            "req1",
            text="파일 확인해줘",
            user="user#1234",
            attachment_paths=["/path/to/file1.txt", "/path/to/file2.png"],
        )

        assert position == 1

        msg = await task_manager.get_intervention("client", "req1")
        assert msg["text"] == "파일 확인해줘"
        assert msg["attachment_paths"] == ["/path/to/file1.txt", "/path/to/file2.png"]

    @pytest.mark.asyncio
    async def test_add_intervention_task_not_found(self, task_manager):
        """없는 태스크에 개입 시도"""
        from src.service.task_manager import TaskNotFoundError

        with pytest.raises(TaskNotFoundError):
            await task_manager.add_intervention("client", "nonexistent", "msg", "user")


# === Fixtures ===

from src.service.task_manager import TaskManager, TaskConflictError, TaskNotRunningError


@pytest.fixture
def task_manager(tmp_path):
    """테스트용 TaskManager (메모리 기반 + 임시 파일)"""
    return TaskManager(storage_path=tmp_path / "tasks.json")


@pytest.fixture
def tasks_file(task_manager, tmp_path):
    """태스크 저장 파일 경로"""
    return tmp_path / "tasks.json"
