#!/bin/bash
# Dorothy Claude Service 배포 스크립트
#
# 환경변수:
#   SERVICE_DIR: 서비스 설치 경로 (기본: $HOME/dorothy-claude-service)

set -e

SERVICE_NAME="dorothy-claude-service"
SERVICE_DIR="${SERVICE_DIR:-$HOME/dorothy-claude-service}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
RELEASE_NAME="$(date +%Y-%m-%d-%H%M%S)"
RELEASE_DIR="$SERVICE_DIR/releases/$RELEASE_NAME"

echo "=== $SERVICE_NAME 배포 ($RELEASE_NAME) ==="
echo ""
echo "설정:"
echo "  SERVICE_DIR: $SERVICE_DIR"
echo "  REPO_DIR:    $REPO_DIR"
echo ""

# 1. Git pull (최신 코드)
echo "1. 최신 코드 가져오기..."
cd "$REPO_DIR"
git fetch origin
git reset --hard origin/main 2>/dev/null || git reset --hard origin/master

# 2. 릴리즈 디렉토리 생성
echo "2. 릴리즈 디렉토리 생성..."
mkdir -p "$RELEASE_DIR"

# 3. 코드 복사 (.git 제외)
echo "3. 코드 복사..."
rsync -av --exclude='.git' --exclude='__pycache__' --exclude='.pytest_cache' --exclude='.venv' "$REPO_DIR/" "$RELEASE_DIR/"

# 4. 공유 자원 심볼릭 링크
echo "4. 공유 자원 심볼릭 링크..."
ln -sfn "$SERVICE_DIR/shared/.env" "$RELEASE_DIR/.env"
ln -sfn "$SERVICE_DIR/shared/.venv" "$RELEASE_DIR/.venv"

# 5. 의존성 업데이트 (공유 venv 사용)
echo "5. 의존성 업데이트..."
source "$SERVICE_DIR/shared/.venv/bin/activate"
pip install --upgrade -q -r "$RELEASE_DIR/requirements.txt"

# 6. 심볼릭 링크 업데이트
echo "6. current 심볼릭 링크 업데이트..."
ln -sfn "$RELEASE_DIR" "$SERVICE_DIR/current"

# 7. 서비스 재시작
echo "7. 서비스 재시작..."
sudo systemctl restart $SERVICE_NAME

# 8. 헬스 체크
echo "8. 헬스 체크..."
sleep 3
if curl -sf http://127.0.0.1:8090/health > /dev/null; then
    echo "   ✅ 서비스 정상 동작"
else
    echo "   ❌ 헬스 체크 실패!"
    echo "   로그 확인: sudo journalctl -u $SERVICE_NAME -n 50"
    exit 1
fi

# 9. 이전 릴리즈 정리 (최근 5개만 유지)
echo "9. 이전 릴리즈 정리..."
cd "$SERVICE_DIR/releases"
ls -t | tail -n +6 | xargs -r rm -rf

echo ""
echo "=== 배포 완료 ==="
echo "릴리즈: $RELEASE_NAME"
echo "상태 확인: sudo systemctl status $SERVICE_NAME"
echo "로그 확인: sudo journalctl -u $SERVICE_NAME -f"
