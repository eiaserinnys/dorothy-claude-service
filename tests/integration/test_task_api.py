"""
태스크 API 통합 테스트

새 태스크 기반 API 엔드포인트 테스트
"""

import pytest
import pytest_asyncio
import asyncio
import json as json_module
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient
from httpx import ASGITransport, AsyncClient

from src.models import ProgressEvent, CompleteEvent, ErrorEvent


class TestExecuteEndpoint:
    """POST /execute 엔드포인트 테스트

    Note: SSE 스트리밍 테스트는 비동기 이벤트 루프 타이밍 문제로 인해
    태스크 상태 조회 방식으로 테스트합니다.
    """

    @pytest.mark.asyncio
    async def test_execute_success(self, async_client_with_mock, task_manager, auth_headers):
        """정상 실행 → 완료"""
        client, mock_runner = async_client_with_mock

        # Claude runner mock 설정
        mock_runner.execute = lambda **kwargs: async_iter_events([
            ProgressEvent(text="작업 중..."),
            CompleteEvent(result="완료되었습니다", attachments=[], claude_session_id="sess-123"),
        ])

        # 실행 요청 (스트리밍 응답)
        events = await collect_sse_events(
            client,
            "POST",
            "/execute",
            json={
                "client_id": "dorothy_bot",
                "request_id": "thread_123",
                "prompt": "테스트 프롬프트",
            },
            headers=auth_headers,
            timeout=5.0,
        )

        # 이벤트 확인
        assert len(events) >= 1
        # complete 이벤트가 있어야 함
        complete_events = [e for e in events if e.get("type") == "complete"]
        assert len(complete_events) >= 1
        assert complete_events[0]["claude_session_id"] == "sess-123"

    @pytest.mark.asyncio
    async def test_execute_with_resume(self, async_client_with_mock, task_manager, auth_headers):
        """resume_session_id로 실행"""
        client, mock_runner = async_client_with_mock

        mock_runner.execute = lambda **kwargs: async_iter_events([
            CompleteEvent(result="이어서 완료", attachments=[], claude_session_id="sess-123"),
        ])

        events = await collect_sse_events(
            client,
            "POST",
            "/execute",
            json={
                "client_id": "dorothy_bot",
                "request_id": "thread_456",
                "prompt": "이어서 작업",
                "resume_session_id": "sess-old",
            },
            headers=auth_headers,
            timeout=5.0,
        )

        assert len(events) >= 1

        # resume_session_id가 태스크에 저장됨
        task = await task_manager.get_task("dorothy_bot", "thread_456")
        assert task is not None
        assert task.resume_session_id == "sess-old"

    @pytest.mark.asyncio
    async def test_execute_conflict_running(self, async_client_with_mock, task_manager, auth_headers):
        """같은 키로 running 태스크가 있으면 409"""
        client, mock_runner = async_client_with_mock

        # 느린 실행 (완료 안 됨)
        mock_runner.execute = lambda **kwargs: slow_async_iter()

        # 첫 번째 요청 시작 (백그라운드)
        task1 = asyncio.create_task(
            client.post(
                "/execute",
                json={
                    "client_id": "dorothy_bot",
                    "request_id": "conflict_test",
                    "prompt": "첫 번째",
                },
                headers=auth_headers,
            )
        )

        # 잠시 대기 (첫 번째 요청이 시작되도록)
        await asyncio.sleep(0.1)

        # 두 번째 요청 (같은 키) - 409 충돌
        response = await client.post(
            "/execute",
            json={
                "client_id": "dorothy_bot",
                "request_id": "conflict_test",
                "prompt": "두 번째",
            },
            headers=auth_headers,
        )
        assert response.status_code == 409

        # 정리
        task1.cancel()
        try:
            await task1
        except asyncio.CancelledError:
            pass

    @pytest.mark.asyncio
    async def test_execute_error(self, async_client_with_mock, task_manager, auth_headers):
        """실행 중 오류 발생"""
        client, mock_runner = async_client_with_mock

        mock_runner.execute = lambda **kwargs: async_iter_events([
            ProgressEvent(text="시작..."),
            ErrorEvent(message="API 오류 발생"),
        ])

        events = await collect_sse_events(
            client,
            "POST",
            "/execute",
            json={
                "client_id": "dorothy_bot",
                "request_id": "error_test",
                "prompt": "테스트",
            },
            headers=auth_headers,
            timeout=5.0,
        )

        # 에러 이벤트 확인
        error_events = [e for e in events if e.get("type") == "error"]
        assert len(error_events) >= 1
        assert "API 오류 발생" in error_events[0]["message"]


class TestTasksEndpoint:
    """태스크 조회 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_get_tasks_by_client(self, async_client, task_manager, auth_headers):
        """GET /tasks/{client_id}"""
        # 태스크 미리 생성
        await task_manager.create_task("dorothy_bot", "111", "p1")
        await task_manager.create_task("dorothy_bot", "222", "p2")

        response = await async_client.get(
            "/tasks/dorothy_bot",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert len(data["tasks"]) == 2

    @pytest.mark.asyncio
    async def test_get_tasks_empty(self, async_client, auth_headers):
        """태스크 없는 클라이언트 조회"""
        response = await async_client.get(
            "/tasks/nonexistent",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["tasks"] == []

    @pytest.mark.asyncio
    async def test_get_task_detail(self, async_client, task_manager, auth_headers):
        """GET /tasks/{client_id}/{request_id}"""
        await task_manager.create_task("dorothy_bot", "123", "prompt")
        await task_manager.complete_task("dorothy_bot", "123", "결과입니다", "sess-abc")

        response = await async_client.get(
            "/tasks/dorothy_bot/123",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "completed"
        assert data["result"] == "결과입니다"
        assert data["claude_session_id"] == "sess-abc"

    @pytest.mark.asyncio
    async def test_get_task_not_found(self, async_client, auth_headers):
        """존재하지 않는 태스크 조회"""
        response = await async_client.get(
            "/tasks/dorothy_bot/nonexistent",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestStreamReconnectEndpoint:
    """SSE 재연결 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_stream_reconnect_running(self, async_client, task_manager, auth_headers):
        """running 태스크에 SSE 재연결"""
        task = await task_manager.create_task("dorothy_bot", "123", "prompt")

        # 백그라운드에서 이벤트 발송
        async def send_events():
            await asyncio.sleep(0.1)
            await task_manager.broadcast("dorothy_bot", "123", {"type": "progress", "text": "진행중"})
            await asyncio.sleep(0.1)
            await task_manager.complete_task("dorothy_bot", "123", "완료", "sess")
            await task_manager.broadcast("dorothy_bot", "123", {"type": "complete", "result": "완료"})

        asyncio.create_task(send_events())

        async with async_client.stream(
            "GET",
            "/tasks/dorothy_bot/123/stream",
            headers=auth_headers,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    event = json_module.loads(line[5:].strip())
                    events.append(event)
                    if event["type"] == "complete":
                        break

        assert len(events) >= 1

    @pytest.mark.asyncio
    async def test_stream_reconnect_completed(self, async_client, task_manager, auth_headers):
        """completed 태스크에 재연결 → 즉시 결과 반환"""
        await task_manager.create_task("dorothy_bot", "123", "prompt")
        await task_manager.complete_task("dorothy_bot", "123", "결과입니다", "sess-123")

        async with async_client.stream(
            "GET",
            "/tasks/dorothy_bot/123/stream",
            headers=auth_headers,
        ) as response:
            assert response.status_code == 200
            events = []
            async for line in response.aiter_lines():
                if line.startswith("data:"):
                    events.append(json_module.loads(line[5:].strip()))

        # 즉시 complete 이벤트
        assert len(events) == 1
        assert events[0]["type"] == "complete"
        assert events[0]["result"] == "결과입니다"

    @pytest.mark.asyncio
    async def test_stream_reconnect_not_found(self, async_client, auth_headers):
        """없는 태스크에 재연결"""
        response = await async_client.get(
            "/tasks/dorothy_bot/nonexistent/stream",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestAckEndpoint:
    """결과 수신 확인 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_ack_success(self, async_client, task_manager, auth_headers):
        """정상 ack → 태스크 삭제"""
        await task_manager.create_task("dorothy_bot", "123", "prompt")
        await task_manager.complete_task("dorothy_bot", "123", "결과", "sess")

        response = await async_client.post(
            "/tasks/dorothy_bot/123/ack",
            headers=auth_headers,
        )

        assert response.status_code == 200

        # 태스크 삭제 확인
        task = await task_manager.get_task("dorothy_bot", "123")
        assert task is None

    @pytest.mark.asyncio
    async def test_ack_not_found(self, async_client, auth_headers):
        """없는 태스크 ack"""
        response = await async_client.post(
            "/tasks/dorothy_bot/nonexistent/ack",
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestInterveneEndpoint:
    """개입 메시지 엔드포인트 테스트"""

    @pytest.mark.asyncio
    async def test_intervene_success(self, async_client, task_manager, auth_headers):
        """실행 중 개입 메시지 전송"""
        await task_manager.create_task("dorothy_bot", "123", "prompt")

        response = await async_client.post(
            "/tasks/dorothy_bot/123/intervene",
            json={
                "text": "이것도 확인해줘",
                "user": "user#1234",
            },
            headers=auth_headers,
        )

        assert response.status_code == 202
        data = response.json()
        assert data["queued"] is True
        assert data["queue_position"] == 1

    @pytest.mark.asyncio
    async def test_intervene_not_running(self, async_client, task_manager, auth_headers):
        """running이 아닌 태스크에 개입"""
        await task_manager.create_task("dorothy_bot", "123", "prompt")
        await task_manager.complete_task("dorothy_bot", "123", "결과", "sess")

        response = await async_client.post(
            "/tasks/dorothy_bot/123/intervene",
            json={
                "text": "개입 시도",
                "user": "user#1234",
            },
            headers=auth_headers,
        )

        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_intervene_not_found(self, async_client, auth_headers):
        """없는 태스크에 개입"""
        response = await async_client.post(
            "/tasks/dorothy_bot/nonexistent/intervene",
            json={
                "text": "개입 시도",
                "user": "user#1234",
            },
            headers=auth_headers,
        )

        assert response.status_code == 404


class TestClientDisconnect:
    """클라이언트 연결 끊김 시나리오 테스트"""

    @pytest.mark.asyncio
    async def test_disconnect_during_execution(self, async_client_with_mock, task_manager, auth_headers):
        """실행 중 클라이언트 연결 끊김 → 결과 보관"""
        client, mock_runner = async_client_with_mock

        # 느린 실행 시뮬레이션
        mock_runner.execute = lambda **kwargs: slow_async_iter_with_complete()

        # 요청 시작 (백그라운드)
        req_task = asyncio.create_task(
            client.post(
                "/execute",
                json={
                    "client_id": "dorothy_bot",
                    "request_id": "disconnect_test",
                    "prompt": "테스트",
                },
                headers=auth_headers,
            )
        )

        # 잠시 대기 후 요청 취소 (클라이언트 연결 끊김 시뮬레이션)
        await asyncio.sleep(0.1)
        req_task.cancel()
        try:
            await req_task
        except asyncio.CancelledError:
            pass

        # 백그라운드 실행은 계속 진행되어 완료
        await asyncio.sleep(0.5)

        # 태스크 상태 확인 (결과 보관됨)
        stored_task = await task_manager.get_task("dorothy_bot", "disconnect_test")
        assert stored_task is not None
        assert stored_task.status.value == "completed"
        assert stored_task.result_delivered is False

    @pytest.mark.asyncio
    async def test_reconnect_after_disconnect(self, async_client_with_mock, task_manager, auth_headers):
        """연결 끊김 후 재연결하여 결과 수신"""
        client, _ = async_client_with_mock

        # 완료된 태스크 생성 (미전달)
        await task_manager.create_task("dorothy_bot", "reconnect_test", "prompt")
        await task_manager.complete_task("dorothy_bot", "reconnect_test", "저장된 결과", "sess")

        # 재연결 (GET으로 태스크 조회)
        response = await client.get(
            "/tasks/dorothy_bot/reconnect_test",
            headers=auth_headers,
        )

        assert response.status_code == 200
        data = response.json()
        assert data["result"] == "저장된 결과"
        assert data["status"] == "completed"


# === Helper Functions ===

async def collect_sse_events(client, method, url, *, json=None, headers=None, timeout=5.0, max_events=10):
    """SSE 스트림에서 이벤트 수집

    Args:
        client: httpx AsyncClient
        method: HTTP 메서드
        url: 요청 URL
        json: 요청 body
        headers: 요청 헤더
        timeout: 타임아웃 (초)
        max_events: 최대 수집 이벤트 수

    Returns:
        수집된 이벤트 리스트 (dict)
    """
    events = []

    async with client.stream(
        method,
        url,
        json=json,
        headers=headers,
        timeout=timeout,
    ) as response:
        if response.status_code != 200:
            return events

        async for line in response.aiter_lines():
            if line.startswith("data:"):
                try:
                    event = json_module.loads(line[5:].strip())
                    events.append(event)

                    # 완료/에러 이벤트 또는 최대 개수 도달 시 종료
                    if event.get("type") in ["complete", "error"] or len(events) >= max_events:
                        break
                except json_module.JSONDecodeError:
                    pass

    return events


async def async_iter_events(events, initial_delay=0.1):
    """이벤트 리스트를 async iterator로 변환

    Args:
        events: 이벤트 리스트
        initial_delay: SSE listener가 등록될 시간을 확보하기 위한 초기 대기 시간
    """
    # SSE listener가 등록될 시간 확보 (race condition 방지)
    await asyncio.sleep(initial_delay)
    for event in events:
        yield event
        await asyncio.sleep(0.01)  # 이벤트 간 짧은 간격


async def slow_async_iter():
    """느린 async iterator (테스트 타임아웃용)"""
    await asyncio.sleep(0.1)
    yield ProgressEvent(text="시작...")
    await asyncio.sleep(10)  # 오래 걸림


async def slow_async_iter_with_complete():
    """느린 async iterator + 완료"""
    await asyncio.sleep(0.1)  # SSE listener 등록 대기
    yield ProgressEvent(text="시작...")
    await asyncio.sleep(0.3)
    yield CompleteEvent(result="완료됨", attachments=[], claude_session_id="sess-123")


# === Fixtures ===

@pytest.fixture
def auth_headers():
    """인증 헤더"""
    return {"Authorization": "Bearer test-token"}


@pytest_asyncio.fixture
async def task_manager(tmp_path):
    """테스트용 TaskManager (격리된 인스턴스)"""
    from src.service.task_manager import TaskManager, get_task_manager, set_task_manager

    # 기존 매니저 백업
    try:
        old_manager = get_task_manager()
    except RuntimeError:
        old_manager = None

    # 테스트용 임시 파일 경로로 새 TaskManager 생성
    test_storage = tmp_path / "tasks.json"
    manager = TaskManager(storage_path=test_storage)
    await manager.load()

    # 전역 인스턴스 교체
    set_task_manager(manager)

    yield manager

    # 정리: 실행 중인 태스크 취소
    await manager.cancel_running_tasks(timeout=1.0)
    set_task_manager(old_manager)


@pytest_asyncio.fixture
async def async_client(task_manager):
    """비동기 테스트 클라이언트 (인증 비활성화, mock 없음)"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test"
        ) as client:
            yield client


@pytest_asyncio.fixture
async def async_client_with_mock(task_manager):
    """비동기 테스트 클라이언트 + Claude runner mock (실행 테스트용)

    mock을 먼저 설정한 후 클라이언트를 생성하여 타이밍 문제 방지
    """
    mock_runner = MagicMock()

    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        # Claude runner mock 적용
        with patch("src.api.tasks.claude_runner", mock_runner):
            from src.main import app
            async with AsyncClient(
                transport=ASGITransport(app=app),
                base_url="http://test"
            ) as client:
                yield client, mock_runner
