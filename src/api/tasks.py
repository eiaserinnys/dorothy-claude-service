"""
Tasks API - 태스크 기반 API 엔드포인트 (v2)

기존 세션 기반 API를 대체하는 새 API.
클라이언트 재시작 시에도 결과를 복구할 수 있도록 설계됨.
"""

import asyncio
import logging
import json
from typing import Optional
from fastapi import APIRouter, HTTPException, Depends
from sse_starlette.sse import EventSourceResponse

from src.models import (
    ExecuteRequest,
    TaskResponse,
    TaskListResponse,
    TaskInterveneRequest,
    InterveneResponse,
    ErrorResponse,
)
from src.service.task_manager import (
    get_task_manager,
    TaskConflictError,
    TaskNotFoundError,
    TaskNotRunningError,
    TaskStatus,
)
from src.service import resource_manager, claude_runner
from src.api.auth import verify_token

logger = logging.getLogger(__name__)

router = APIRouter()


def task_to_response(task) -> TaskResponse:
    """Task를 TaskResponse로 변환"""
    from src.models import TaskStatus as ResponseTaskStatus
    return TaskResponse(
        client_id=task.client_id,
        request_id=task.request_id,
        status=ResponseTaskStatus(task.status.value),
        result=task.result,
        error=task.error,
        claude_session_id=task.claude_session_id,
        result_delivered=task.result_delivered,
        created_at=task.created_at,
        completed_at=task.completed_at,
    )


@router.post(
    "/execute",
    responses={
        409: {"model": ErrorResponse},
        503: {"model": ErrorResponse},
    },
)
async def execute_task(
    request: ExecuteRequest,
    _: str = Depends(verify_token),
):
    """
    Claude Code 실행 (SSE 스트리밍)

    태스크를 생성하고 Claude Code를 실행합니다.
    결과는 SSE로 스트리밍되며, 클라이언트 연결이 끊어져도
    결과는 보관되어 나중에 조회할 수 있습니다.
    """
    task_manager = get_task_manager()

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

    # 태스크 생성
    try:
        task = await task_manager.create_task(
            client_id=request.client_id,
            request_id=request.request_id,
            prompt=request.prompt,
            resume_session_id=request.resume_session_id,
        )
    except TaskConflictError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "TASK_CONFLICT",
                    "message": f"이미 실행 중인 태스크가 있습니다: {request.client_id}:{request.request_id}",
                    "details": {},
                }
            },
        )

    async def event_generator():
        """SSE 이벤트 생성기"""
        event_queue = asyncio.Queue()
        await task_manager.add_listener(request.client_id, request.request_id, event_queue)

        try:
            async with resource_manager.acquire(timeout=5.0):
                # 개입 메시지 가져오기 함수
                async def get_intervention():
                    return await task_manager.get_intervention(
                        request.client_id, request.request_id
                    )

                # 개입 메시지 전송 콜백
                async def on_intervention_sent(user: str, text: str):
                    event = {"type": "intervention_sent", "user": user, "text": text}
                    await task_manager.broadcast(
                        request.client_id, request.request_id, event
                    )

                # 진행 상황 브로드캐스트 함수
                async def broadcast_event(event_dict):
                    await task_manager.broadcast(
                        request.client_id, request.request_id, event_dict
                    )

                # Claude Code 실행
                async for event in claude_runner.execute(
                    prompt=request.prompt,
                    resume_session_id=request.resume_session_id,
                    get_intervention=get_intervention,
                    on_intervention_sent=on_intervention_sent,
                ):
                    event_dict = event.model_dump()

                    # 리스너들에게 브로드캐스트
                    await broadcast_event(event_dict)

                    # 완료 또는 오류 시 태스크 상태 업데이트
                    if event.type == "complete":
                        await task_manager.complete_task(
                            request.client_id,
                            request.request_id,
                            result=event.result,
                            claude_session_id=event.claude_session_id,
                        )
                    elif event.type == "error":
                        await task_manager.error_task(
                            request.client_id,
                            request.request_id,
                            error=event.message,
                        )

                    # 클라이언트에게 전송
                    yield {
                        "event": event.type,
                        "data": json.dumps(event_dict, ensure_ascii=False),
                    }

        except RuntimeError as e:
            # 리소스 획득 실패
            error_msg = str(e)
            await task_manager.error_task(
                request.client_id, request.request_id, error=error_msg
            )
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False),
            }

        except Exception as e:
            logger.exception(f"Task execution error: {e}")
            error_msg = f"실행 오류: {str(e)}"
            await task_manager.error_task(
                request.client_id, request.request_id, error=error_msg
            )
            yield {
                "event": "error",
                "data": json.dumps({"type": "error", "message": error_msg}, ensure_ascii=False),
            }

        finally:
            await task_manager.remove_listener(
                request.client_id, request.request_id, event_queue
            )

    return EventSourceResponse(event_generator())


@router.get(
    "/tasks/{client_id}",
    response_model=TaskListResponse,
)
async def get_tasks(
    client_id: str,
    _: str = Depends(verify_token),
):
    """
    클라이언트의 태스크 목록 조회

    클라이언트가 재시작 후 미전달 결과를 확인하는 데 사용합니다.
    """
    task_manager = get_task_manager()
    tasks = await task_manager.get_tasks_by_client(client_id)

    return TaskListResponse(
        tasks=[task_to_response(task) for task in tasks]
    )


@router.get(
    "/tasks/{client_id}/{request_id}",
    response_model=TaskResponse,
    responses={404: {"model": ErrorResponse}},
)
async def get_task(
    client_id: str,
    request_id: str,
    _: str = Depends(verify_token),
):
    """
    특정 태스크 조회
    """
    task_manager = get_task_manager()
    task = await task_manager.get_task(client_id, request_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "message": f"태스크를 찾을 수 없습니다: {client_id}:{request_id}",
                    "details": {},
                }
            },
        )

    return task_to_response(task)


@router.get(
    "/tasks/{client_id}/{request_id}/stream",
    responses={404: {"model": ErrorResponse}},
)
async def reconnect_stream(
    client_id: str,
    request_id: str,
    _: str = Depends(verify_token),
):
    """
    태스크 SSE 스트림에 재연결

    running 태스크: 진행 중인 이벤트를 계속 수신
    completed 태스크: 저장된 결과를 즉시 반환
    error 태스크: 저장된 에러를 즉시 반환
    """
    task_manager = get_task_manager()
    task = await task_manager.get_task(client_id, request_id)

    if not task:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "message": f"태스크를 찾을 수 없습니다: {client_id}:{request_id}",
                    "details": {},
                }
            },
        )

    async def event_generator():
        # 이미 완료된 태스크면 즉시 결과 반환
        if task.status == TaskStatus.COMPLETED:
            yield {
                "event": "complete",
                "data": json.dumps({
                    "type": "complete",
                    "result": task.result,
                    "claude_session_id": task.claude_session_id,
                    "attachments": [],
                }, ensure_ascii=False),
            }
            return

        if task.status == TaskStatus.ERROR:
            yield {
                "event": "error",
                "data": json.dumps({
                    "type": "error",
                    "message": task.error,
                }, ensure_ascii=False),
            }
            return

        # running 태스크면 리스너 등록하고 이벤트 대기
        event_queue = asyncio.Queue()
        await task_manager.add_listener(client_id, request_id, event_queue)

        try:
            while True:
                try:
                    event = await asyncio.wait_for(event_queue.get(), timeout=30.0)
                    yield {
                        "event": event.get("type", "unknown"),
                        "data": json.dumps(event, ensure_ascii=False),
                    }

                    # 완료 또는 에러면 종료
                    if event.get("type") in ["complete", "error"]:
                        break

                except asyncio.TimeoutError:
                    # keepalive (빈 코멘트)
                    yield {"comment": "keepalive"}

        finally:
            await task_manager.remove_listener(client_id, request_id, event_queue)

    return EventSourceResponse(event_generator())


@router.post(
    "/tasks/{client_id}/{request_id}/ack",
    responses={404: {"model": ErrorResponse}},
)
async def ack_task(
    client_id: str,
    request_id: str,
    _: str = Depends(verify_token),
):
    """
    결과 수신 확인

    클라이언트가 결과를 성공적으로 수신했음을 알립니다.
    확인된 태스크는 서버에서 삭제됩니다.
    """
    task_manager = get_task_manager()
    success = await task_manager.ack_task(client_id, request_id)

    if not success:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "message": f"태스크를 찾을 수 없습니다: {client_id}:{request_id}",
                    "details": {},
                }
            },
        )

    return {"success": True}


@router.post(
    "/tasks/{client_id}/{request_id}/intervene",
    response_model=InterveneResponse,
    status_code=202,
    responses={
        404: {"model": ErrorResponse},
        409: {"model": ErrorResponse},
    },
)
async def intervene_task(
    client_id: str,
    request_id: str,
    request: TaskInterveneRequest,
    _: str = Depends(verify_token),
):
    """
    실행 중인 태스크에 개입 메시지 전송

    running 상태의 태스크에만 메시지를 전송할 수 있습니다.
    """
    task_manager = get_task_manager()

    try:
        queue_position = await task_manager.add_intervention(
            client_id=client_id,
            request_id=request_id,
            text=request.text,
            user=request.user,
            attachment_paths=request.attachment_paths,
        )

        return InterveneResponse(
            queued=True,
            queue_position=queue_position,
        )

    except TaskNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={
                "error": {
                    "code": "TASK_NOT_FOUND",
                    "message": f"태스크를 찾을 수 없습니다: {client_id}:{request_id}",
                    "details": {},
                }
            },
        )

    except TaskNotRunningError:
        raise HTTPException(
            status_code=409,
            detail={
                "error": {
                    "code": "TASK_NOT_RUNNING",
                    "message": f"태스크가 실행 중이 아닙니다: {client_id}:{request_id}",
                    "details": {},
                }
            },
        )
