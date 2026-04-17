"""
MQutils/middleware.py
Flask before_request 미들웨어 모음

사용법:
    from MQutils.middleware import register_middlewares
    register_middlewares(app, db)
"""
from datetime import datetime
from flask import session, request, redirect


EXPIRY_BYPASS_PREFIXES = (
    '/billing', '/login', '/logout', '/register', '/static',
    '/api/billing', '/api/health', '/ping', '/privacy', '/terms', '/'
)


def register_middlewares(app, db) -> None:
    """app에 before_request 훅을 등록합니다."""

    @app.before_request
    def check_subscription_expiry():
        """점주(owner) 세션에서 매장 만기·정지 상태 감지 → /billing/expired 리다이렉트"""
        path = request.path
        if any(path.startswith(p) for p in EXPIRY_BYPASS_PREFIXES):
            return

        role = session.get('role')
        store_id = session.get('store_id')

        if role != 'owner' or not store_id:
            return

        try:
            from models import Store
            store = db.session.get(Store, store_id)
            if store:
                if store.status == 'suspended':
                    if not path.startswith('/billing'):
                        return redirect('/billing/expired')
                elif store.expires_at and datetime.utcnow() > store.expires_at:
                    if not path.startswith('/billing'):
                        return redirect('/billing/expired')
        except Exception as e:
            print(f'⚠️ [만기 체크 오류] {e}')
