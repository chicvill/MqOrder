"""
app.py  ─  MQnet SaaS Application Factory
모든 비즈니스 로직은 routes/* 와 MQutils/* 로 분리되어 있습니다.
"""
import os
import sys

# ─── [Win] .venv 경로 보정 ───────────────────────────────────
if sys.platform == 'win32':
    _venv = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
    if os.path.exists(_venv) and _venv not in sys.path:
        sys.path.insert(0, _venv)

from datetime import datetime, timedelta

from dotenv import load_dotenv
load_dotenv()

from flask import Flask
from flask_apscheduler import APScheduler
from werkzeug.middleware.proxy_fix import ProxyFix
from sqlalchemy import text

BASE_DIR   = os.path.dirname(os.path.abspath(__file__))
IS_RENDER  = 'RENDER' in os.environ
DEBUG_MODE = os.environ.get('FLASK_DEBUG') == '1' or (not IS_RENDER and sys.platform == 'win32')

# ─── Cloudflare Tunnel (비차단 백그라운드) ───────────────────
print(f"🚀 [Step 1/2] SaaS 웹 서버 가동 중... (Port: {os.environ.get('PORT', 10000)})")
from MQutils.tunnel import start_cloudflare_tunnel
start_cloudflare_tunnel(BASE_DIR, IS_RENDER)

# ─── Flask App 생성 ──────────────────────────────────────────
app = Flask(__name__, static_folder='static', static_url_path='/static')
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

# ─── 설정 ────────────────────────────────────────────────────
app.config.update(
    SECRET_KEY               = os.environ.get('SECRET_KEY', 'mqnet-secret-2026'),
    DEBUG                    = DEBUG_MODE,
    SESSION_COOKIE_HTTPONLY  = True,
    PERMANENT_SESSION_LIFETIME = timedelta(days=7),
    UPLOAD_FOLDER            = os.path.join(BASE_DIR, 'static', 'images'),
    SQLALCHEMY_TRACK_MODIFICATIONS = False,
)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# 세션 쿠키 (도메인 모드)
if os.getenv("DOMAIN_MODE") == "1":
    _domain = os.getenv('SESSION_COOKIE_DOMAIN', '.chicvill.store')
    app.config.update(
        SESSION_COOKIE_DOMAIN   = _domain,
        SESSION_COOKIE_SECURE   = True,
        SESSION_COOKIE_SAMESITE = 'None',
    )
    print(f"🌐 [도메인 모드] 세션 쿠키 도메인: {_domain}")
else:
    app.config.update(
        SESSION_COOKIE_SECURE   = False,
        SESSION_COOKIE_SAMESITE = 'Lax',
    )

app.url_map.strict_slashes = False
app.jinja_env.add_extension('jinja2.ext.do')

# ─── DB 설정 ─────────────────────────────────────────────────
db_url = os.environ.get('DATABASE_URL')
if not db_url:
    db_url = f"sqlite:///{os.path.join(BASE_DIR, 'instance', 'mqnet.db')}"
    print("🗄️ [DB] 로컬 SQLite 사용")
else:
    # PostgreSQL 드라이버 보정
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
    elif db_url.startswith("postgresql://"):
        db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
    if ":6543" in db_url:
        db_url = db_url.replace(":6543", ":5432")
    try:
        from sqlalchemy.engine.url import make_url
        u = make_url(db_url)
        print(f"🔗 [DB] {u.drivername}://{u.username}:****@{u.host}:{u.port}/{u.database}")
    except Exception:
        pass

from sqlalchemy.pool import NullPool
app.config['SQLALCHEMY_DATABASE_URI']    = db_url
app.config['SQLALCHEMY_ENGINE_OPTIONS']  = {'poolclass': NullPool, 'pool_pre_ping': True}
app.config['SQLALCHEMY_POOL_SIZE']       = None

# ─── DB 초기화 ───────────────────────────────────────────────
from models import db
db.init_app(app)

with app.app_context():
    if os.environ.get('LOCAL_SKIP_MIGRATION') == 'true':
        print("⏭️ [DB] create_all 건너뜀 (LOCAL_SKIP_MIGRATION=true)")
    else:
        print("🔍 [DB] 테이블 연결 확인 중...")
        try:
            db.create_all()
            print("✅ [DB] 연결 완료.")
        except Exception as e:
            print(f"⚠️ [DB] 연결 대기: {e}")

    # 컬럼 보정은 항상 실행 (LOCAL_SKIP_MIGRATION 무관)
    try:
        from MQutils.db_migrate import run_migrations
        run_migrations(db)
    except Exception as e:
        print(f"⚠️ [DB 보정] {e}")

# ─── APScheduler ─────────────────────────────────────────────
scheduler = APScheduler()
scheduler.init_app(app)

# ─── SocketIO ────────────────────────────────────────────────
from extensions import socketio
socketio.init_app(app)

from sockets import register_socketio_events
register_socketio_events(socketio)

# ─── Blueprints & Route Modules ──────────────────────────────
from routes.attendance import attendance_bp
from routes.attendance_extra import init_extra_routes as _init_extra_att
_init_extra_att(attendance_bp)
app.register_blueprint(attendance_bp)

from routes.portal   import portal_bp
from routes.knowledge import knowledge_bp
from routes.billing  import billing_bp
from routes.misc     import misc_bp
app.register_blueprint(portal_bp)
app.register_blueprint(knowledge_bp)
app.register_blueprint(billing_bp)
app.register_blueprint(misc_bp)

from routes.auth  import init_auth_routes
from routes.admin import init_admin_routes
from routes.store import init_store_routes
init_auth_routes(app)
init_admin_routes(app)
init_store_routes(app)

# ─── 미들웨어 ────────────────────────────────────────────────
from MQutils.middleware import register_middlewares
register_middlewares(app, db)

# ─── 하위 호환 별칭 (Blueprint 이전 전 url_for 호환) ─────────
# misc_bp 로 이전된 라우트들을 기존 endpoint 이름으로도 참조 가능하게 유지
from flask import redirect as _redir, url_for as _uf
from routes.misc import (
    index as _index_fn,
    help_page as _help_fn,
    privacy_page as _privacy_fn,
    terms_page as _terms_fn,
    ping as _ping_fn,
    mobile_receipt as _receipt_fn,
    payment_info as _payment_info_fn,
)
app.add_url_rule('/_compat/index',          'index',        _index_fn)
app.add_url_rule('/_compat/help',           'help_page',    _help_fn)
app.add_url_rule('/_compat/privacy',        'privacy_page', _privacy_fn)
app.add_url_rule('/_compat/terms',          'terms_page',   _terms_fn)
app.add_url_rule('/_compat/ping',           'ping',         _ping_fn)
app.add_url_rule('/_compat/receipt/<order_id>', 'mobile_receipt', _receipt_fn)
app.add_url_rule('/_compat/<store_id>/payment_info', 'payment_info', _payment_info_fn)


# ─── 전역 컨텍스트 & 필터 ────────────────────────────────────
from MQutils import format_phone
app.jinja_env.filters['format_phone'] = format_phone

@app.context_processor
def inject_globals():
    return {
        'timedelta': timedelta,
        'now': datetime.now(),
        'config': {
            'TOSS_CLIENT_KEY': os.getenv('TOSS_CLIENT_KEY', 'test_ck_placeholder'),
            'SERVICE_DOMAIN':  os.getenv('SERVICE_DOMAIN', 'localhost:10000'),
        }
    }

@app.template_filter('format_currency')
def format_currency_filter(value):
    if value is None: return "0원"
    return "{:,}원".format(value)

@app.errorhandler(403)
def forbidden(e):
    from flask import render_template as rt
    return rt('access_denied.html'), 403


# ─── 진입점 (python app.py) ──────────────────────────────────
if __name__ == '__main__':
    import time
    port = int(os.environ.get('PORT', 10000))
    print(f"🔥 [서버 구동] 포트 {port}번에서 MQnet Central 기동 준비 중...")
    time.sleep(1)

    skip_migration = os.environ.get('LOCAL_SKIP_MIGRATION') == 'true'
    is_reloader    = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

    with app.app_context():
        if not skip_migration and not is_reloader:
            # 초기 계정·설정
            from werkzeug.security import generate_password_hash
            from models import User, Store, SystemConfig, Order

            try:
                db.create_all()
            except Exception as e:
                print(f"⚠️ [DB 생성] {e}")

            if not User.query.filter_by(username='admin').first():
                db.session.add(User(
                    username='admin',
                    password=generate_password_hash('1212'),
                    role='admin', is_approved=True, full_name='최고관리자'
                ))

            if not SystemConfig.query.first():
                db.session.add(SystemConfig(
                    site_name='MQnet Central',
                    hq_bank='농협은행',
                    hq_account='302-0000-0000-00',
                    hq_holder='(주)MQ네트웍스'
                ))

            db.session.commit()

            # 스키마 자동 보정
            from MQutils.db_migrate import run_migrations
            run_migrations(db)

        elif skip_migration:
            print("⏭️ [DB] 마이그레이션 건너뜀")

        print("👤 [계정/설정] 서버 구동 준비 완료")

        # 스케줄러 작업 등록
        try:
            from MQutils.scheduler_config import setup_scheduler
            setup_scheduler(scheduler, app, db)
        except Exception as se:
            print(f"⚠️ [스케줄러] 초기화 실패: {se}")

    print(f"🚀 [서버 가동] http://localhost:{port} 에서 MQnet 활성화")
    socketio.run(app, debug=DEBUG_MODE, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
