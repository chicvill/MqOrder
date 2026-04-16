import os
import sys
import json

# [강제 경로 보정] 로컬(Windows) 환경에서 .venv 내부 부품을 찾도록 설정
if sys.platform == 'win32':
    _venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
    if os.path.exists(_venv_path) and _venv_path not in sys.path:
        sys.path.insert(0, _venv_path)
import time
import socket
import random
import uuid
import csv
import io
import smtplib
import re
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from datetime import datetime, timedelta, timezone

# ---------------------------------------------------------
# 외부 유틸리티 모듈 임포트
# ---------------------------------------------------------
from MQutils.ai_engine import get_ai_recommended_menu, get_ai_operation_insight

from flask import Flask, render_template, request, jsonify, redirect, url_for, session, flash
from flask_socketio import SocketIO, emit
from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import func, desc, text, or_, and_
from werkzeug.middleware.proxy_fix import ProxyFix
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps
from dotenv import load_dotenv
from flask_apscheduler import APScheduler
import threading

# 환경변수 로드
load_dotenv()
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# ---------------------------------------------------------
# Flask 앱 및 환경 판별
# ---------------------------------------------------------
app = Flask(__name__, static_folder='static', static_url_path='/static')
is_render = 'RENDER' in os.environ
def start_cloudflare_tunnel():
    """Cloudflare 터널을 백그라운드에서 실행합니다. Render 환경에서는 http2를 강제합니다."""
    token = os.getenv("CLOUDFLARE_TUNNEL_TOKEN")
    if not token:
        print("⚠️ [Tunnel] CLOUDFLARE_TUNNEL_TOKEN이 없어 도메인 연결을 건너뜁니다.")
        return

    def run_tunnel():
        import subprocess
        import time
        # 1. OS별 실행 파일 결정
        if sys.platform == 'win32':
            cf_exe = os.path.join(BASE_DIR, "cloudflared.exe")
        else:
            cf_exe = "cloudflared"

        # 2. Render 환경(Linux)에서 QUIC 에러 방지를 위해 http2 프로토콜 강제
        protocol = "http2" if is_render else "quic"
        
        print(f"🔗 [Step 2/2] 도메인 터널(Cloudflare)을 연결 중입니다... (Protocol: {protocol})")
        # 인자 순서를 run --token 뒤로 배치하여 프로토콜 설정을 확실히 적용
        cmd = [cf_exe, "tunnel", "run", "--token", token, "--protocol", protocol]

        while True:
            try:
                subprocess.run(cmd, check=False)
                print(f"🔄 [Tunnel] 터널 재연결 시도 중... (Protocol: {protocol})")
                time.sleep(5)
            except Exception as e:
                print(f"❌ [Tunnel] 실행 오류: {e}")
                break

    # 중복 실행 방지
    if not os.environ.get('TUNNEL_RUNNING'):
        os.environ['TUNNEL_RUNNING'] = 'true'
        threading.Thread(target=run_tunnel, daemon=True).start()

# [실행] SaaS 서버 및 터널 초기화
print(f"🚀 [Step 1/2] SaaS 웹 서버를 가동합니다... (Port: {os.environ.get('PORT', 10000)})")
start_cloudflare_tunnel()

debug_mode = os.environ.get('FLASK_DEBUG') == '1' or (not is_render and sys.platform == 'win32')
app.config['DEBUG'] = debug_mode

app.jinja_env.add_extension('jinja2.ext.do')  # {% do %} 태그 활성화
scheduler = APScheduler()
scheduler.init_app(app) # 스케줄러와 앱 연결
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1) 
app.config['SECRET_KEY'] = 'suragol-secret-key-2026'

# [세션 쿠키 설정 극강화]
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=7)

# [멀티 도메인 세션 공유]
if os.getenv("DOMAIN_MODE") == "1":
    _cookie_domain = os.getenv('SESSION_COOKIE_DOMAIN', '.chicvill.store')
    app.config['SESSION_COOKIE_DOMAIN'] = _cookie_domain
    app.config['SESSION_COOKIE_SECURE'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'None'
    print(f"🌐 [도메인 모드] 세션 쿠키 도메인: {_cookie_domain}")
else:
    app.config['SESSION_COOKIE_SECURE'] = False
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.url_map.strict_slashes = False # URL 끝 슬래시(/) 유무에 상관없이 접속 허용
app.config['UPLOAD_FOLDER'] = os.path.join(BASE_DIR, 'static', 'images')
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# [DB 설정] 환경변수에 DATABASE_URL이 있으면 우선 사용 (Supabase 등), 없으면 로컬 SQLite 사용
db_url = os.environ.get('DATABASE_URL')

# ---------------------------------------------------------
# DB 연결 설정 및 패치
# ---------------------------------------------------------
if db_url:
    # [호스트 보정] 프로젝트별 고유 호스트명 사용 권장
    # (wdikgmyhuxhhyeljnyqa.supabase.co 형태로 자동 전환 시도 가능하나 일단 전달받은 URL 유지)
    
    if "postgresql://" in db_url or "postgres://" in db_url:
        try:
            # 1순위: psycopg2 시도
            import psycopg2
            if "postgresql+pg8000://" in db_url:
                db_url = db_url.replace("postgresql+pg8000://", "postgresql://", 1)
            print("🐘 [DB 엔진] psycopg2 엔진을 사용합니다.")
        except ImportError:
            # 2순위: pg8000 전환 (psycopg2 없는 환경용)
            if "postgresql+pg8000://" not in db_url:
                db_url = db_url.replace("postgresql://", "postgresql+pg8000://", 1)
                db_url = db_url.replace("postgres://", "postgresql+pg8000://", 1)
            
            # [강제 보정] pg8000 드라이버 환경에서 포트(6543) 이슈 방지
            if ":6543" in db_url:
                db_url = db_url.replace(":6543", ":5432")
            
            print("🐘 [DB 엔진] 환경 변수에 설정된 주소로 pg8000을 통해 연결합니다.")

    # 연결 문자열 로깅 (보안 마스킹)
    try:
        from sqlalchemy.engine.url import make_url
        url_obj = make_url(db_url)
        safe_url = f"{url_obj.drivername}://{url_obj.username}:****@{url_obj.host}:{url_obj.port}/{url_obj.database}"
        print(f"🔗 [DB 접속 시도] {safe_url}")
    except Exception:
        print("🔗 [DB 접속 시도] URL 형식을 확인 중입니다...")

app.config['SQLALCHEMY_DATABASE_URI'] = db_url
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    "pool_pre_ping": True,
    "pool_recycle": 600,  # 연결 회전 주기를 더 짧게 설정
    "pool_size": 10,
    "max_overflow": 20,
    "connect_args": {
        "timeout": 60,  # 타임아웃을 60초로 더 연장
        "ssl_context": True  # [핵심] SSL 보안 연결 강제 활성화
    }
}
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# [클라우드 최적화] 전역 DB 엔진 옵션 주입 (철벽 생존 모드 - NullPool)
from sqlalchemy.pool import NullPool
app.config['SQLALCHEMY_ENGINE_OPTIONS'] = {
    'poolclass': NullPool,
    'pool_pre_ping': True
}
# 불필요한 기본 풀 설정이 주입되지 않도록 강제 방어
app.config['SQLALCHEMY_POOL_SIZE'] = None
app.config['SQLALCHEMY_POOL_TIMEOUT'] = None
app.config['SQLALCHEMY_POOL_RECYCLE'] = None
app.config['SQLALCHEMY_MAX_OVERFLOW'] = None

from models import db, Order, OrderItem, Waiting, Store, User, SystemConfig, TaxInvoice, ServiceRequest, Customer, PointTransaction, Attendance, Subscription

# SQLALchemy 인스턴스 초기화 (모델의 db 사용)
db.init_app(app)

# [진짜 최종 마이그레이션] PostgreSQL 호환성 및 부족한 컬럼 자동 생성
with app.app_context():
    # 로컬에서 Supabase 접속 시 락(Lock) 충돌 방지를 위해 마이그레이션 건너뛰기 옵션 추가
    if os.environ.get('LOCAL_SKIP_MIGRATION') == 'true':
        print("⏭️ [DB] 마이그레이션을 건너뛰고 바로 연결합니다. (로컬 모드)")
    else:
        # [클라우드 배포] 부팅 속도를 위해 최소한의 테이블 확인만 수행합니다.
        print("🔍 [DB 준비] 데이터베이스 연결을 시도합니다...")
        try:
            db.create_all()
            print("✅ [DB] 연결 완료.")
        except Exception as e:
            print(f"⚠️ [DB 지연] 연결 대기 중... (첫 접속 시 재시도됨): {e}")


# --- 라우트 및 소켓 초기 설정 ---
from extensions import socketio
socketio.init_app(app)

from sockets import register_socketio_events
register_socketio_events(socketio)

from routes.attendance import attendance_bp
app.register_blueprint(attendance_bp)

from routes.portal import portal_bp
app.register_blueprint(portal_bp)

from routes.auth import init_auth_routes
init_auth_routes(app)

from routes.admin import init_admin_routes
init_admin_routes(app)

from routes.store import init_store_routes
init_store_routes(app)

from routes.knowledge import knowledge_bp
app.register_blueprint(knowledge_bp)

from routes.billing import billing_bp
app.register_blueprint(billing_bp)

from MQutils import (
    login_required, admin_required, staff_required, manager_required, owner_only_required,
    store_access_required, send_waiting_sms, check_nearby_waiting,
    format_phone, calculate_commission, get_staff_performance, send_daily_backup
)

# ─────────────────────────────────────────────────────────────
# [SaaS] 구독 만기 체크 미들웨어
# 점주(owner) 로그인 상태에서 매장 만료 감지 → /billing/expired 리다이렉트
# ─────────────────────────────────────────────────────────────
EXPIRY_BYPASS_PREFIXES = (
    '/billing', '/login', '/logout', '/register', '/static',
    '/api/billing', '/api/health', '/ping', '/privacy', '/terms', '/'
)

@app.before_request
def check_subscription_expiry():
    # 바이패스 경로는 체크 생략
    path = request.path
    if any(path.startswith(p) for p in EXPIRY_BYPASS_PREFIXES):
        return

    role = session.get('role')
    store_id = session.get('store_id')

    # 점주만 체크 (admin / staff 는 면제)
    if role != 'owner' or not store_id:
        return

    try:
        store = db.session.get(Store, store_id)
        if store and store.expires_at:
            if datetime.utcnow() > store.expires_at:
                # 이미 /billing/expired 를 향하는 중이면 루프 방지
                if not path.startswith('/billing'):
                    return redirect('/billing/expired')
    except Exception as e:
        print(f'⚠️ [만기 체크 오류] {e}')

@app.context_processor
def inject_globals():
    return {
        'timedelta': timedelta,
        'now': datetime.now(),
        'config': {
            'TOSS_CLIENT_KEY': os.getenv('TOSS_CLIENT_KEY', 'test_ck_placeholder'),
            'SERVICE_DOMAIN': os.getenv('SERVICE_DOMAIN', 'localhost:10000'),
        }
    }

app.jinja_env.filters['format_phone'] = format_phone

# --- [Temporary Seed Route] ---
@app.route('/api/internal/seed-demo')
def internal_seed_demo():
    import random
    from datetime import datetime, timedelta
    from models import Store, Order, OrderItem, Customer
    
    store_id = 'wangpung'
    store = db.session.get(Store, store_id)
    if not store:
        return "Store not found", 404
        
    menus = []
    if store.menu_data:
        for cat, items in store.menu_data.items():
            for item in items:
                menus.append(item)
    
    if not menus:
        menus = [{"name": "짜장면", "price": 7000}, {"name": "짬뽕", "price": 8000}, {"name": "탕수육", "price": 18000}]

    now = datetime.utcnow()
    phones = [f"010-1234-567{i}" for i in range(10)]
    for phone in phones:
        if not Customer.query.filter_by(store_id=store_id, phone=phone).first():
            db.session.add(Customer(store_id=store_id, phone=phone))
    db.session.commit()
    
    all_customers = Customer.query.filter_by(store_id=store_id).all()

    for i in range(100):
        days_ago = random.randint(0, 30)
        order_time = now - timedelta(days=days_ago, hours=random.randint(0, 23))
        order_id = f"demo_{order_time.strftime('%Y%m%d%H%M')}_{i}"
        
        cust = random.choice(all_customers)
        order = Order(id=order_id, store_id=store_id, table_id=random.randint(1, 10), status='paid', created_at=order_time, phone=cust.phone)
        
        total = 0
        for _ in range(random.randint(1, 4)):
            m = random.choice(menus)
            qty = random.randint(1, 2)
            db.session.add(OrderItem(order_id=order_id, menu_id=0, name=m['name'], price=m['price'], quantity=qty))
            total += m['price'] * qty
        
        order.total_price = total
        cust.visit_count += 1
        cust.total_spent += total
        db.session.add(order)
        
    db.session.commit()
    return "Seed Success"

# MQnet Central Index
@app.route('/')
def index():
    user_id = session.get('user_id')
    
    # 1. 로그인 정보가 없으면 홍보용 랜딩 페이지(Landing Page)를 보여줍니다.
    if not user_id:
        return render_template('landing.html')
    
    # 2. 로그인 상태라면 통합 포털 허브로 이동합니다.
    return redirect(url_for('portal.home'))


# 시스템 도움말 페이지
@app.route('/help')
def help_page():
    return render_template('help.html')


    # [알림] 실제 결제 승인 로직은 routes/billing.py 의 toss_success_page 에서 통합 관리합니다.
    return redirect(url_for('billing.toss_success_page', **request.args))

# --- 계좌이체 안내 페이지 ---
@app.route('/<store_id>/payment_info')
def payment_info(store_id):
    store = db.session.get(Store, store_id)
    if not store:
        return "Store not found", 404
    amount   = request.args.get('amount', '')
    memo     = request.args.get('memo', '')
    order_id = request.args.get('order_id', '')
    return render_template('bank_info.html', store=store, amount=amount, memo=memo, order_id=order_id)


# [커스텀 필터] 화폐 포맷 (10,000원 형식)
@app.template_filter('format_currency')
def format_currency_filter(value):
    if value is None: return "0원"
    return "{:,}원".format(value)

# [신규] 디지털 영수증 페이지
@app.route('/receipt/<order_id>')
def mobile_receipt(order_id):
    order = db.session.get(Order, order_id)
    if not order: return "Order not found", 404
    store = db.session.get(Store, order.store_id)
    return render_template('receipt.html', order=order, store=store)

# [API] 현금영수증 신청 정보 저장
@app.route('/api/order/<order_id>/cash_receipt', methods=['POST'])
def save_cash_receipt(order_id):
    order = db.session.get(Order, order_id)
    if not order: return jsonify({'status': 'error', 'message': 'Order not found'}), 404
    data = request.json
    order.cash_receipt_type = data.get('type')
    order.cash_receipt_number = data.get('number')
    db.session.commit()
    return jsonify({'status': 'success'})

# [테스트용] 입금 신호 시뮬레이션 API
@app.route('/api/payment/mock', methods=['POST'])
def mock_payment_trigger():
    data = request.json
    sender = data.get('sender')
    amount = int(data.get('amount', 0))
    
    # 입금 대기 중인 주문 중 이름과 금액이 일치하는 가장 최근 주문 검색
    order = Order.query.filter_by(depositor_name=sender, total_price=amount, status='pending').order_by(Order.created_at.desc()).first()
    
    if order:
        order.status = 'paid'
        order.paid_at = datetime.utcnow()
        
        # [신규] 무통장/현금 결제 시 영수증 신청 내역이 있으면 자동 발급 처리
        if order.payment_method in ['bank', 'cash', 'postpaid'] and order.cash_receipt_type:
            # 이미 발급된 영수증이 있는지 확인 (중복 발급 방지)
            existing = TaxInvoice.query.filter_by(order_id=order.id).first()
            if not existing:
                ti = TaxInvoice(order_id=order.id, store_id=order.store_id, amount=order.total_price, status='issued')
                db.session.add(ti)
                print(f"🧾 [자동발급] 시뮬레이션 주문 {order.id} 현금영수증 발행 완료")
        
        db.session.commit()
        
        # 실시간 상태 업데이트 전송
        socketio.emit('order_update', {
            'order_id': order.id,
            'status': 'paid',
            'payment_status': 'paid'
        }, room=order.store_id)
        
        return jsonify({'status': 'success', 'message': f'Order {order.id} marked as paid.'})
    return jsonify({'status': 'error', 'message': 'Matching order not found'}), 404

@app.errorhandler(403)
def forbidden(e):
    return render_template('access_denied.html'), 403

# ---------------------------------------------------------
# [Keep-Alive] Render 슬립 방지 핑 (10분마다 자기 자신에게 요청)
# ---------------------------------------------------------
def keep_alive_ping():
    """Render 무료 플랜 서버가 잠들지 않도록 주기적으로 자기 자신에게 핑을 보냅니다.
    단순 핑이 아닌 DB 조회를 함께 수행하여 연결 상태를 확실히 점검합니다."""
    import urllib.request
    render_url = os.environ.get('RENDER_EXTERNAL_URL')
    
    # 1. DB 상태 점검 (가장 확실한 방법)
    db_ok = False
    try:
        with app.app_context():
            db.session.execute(text("SELECT 1"))
            db_ok = True
            print("🟢 [Health] 데이터베이스 연결 확인됨")
    except Exception as e:
        print(f"🚨 [오류 경보] DB 연결 실패: {str(e)}")
        # 향후 여기에 이메일 발송 또는 관리자 알림 로직 추가 가능
    # Render 프리티어 등에서 서버가 잠들지 않도록 주기적으로 자기 자신 호출
    # [보정] 외부 도메인 대신 내부 로컬 주소(127.0.0.1)를 호출하여 DNS 오류 방지
    try:
        from urllib.request import urlopen
        urlopen("http://127.0.0.1:10000/health", timeout=10)
        print("🕒 [Keep-Alive] 핑 성공 (내부 주소)")
    except Exception as e:
        # 실패하더라도 서비스엔 지장 없음
        print(f"⚠️ [Keep-Alive] 핑 실패: {e}")

@app.route('/ping')
def ping():
    """Keep-Alive 및 DB 점검 헬스 체크 엔드포인트"""
    db_status = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)}"
        print(f"🚨 [Health Check] DB 접속 오류: {e}")
        
    return jsonify({
        'status': 'ok', 
        'db_status': db_status,
        'timestamp': datetime.utcnow().isoformat()
    }), 200 if db_status == "ok" else 500

# [안정성 보강] 스케줄러 작업 설정은 메인 블록 내부에서 수행합니다.

# [최종] 라우트 추가 - 구글 플레이 필수 문서
@app.route('/privacy')
def privacy_page():
    return render_template('privacy.html')

@app.route('/terms')
def terms_page():
    return render_template('terms.html')

# [신규] 시스템 상태 체크 API (프론트엔드 모니터링용)
@app.route('/api/health')
def health_check():
    health = {"server": "online", "db": "offline", "time": datetime.now().strftime('%H:%M:%S')}
    try:
        # DB에 아주 가벼운 쿼리를 날려 연결 확인
        db.session.execute(text('SELECT 1'))
        health["db"] = "online"
    except Exception as e:
        health["db"] = f"error: {str(e)[:50]}"
    return jsonify(health)

if __name__ == '__main__':
    # Render는 PORT 환경변수를 사용합니다.
    port = int(os.environ.get('PORT', 10000))
    print(f"🔥 [서버 구동] 포트 {port}번에서 MQnet Central 기동...")
    
    # [지연 부팅] DB 풀러 안정화를 위해 3초 대기 후 접속 시도
    import time
    time.sleep(3)
    
    with app.app_context():
        try:
            db.create_all()
            
            # [자동 생성] 초기 관리자 계정이 없는 경우 생성 (테스트용)
            if not User.query.filter_by(username='admin').first():
                from werkzeug.security import generate_password_hash
                admin_user = User(
                    username='admin', 
                    password=generate_password_hash('1212'), 
                    role='admin', 
                    is_approved=True,
                    full_name='최고관리자'
                )
                db.session.add(admin_user)
                
            # [자동 생성] 시스템 기본 설정 및 본사 계좌 정보
            config = SystemConfig.query.first()
            if not config:
                config = SystemConfig(
                    site_name='MQnet Central',
                    hq_bank='농협은행',
                    hq_account='302-0000-0000-00',
                    hq_holder='(주)MQ네트웍스'
                )
                db.session.add(config)
            
            # [컬럼 보정] 직접 엔진 연결을 사용하여 DDL(ALTER) 실행 (더 확실한 방식)
            try:
                with db.engine.connect() as conn:
                    # Orders 테이블 보정
                    conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS payment_method VARCHAR(20)"))
                    conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS order_no VARCHAR(10)"))
                    conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS depositor_name VARCHAR(100)"))
                    conn.execute(text("ALTER TABLE orders ADD COLUMN IF NOT EXISTS is_prepaid BOOLEAN DEFAULT FALSE"))
                    
                    # Users 테이블 보정 (급여/계좌 정보)
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS bank_name VARCHAR(50)"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS account_no VARCHAR(50)"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hourly_rate INTEGER DEFAULT 10000"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS position VARCHAR(50)"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS work_schedule JSON"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS contract_start DATE"))
                    conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS contract_end DATE"))

                    # Stores 테이블 보정 (SaaS/보안 설정)
                    conn.execute(text("ALTER TABLE stores ADD COLUMN IF NOT EXISTS disable_auto_logout BOOLEAN DEFAULT FALSE"))
                    conn.execute(text("ALTER TABLE stores ADD COLUMN IF NOT EXISTS billing_key VARCHAR(100)"))
                    
                    conn.commit()
                print("🛠️ [DB 보정] 모든 테이블 컬럼이 성공적으로 최신화되었습니다.")
            except Exception as e:
                print(f"⚠️ [DB 보정 안내] 이미 컬럼이 존재하거나 권한 이슈로 스킵됨: {e}")

            print("👤 [계정/설정] 초기 데이터 준비 완료")
            print("✅ [DB 준비 완료]")

            # [스케줄러] 백그라운드 작업 시작
            try:
                if not scheduler.running:
                    # 백업 작업 등록 (매주 월요일 0시)
                    from MQutils.backup import send_daily_backup
                    models_to_backup = [('운영자 및 유저', User), ('가맹점 정보', Store), ('주문 내역', Order)]
                    scheduler.add_job(id='weekly_backup_job', func=send_daily_backup, args=(app, db, models_to_backup), trigger='cron', day_of_week='mon', hour=0, minute=0)
                    
                    # 접속 상태 유지 핑 (10분 주기)
                    scheduler.add_job(id='keep_alive_job', func=keep_alive_ping, trigger='interval', minutes=10)
                    
                    # [SaaS] 정기 결제 자동 수금 (새벽 2시)
                    from routes.billing import auto_collect_subscriptions
                    scheduler.add_job(id='auto_billing_job', func=auto_collect_subscriptions, args=(app,), trigger='cron', hour=2, minute=0)
                    
                    scheduler.start()
                    print("⏰ [스케줄러] 정기 백업 및 자동 결제 엔진 활성화")
            except Exception as se:
                print(f"⚠️ [스케줄러 경고] 이미 실행 중이거나 초기화 실패: {se}")

        except Exception as e:
            print(f"⚠️ [DB 경고] {e}")

    # [실행] 서버 기동
    print(f"🚀 [서버 가동] http://localhost:{port} 에서 MQnet 시스템이 활성화되었습니다.")
    socketio.run(app, debug=debug_mode, host='0.0.0.0', port=port, allow_unsafe_werkzeug=True)
