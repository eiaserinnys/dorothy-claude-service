#!/bin/bash
# Dorothy Claude Service 설치 스크립트
#
# 환경변수:
#   SERVICE_DIR: 서비스 설치 경로 (기본: $HOME/dorothy-claude-service)
#   WORKSPACE_DIR: Claude Code 작업 디렉토리 (기본: $HOME/claude-workspace)

set -e

SERVICE_NAME="dorothy-claude-service"
SERVICE_DIR="${SERVICE_DIR:-$HOME/dorothy-claude-service}"
WORKSPACE_DIR="${WORKSPACE_DIR:-$HOME/claude-workspace}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CURRENT_USER="$(whoami)"
CURRENT_GROUP="$(id -gn)"

echo "=== $SERVICE_NAME 설치 스크립트 ==="
echo ""
echo "설정:"
echo "  SERVICE_DIR:   $SERVICE_DIR"
echo "  WORKSPACE_DIR: $WORKSPACE_DIR"
echo "  USER:          $CURRENT_USER"
echo ""

# 1. 디렉토리 구조 생성
echo "1. 디렉토리 구조 생성..."
mkdir -p "$SERVICE_DIR/releases"
mkdir -p "$SERVICE_DIR/shared"

# 2. 심볼릭 링크가 없으면 안내
if [ ! -L "$SERVICE_DIR/current" ]; then
    echo "   - current 심볼릭 링크 생성 필요"
    echo "   - 배포 후 'ln -sfn releases/<release> current' 실행 필요"
fi

# 3. .env 파일 확인
if [ ! -f "$SERVICE_DIR/shared/.env" ]; then
    echo "2. .env 파일 생성..."
    cp "$SCRIPT_DIR/../.env.example" "$SERVICE_DIR/shared/.env"
    # WORKSPACE_DIR 설정
    sed -i "s|WORKSPACE_DIR=.*|WORKSPACE_DIR=$WORKSPACE_DIR|" "$SERVICE_DIR/shared/.env"
    echo "   ⚠️  $SERVICE_DIR/shared/.env 파일을 편집하세요!"
else
    echo "2. .env 파일 존재 (스킵)"
fi

# 4. systemd 서비스 파일 생성 (템플릿에서)
echo "3. systemd 서비스 파일 생성..."

# 메인 서비스 파일
sed -e "s|__USER__|$CURRENT_USER|g" \
    -e "s|__GROUP__|$CURRENT_GROUP|g" \
    -e "s|__SERVICE_DIR__|$SERVICE_DIR|g" \
    -e "s|__WORKSPACE_DIR__|$WORKSPACE_DIR|g" \
    "$SCRIPT_DIR/$SERVICE_NAME.service.template" > "/tmp/$SERVICE_NAME.service"

# 헬스 체크 서비스 파일
sed -e "s|__USER__|$CURRENT_USER|g" \
    -e "s|__GROUP__|$CURRENT_GROUP|g" \
    -e "s|__SERVICE_DIR__|$SERVICE_DIR|g" \
    "$SCRIPT_DIR/$SERVICE_NAME-health.service.template" > "/tmp/$SERVICE_NAME-health.service"

# 5. systemd에 설치
echo "4. systemd에 서비스 설치..."
sudo cp "/tmp/$SERVICE_NAME.service" /etc/systemd/system/
sudo cp "/tmp/$SERVICE_NAME-health.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 6. 서비스 활성화
echo "5. 서비스 활성화..."
sudo systemctl enable $SERVICE_NAME

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. $SERVICE_DIR/shared/.env 파일 편집"
echo "  2. 공유 가상환경 생성:"
echo "     python3 -m venv $SERVICE_DIR/shared/.venv"
echo "     source $SERVICE_DIR/shared/.venv/bin/activate"
echo "     pip install -r requirements.txt"
echo "  3. 배포: ./scripts/deploy.sh"
echo "  4. 시작: sudo systemctl start $SERVICE_NAME"
echo "  5. 상태: sudo systemctl status $SERVICE_NAME"
echo "  6. 로그: sudo journalctl -u $SERVICE_NAME -f"
