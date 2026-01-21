# Dorothy Claude Service

Claude Code 실행 로직을 REST API로 제공하는 독립 서비스입니다.

## 개요

이 서비스는 Dorothy Bot의 Claude Code 실행 로직을 분리하여:
- Discord Bot이 HTTP 클라이언트로 Claude Code를 호출
- 세션 관리, 리소스 제한, 첨부 파일 처리를 서비스 레벨에서 관리
- SSE 스트리밍으로 실시간 진행 상황 전달

## 프로젝트 구조

```
dorothy-claude-service/
├── docs/
│   ├── api-schema.md      # REST API 스키마
│   └── test-plan.md       # 테스트 계획
├── scripts/
│   ├── deploy.sh          # 배포 스크립트
│   ├── install-service.sh # systemd 서비스 설치
│   ├── health-check.sh    # 헬스 체크 스크립트
│   └── *.service/*.timer  # systemd 유닛 파일
├── src/
│   ├── main.py            # FastAPI 앱 엔트리포인트
│   ├── config.py          # 설정 관리
│   ├── api/               # API 라우터
│   ├── service/           # 비즈니스 로직
│   └── models/            # Pydantic 모델
├── tests/
│   ├── unit/              # 단위 테스트
│   ├── integration/       # 통합 테스트
│   └── e2e/               # E2E 테스트
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
└── README.md
```

## 빠른 시작

### 로컬 개발

```bash
# 가상환경 생성 및 의존성 설치
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# 환경변수 설정
export ENVIRONMENT=development
export CLAUDE_SERVICE_TOKEN="your-secret-token"
export ANTHROPIC_API_KEY="your-anthropic-key"

# 서버 실행 (개발 모드)
uvicorn src.main:app --reload --port 8080 --loop uvloop
```

### Docker 실행

```bash
# .env 파일 생성
cp .env.example .env
# .env 파일 편집...

# 서비스 시작
docker compose up -d

# 로그 확인
docker compose logs -f
```

## 프로덕션 배포

### 최초 설치

```bash
# 1. 서비스 디렉토리 생성 및 systemd 설치
./scripts/install-service.sh

# 2. 환경변수 설정
vi /home/eias/dorothy-claude-service/shared/.env

# 3. 배포
./scripts/deploy.sh
```

### 서비스 관리

```bash
# 상태 확인
sudo systemctl status dorothy-claude-service

# 시작/정지/재시작
sudo systemctl start dorothy-claude-service
sudo systemctl stop dorothy-claude-service
sudo systemctl restart dorothy-claude-service

# 로그 확인
sudo journalctl -u dorothy-claude-service -f

# 헬스 체크 타이머 활성화 (선택)
sudo systemctl enable --now dorothy-claude-service-health.timer
```

### 배포 구조

```
/home/eias/dorothy-claude-service/
├── current -> releases/2026-01-21-120000/  # 현재 배포
├── releases/
│   ├── 2026-01-21-120000/                   # 릴리즈 (최근 3개 유지)
│   └── ...
└── shared/
    └── .env                                  # 환경변수 (공유)
```

## API 사용 예시

### 세션 생성

```bash
curl -X POST http://localhost:8080/sessions \
  -H "Authorization: Bearer $CLAUDE_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"thread_id": 123456789, "user": "testuser"}'
```

### 쿼리 실행 (SSE 스트리밍)

```bash
curl -N http://localhost:8080/sessions/ses_abc123/query \
  -H "Authorization: Bearer $CLAUDE_SERVICE_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "현재 디렉토리의 파일 목록을 보여줘"}'
```

## 개발

### 테스트 실행

```bash
# 단위 테스트
pytest tests/unit -v

# 통합 테스트
pytest tests/integration -v

# 커버리지 포함
pytest --cov=src --cov-report=html
```

### 코드 품질

```bash
# 포맷팅
ruff format src tests

# 린트
ruff check src tests

# 타입 체크
mypy src
```

## 환경변수

| 변수 | 설명 | 기본값 |
|------|------|--------|
| `CLAUDE_SERVICE_TOKEN` | API 인증 토큰 | (필수) |
| `ANTHROPIC_API_KEY` | Anthropic API 키 | (필수) |
| `MAX_CONCURRENT_SESSIONS` | 최대 동시 세션 수 | 3 |
| `WORKSPACE_DIR` | 작업 디렉토리 | /workspace |
| `LOG_LEVEL` | 로그 레벨 | INFO |
| `PORT` | 서버 포트 | 8080 |

## 관련 문서

- [API 스키마](docs/api-schema.md)
- [테스트 계획](docs/test-plan.md)
