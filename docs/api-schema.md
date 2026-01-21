# Claude Code Service REST API 스키마

## 개요

이 문서는 Claude Code Service의 REST API 스키마를 정의합니다.
기존 Dorothy Bot의 `ClaudeAgentService`를 REST API로 노출하여,
Discord Bot이 HTTP 클라이언트로 호출할 수 있게 합니다.

## 기본 정보

- **Base URL**: `http://localhost:8080` (프로덕션: 환경변수로 설정)
- **Content-Type**: `application/json`
- **인증**: Bearer 토큰 (헤더: `Authorization: Bearer <token>`)

## 엔드포인트

### 1. 세션 관리

#### POST /sessions
새 Claude Code 세션 시작

**Request Body:**
```json
{
  "thread_id": 123456789,         // Discord 스레드 ID (필수)
  "user": "username#1234",        // 요청한 사용자 (필수)
  "resume_session_id": "abc123"   // 이전 세션 ID (선택, 대화 연속성용)
}
```

**Response (201 Created):**
```json
{
  "session_id": "ses_abc123",
  "thread_id": 123456789,
  "status": "ready",
  "created_at": "2026-01-21T10:00:00Z"
}
```

**Error Responses:**
- `400 Bad Request`: thread_id 또는 user 누락
- `409 Conflict`: 해당 thread_id에 이미 활성 세션 존재
- `503 Service Unavailable`: 동시 실행 제한 초과

#### GET /sessions/{session_id}
세션 상태 조회

**Response (200 OK):**
```json
{
  "session_id": "ses_abc123",
  "thread_id": 123456789,
  "status": "running",           // ready | running | completed | error
  "user": "username#1234",
  "created_at": "2026-01-21T10:00:00Z",
  "updated_at": "2026-01-21T10:05:00Z"
}
```

#### DELETE /sessions/{session_id}
세션 종료/중단

**Response (200 OK):**
```json
{
  "session_id": "ses_abc123",
  "status": "terminated",
  "partial_result": "..."         // 중단 시 부분 결과 (있으면)
}
```

### 2. 쿼리 실행

#### POST /sessions/{session_id}/query
Claude Code에 프롬프트 전송 (SSE 스트리밍)

**Request Body:**
```json
{
  "prompt": "파일을 읽어줘",
  "attachment_paths": ["/tmp/file.txt"]  // 첨부 파일 경로 (선택)
}
```

**Response (200 OK, SSE Stream):**
```
event: progress
data: {"type": "progress", "text": "파일을 읽고 있습니다..."}

event: progress
data: {"type": "progress", "text": "분석 중입니다..."}

event: memory
data: {"type": "memory", "used_gb": 2.5, "total_gb": 4.0, "percent": 62.5}

event: complete
data: {"type": "complete", "result": "파일 내용: ...", "attachments": []}

event: error
data: {"type": "error", "message": "실행 오류: ..."}
```

**SSE Event Types:**
- `progress`: 진행 상황 업데이트
- `memory`: 메모리 사용량 리포트
- `intervention_sent`: 개입 메시지 전송 확인
- `complete`: 실행 완료 (최종 결과)
- `error`: 오류 발생

### 3. 개입 메시지

#### POST /sessions/{session_id}/intervene
실행 중인 세션에 개입 메시지 전송

**Request Body:**
```json
{
  "text": "잠깐, 다른 파일도 확인해줘",
  "user": "username#1234",
  "attachment_paths": []
}
```

**Response (202 Accepted):**
```json
{
  "queued": true,
  "queue_position": 1
}
```

**Error Responses:**
- `404 Not Found`: 세션 없음
- `409 Conflict`: 세션이 실행 중이 아님

### 4. 첨부 파일 관리

#### POST /attachments
첨부 파일 업로드

**Request (multipart/form-data):**
- `file`: 업로드할 파일
- `thread_id`: 스레드 ID (디렉토리 구분용)

**Response (201 Created):**
```json
{
  "path": "/tmp/claude-code-attachments/123456/1705838400000_file.txt",
  "filename": "file.txt",
  "size": 1234,
  "content_type": "text/plain"
}
```

**Error Responses:**
- `400 Bad Request`: 파일 크기 초과 (8MB)
- `400 Bad Request`: 위험한 파일 확장자 (.env, .pem 등)

#### DELETE /attachments/{thread_id}
스레드의 첨부 파일 정리

**Response (200 OK):**
```json
{
  "cleaned": true,
  "files_removed": 5
}
```

### 5. 상태 확인

#### GET /health
헬스 체크

**Response (200 OK):**
```json
{
  "status": "healthy",
  "version": "1.0.0",
  "uptime_seconds": 3600
}
```

#### GET /status
서비스 상태 조회

**Response (200 OK):**
```json
{
  "active_sessions": 2,
  "max_concurrent": 3,
  "sessions": [
    {
      "session_id": "ses_abc123",
      "thread_id": 123456789,
      "status": "running",
      "user": "username#1234"
    }
  ]
}
```

### 6. 세션 제목 생성

#### POST /sessions/{session_id}/title
세션 제목 생성 요청

**Response (200 OK):**
```json
{
  "title": "Discord 봇 에러 핸들링 개선"
}
```

**Error Responses:**
- `404 Not Found`: 세션 없음
- `408 Request Timeout`: 제목 생성 타임아웃

## 에러 응답 형식

모든 에러 응답은 다음 형식을 따릅니다:

```json
{
  "error": {
    "code": "SESSION_NOT_FOUND",
    "message": "세션을 찾을 수 없습니다",
    "details": {}
  }
}
```

### 에러 코드

| 코드 | HTTP 상태 | 설명 |
|------|----------|------|
| `INVALID_REQUEST` | 400 | 잘못된 요청 파라미터 |
| `UNAUTHORIZED` | 401 | 인증 실패 |
| `SESSION_NOT_FOUND` | 404 | 세션 없음 |
| `SESSION_CONFLICT` | 409 | 세션 상태 충돌 |
| `RATE_LIMIT_EXCEEDED` | 429 | 동시 실행 제한 초과 |
| `INTERNAL_ERROR` | 500 | 내부 서버 오류 |
| `SERVICE_UNAVAILABLE` | 503 | 서비스 사용 불가 |

## 인증

### Bearer 토큰
```
Authorization: Bearer <CLAUDE_SERVICE_TOKEN>
```

토큰은 환경변수 `CLAUDE_SERVICE_TOKEN`으로 설정합니다.
내부 네트워크에서만 사용되므로 간단한 공유 시크릿 방식을 사용합니다.

## 제한 사항

- **최대 동시 세션**: 3개 (환경변수 `MAX_CONCURRENT_SESSIONS`로 조정)
- **첨부 파일 최대 크기**: 8MB
- **쿼리 타임아웃**: 600초 (10분)
- **세션 제목 생성 타임아웃**: 30초

## 버전 관리

API 버전은 URL에 포함하지 않고, 헤더로 관리합니다:
```
X-API-Version: 2026-01-21
```

현재 버전: `2026-01-21`
