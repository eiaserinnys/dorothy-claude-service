#!/bin/bash
# Dorothy Claude Service 설치 스크립트

set -e

SERVICE_NAME="dorothy-claude-service"
SERVICE_DIR="/home/eias/dorothy-claude-service"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "=== $SERVICE_NAME 설치 스크립트 ==="

# 1. 디렉토리 구조 생성
echo "1. 디렉토리 구조 생성..."
mkdir -p "$SERVICE_DIR/releases"
mkdir -p "$SERVICE_DIR/shared"

# 2. 심볼릭 링크가 없으면 생성
if [ ! -L "$SERVICE_DIR/current" ]; then
    echo "   - current 심볼릭 링크 생성 필요"
    echo "   - 배포 후 'ln -sfn releases/<release> current' 실행 필요"
fi

# 3. .env 파일 확인
if [ ! -f "$SERVICE_DIR/shared/.env" ]; then
    echo "2. .env 파일 생성..."
    cp "$SCRIPT_DIR/../.env.example" "$SERVICE_DIR/shared/.env"
    echo "   ⚠️  $SERVICE_DIR/shared/.env 파일을 편집하세요!"
else
    echo "2. .env 파일 존재 (스킵)"
fi

# 4. systemd 서비스 설치
echo "3. systemd 서비스 설치..."
sudo cp "$SCRIPT_DIR/$SERVICE_NAME.service" /etc/systemd/system/
sudo systemctl daemon-reload

# 5. 서비스 활성화 (자동 시작)
echo "4. 서비스 활성화..."
sudo systemctl enable $SERVICE_NAME

echo ""
echo "=== 설치 완료 ==="
echo ""
echo "다음 단계:"
echo "  1. $SERVICE_DIR/shared/.env 파일 편집"
echo "  2. 배포: ./scripts/deploy.sh"
echo "  3. 시작: sudo systemctl start $SERVICE_NAME"
echo "  4. 상태: sudo systemctl status $SERVICE_NAME"
echo "  5. 로그: sudo journalctl -u $SERVICE_NAME -f"
