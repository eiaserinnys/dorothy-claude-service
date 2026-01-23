"""
Attachments API 통합 테스트

첨부 파일 업로드 및 정리 엔드포인트 테스트
"""

import pytest
import io
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    """FastAPI 테스트 클라이언트 (인증 비활성화)"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': ''}, clear=False):
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


@pytest.fixture
def auth_client():
    """인증 활성화된 테스트 클라이언트"""
    with patch.dict('os.environ', {'CLAUDE_SERVICE_TOKEN': 'test-token'}, clear=False):
        import importlib
        import src.api.auth as auth_module
        importlib.reload(auth_module)

        from src.main import app
        with TestClient(app) as test_client:
            yield test_client


class TestUploadAttachment:
    """POST /attachments 엔드포인트 테스트"""

    def test_upload_text_file(self, client):
        """텍스트 파일 업로드"""
        file_content = b"Hello, World!"
        files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
        data = {"thread_id": "123456"}

        response = client.post("/attachments", files=files, data=data)

        assert response.status_code == 201
        result = response.json()
        assert result["filename"] == "test.txt"
        assert result["size"] == len(file_content)
        assert result["content_type"] == "text/plain"
        assert "path" in result

    def test_upload_image_file(self, client):
        """이미지 파일 업로드"""
        # 최소한의 PNG 헤더
        png_header = b'\x89PNG\r\n\x1a\n' + b'\x00' * 100
        files = {"file": ("image.png", io.BytesIO(png_header), "image/png")}
        data = {"thread_id": "123456"}

        response = client.post("/attachments", files=files, data=data)

        assert response.status_code == 201
        result = response.json()
        assert result["filename"] == "image.png"

    def test_upload_requires_thread_id(self, client):
        """thread_id 필수"""
        file_content = b"content"
        files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}

        response = client.post("/attachments", files=files)

        assert response.status_code == 422  # Validation error

    def test_upload_requires_file(self, client):
        """file 필수"""
        data = {"thread_id": "123456"}

        response = client.post("/attachments", data=data)

        assert response.status_code == 422

    def test_upload_dangerous_extension_rejected(self, client):
        """.env 파일 업로드 거부"""
        file_content = b"SECRET=value"
        # Path('.env').suffix는 빈 문자열이므로 credentials.env 사용
        files = {"file": ("credentials.env", io.BytesIO(file_content), "text/plain")}
        data = {"thread_id": "123456"}

        response = client.post("/attachments", files=files, data=data)

        assert response.status_code == 400
        assert "허용되지 않는" in response.json()["detail"]["error"]["message"]

    def test_upload_pem_file_rejected(self, client):
        """.pem 파일 업로드 거부"""
        file_content = b"-----BEGIN PRIVATE KEY-----"
        files = {"file": ("key.pem", io.BytesIO(file_content), "application/x-pem-file")}
        data = {"thread_id": "123456"}

        response = client.post("/attachments", files=files, data=data)

        assert response.status_code == 400

    def test_upload_large_file_rejected(self, client):
        """대용량 파일 업로드 거부"""
        # 9MB 파일 (8MB 제한 초과)
        large_content = b"x" * (9 * 1024 * 1024)
        files = {"file": ("large.bin", io.BytesIO(large_content), "application/octet-stream")}
        data = {"thread_id": "123456"}

        response = client.post("/attachments", files=files, data=data)

        assert response.status_code == 400
        assert "너무 큽니다" in response.json()["detail"]["error"]["message"]

    def test_upload_requires_auth(self, auth_client):
        """인증 필요"""
        file_content = b"content"
        files = {"file": ("test.txt", io.BytesIO(file_content), "text/plain")}
        data = {"thread_id": "123456"}

        # 인증 없이
        response = auth_client.post("/attachments", files=files, data=data)
        assert response.status_code == 401

        # 인증 있음
        response = auth_client.post(
            "/attachments",
            files=files,
            data=data,
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 201


class TestCleanupAttachments:
    """DELETE /attachments/{thread_id} 엔드포인트 테스트"""

    def test_cleanup_nonexistent_thread(self, client):
        """존재하지 않는 스레드 정리 (0개 삭제)"""
        response = client.delete("/attachments/999999")

        assert response.status_code == 200
        result = response.json()
        assert result["cleaned"] is True
        assert result["files_removed"] == 0

    def test_cleanup_after_upload(self, client):
        """업로드 후 정리"""
        thread_id = "123456"

        # 파일 업로드
        files = {"file": ("test.txt", io.BytesIO(b"content"), "text/plain")}
        data = {"thread_id": thread_id}
        client.post("/attachments", files=files, data=data)

        # 정리
        response = client.delete(f"/attachments/{thread_id}")

        assert response.status_code == 200
        result = response.json()
        assert result["cleaned"] is True
        assert result["files_removed"] >= 1

    def test_cleanup_multiple_files(self, client):
        """여러 파일 정리"""
        thread_id = "123456"

        # 여러 파일 업로드
        for i in range(3):
            files = {"file": (f"test{i}.txt", io.BytesIO(f"content{i}".encode()), "text/plain")}
            data = {"thread_id": thread_id}
            client.post("/attachments", files=files, data=data)

        # 정리
        response = client.delete(f"/attachments/{thread_id}")

        assert response.status_code == 200
        result = response.json()
        assert result["files_removed"] == 3

    def test_cleanup_requires_auth(self, auth_client):
        """정리도 인증 필요"""
        # 인증 없이
        response = auth_client.delete("/attachments/123456")
        assert response.status_code == 401

        # 인증 있음
        response = auth_client.delete(
            "/attachments/123456",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code == 200


class TestAttachmentIntegration:
    """첨부 파일 전체 흐름 테스트"""

    def test_upload_and_verify_path(self, client):
        """업로드 후 경로 확인"""
        import os
        from pathlib import Path

        thread_id = 987654321  # API expects integer
        file_content = b"Integration test content"
        files = {"file": ("integration.txt", io.BytesIO(file_content), "text/plain")}
        data = {"thread_id": str(thread_id)}  # Form data is always string

        response = client.post("/attachments", files=files, data=data)
        assert response.status_code == 201

        result = response.json()
        file_path = Path(result["path"])

        # 파일이 실제로 존재하는지 확인
        assert file_path.exists()
        assert file_path.read_bytes() == file_content

        # 정리
        client.delete(f"/attachments/{thread_id}")
        assert not file_path.exists()
