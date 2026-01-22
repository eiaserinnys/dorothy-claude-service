# Dorothy Claude Service - Claude Code Guide

이 문서는 Claude Code가 이 프로젝트를 이해하고 개발하는 데 필요한 지침을 담고 있습니다.

## 프로젝트 개요

Dorothy Claude Service는 Claude Code SDK를 REST API로 래핑한 서비스입니다.
Discord Bot(Dorothy Bot)이 HTTP 클라이언트로 Claude Code를 호출할 수 있게 해줍니다.

### 주요 특징

- **SSE 스트리밍**: 쿼리 실행 결과를 실시간으로 전달
- **세션 관리**: 동시 실행 제한, 타임아웃, 자동 정리
- **개입 메시지**: 실행 중인 세션에 추가 입력 전송
- **첨부 파일**: 파일 업로드 및 세션 연결

## 기술 스택

- **Python 3.12+**: FastAPI, uvicorn
- **Claude Agent SDK**: Claude Code 실행
- **SSE (Server-Sent Events)**: 실시간 스트리밍

## 프로젝트 구조

```
src/
├── main.py           # FastAPI 앱, 라이프사이클, 헬스 체크
├── config.py         # 환경변수 기반 설정 관리
├── api/
│   ├── sessions.py   # 세션 관리 API (/sessions)
│   ├── attachments.py# 첨부 파일 API (/attachments)
│   └── auth.py       # Bearer 토큰 인증
├── service/
│   ├── session_manager.py  # 세션 생명주기 관리
│   ├── resource_manager.py # 동시 실행 제한 (세마포어)
│   ├── claude_runner.py    # Claude Code 프로세스 실행
│   └── file_manager.py     # 첨부 파일 관리
└── models/           # Pydantic 모델
```

## 개발 환경 설정

```bash
# 가상환경 생성
python -m venv .venv
source .venv/bin/activate

# 의존성 설치
pip install -r requirements.txt

# 환경변수 설정
cp .env.example .env
# .env 파일 편집

# 서버 실행 (개발 모드)
uvicorn src.main:app --reload --port 8080
```

## 테스트 실행

```bash
# 단위 테스트
pytest tests/unit -v

# 통합 테스트
pytest tests/integration -v

# 전체 테스트 + 커버리지
pytest --cov=src --cov-report=html
```

## API 엔드포인트 요약

| 메서드 | 경로 | 설명 |
|--------|------|------|
| GET | /health | 헬스 체크 |
| GET | /status | 서비스 상태 (활성 세션 목록) |
| POST | /sessions | 새 세션 생성 |
| GET | /sessions/{id} | 세션 정보 조회 |
| DELETE | /sessions/{id} | 세션 종료 |
| POST | /sessions/{id}/query | 쿼리 실행 (SSE) |
| POST | /sessions/{id}/intervene | 개입 메시지 전송 |
| POST | /attachments | 첨부 파일 업로드 |

자세한 API 스키마는 `docs/api-schema.md` 참조.

## 핵심 설계 결정

### 1. 동시 실행 제한

`resource_manager.py`의 세마포어로 최대 동시 세션 수 제한.
서버 리소스 보호 및 Claude API 비용 관리 목적.

### 2. SSE 스트리밍

`sse-starlette` 라이브러리로 Server-Sent Events 구현.
클라이언트가 연결을 끊으면 자동으로 세션 정리.

### 3. 민감 정보 마스킹

`claude_runner.py`에서 출력 스트림의 API 키, 토큰 등을 자동 마스킹.

### 4. 환경별 설정

- **개발**: 텍스트 로그, CORS 완화, Swagger 문서 활성화
- **프로덕션**: JSON 로그, CORS 제한, Swagger 비활성화

## 배포

### systemd 서비스

```bash
# 설치
./scripts/install-service.sh

# 배포
./scripts/deploy.sh

# 상태 확인
sudo systemctl status dorothy-claude-service
```

### 프로덕션 경로

```
/home/eias/dorothy-claude-service/
├── current -> releases/xxx/
├── releases/
└── shared/.env
```

## 관련 프로젝트

- **dorothy_bot**: 이 서비스를 호출하는 Discord Bot
- **dorothy-core**: 공통 유틸리티 라이브러리
