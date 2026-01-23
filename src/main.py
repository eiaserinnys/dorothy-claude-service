"""
Claude Code Service - FastAPI Application

Discord Bot에서 REST API로 호출하는 Claude Code 실행 서비스.
"""

import asyncio
import time
import logging
from pathlib import Path
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import attachments_router
from src.api.tasks import router as tasks_router
from src.service import resource_manager, file_manager
from src.service.task_manager import init_task_manager, get_task_manager
from src.service.discord_notifier import discord_notifier
from src.models import HealthResponse
from src.config import get_settings, setup_logging

# 설정 로드
settings = get_settings()

# 로깅 설정
logger = setup_logging(settings)

# 서비스 시작 시간 (uptime 계산용)
_start_time = time.time()

# 백그라운드 태스크 참조
_cleanup_task = None


async def periodic_cleanup():
    """주기적 태스크 정리 (24시간 이상 된 완료 태스크)"""
    while True:
        try:
            await asyncio.sleep(3600)  # 1시간마다 실행
            task_manager = get_task_manager()
            cleaned = await task_manager.cleanup_old_tasks(max_age_hours=24)
            if cleaned > 0:
                logger.info(f"Periodic cleanup: removed {cleaned} old tasks")
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"Periodic cleanup error: {e}")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    global _cleanup_task

    # Startup
    logger.info("🚀 Claude Code Service starting...")
    logger.info(f"  Version: {settings.version}")
    logger.info(f"  Environment: {settings.environment}")
    logger.info(f"  Max concurrent sessions: {resource_manager.max_concurrent}")
    logger.info(f"  Workspace: {settings.workspace_dir}")

    # TaskManager 초기화 및 로드
    storage_path = Path(settings.workspace_dir) / "data" / "tasks.json"
    task_manager = init_task_manager(storage_path=storage_path)
    loaded = await task_manager.load()
    logger.info(f"  Loaded {loaded} tasks from storage")

    # 주기적 정리 태스크 시작
    _cleanup_task = asyncio.create_task(periodic_cleanup())
    logger.info("  Started periodic cleanup task")

    # Discord 알림 발송 (비동기, 실패해도 서비스에 영향 없음)
    await discord_notifier.notify_startup(
        version=settings.version,
        environment=settings.environment,
        loaded_tasks=loaded,
    )

    yield

    # Shutdown
    logger.info("👋 Claude Code Service shutting down...")

    # Discord 종료 알림 발송
    uptime = int(time.time() - _start_time)
    await discord_notifier.notify_shutdown(uptime_seconds=uptime)

    # 주기적 정리 태스크 중지
    if _cleanup_task:
        _cleanup_task.cancel()
        try:
            await _cleanup_task
        except asyncio.CancelledError:
            pass

    # 실행 중인 태스크 취소 (고아 프로세스 방지)
    try:
        task_manager = get_task_manager()
        cancelled = await task_manager.cancel_running_tasks(timeout=5.0)
        if cancelled > 0:
            logger.info(f"  Cancelled {cancelled} running tasks")
        await task_manager._save()
        logger.info("  Saved tasks to storage")
    except RuntimeError:
        pass  # TaskManager가 초기화되지 않은 경우

    # 오래된 첨부 파일 정리
    cleaned = file_manager.cleanup_old_files(max_age_hours=1)
    if cleaned > 0:
        logger.info(f"  Cleaned up {cleaned} attachment directories")


app = FastAPI(
    title="Claude Code Service",
    description="REST API for Claude Code execution",
    version=settings.version,
    lifespan=lifespan,
    # 프로덕션에서는 OpenAPI 문서 비활성화
    docs_url="/docs" if not settings.is_production else None,
    redoc_url="/redoc" if not settings.is_production else None,
)

# CORS 설정
# 프로덕션: localhost만 허용 (같은 서버에서만 접근)
# 개발: 모든 origin 허용
_allowed_origins = ["http://localhost:*", "http://127.0.0.1:*"] if settings.is_production else ["*"]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# === Health & Status Endpoints ===

@app.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """헬스 체크 엔드포인트"""
    return HealthResponse(
        status="healthy",
        version=settings.version,
        uptime_seconds=int(time.time() - _start_time),
        environment=settings.environment,
    )


@app.get("/status", tags=["health"])
async def get_status():
    """서비스 상태 조회"""
    task_manager = get_task_manager()
    running_tasks = [t for t in task_manager._tasks.values() if t.status == "running"]

    return {
        "active_tasks": len(running_tasks),
        "max_concurrent": resource_manager.max_concurrent,
        "tasks": [
            {
                "client_id": t.client_id,
                "request_id": t.request_id,
                "status": t.status,
                "created_at": t.created_at.isoformat(),
            }
            for t in running_tasks
        ],
    }


# === API Routers ===

# Task API - 태스크 기반 API
app.include_router(tasks_router, tags=["tasks"])

# Attachments API
app.include_router(attachments_router, prefix="/attachments", tags=["attachments"])


# === Exception Handlers ===

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 핸들러"""
    logger.exception(f"Unhandled exception: {exc}")
    return JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_ERROR",
                "message": str(exc),
                "details": {},
            }
        },
    )


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "src.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.is_development,
        access_log=not settings.is_production,
    )
