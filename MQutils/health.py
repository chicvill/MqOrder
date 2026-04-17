"""
MQutils/health.py
Keep-Alive 핑 & DB 헬스체크 유틸리티
"""
import os


def keep_alive_ping(app, db, text) -> None:
    """Render 무료 플랜 슬립 방지 + DB 연결 상태 점검.

    APScheduler에서 10분 주기로 호출합니다.
    """
    # 1. DB 연결 점검
    try:
        with app.app_context():
            db.session.execute(text("SELECT 1"))
            print("🟢 [Health] 데이터베이스 연결 확인됨")
    except Exception as e:
        print(f"🚨 [오류 경보] DB 연결 실패: {e}")

    # 2. 내부 핑 (서버 슬립 방지)
    try:
        from urllib.request import urlopen
        urlopen("http://127.0.0.1:10000/health", timeout=10)
        print("🕒 [Keep-Alive] 핑 성공 (내부 주소)")
    except Exception as e:
        print(f"⚠️ [Keep-Alive] 핑 실패: {e}")
