"""
Claude Code Service - FastAPI Application

Discord Bot에서 REST API로 호출하는 Claude Code 실행 서비스.
"""

import time
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from src.api import sessions_router, attachments_router
from src.service import session_manager, resource_manager, file_manager
from src.models import SessionResponse, StatusResponse, HealthResponse
from src.config import get_settings, setup_logging

# 설정 로드
settings = get_settings()

# 로깅 설정
logger = setup_logging(settings)

# 서비스 시작 시간 (uptime 계산용)
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    # Startup
    logger.info("🚀 Claude Code Service starting...")
    logger.info(f"  Version: {settings.version}")
    logger.info(f"  Environment: {settings.environment}")
    logger.info(f"  Max concurrent sessions: {resource_manager.max_concurrent}")
    logger.info(f"  Workspace: {settings.workspace_dir}")

    yield

    # Shutdown
    logger.info("👋 Claude Code Service shutting down...")

    # 활성 세션 종료
    terminated = await session_manager.terminate_all()
    if terminated > 0:
        logger.info(f"  Terminated {terminated} active sessions")

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


@app.get("/status", response_model=StatusResponse, tags=["health"])
async def get_status():
    """서비스 상태 조회"""
    active_sessions = session_manager.get_active_sessions()

    return StatusResponse(
        active_sessions=len(active_sessions),
        max_concurrent=resource_manager.max_concurrent,
        sessions=[
            SessionResponse(
                session_id=s.session_id,
                thread_id=s.thread_id,
                status=s.status,
                user=s.user,
                created_at=s.created_at,
                updated_at=s.updated_at,
            )
            for s in active_sessions
        ],
    )


# === API Routers ===

app.include_router(sessions_router, prefix="/sessions", tags=["sessions"])
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
