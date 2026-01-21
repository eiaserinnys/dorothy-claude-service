"""
Sessions API - 세션 관리 엔드포인트
"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
import json

from src.models import (
    SessionStatus,
    CreateSessionRequest,
    QueryRequest,
    InterveneRequest,
    SessionResponse,
    SessionCreateResponse,
    SessionDeleteResponse,
    InterveneResponse,
    TitleResponse,
    ErrorResponse,
    ErrorDetail,
)
from src.service import (
    session_manager,
    resource_manager,
    claude_runner,
)
from src.api.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()


@router.post(
    "",
    response_model=SessionCreateResponse,
    status_code=201,
    responses={
        400: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def create_session(
    request: CreateSessionRequest,
    _: str = Depends(verify_token),
):
    """
    새 Claude Code 세션 생성
    """
    # 동시 실행 제한 확인
    if not resource_manager.can_acquire():
        raise HTTPException(
            status_code=503,
            detail={
                "error": {
                    "code": "RATE_LIMIT_EXCEEDED",
                    "message": f"동시 실행 제한 초과 (max={resource_manager.max_concurrent})",
                    "details": {},
                }
            },
        )

    try:
        session = await session_manager.create_session(
            thread_id=request.thread_id,
            user=request.user,
            resume_session_id=request.resume_session_id,
        )

        return SessionCreateResponse(
            session_id=session.session_id,
            thread_id=session.thread_id,
            status=session.status,
            created_at=session.created_at,
        )

    except ValueError as e:
        # 이미 활성 세션 존재
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "SESSION_CONFLICT",
                    "message": str(e),
                    "details": {},
                }
            },
        )


@router.get(
    "/{session_id}",
    response_model=SessionResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_session(
    session_id: str,
    _: str = Depends(verify_token),
):
    """
    세션 상태 조회
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"세션을 찾을 수 없습니다: {session_id}",
                    "details": {},
                }
            },
        )

    return SessionResponse(
        session_id=session.session_id,
        thread_id=session.thread_id,
        status=session.status,
        user=session.user,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


@router.delete(
    "/{session_id}",
    response_model=SessionDeleteResponse,
    responses={404: {"model": ErrorResponse}},
)
async def delete_session(
    session_id: str,
    _: str = Depends(verify_token),
):
    """
    세션 종료/중단
    """
    session = await session_manager.delete_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"세션을 찾을 수 없습니다: {session_id}",
                    "details": {},
                }
            },
        )

    return SessionDeleteResponse(
        session_id=session.session_id,
        status=session.status,
        partial_result=session.result,
    )


@router.post(
    "/{session_id}/query",
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def execute_query(
    session_id: str,
    request: QueryRequest,
    _: str = Depends(verify_token),
):
    """
    Claude Code에 프롬프트 전송 (SSE 스트리밍)
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"세션을 찾을 수 없습니다: {session_id}",
                    "details": {},
                }
            },
        )

    if session.status not in [SessionStatus.READY, SessionStatus.RUNNING]:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "SESSION_CONFLICT",
                    "message": f"세션이 실행 가능한 상태가 아닙니다: {session.status}",
                    "details": {},
                }
            },
        )

    async def event_generator():
        """SSE 이벤트 생성기"""
        # 세션 상태를 RUNNING으로 변경
        await session_manager.update_status(session_id, SessionStatus.RUNNING)

        try:
            async with resource_manager.acquire(timeout=5.0):
                # 개입 메시지 가져오기 함수
                async def get_intervention():
                    return await session_manager.get_intervention_message(session_id)

                # 개입 메시지 전송 콜백
                async def on_intervention_sent(user: str, text: str):
                    logger.info(f"[Intervention] Sent from {user}: {text[:50]}...")

                # Claude Code 실행
                async for event in claude_runner.execute(
                    prompt=request.prompt,
                    resume_session_id=session.resume_session_id,
                    get_intervention=get_intervention,
                    on_intervention_sent=on_intervention_sent,
                ):
                    yield {
                        "event": event.type,
                        "data": json.dumps(event.model_dump(), ensure_ascii=False),
                    }

                    # 완료 또는 오류 시 세션 상태 업데이트
                    if event.type == "complete":
                        await session_manager.update_status(
                            session_id,
                            SessionStatus.COMPLETED,
                            result=event.result,
                            claude_session_id=event.claude_session_id
                        )
                    elif event.type == "error":
                        await session_manager.update_status(
                            session_id,
                            SessionStatus.ERROR,
                            result=event.message
                        )

        except RuntimeError as e:
            # 리소스 획득 실패
            error_event = {
                "type": "error",
                "message": str(e)
            }
            yield {
                "event": "error",
                "data": json.dumps(error_event, ensure_ascii=False),
            }
            await session_manager.update_status(
                session_id,
                SessionStatus.ERROR,
                result=str(e)
            )

        except Exception as e:
            logger.exception(f"Query execution error: {e}")
            error_event = {
                "type": "error",
                "message": f"실행 오류: {str(e)}"
            }
            yield {
                "event": "error",
                "data": json.dumps(error_event, ensure_ascii=False),
            }
            await session_manager.update_status(
                session_id,
                SessionStatus.ERROR,
                result=str(e)
            )

    return EventSourceResponse(event_generator())


@router.post(
    "/{session_id}/intervene",
    response_model=InterveneResponse,
    status_code=202,
    responses={404: {"model": ErrorResponse}, 409: {"model": ErrorResponse}},
)
async def send_intervention(
    session_id: str,
    request: InterveneRequest,
    _: str = Depends(verify_token),
):
    """
    실행 중인 세션에 개입 메시지 전송
    """
    try:
        queue_position = await session_manager.add_intervention_message(
            session_id=session_id,
            text=request.text,
            user=request.user,
            attachment_paths=request.attachment_paths,
        )

        return InterveneResponse(
            queued=True,
            queue_position=queue_position,
        )

    except ValueError as e:
        error_msg = str(e)
        if "not found" in error_msg.lower():
            raise HTTPException(
                status_code=404,
                detail={
                    "error": {
                        "code": "SESSION_NOT_FOUND",
                        "message": error_msg,
                        "details": {},
                    }
                },
            )
        else:
            raise HTTPException(
                status_code=409,
                detail={
                    "error": {
                        "code": "SESSION_CONFLICT",
                        "message": error_msg,
                        "details": {},
                    }
                },
            )


@router.post(
    "/{session_id}/title",
    response_model=TitleResponse,
    responses={
        404: {"model": ErrorResponse},
        408: {"model": ErrorResponse},
    },
)
async def generate_title(
    session_id: str,
    _: str = Depends(verify_token),
):
    """
    세션 제목 생성
    """
    session = await session_manager.get_session(session_id)
    if not session:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "SESSION_NOT_FOUND",
                    "message": f"세션을 찾을 수 없습니다: {session_id}",
                    "details": {},
                }
            },
        )

    # Claude Code 세션 ID가 없으면 현재 세션 ID 사용
    resume_id = session.claude_session_id or session.resume_session_id
    if not resume_id:
        raise HTTPException(
            status_code=400,
            detail={
                "error": {
                    "code": "INVALID_REQUEST",
                    "message": "제목 생성을 위한 세션 ID가 없습니다",
                    "details": {},
                }
            },
        )

    title = await claude_runner.generate_title(resume_id)
    if not title:
        raise HTTPException(
            status_code=408,
            detail={
                "error": {
                    "code": "TIMEOUT",
                    "message": "제목 생성 타임아웃",
                    "details": {},
                }
            },
        )

    return TitleResponse(title=title)
