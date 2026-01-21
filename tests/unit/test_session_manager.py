"""
SessionManager 단위 테스트
"""

import pytest
import asyncio

from src.service.session_manager import SessionManager
from src.models import SessionStatus


@pytest.fixture
def session_manager():
    """테스트용 SessionManager"""
    return SessionManager()


@pytest.mark.asyncio
async def test_create_session(session_manager):
    """세션 생성 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    assert session.session_id.startswith("ses_")
    assert session.thread_id == 123456
    assert session.user == "test_user#1234"
    assert session.status == SessionStatus.READY


@pytest.mark.asyncio
async def test_create_session_conflict(session_manager):
    """중복 세션 생성 시 에러 테스트"""
    await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    with pytest.raises(ValueError, match="already has an active session"):
        await session_manager.create_session(
            thread_id=123456,
            user="another_user#5678",
        )


@pytest.mark.asyncio
async def test_get_session(session_manager):
    """세션 조회 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    retrieved = await session_manager.get_session(session.session_id)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id

    # 존재하지 않는 세션
    not_found = await session_manager.get_session("ses_nonexistent")
    assert not_found is None


@pytest.mark.asyncio
async def test_get_session_by_thread(session_manager):
    """thread_id로 세션 조회 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    retrieved = await session_manager.get_session_by_thread(123456)
    assert retrieved is not None
    assert retrieved.session_id == session.session_id

    # 존재하지 않는 thread
    not_found = await session_manager.get_session_by_thread(999999)
    assert not_found is None


@pytest.mark.asyncio
async def test_update_status(session_manager):
    """세션 상태 업데이트 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    updated = await session_manager.update_status(
        session.session_id,
        SessionStatus.RUNNING,
    )
    assert updated is not None
    assert updated.status == SessionStatus.RUNNING

    # 완료 상태로 변경 시 thread_sessions에서 제거
    updated = await session_manager.update_status(
        session.session_id,
        SessionStatus.COMPLETED,
        result="Test result",
    )
    assert updated.status == SessionStatus.COMPLETED
    assert updated.result == "Test result"

    # thread_id로 조회 시 None
    by_thread = await session_manager.get_session_by_thread(123456)
    assert by_thread is None


@pytest.mark.asyncio
async def test_delete_session(session_manager):
    """세션 삭제 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    deleted = await session_manager.delete_session(session.session_id)
    assert deleted is not None
    assert deleted.status == SessionStatus.TERMINATED

    # thread_id로 조회 시 None
    by_thread = await session_manager.get_session_by_thread(123456)
    assert by_thread is None


@pytest.mark.asyncio
async def test_intervention_message(session_manager):
    """개입 메시지 테스트"""
    session = await session_manager.create_session(
        thread_id=123456,
        user="test_user#1234",
    )

    # RUNNING 상태가 아니면 에러
    with pytest.raises(ValueError, match="not running"):
        await session_manager.add_intervention_message(
            session.session_id,
            text="Test message",
            user="test_user#1234",
        )

    # RUNNING 상태로 변경
    await session_manager.update_status(session.session_id, SessionStatus.RUNNING)

    # 개입 메시지 추가
    position = await session_manager.add_intervention_message(
        session.session_id,
        text="Test message",
        user="test_user#1234",
    )
    assert position == 1

    # 메시지 가져오기
    message = await session_manager.get_intervention_message(session.session_id)
    assert message is not None
    assert message["text"] == "Test message"
    assert message["user"] == "test_user#1234"

    # 큐가 비었으면 None
    empty = await session_manager.get_intervention_message(session.session_id)
    assert empty is None


@pytest.mark.asyncio
async def test_get_active_sessions(session_manager):
    """활성 세션 목록 테스트"""
    # 세션 3개 생성
    s1 = await session_manager.create_session(thread_id=1, user="user1")
    s2 = await session_manager.create_session(thread_id=2, user="user2")
    s3 = await session_manager.create_session(thread_id=3, user="user3")

    active = session_manager.get_active_sessions()
    assert len(active) == 3

    # 하나 완료
    await session_manager.update_status(s2.session_id, SessionStatus.COMPLETED)

    active = session_manager.get_active_sessions()
    assert len(active) == 2


@pytest.mark.asyncio
async def test_terminate_all(session_manager):
    """모든 세션 종료 테스트"""
    await session_manager.create_session(thread_id=1, user="user1")
    await session_manager.create_session(thread_id=2, user="user2")
    await session_manager.create_session(thread_id=3, user="user3")

    terminated = await session_manager.terminate_all()
    assert terminated == 3

    active = session_manager.get_active_sessions()
    assert len(active) == 0
