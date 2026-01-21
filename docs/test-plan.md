# Claude Code Service 테스트 계획

## 1. 테스트 전략 개요

### 테스트 피라미드

```
        /\
       /  \    E2E Tests (5%)
      /----\   - Dorothy Bot + Service 통합
     /      \
    /--------\ Integration Tests (25%)
   /          \ - API 엔드포인트 테스트
  /------------\ - SSE 스트리밍 테스트
 /              \
/----------------\ Unit Tests (70%)
                   - SessionManager
                   - ResourceManager
                   - FileManager
```

## 2. 단위 테스트 (Unit Tests)

### 2.1 SessionManager 테스트

**파일**: `tests/unit/test_session_manager.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_create_session` | 새 세션 생성 |
| `test_create_session_duplicate_thread` | 같은 thread_id로 중복 생성 시 에러 |
| `test_get_session` | 세션 조회 |
| `test_get_session_not_found` | 존재하지 않는 세션 조회 |
| `test_update_session_status` | 세션 상태 업데이트 |
| `test_delete_session` | 세션 삭제 |
| `test_list_sessions` | 활성 세션 목록 |

### 2.2 ResourceManager 테스트

**파일**: `tests/unit/test_resource_manager.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_acquire_slot` | 슬롯 획득 성공 |
| `test_acquire_slot_limit_exceeded` | 동시 실행 제한 초과 |
| `test_release_slot` | 슬롯 반환 |
| `test_get_active_count` | 활성 세션 수 조회 |
| `test_concurrent_acquire` | 동시 획득 테스트 (race condition) |

### 2.3 FileManager 테스트

**파일**: `tests/unit/test_file_manager.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_save_attachment` | 첨부 파일 저장 |
| `test_save_attachment_size_limit` | 파일 크기 제한 (8MB) |
| `test_save_attachment_dangerous_extension` | 위험한 확장자 차단 |
| `test_cleanup_thread_attachments` | 스레드 첨부 파일 정리 |
| `test_is_safe_path` | 경로 보안 검증 |
| `test_extract_attachments` | 출력에서 [ATTACH:] 추출 |

### 2.4 OutputSanitizer 테스트

**파일**: `tests/unit/test_output_sanitizer.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_sanitize_api_keys` | API 키 마스킹 (OpenAI, Anthropic) |
| `test_sanitize_github_tokens` | GitHub 토큰 마스킹 |
| `test_sanitize_env_vars` | 환경변수 마스킹 |
| `test_no_false_positives` | 일반 텍스트는 변경 안 함 |

## 3. 통합 테스트 (Integration Tests)

### 3.1 API 엔드포인트 테스트

**파일**: `tests/integration/test_api_endpoints.py`

```python
# 테스트 클라이언트 설정
@pytest.fixture
def client():
    from src.main import app
    with TestClient(app) as client:
        yield client
```

| 테스트 케이스 | HTTP 메서드 | 엔드포인트 |
|--------------|------------|-----------|
| `test_health_check` | GET | /health |
| `test_create_session` | POST | /sessions |
| `test_create_session_unauthorized` | POST | /sessions (토큰 없음) |
| `test_get_session` | GET | /sessions/{id} |
| `test_delete_session` | DELETE | /sessions/{id} |
| `test_upload_attachment` | POST | /attachments |
| `test_get_status` | GET | /status |

### 3.2 SSE 스트리밍 테스트

**파일**: `tests/integration/test_sse_streaming.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_query_streaming_basic` | 기본 쿼리 스트리밍 |
| `test_query_streaming_progress_events` | progress 이벤트 수신 |
| `test_query_streaming_memory_events` | memory 이벤트 수신 |
| `test_query_streaming_complete` | complete 이벤트로 종료 |
| `test_query_streaming_error` | error 이벤트 처리 |
| `test_query_streaming_timeout` | 타임아웃 처리 |

### 3.3 개입 메시지 테스트

**파일**: `tests/integration/test_intervention.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_intervene_while_running` | 실행 중 개입 메시지 |
| `test_intervene_not_running` | 실행 안 할 때 개입 시도 |
| `test_multiple_interventions` | 여러 개입 메시지 큐잉 |

## 4. E2E 테스트 (End-to-End Tests)

### 4.1 Dorothy Bot 통합 테스트

**파일**: `tests/e2e/test_bot_integration.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_bot_create_session_via_service` | 봇이 서비스로 세션 생성 |
| `test_bot_query_via_service` | 봇이 서비스로 쿼리 전송 |
| `test_bot_receive_streaming_response` | 봇이 스트리밍 응답 수신 |
| `test_bot_handle_service_error` | 서비스 에러 시 봇 처리 |
| `test_bot_session_continuity` | 세션 연속성 (resume) |

### 4.2 Docker Compose 통합 테스트

**파일**: `tests/e2e/test_docker_compose.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_service_starts` | 서비스 정상 시작 |
| `test_health_check_passes` | 헬스체크 통과 |
| `test_volume_mounts` | 볼륨 마운트 확인 |
| `test_graceful_shutdown` | 정상 종료 |

## 5. 성능 테스트

### 5.1 부하 테스트

**파일**: `tests/performance/test_load.py`

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_concurrent_sessions_3` | 동시 3개 세션 실행 |
| `test_concurrent_sessions_exceed_limit` | 제한 초과 시 거부 |
| `test_session_throughput` | 초당 세션 생성 처리량 |

### 5.2 메모리 테스트

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_no_memory_leak_sessions` | 세션 생성/삭제 반복 시 메모리 누수 |
| `test_no_memory_leak_attachments` | 첨부 파일 처리 시 메모리 누수 |

## 6. 테스트 환경

### 6.1 로컬 테스트

```bash
# 단위 테스트
pytest tests/unit -v

# 통합 테스트
pytest tests/integration -v

# 전체 테스트 (커버리지 포함)
pytest --cov=src --cov-report=html
```

### 6.2 CI 테스트 (GitHub Actions)

```yaml
# .github/workflows/test.yml
name: Tests
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: pip install -r requirements.txt
      - run: pytest --cov=src
```

### 6.3 E2E 테스트 환경

E2E 테스트는 실제 Claude Code CLI가 필요하므로:
1. Docker Compose로 전체 스택 실행
2. 테스트용 Claude API 키 사용 (비용 최소화)
3. 모의 응답으로 대부분 테스트, 실제 API는 최소 사용

## 7. 테스트 커버리지 목표

| 구분 | 목표 |
|------|------|
| 전체 코드 커버리지 | 80% 이상 |
| 핵심 로직 (session, resource) | 90% 이상 |
| API 엔드포인트 | 100% |

## 8. 테스트 데이터

### Mock 데이터

```python
# tests/conftest.py
@pytest.fixture
def mock_session():
    return {
        "session_id": "ses_test123",
        "thread_id": 123456789,
        "user": "testuser#1234",
        "status": "ready"
    }

@pytest.fixture
def mock_claude_response():
    return {
        "result": "테스트 응답입니다.",
        "session_id": "abc123"
    }
```

### 테스트용 첨부 파일

```python
@pytest.fixture
def test_file(tmp_path):
    file = tmp_path / "test.txt"
    file.write_text("테스트 내용")
    return file
```

## 9. 롤백 테스트

Feature flag 전환 테스트:

| 테스트 케이스 | 설명 |
|--------------|------|
| `test_feature_flag_service_mode` | CLAUDE_SERVICE_URL 설정 시 서비스 모드 |
| `test_feature_flag_local_mode` | 설정 없을 때 로컬 모드 |
| `test_switch_to_local_on_service_error` | 서비스 에러 시 로컬 폴백 |
