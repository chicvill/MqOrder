FROM python:3.11-slim

# 1. Cloudflare 터널(linux-amd64) 설치 및 시스템 패키지 정리
RUN apt-get update && apt-get install -y curl && \
    curl -L --output /usr/local/bin/cloudflared https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64 && \
    chmod +x /usr/local/bin/cloudflared && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 2. 소스 복사 및 의존성 설치
COPY . .
RUN pip install --no-cache-dir -r requirements.txt

# 3. 환경 변수 설정
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# 4. Render 포트 환경변수($PORT)를 사용하여 Gunicorn 실행
CMD gunicorn --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT app:app
