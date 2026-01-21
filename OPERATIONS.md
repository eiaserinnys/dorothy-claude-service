# Dorothy Claude Service - 운영 가이드

## 서비스 정보

| 항목 | 값 |
|------|-----|
| 서비스명 | `dorothy-claude-service` |
| 포트 | 8090 (localhost 전용) |
| 프로토콜 | HTTP (REST API + SSE) |
| 프로덕션 경로 | `/home/eias/dorothy-claude-service/` |
| systemd 유닛 | `dorothy-claude-service.service` |

## 기본 명령어

### 서비스 관리

```bash
# 상태 확인
systemctl status dorothy-claude-service

# 시작/정지/재시작
sudo systemctl start dorothy-claude-service
sudo systemctl stop dorothy-claude-service
sudo systemctl restart dorothy-claude-service

# 로그 확인
sudo journalctl -u dorothy-claude-service -f
sudo journalctl -u dorothy-claude-service -n 100 --no-pager
```

### 헬스 체크

```bash
# 헬스 체크 API
curl -s http://127.0.0.1:8090/health | python3 -m json.tool

# 상태 API
curl -s http://127.0.0.1:8090/status | python3 -m json.tool
```

## 프로덕션 구조

```
/home/eias/dorothy-claude-service/
├── current -> releases/YYYYMMDD_HHMMSS/  # 현재 활성 릴리즈
├── releases/                              # 릴리즈 이력
│   └── YYYYMMDD_HHMMSS/
│       ├── src/
│       ├── .venv/
│       └── .env -> ../shared/.env
└── shared/
    └── .env                               # 환경변수 (릴리즈간 공유)
```

## 환경변수

위치: `/home/eias/dorothy-claude-service/shared/.env`

| 변수 | 설명 |
|------|------|
| `CLAUDE_SERVICE_TOKEN` | Dorothy Bot과 공유하는 인증 토큰 |
| `WORKSPACE_DIR` | Claude Code 작업 디렉토리 |
| `MAX_CONCURRENT_SESSIONS` | 최대 동시 세션 수 (기본: 3) |
| `SESSION_TIMEOUT_SECONDS` | 세션 타임아웃 (기본: 1800초) |

## 배포

### 신규 릴리즈 배포

```bash
cd /home/eias/claude-workspace/dorothy-claude-service

# 릴리즈 디렉토리 생성
RELEASE_DIR=/home/eias/dorothy-claude-service/releases/$(date +%Y%m%d_%H%M%S)
mkdir -p "$RELEASE_DIR"

# 코드 복사
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.git' \
  ./ "$RELEASE_DIR/"

# venv 생성 및 의존성 설치
cd "$RELEASE_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# .env 심볼릭 링크
ln -sf ../shared/.env .env

# current 심볼릭 링크 업데이트
cd /home/eias/dorothy-claude-service
rm -f current
ln -s "$RELEASE_DIR" current

# 서비스 재시작
sudo systemctl restart dorothy-claude-service
```

### 롤백

```bash
# 이전 릴리즈로 current 변경
cd /home/eias/dorothy-claude-service
ls releases/  # 이전 릴리즈 확인
rm -f current
ln -s releases/YYYYMMDD_HHMMSS current  # 원하는 릴리즈 선택

# 서비스 재시작
sudo systemctl restart dorothy-claude-service
```

## 연결 설정

### Dorothy Bot 연결

Dorothy Bot에서 원격 모드로 연결하려면:

1. `/home/eias/dorothy_bot/shared/.env`에 추가:
   ```
   CLAUDE_SERVICE_URL=http://127.0.0.1:8090
   CLAUDE_SERVICE_TOKEN=<토큰>
   ```

2. Dorothy Bot 재시작 (대시보드 또는 GitHub Actions)

### 로컬 모드로 롤백

Dorothy Bot에서 로컬 모드로 롤백하려면:

1. `.env`에서 `CLAUDE_SERVICE_URL` 제거 또는 주석 처리
2. Dorothy Bot 재시작

## 문제 해결

### 서비스 시작 실패

```bash
# 상세 로그 확인
sudo journalctl -u dorothy-claude-service -n 50 --no-pager

# 수동 실행으로 에러 확인
cd /home/eias/dorothy-claude-service/current
source .venv/bin/activate
uvicorn src.main:app --host 127.0.0.1 --port 8090
```

### 인증 실패

1. 토큰 일치 확인:
   - `dorothy-claude-service/shared/.env`의 `CLAUDE_SERVICE_TOKEN`
   - `dorothy_bot/shared/.env`의 `CLAUDE_SERVICE_TOKEN`

2. 서비스 재시작 후 환경변수 로드 확인

### 세션 누적

세션이 정리되지 않으면:

```bash
# 서비스 재시작 (모든 세션 종료)
sudo systemctl restart dorothy-claude-service
```
