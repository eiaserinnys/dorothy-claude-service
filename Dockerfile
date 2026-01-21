# Claude Code Service Dockerfile
#
# Python + Node.js 환경 (Claude Code CLI는 Node.js 기반)

FROM python:3.12-slim

# Node.js 설치 (Claude Code CLI용)
RUN apt-get update && apt-get install -y \
    curl \
    git \
    ssh \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y nodejs \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Claude Code CLI 설치
RUN npm install -g @anthropic-ai/claude-code

# 작업 디렉토리
WORKDIR /app

# Python 의존성 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 애플리케이션 코드 복사
COPY src/ ./src/

# 헬스체크용 curl 확인
RUN curl --version

# 환경변수 기본값
ENV PORT=8080
ENV LOG_LEVEL=INFO
ENV MAX_CONCURRENT_SESSIONS=3

# 포트 노출
EXPOSE 8080

# 실행
CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8080"]
