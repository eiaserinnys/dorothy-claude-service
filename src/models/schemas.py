"""
Pydantic 모델 - Request/Response 스키마
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


# === Enums ===

class SessionStatus(str, Enum):
    """세션 상태"""
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    ERROR = "error"
    TERMINATED = "terminated"


class SSEEventType(str, Enum):
    """SSE 이벤트 타입"""
    PROGRESS = "progress"
    MEMORY = "memory"
    INTERVENTION_SENT = "intervention_sent"
    COMPLETE = "complete"
    ERROR = "error"


# === Request Models ===

class CreateSessionRequest(BaseModel):
    """세션 생성 요청"""
    thread_id: int = Field(..., description="Discord 스레드 ID")
    user: str = Field(..., description="요청한 사용자")
    resume_session_id: Optional[str] = Field(None, description="이전 세션 ID (대화 연속성용)")


class QueryRequest(BaseModel):
    """쿼리 실행 요청"""
    prompt: str = Field(..., description="사용자 프롬프트")
    attachment_paths: Optional[List[str]] = Field(None, description="첨부 파일 경로 목록")


class InterveneRequest(BaseModel):
    """개입 메시지 요청"""
    text: str = Field(..., description="메시지 텍스트")
    user: str = Field(..., description="요청한 사용자")
    attachment_paths: Optional[List[str]] = Field(None, description="첨부 파일 경로 목록")


# === Response Models ===

class SessionResponse(BaseModel):
    """세션 정보 응답"""
    session_id: str
    thread_id: int
    status: SessionStatus
    user: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class SessionCreateResponse(BaseModel):
    """세션 생성 응답"""
    session_id: str
    thread_id: int
    status: SessionStatus
    created_at: datetime


class SessionDeleteResponse(BaseModel):
    """세션 삭제 응답"""
    session_id: str
    status: SessionStatus
    partial_result: Optional[str] = None


class InterveneResponse(BaseModel):
    """개입 메시지 응답"""
    queued: bool
    queue_position: int


class AttachmentUploadResponse(BaseModel):
    """첨부 파일 업로드 응답"""
    path: str
    filename: str
    size: int
    content_type: str


class AttachmentCleanupResponse(BaseModel):
    """첨부 파일 정리 응답"""
    cleaned: bool
    files_removed: int


class TitleResponse(BaseModel):
    """세션 제목 응답"""
    title: str


class HealthResponse(BaseModel):
    """헬스 체크 응답"""
    status: str
    version: str
    uptime_seconds: int


class StatusResponse(BaseModel):
    """서비스 상태 응답"""
    active_sessions: int
    max_concurrent: int
    sessions: List[SessionResponse]


# === Error Response ===

class ErrorDetail(BaseModel):
    """에러 상세 정보"""
    code: str
    message: str
    details: dict = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """에러 응답"""
    error: ErrorDetail


# === SSE Event Models ===

class ProgressEvent(BaseModel):
    """진행 상황 이벤트"""
    type: str = "progress"
    text: str


class MemoryEvent(BaseModel):
    """메모리 사용량 이벤트"""
    type: str = "memory"
    used_gb: float
    total_gb: float
    percent: float


class InterventionSentEvent(BaseModel):
    """개입 메시지 전송 확인 이벤트"""
    type: str = "intervention_sent"
    user: str
    text: str


class CompleteEvent(BaseModel):
    """실행 완료 이벤트"""
    type: str = "complete"
    result: str
    attachments: List[str] = Field(default_factory=list)


class ErrorEvent(BaseModel):
    """오류 이벤트"""
    type: str = "error"
    message: str
