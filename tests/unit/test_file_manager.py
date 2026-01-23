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


def test_cleanup_old_files(file_manager):
    """오래된 파일 정리 테스트"""
    import time

    # 오래된 디렉토리 생성 (과거 시간으로 설정)
    old_thread_dir = file_manager.get_thread_dir(111111)
    (old_thread_dir / "old_file.txt").write_text("old content")

    # 최근 디렉토리 생성
    new_thread_dir = file_manager.get_thread_dir(222222)
    (new_thread_dir / "new_file.txt").write_text("new content")

    # 오래된 디렉토리의 mtime을 25시간 전으로 변경
    import os
    old_time = time.time() - (25 * 3600)
    os.utime(old_thread_dir, (old_time, old_time))

    # 정리 실행 (24시간 기준)
    cleaned = file_manager.cleanup_old_files(max_age_hours=24)

    # 결과 확인
    assert cleaned == 1
    assert not old_thread_dir.exists()
    assert new_thread_dir.exists()


def test_cleanup_old_files_empty_dir(file_manager):
    """빈 디렉토리에서 정리"""
    cleaned = file_manager.cleanup_old_files(max_age_hours=24)
    assert cleaned == 0


def test_is_safe_path_in_attachment_dir(file_manager):
    """첨부 파일 디렉토리 내 경로 허용"""
    thread_dir = file_manager.get_thread_dir(123456)
    test_file = thread_dir / "test.txt"
    test_file.write_text("content")

    assert file_manager.is_safe_path(str(test_file)) is True


def test_is_safe_path_outside_allowed_dir(file_manager):
    """허용되지 않은 디렉토리 거부"""
    assert file_manager.is_safe_path("/etc/passwd") is False
    assert file_manager.is_safe_path("/home/user/secret.txt") is False


def test_is_safe_path_dangerous_extension(file_manager):
    """위험한 확장자 거부"""
    thread_dir = file_manager.get_thread_dir(123456)
    # Path('.env').suffix는 빈 문자열이므로 credentials.env 사용
    env_file = thread_dir / "credentials.env"
    env_file.write_text("SECRET=value")

    assert file_manager.is_safe_path(str(env_file)) is False


def test_is_safe_path_workspace_dir(file_manager, tmp_path):
    """워크스페이스 디렉토리 내 파일 허용"""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    test_file = workspace / "test.txt"
    test_file.write_text("content")

    assert file_manager.is_safe_path(str(test_file), workspace_dir=str(workspace)) is True


def test_is_safe_path_nonexistent_file(file_manager):
    """존재하지 않는 파일 거부"""
    assert file_manager.is_safe_path("/tmp/nonexistent_file_12345.txt") is False


def test_is_safe_path_directory(file_manager):
    """디렉토리 거부"""
    thread_dir = file_manager.get_thread_dir(123456)
    assert file_manager.is_safe_path(str(thread_dir)) is False


def test_is_safe_path_large_file(file_manager):
    """너무 큰 파일 거부"""
    thread_dir = file_manager.get_thread_dir(123456)
    large_file = thread_dir / "large.bin"
    large_file.write_bytes(b"x" * (9 * 1024 * 1024))  # 9MB

    assert file_manager.is_safe_path(str(large_file)) is False
