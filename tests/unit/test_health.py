"""
Health endpoint unit tests
"""

import pytest


def test_health_check(client):
    """헬스 체크 엔드포인트 테스트"""
    response = client.get("/health")
    assert response.status_code == 200

    data = response.json()
    assert data["status"] == "healthy"
    assert "version" in data
    assert "uptime_seconds" in data
    assert data["uptime_seconds"] >= 0


def test_status_endpoint(client):
    """상태 엔드포인트 테스트"""
    response = client.get("/status")
    assert response.status_code == 200

    data = response.json()
    assert "active_sessions" in data
    assert "max_concurrent" in data
    assert "sessions" in data
    assert isinstance(data["sessions"], list)
