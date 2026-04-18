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
    def check_dynamic_session():
        """
        [고도화] 매장 설정의 '자동 로그아웃 방지' 여부에 따라 세션 만료 정책을 실시간 적용합니다.
        """
        if 'user_id' in session and 'store_id' in session:
            try:
                from models import Store
                from datetime import timedelta
                from flask import current_app
                
                store = db.session.get(Store, session['store_id'])
                if store and store.disable_auto_logout:
                    # 자동 로그아웃 방지가 활성화된 경우: 세션을 영구(Permanent)로 설정하고 만료 시간을 1년으로 연장
                    session.permanent = True
                    # 개별 요청마다 만료 시간을 갱신하여 사실상 무제한 유지가 가능하게 함
                    current_app.permanent_session_lifetime = timedelta(days=365)
                else:
                    # 설정이 꺼져 있는 경우: 기본 정책(7일 또는 브라우저 종료 시 삭제) 유지
                    # session.permanent = False # 선택 사항: 명시적으로 끄고 싶을 때만 사용
                    pass
            except:
                pass

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
