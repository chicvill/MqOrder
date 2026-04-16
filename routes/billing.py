# routes/billing.py
# 구독 결제 및 만기 관리 라우트

from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from datetime import datetime, timedelta
from functools import wraps
from models import db, User, Store, Subscription, TaxInvoice
import os
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
