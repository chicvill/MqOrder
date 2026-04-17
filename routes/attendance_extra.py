"""
routes/attendance_extra.py
근로계약서 디지털 서명 + 고객 빌링키 등록 추가 라우트.
app.py에서 attendance_bp 등록 후 이 모듈을 임포트합니다.
attendance_bp는 app.py에서 주입됩니다.
"""
from flask import request, jsonify, session, render_template
from datetime import datetime
from models import db, Store, User, Customer
from MQutils import login_required

# app.py에서 임포트 시 자동으로 주입됨
# 라우트 등록은 init_extra_routes(bp) 호출 방식으로 처리


def init_extra_routes(bp):
    """attendance_bp에 추가 라우트를 등록합니다."""

    # ─── 디지털 근로계약서 페이지 ───
    @bp.route('/admin/contract/<int:worker_id>')
    @login_required
    def admin_employment_contract(worker_id):
        if session.get('role') not in ['admin', 'owner']:
            return render_template('access_denied.html'), 403
        store_id = session.get('store_id')
        store  = db.session.get(Store, store_id)
        worker = db.session.get(User, worker_id)
        if not store or not worker or worker.store_id != store_id:
            return "잘못된 접근입니다.", 403
        now_date = datetime.now().strftime('%Y년 %m월 %d일')
        return render_template('admin/employment_contract.html',
                               store=store, worker=worker, now_date=now_date)

    # ─── 근로계약서 서명 저장 API ───
    @bp.route('/api/staff/<int:worker_id>/save-contract', methods=['POST'])
    @login_required
    def api_save_contract_signature(worker_id):
        if session.get('role') not in ['admin', 'owner']:
            return jsonify({'error': 'Forbidden'}), 403
        data       = request.json or {}
        sig_owner  = data.get('signature_owner')
        sig_worker = data.get('signature_worker')
        if not sig_owner or not sig_worker:
            return jsonify({'status': 'error', 'message': '서명이 누락되었습니다.'}), 400
        store_id = session.get('store_id')
        store  = db.session.get(Store, store_id)
        worker = db.session.get(User, worker_id)
        if not store or not worker:
            return jsonify({'error': 'Not found'}), 404
        store.signature_owner = sig_owner
        db.session.commit()
        print(f"✍️ [계약서] {store.name} ↔ {worker.full_name or worker.username} 서명 저장 완료")
        return jsonify({'status': 'success', 'message': '서명이 저장되었습니다.'})

    # ─── 고객 빌링키(카드) 등록 콜백 ───
    @bp.route('/api/<slug>/customer/billing-auth')
    def customer_billing_auth_callback(slug):
        import requests as req
        import base64 as _b64
        import os

        auth_key     = request.args.get('authKey')
        customer_key = request.args.get('customerKey')
        phone        = request.args.get('phone', '')

        if not auth_key or not customer_key:
            return "잘못된 요청입니다.", 400

        secret_key = os.getenv('TOSS_SECRET_KEY', '')
        auth_str   = _b64.b64encode(f"{secret_key}:".encode()).decode()
        headers    = {'Authorization': f'Basic {auth_str}', 'Content-Type': 'application/json'}

        try:
            resp = req.post(
                'https://api.tosspayments.com/v1/billing/authorizations/issue',
                json={'authKey': auth_key, 'customerKey': customer_key},
                headers=headers, timeout=10
            )
            if resp.status_code == 200:
                billing_key = resp.json().get('billingKey')
                customer = Customer.query.filter_by(store_id=slug, phone=phone).first()
                if customer:
                    customer.billing_key  = billing_key
                    customer.customer_key = customer_key
                    db.session.commit()
                    print(f"💳 [고객 빌링키] {phone} 카드 등록 완료 — {slug}")
                    return ("<script>"
                            "alert('카드가 등록되었습니다. 다음 방문부터 간편결제가 가능합니다.');"
                            "window.close();"
                            "</script>")
                return "고객 정보를 찾을 수 없습니다.", 404
            else:
                return f"카드 등록 실패: {resp.json().get('message')}", 400
        except Exception as e:
            return f"서버 오류: {e}", 500
