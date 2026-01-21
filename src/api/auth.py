"""
Authentication - Bearer 토큰 인증
"""

import os
from fastapi import HTTPException, Header
from typing import Optional


# 환경변수에서 토큰 읽기
CLAUDE_SERVICE_TOKEN = os.getenv("CLAUDE_SERVICE_TOKEN", "")


async def verify_token(authorization: Optional[str] = Header(None)) -> str:
    """
    Bearer 토큰 검증

    Args:
        authorization: Authorization 헤더 값

    Returns:
        검증된 토큰

    Raises:
        HTTPException: 인증 실패
    """
    # 토큰이 설정되지 않은 경우 (개발 모드)
    if not CLAUDE_SERVICE_TOKEN:
        return ""

    if not authorization:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Authorization 헤더가 필요합니다",
                    "details": {},
                }
            },
        )

    # Bearer 토큰 파싱
    parts = authorization.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Bearer 토큰 형식이 올바르지 않습니다",
                    "details": {},
                }
            },
        )

    token = parts[1]

    # 토큰 검증
    if token != CLAUDE_SERVICE_TOKEN:
        raise HTTPException(
            status_code=401,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "유효하지 않은 토큰입니다",
                    "details": {},
                }
            },
        )

    return token
