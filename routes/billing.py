# routes/billing.py
# 구독 결제 및 만기 관리 라우트

from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from datetime import datetime, timedelta
from functools import wraps
from models import db, User, Store, Subscription, TaxInvoice
import os, base64, requests, time
from MQutils.messenger import SolapiMessenger

billing_bp = Blueprint('billing', __name__)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        return f(*args, **kwargs)
    return decorated

# ─── 구독 현황 / 결제 안내 페이지 ───
@billing_bp.route('/billing')
@login_required
def billing_home():
    user = db.session.get(User, session['user_id'])
    if not user or not user.store_id:
        flash('연결된 매장이 없습니다.', 'error')
        return redirect(url_for('portal.home'))

    store = db.session.get(Store, user.store_id)
    if not store:
        flash('매장 정보를 찾을 수 없습니다.', 'error')
        return redirect(url_for('portal.home'))

    # 구독 이력 (최신 순 5건)
    history = Subscription.query.filter_by(store_id=store.id)\
                .order_by(Subscription.created_at.desc()).limit(5).all()

    # 만기까지 남은 일수
    now = datetime.utcnow()
    days_left = None
    is_expired = False
    is_trial = store.payment_status == 'trial'

    if store.expires_at:
        delta = store.expires_at - now
        days_left = max(0, delta.days)
        is_expired = delta.total_seconds() <= 0

    return render_template('billing.html',
        user=user, store=store, history=history,
        days_left=days_left, is_expired=is_expired, is_trial=is_trial,
        now=now
    )

# ─── 구독 만료 안내 전용 페이지 ───
@billing_bp.route('/billing/expired')
@login_required
def billing_expired():
    user = db.session.get(User, session['user_id'])
    store = db.session.get(Store, user.store_id) if user and user.store_id else None
    return render_template('billing.html',
        user=user, store=store, days_left=0,
        is_expired=True, is_trial=False, history=[], now=datetime.utcnow()
    )

# ─── 토스 페이먼츠 결제 성공 콜백 API ───
@billing_bp.route('/api/billing/toss-success', methods=['POST'])
@login_required
def toss_payment_success():
    """토스 페이먼츠 결제 완료 후 웹훅/콜백으로 호출되는 API"""
    data = request.json or {}
    order_id   = data.get('orderId')
    payment_key = data.get('paymentKey')
    amount     = int(data.get('amount', 50000))

    user = db.session.get(User, session['user_id'])
    if not user or not user.store_id:
        return jsonify({'status': 'error', 'message': 'No store linked'}), 400

    store = db.session.get(Store, user.store_id)
    if not store:
        return jsonify({'status': 'error', 'message': 'Store not found'}), 404

    now = datetime.utcnow()
    # 현재 만기일이 미래면 그 시점부터, 이미 만료됐으면 지금부터 30일 연장
    base = store.expires_at if (store.expires_at and store.expires_at > now) else now
    new_expires = base + timedelta(days=30)

    # Store 업데이트
    store.expires_at = new_expires
    store.payment_status = 'paid'
    store.status = 'active'

    # Subscription 이력 추가
    sub = Subscription(
        store_id=store.id,
        plan='standard',
        amount=amount,
        method='card',
        status='active',
        period_start=base,
        period_end=new_expires,
        paid_at=now
    )
    db.session.add(sub)
    db.session.commit()

    print(f"✅ [결제완료] {store.name} → 만기: {new_expires.strftime('%Y-%m-%d')}")

    # [신규] 매장주에게 이메일 영수증/안내 발송
    if store.business_email:
        try:
            messenger = SolapiMessenger()
            subject = f"[{store.name}] MQnet 서비스 이용료 결제가 완료되었습니다."
            body = f"""
            <div style="font-family:sans-serif; max-width:600px; border:1px solid #eee; padding:30px; border-radius:15px;">
                <h2 style="color:#2563eb;">MQnet 결제 완료 안내</h2>
                <p>안녕하세요, <b>{store.ceo_name or store.name}</b> 대표님.</p>
                <p>MQnet 서비스 구독 결제가 성공적으로 처리되었습니다.</p>
                <hr style="border:none; border-top:1px solid #eee; margin:20px 0;">
                <table style="width:100%; border-collapse:collapse;">
                    <tr><td style="color:#666; padding:8px 0;">결제 매장</td><td style="font-weight:bold;">{store.name}</td></tr>
                    <tr><td style="color:#666; padding:8px 0;">결제 금액</td><td style="font-weight:bold;">{amount:,}원 (카드결제)</td></tr>
                    <tr><td style="color:#666; padding:8px 0;">구독 기간</td><td style="font-weight:bold;">{base.strftime('%Y-%m-%d')} ~ {new_expires.strftime('%Y-%m-%d')}</td></tr>
                </table>
                <hr style="border:none; border-top:1px solid #eee; margin:20px 0;">
                <p style="font-size:0.9rem; color:#666;">본 메일은 시스템에 의해 자동 발송되었습니다. 관련 문의는 MQnet 파트너 센터로 연락 바랍니다.</p>
            </div>
            """
            messenger.send_email(store.business_email, subject, body)
        except Exception as e:
            print(f"⚠️ [Email Notification Skip] {e}")

    return jsonify({
        'status': 'success',
        'new_expires': new_expires.isoformat() + 'Z',
        'message': f'구독이 {new_expires.strftime("%Y년 %m월 %d일")}까지 연장되었습니다.'
    })

# ─── 토스 페이먼츠 결제 성공 (GET) ───
@billing_bp.route('/billing/success')
@login_required
def toss_success_page():
    """결제 성공 후 리다이렉트되어 들어오는 페이지. Toss API로 최종 승인 처리."""
    payment_key = request.args.get('paymentKey')
    order_id = request.args.get('orderId')
    amount = request.args.get('amount')

    if not all([payment_key, order_id, amount]):
        flash("결제 정보가 누락되었습니다.", "error")
        return redirect(url_for('billing.billing_home'))

    # [핵심] 토스 결제 승인 API 호출 (Secret Key 인증 필요)
    secret_key = os.getenv('TOSS_SECRET_KEY', 'test_sk_placeholder')
    # SecretKey: 뒤에 :을 붙이고 base64 인코딩
    auth_str = base64.b64encode(f"{secret_key}:".encode('utf-8')).decode('utf-8')
    
    headers = {
        'Authorization': f'Basic {auth_str}',
        'Content-Type': 'application/json'
    }
    
    payload = {
        'paymentKey': payment_key,
        'orderId': order_id,
        'amount': amount
    }

    try:
        resp = requests.post('https://api.tosspayments.com/v1/payments/confirm', json=payload, headers=headers)
        res_data = resp.json()

        if resp.status_code == 200:
            # 승인 성공: DB 업데이트 (기존 로직 활용 또는 통합)
            update_subscription_success(order_id, amount)
            flash("구독 결제가 성공적으로 완료되었습니다!", "success")
        else:
            # 승인 실패
            error_msg = res_data.get('message', '결제 승인 중 오류가 발생했습니다.')
            flash(f"결제 실패: {error_msg}", "error")
            
    except Exception as e:
        print(f"❌ [Toss Confirm Error] {e}")
        flash("결제 연동 중 서버 오류가 발생했습니다.", "error")

    return redirect(url_for('billing.billing_home'))

def update_subscription_success(order_id, amount):
    """결제 완료 후 DB 상태를 업데이트하는 내부 함수"""
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    if not user or not user.store_id: return False

    store = db.session.get(Store, user.store_id)
    if not store: return False

    now = datetime.utcnow()
    base = store.expires_at if (store.expires_at and store.expires_at > now) else now
    new_expires = base + timedelta(days=30)

    store.expires_at = new_expires
    store.payment_status = 'paid'
    store.status = 'active'

    sub = Subscription(
        store_id=store.id,
        plan='standard',
        amount=int(amount),
        method='card',
        status='active',
        period_start=base,
        period_end=new_expires,
        paid_at=now
    )
    db.session.add(sub)
    db.session.commit()
    
    # [알림톡/이메일 발송]
    if store.business_email:
        try:
            messenger = SolapiMessenger()
            subject = f"[{store.name}] MQnet 구독 결제 완료 안내"
            body = f"안녕하세요. {store.name}의 {amount}원 결제가 {new_expires.strftime('%Y-%m-%d')}까지 연장되었습니다."
            messenger.send_email(store.business_email, subject, body)
        except: pass
    
    return True

# ─── 정기 결제 빌링키 발급 성공 ───
@billing_bp.route('/billing/auth-success')
@login_required
def toss_billing_auth_success():
    """정기 결제 수단 등록 성공 시 호출되는 콜백"""
    auth_key = request.args.get('authKey')
    customer_key = request.args.get('customerKey')

    # 1. 빌링키 발급 요청
    secret_key = os.getenv('TOSS_SECRET_KEY', 'test_sk_placeholder')
    auth_str = base64.b64encode(f"{secret_key}:".encode('utf-8')).decode('utf-8')
    headers = {'Authorization': f'Basic {auth_str}', 'Content-Type': 'application/json'}
    
    payload = {'authKey': auth_key, 'customerKey': customer_key}
    
    try:
        resp = requests.post('https://api.tosspayments.com/v1/billing/authorizations/issue', json=payload, headers=headers)
        res_data = resp.json()
        
        if resp.status_code == 200:
            billing_key = res_data.get('billingKey')
            # 2. Store에 빌링키 저장
            user = db.session.get(User, session['user_id'])
            store = db.session.get(Store, user.store_id)
            store.billing_key = billing_key
            db.session.commit()
            flash("정기 결제 수단이 안전하게 등록되었습니다.", "success")
        else:
            flash(f"등록 실패: {res_data.get('message')}", "error")
    except:
        flash("서버 통신 중 오류가 발생했습니다.", "error")

    return redirect(url_for('billing.billing_home'))

# ─── [스케줄러 작업] 자동 결제 실행 ───
def auto_collect_subscriptions(app):
    """
    매일 새벽 정기 결제 대상 매장을 찾아 자동 결제 요청을 보냅니다.
    """
    with app.app_context():
        now = datetime.utcnow()
        # 내일 만료되는 매장 중 빌링키가 있는 매장 조회
        target_limit = now + timedelta(days=1)
        stores = Store.query.filter(
            Store.billing_key.isnot(None), 
            Store.expires_at <= target_limit,
            Store.status == 'active'
        ).all()

        print(f"🕒 [Auto-Billing] {len(stores)}개 매장 정기 결제 검토 중...")
        
        secret_key = os.getenv('TOSS_SECRET_KEY', 'test_sk_placeholder')
        auth_str = base64.b64encode(f"{secret_key}:".encode('utf-8')).decode('utf-8')
        headers = {'Authorization': f'Basic {auth_str}', 'Content-Type': 'application/json'}

        for s in stores:
            try:
                # 결제 요청
                payload = {
                    'amount': s.monthly_fee or 50000,
                    'orderId': f"auto_{s.id}_{int(time.time())}",
                    'orderName': f"MQnet 정기 구독 — {s.name}",
                    'customerKey': f"cust_{s.id}"
                }
                resp = requests.post(f'https://api.tosspayments.com/v1/billing/{s.billing_key}', json=payload, headers=headers)
                
                if resp.status_code == 200:
                    # 결제 성공 시 만기 연장
                    base = s.expires_at if s.expires_at > now else now
                    new_expires = base + timedelta(days=30)
                    s.expires_at = new_expires
                    
                    db.session.add(Subscription(
                        store_id=s.id, plan='standard', amount=payload['amount'],
                        method='auto_card', status='active',
                        period_start=base, period_end=new_expires, paid_at=now
                    ))
                    print(f"✅ [Auto-Billing Success] {s.name} 결제 완료")
                else:
                    # 결제 실패 시 관리자 알림 (checklist 반영)
                    print(f"❌ [Auto-Billing Fail] {s.name}: {resp.json().get('message')}")
                    # 여기서 관리자에게 알림톡/메일을 보내는 로직을 추가할 수 있습니다.
                    
            except Exception as e:
                print(f"⚠️ [Auto-Billing Error] {s.name}: {e}")
        
        db.session.commit()

        # ─── [2단계] Trial 만료 자동 정지 ───
        # 빌링키 없이 무료 체험 기간이 지난 매장을 찾아서 정지 처리
        expired_trials = Store.query.filter(
            Store.billing_key.is_(None),
            Store.payment_status == 'trial',
            Store.expires_at <= now,
            Store.status == 'active'
        ).all()

        print(f"⏰ [Trial-Expiry] {len(expired_trials)}개 무료 체험 만료 매장 정지 처리 중...")

        for s in expired_trials:
            s.status = 'suspended'
            s.payment_status = 'expired'
            print(f"🔒 [Trial-Expired] {s.name} 매장 정지 처리 완료")

            # 점주에게 이메일 안내 발송
            if s.business_email:
                try:
                    messenger = SolapiMessenger()
                    subject = f"[MQnet] {s.name} 무료 체험 종료 안내"
                    body = f"""
                    <div style="font-family:sans-serif; max-width:600px; border:1px solid #eee; padding:30px; border-radius:15px;">
                        <h2 style="color:#dc2626;">MQnet 무료 체험 종료 안내</h2>
                        <p>안녕하세요, <b>{s.ceo_name or s.name}</b> 대표님.</p>
                        <p>30일 무료 체험 기간이 만료되어 서비스가 일시 정지되었습니다.</p>
                        <p>서비스를 계속 이용하시려면 <a href="https://mq.chicvill.store/billing" style="color:#2563eb; font-weight:bold;">구독 결제 페이지</a>에서 월 5만원 구독을 시작해 주세요.</p>
                        <hr style="border:none;border-top:1px solid #eee;margin:20px 0;">
                        <p style="font-size:0.85rem;color:#888;">결제 후 즉시 서비스가 재활성화됩니다.</p>
                    </div>
                    """
                    messenger.send_email(s.business_email, subject, body)
                except Exception as e:
                    print(f"⚠️ [Trial-Expiry Email Error] {s.name}: {e}")

        db.session.commit()



@billing_bp.route('/api/billing/toss-fail', methods=['POST', 'GET'])
def toss_payment_fail():
    """결제 실패 시 처리"""
    code = request.args.get('code')
    message = request.args.get('message')
    print(f"❌ [결제실패] {code}: {message}")
    flash(f"결제에 실패했습니다: {message}", "error")
    return redirect(url_for('billing.billing_home'))

# ─── 수동 무료 연장 (관리자 전용) ───
@billing_bp.route('/api/billing/extend/<store_id>', methods=['POST'])
def admin_extend(store_id):
    if session.get('role') != 'admin':
        return jsonify({'status': 'error', 'message': '권한이 없습니다.'}), 403

    store = db.session.get(Store, store_id)
    if not store:
        return jsonify({'status': 'error', 'message': 'Store not found'}), 404

    days = int(request.json.get('days', 30))
    now  = datetime.utcnow()
    base = store.expires_at if (store.expires_at and store.expires_at > now) else now
    store.expires_at = base + timedelta(days=days)
    store.payment_status = 'paid'
    store.status = 'active'

    db.session.add(Subscription(
        store_id=store.id,
        plan='standard',
        amount=0,
        method='admin_extend',
        status='active',
        period_start=base,
        period_end=store.expires_at,
        paid_at=now
    ))
    db.session.commit()
    return jsonify({'status': 'success', 'new_expires': store.expires_at.isoformat() + 'Z'})
