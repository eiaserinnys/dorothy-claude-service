"""
FileManager 단위 테스트
"""

import pytest
import tempfile
from pathlib import Path

from src.service.file_manager import FileManager, AttachmentError


@pytest.fixture
def file_manager():
    """테스트용 FileManager (임시 디렉토리)"""
    with tempfile.TemporaryDirectory() as tmpdir:
        yield FileManager(base_dir=tmpdir)


def test_validate_file_size(file_manager):
    """파일 크기 검증 테스트"""
    # 정상 크기
    file_manager.validate_file("test.txt", 1024)

    # 너무 큰 파일
    with pytest.raises(AttachmentError, match="너무 큽니다"):
        file_manager.validate_file("test.txt", 10 * 1024 * 1024)


def test_validate_file_extension(file_manager):
    """파일 확장자 검증 테스트"""
    # 정상 확장자
    file_manager.validate_file("test.txt", 1024)
    file_manager.validate_file("test.py", 1024)
    file_manager.validate_file("test.png", 1024)

    # 위험한 확장자
    with pytest.raises(AttachmentError, match="허용되지 않는"):
        file_manager.validate_file("test.env", 1024)

    with pytest.raises(AttachmentError, match="허용되지 않는"):
        file_manager.validate_file("test.pem", 1024)


@pytest.mark.asyncio
async def test_save_file(file_manager):
    """파일 저장 테스트"""
    content = b"Hello, World!"

    result = await file_manager.save_file(
        thread_id=123456,
        filename="test.txt",
        content=content,
    )

    assert result["filename"] == "test.txt"
    assert result["size"] == len(content)
    assert result["content_type"] == "text/plain"
    assert Path(result["path"]).exists()


def test_cleanup_thread(file_manager):
    """스레드 첨부 파일 정리 테스트"""
    # 파일 생성
    thread_dir = file_manager.get_thread_dir(123456)
    (thread_dir / "test1.txt").write_text("test1")
    (thread_dir / "test2.txt").write_text("test2")

    # 정리
    removed = file_manager.cleanup_thread(123456)
    assert removed == 2
    assert not thread_dir.exists()


def test_get_stats(file_manager):
    """통계 조회 테스트"""
    stats = file_manager.get_stats()

    assert "base_dir" in stats
    assert "thread_count" in stats
    assert "total_files" in stats
    assert "total_size_mb" in stats
