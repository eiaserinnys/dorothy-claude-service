#!/bin/bash
# Dorothy Claude Service 헬스 체크 스크립트
# cron이나 systemd timer로 주기적으로 실행하여 서비스 상태 모니터링

SERVICE_NAME="dorothy-claude-service"
HEALTH_URL="http://127.0.0.1:8090/health"
DISCORD_WEBHOOK_URL="${DISCORD_ALERT_WEBHOOK_URL:-}"
ALERT_FILE="/tmp/${SERVICE_NAME}-alert-sent"
MAX_RETRIES=3
RETRY_DELAY=5

# 알림 전송 함수
send_discord_alert() {
    local status="$1"
    local message="$2"
    local color="$3"  # 3066993 = green, 15158332 = red, 16776960 = yellow

    if [ -z "$DISCORD_WEBHOOK_URL" ]; then
        echo "Warning: DISCORD_ALERT_WEBHOOK_URL not set, skipping Discord notification"
        return
    fi

    local payload=$(cat <<EOF
{
    "embeds": [{
        "title": "🤖 Dorothy Claude Service Alert",
        "description": "$message",
        "color": $color,
        "fields": [
            {"name": "Service", "value": "$SERVICE_NAME", "inline": true},
            {"name": "Status", "value": "$status", "inline": true},
            {"name": "Server", "value": "$(hostname)", "inline": true}
        ],
        "timestamp": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    }]
}
EOF
)

    curl -s -H "Content-Type: application/json" -d "$payload" "$DISCORD_WEBHOOK_URL" > /dev/null
}

# 헬스 체크 실행
check_health() {
    local response
    local http_code

    for i in $(seq 1 $MAX_RETRIES); do
        response=$(curl -s -o /tmp/health-response.json -w "%{http_code}" "$HEALTH_URL" 2>/dev/null)

        if [ "$response" = "200" ]; then
            return 0
        fi

        if [ $i -lt $MAX_RETRIES ]; then
            echo "Attempt $i failed, retrying in ${RETRY_DELAY}s..."
            sleep $RETRY_DELAY
        fi
    done

    return 1
}

# 메인 로직
main() {
    if check_health; then
        # 서비스 정상
        if [ -f "$ALERT_FILE" ]; then
            # 이전에 알림을 보냈으면 복구 알림 전송
            send_discord_alert "✅ Recovered" "Service is back online and healthy." "3066993"
            rm -f "$ALERT_FILE"
            echo "$(date): Service recovered"
        else
            echo "$(date): Service healthy"
        fi
    else
        # 서비스 다운
        if [ ! -f "$ALERT_FILE" ]; then
            # 처음 다운된 경우에만 알림 전송 (중복 방지)
            send_discord_alert "🔴 Down" "Service is not responding. Health check failed after $MAX_RETRIES attempts." "15158332"
            touch "$ALERT_FILE"
            echo "$(date): Service down - alert sent"
        else
            echo "$(date): Service still down (alert already sent)"
        fi

        # 선택적: 자동 재시작 시도
        if [ "${AUTO_RESTART:-false}" = "true" ]; then
            echo "Attempting automatic restart..."
            sudo systemctl restart $SERVICE_NAME
        fi
    fi
}

main "$@"
