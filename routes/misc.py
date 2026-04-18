"""
routes/misc.py
잡다한 단일 라우트 모음 (영수증, 결제정보, 헬스체크, 법적 문서 등)

사용법:
    from routes.misc import misc_bp
    app.register_blueprint(misc_bp)
"""
from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, redirect, url_for, session
from sqlalchemy import text

from models import db, Order, Store, TaxInvoice
from extensions import socketio

misc_bp = Blueprint('misc', __name__)


# ─── 메인 인덱스 ───────────────────────────────────────────
@misc_bp.route('/')
def index():
    if not session.get('user_id'):
        return render_template('landing.html')
    return redirect(url_for('portal.home'))


# ─── 도움말 ────────────────────────────────────────────────
@misc_bp.route('/help')
def help_page():
    return render_template('help.html')


# ─── 법적 문서 ──────────────────────────────────────────────
@misc_bp.route('/privacy')
def privacy_page():
    return render_template('privacy.html')


@misc_bp.route('/terms')
def terms_page():
    return render_template('terms.html')


# ─── 헬스체크 ───────────────────────────────────────────────
@misc_bp.route('/ping')
def ping():
    """Keep-Alive & DB 상태 체크"""
    db_status = "ok"
    try:
        db.session.execute(text("SELECT 1"))
    except Exception as e:
        db_status = f"error: {str(e)[:80]}"
        print(f"🚨 [Health] DB 접속 오류: {e}")
    code = 200 if db_status == "ok" else 500
    return jsonify({'status': 'ok', 'db_status': db_status,
                    'timestamp': datetime.utcnow().isoformat()}), code


@misc_bp.route('/api/health')
def health_check_api(): # 이름을 유니크하게 변경
    """프론트엔드 모니터링용 상세 헬스체크"""
    health = {"server": "online", "db": "offline", "time": datetime.now().strftime('%H:%M:%S')}
    try:
        db.session.execute(text('SELECT 1'))
        health["db"] = "online"
    except Exception as e:
        health["db"] = f"error: {str(e)[:50]}"
    return jsonify(health)

@misc_bp.route('/health')
def health_check_simple():
    """Keep-alive 핑 대응을 위한 단순 헬스체크"""
    return "OK", 200


# ─── 계좌이체 안내 ──────────────────────────────────────────
@misc_bp.route('/<store_id>/payment_info')
def payment_info(store_id):
    store = db.session.get(Store, store_id)
    if not store:
        return "Store not found", 404
    return render_template(
        'bank_info.html', store=store,
        amount=request.args.get('amount', ''),
        memo=request.args.get('memo', ''),
        order_id=request.args.get('order_id', '')
    )


# ─── 디지털 영수증 ──────────────────────────────────────────
@misc_bp.route('/receipt/<order_id>')
def mobile_receipt(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        return "Order not found", 404
    store = db.session.get(Store, order.store_id)
    return render_template('receipt.html', order=order, store=store)


# ─── 현금영수증 신청 저장 ────────────────────────────────────
@misc_bp.route('/api/order/<order_id>/cash_receipt', methods=['POST'])
def save_cash_receipt(order_id):
    order = db.session.get(Order, order_id)
    if not order:
        return jsonify({'status': 'error', 'message': 'Order not found'}), 404
    data = request.json or {}
    order.cash_receipt_type   = data.get('type')
    order.cash_receipt_number = data.get('number')
    db.session.commit()
    return jsonify({'status': 'success'})


# ─── 입금 시뮬레이션 (테스트용) ─────────────────────────────
@misc_bp.route('/api/payment/mock', methods=['POST'])
def mock_payment_trigger():
    data   = request.json or {}
    sender = data.get('sender')
    amount = int(data.get('amount', 0))

    order = (Order.query
             .filter_by(depositor_name=sender, total_price=amount, status='pending')
             .order_by(Order.created_at.desc())
             .first())
    if not order:
        return jsonify({'status': 'error', 'message': 'Matching order not found'}), 404

    order.status  = 'paid'
    order.paid_at = datetime.utcnow()

    if order.payment_method in ['bank', 'cash', 'postpaid'] and order.cash_receipt_type:
        if not TaxInvoice.query.filter_by(order_id=order.id).first():
            db.session.add(TaxInvoice(
                order_id=order.id, store_id=order.store_id,
                amount=order.total_price, status='issued'
            ))
            print(f"🧾 [자동발급] {order.id} 현금영수증 발행 완료")

    db.session.commit()
    socketio.emit('order_update',
                  {'order_id': order.id, 'status': 'paid', 'payment_status': 'paid'},
                  room=order.store_id)
    return jsonify({'status': 'success', 'message': f'Order {order.id} marked as paid.'})


# ─── 데모 데이터 시딩 (개발용) ──────────────────────────────
@misc_bp.route('/api/internal/seed-demo')
def internal_seed_demo():
    import random
    from models import Customer

    store_id = 'wangpung'
    store = db.session.get(Store, store_id)
    if not store:
        return "Store not found", 404

    menus = []
    if store.menu_data:
        for cat, items in store.menu_data.items():
            menus.extend(items)
    if not menus:
        menus = [{"name": "짜장면", "price": 7000},
                 {"name": "짬뽕",  "price": 8000},
                 {"name": "탕수육", "price": 18000}]

    now    = datetime.utcnow()
    phones = [f"010-1234-567{i}" for i in range(10)]
    for phone in phones:
        if not Customer.query.filter_by(store_id=store_id, phone=phone).first():
            db.session.add(Customer(store_id=store_id, phone=phone))
    db.session.commit()

    all_customers = Customer.query.filter_by(store_id=store_id).all()
    from models import OrderItem
    for i in range(100):
        from datetime import timedelta
        order_time = now - timedelta(days=random.randint(0, 30),
                                     hours=random.randint(0, 23))
        order_id   = f"demo_{order_time.strftime('%Y%m%d%H%M')}_{i}"
        cust       = random.choice(all_customers)
        order      = Order(id=order_id, store_id=store_id,
                           table_id=random.randint(1, 10),
                           status='paid', created_at=order_time,
                           phone=cust.phone)
        total = 0
        for _ in range(random.randint(1, 4)):
            m   = random.choice(menus)
            qty = random.randint(1, 2)
            db.session.add(OrderItem(
                order_id=order_id, menu_id=0,
                name=m['name'], price=m['price'], quantity=qty
            ))
            total += m['price'] * qty
        order.total_price    = total
        cust.visit_count    += 1
        cust.total_spent    += total
        db.session.add(order)

    db.session.commit()
    return "Seed Success"
