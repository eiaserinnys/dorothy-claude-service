#!/bin/bash
# Dorothy Claude Service 배포 스크립트

set -e

SERVICE_NAME="dorothy-claude-service"
SERVICE_DIR="/home/eias/dorothy-claude-service"
REPO_DIR="/home/eias/claude-workspace/dorothy-claude-service"
RELEASE_NAME="$(date +%Y-%m-%d-%H%M%S)"
RELEASE_DIR="$SERVICE_DIR/releases/$RELEASE_NAME"

echo "=== $SERVICE_NAME 배포 ($RELEASE_NAME) ==="

# 1. Git pull (최신 코드)
echo "1. 최신 코드 가져오기..."
cd "$REPO_DIR"
git fetch origin
git reset --hard origin/master

# 2. 릴리즈 디렉토리 생성
echo "2. 릴리즈 디렉토리 생성..."
mkdir -p "$RELEASE_DIR"

# 3. 코드 복사 (.git 제외)
echo "3. 코드 복사..."
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' "$REPO_DIR/" "$RELEASE_DIR/"

# 4. 가상환경 생성 및 의존성 설치
echo "4. Python 가상환경 설정..."
cd "$RELEASE_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

# 5. 심볼릭 링크 업데이트
echo "5. current 심볼릭 링크 업데이트..."
ln -sfn "$RELEASE_DIR" "$SERVICE_DIR/current"

# 6. 서비스 재시작
echo "6. 서비스 재시작..."
sudo systemctl restart $SERVICE_NAME

# 7. 헬스 체크
echo "7. 헬스 체크..."
sleep 3
if curl -sf http://127.0.0.1:8090/health > /dev/null; then
    echo "   ✅ 서비스 정상 동작"
else
    echo "   ❌ 헬스 체크 실패!"
    echo "   로그 확인: sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# 8. 이전 릴리즈 정리 (최근 3개만 유지)
echo "8. 이전 릴리즈 정리..."
cd "$SERVICE_DIR/releases"
ls -t | tail -n +4 | xargs -r rm -rf

echo ""
echo "=== 배포 완료 ==="
echo "릴리즈: $RELEASE_NAME"
echo "상태 확인: sudo systemctl status $SERVICE_NAME"
echo "로그 확인: sudo journalctl -u $SERVICE_NAME -f"
