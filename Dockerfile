# Python 3.11 슬림 이미지를 기반으로 사용
FROM python:3.11-slim

# 작업 디렉토리 설정
WORKDIR /app

# 필수 라이브러리 설치 (OpenCV 등 이미지 처리가 필요한 경우 필수 패키지 포함)
RUN apt-get update && apt-get install -y \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

# 의존성 파일 복사 및 설치
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 소스 코드 복사
COPY . .

# Flask 앱 실행을 위한 환경 변수
ENV FLASK_APP=app.py
ENV PYTHONUNBUFFERED=1

# Socket.IO 지원을 위해 Gunicorn(Eventlet) 사용
EXPOSE 5000
CMD ["gunicorn", "--worker-class", "eventlet", "-w", "1", "--bind", "0.0.0.0:5000", "app:app"]
