"""
MQutils/scheduler_config.py
APScheduler 작업 등록 모듈

사용법:
    from MQutils.scheduler_config import setup_scheduler
    setup_scheduler(scheduler, app, db)
"""


def setup_scheduler(scheduler, app, db) -> None:
    """백그라운드 정기 작업을 스케줄러에 등록합니다."""
    if scheduler.running:
        return

    from models import User, Store, Order
    from MQutils.backup import send_daily_backup
    from MQutils.health import keep_alive_ping
    from sqlalchemy import text

    # 1. 주간 백업 (매주 월요일 00:00)
    models_to_backup = [
        ('운영자 및 유저', User),
        ('가맹점 정보', Store),
        ('주문 내역', Order),
    ]
    scheduler.add_job(
        id='weekly_backup_job',
        func=send_daily_backup,
        args=(app, db, models_to_backup),
        trigger='cron', day_of_week='mon', hour=0, minute=0
    )

    # 2. Keep-Alive 핑 (10분 주기)
    scheduler.add_job(
        id='keep_alive_job',
        func=keep_alive_ping,
        args=(app, db, text),
        trigger='interval', minutes=10
    )

    # 3. SaaS 자동 결제 수금 (매일 새벽 02:00)
    from routes.billing import auto_collect_subscriptions
    scheduler.add_job(
        id='auto_billing_job',
        func=auto_collect_subscriptions,
        args=(app,),
        trigger='cron', hour=2, minute=0
    )

    scheduler.start()
    print("⏰ [스케줄러] 정기 백업 · Keep-Alive · 자동 결제 엔진 활성화")
