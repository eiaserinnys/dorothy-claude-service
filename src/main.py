"""
Claude Code Service - FastAPI Application

Discord Bot에서 REST API로 호출하는 Claude Code 실행 서비스.
"""

import os
import time
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

# TODO: Import routers when implemented
# from src.api import sessions, attachments, health

# 서비스 시작 시간 (uptime 계산용)
_start_time = time.time()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """애플리케이션 라이프사이클 관리"""
    # Startup
    print("🚀 Claude Code Service starting...")
    # TODO: Initialize services (SessionManager, ResourceManager, etc.)
    yield
    # Shutdown
    print("👋 Claude Code Service shutting down...")
    # TODO: Cleanup active sessions


app = FastAPI(
    title="Claude Code Service",
    description="REST API for Claude Code execution",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS 설정 (내부 네트워크용)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 프로덕션에서는 제한
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Health check endpoint
@app.get("/health")
async def health_check():
    """헬스 체크 엔드포인트"""
    return {
        "status": "healthy",
        "version": "0.1.0",
        "uptime_seconds": int(time.time() - _start_time),
    }


# Status endpoint
@app.get("/status")
async def get_status():
    """서비스 상태 조회"""
    # TODO: Implement with SessionManager
    return {
        "active_sessions": 0,
        "max_concurrent": int(os.getenv("MAX_CONCURRENT_SESSIONS", "3")),
        "sessions": [],
    }


# TODO: Include routers
# app.include_router(sessions.router, prefix="/sessions", tags=["sessions"])
# app.include_router(attachments.router, prefix="/attachments", tags=["attachments"])


# Global exception handler
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """전역 예외 핸들러"""
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
        host="0.0.0.0",
        port=int(os.getenv("PORT", "8080")),
        reload=True,
    )
