from flask import Blueprint, render_template, session, redirect, url_for, jsonify
from models import db, User, Store, Subscription
from sqlalchemy import or_
from functools import wraps
from datetime import datetime, timedelta

portal_bp = Blueprint('portal', __name__)

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login'))
        user = db.session.get(User, session['user_id'])
        if not user or user.role != 'admin':
            return "권한이 없습니다.", 403
        return f(*args, **kwargs)
    return decorated_function

# ─── 포털 홈 ───
@portal_bp.route('/portal/home')
@login_required
def home():
    user = db.session.get(User, session['user_id'])
    if not user:
        session.clear()
        return redirect(url_for('login'))

    now = datetime.utcnow()
    menu_tree = []

    # ── 1. 최고 관리자 (Admin) ──
    if user.role == 'admin':
        stores = Store.query.all()
        store_items = []
        for s in stores:
            store_items.append({
                'name': f"{s.name} ({s.id})",
                'links': [
                    {'label': 'AI 카운터', 'url': f"/counter"},
                    {'label': '매장 관리',  'url': f"/admin/manage/{s.id}"}
                ]
            })
        menu_tree.append({'name': '전체 매장', 'children': store_items})
        menu_tree.append({
            'name': '학습 및 지원',
            'children': [
                {'name': '기술 지식 창고', 'url': url_for('knowledge.index'),
                 'icon': 'fa-brain', 'icon_class': 'green'}
            ]
        })

    # ── 2. 파트너 (Partner) ──
    elif user.role == 'partner':
        managed_stores = Store.query.filter_by(recommended_by=user.id).all()
        store_items = []
        for s in managed_stores:
            store_items.append({
                'name': s.name,
                'links': [
                    {'label': 'AI 분석', 'url': f"/report/{s.id}"},
                    {'label': '매장 설정', 'url': f"/admin/manage/{s.id}"}
                ]
            })
        menu_tree.append({
            'name': '파트너 대시보드',
            'children': [
                {'name': '신규 매장 등록', 'url': '/partner/store/register',
                 'icon': 'fa-plus-circle', 'icon_class': 'cyan'}
            ]
        })
        menu_tree.append({'name': '담당 매장', 'children': store_items})

    # ── 3. 점주 (Owner) ──
    elif user.role == 'owner':
        store = db.session.get(Store, user.store_id) if user.store_id else None
        if store:
            # store_id를 URL에 직접 내장하는 빠른 실행 아이콘 메뉴
            quick_items = [
                {'name': '실시간 카운터',  'url': f"/counter",
                 'icon': 'fa-desktop',     'icon_class': 'cyan'},
                {'name': '주방 대시보드',  'url': f"/kitchen",
                 'icon': 'fa-utensils',    'icon_class': 'orange'},
                {'name': '매출 통계',      'url': f"/admin/manage/{store.id}",
                 'icon': 'fa-chart-bar',   'icon_class': 'blue'},
                {'name': 'QR 코드 인쇄',  'url': f"/qr_print/{store.id}",
                 'icon': 'fa-qrcode',      'icon_class': 'purple'},
                {'name': '구독 / 결제',    'url': '/billing',
                 'icon': 'fa-credit-card', 'icon_class': 'green'},
                {'name': '매장 설정',      'url': f"/admin/manage/{store.id}?tab=settings",
                 'icon': 'fa-gear',        'icon_class': 'orange'},
            ]
            menu_tree.append({'name': '매장 관리', 'store': store, 'children': quick_items})

            # 추가 메뉴 리스트
            extra_items = [
                {'name': '직원 근태 관리', 'url': '/attendance',
                 'icon': 'fa-clock', 'icon_class': 'cyan'},
                {'name': '웨이팅 관리',   'url': f"/waiting",
                 'icon': 'fa-list-ol', 'icon_class': 'blue'},
            ]
            menu_tree.append({'name': '운영 도구', 'children': extra_items})
        else:
            menu_tree.append({'name': '알림', 'children': [
                {'name': '연결된 매장이 없습니다.', 'url': '#',
                 'icon': 'fa-exclamation-circle', 'icon_class': 'red'}
            ]})

    # ── 4. 직원 (Staff) ──
    else:
        menu_tree.append({
            'name': '업무 포털',
            'children': [
                {'name': '출퇴근 관리', 'url': '/attendance',
                 'icon': 'fa-clock', 'icon_class': 'cyan'},
                {'name': '주문 확인',   'url': '/counter',
                 'icon': 'fa-list',    'icon_class': 'blue'},
            ]
        })

    return render_template('portal/portal_home.html',
        user=user, menu_tree=menu_tree, now=now, timedelta=timedelta)

# ─── Admin: 전체 매장 현황 ───
@portal_bp.route('/admin/stores')
@admin_required
def admin_stores():
    stores = Store.query.order_by(Store.created_at.desc()).all()
    return render_template('admin/admin_stores.html', stores=stores)

# ─── Admin: 구독 현황 대시보드 ───
@portal_bp.route('/admin/stores-billing')
@admin_required
def admin_stores_billing():
    now = datetime.utcnow()
    stores = Store.query.order_by(Store.created_at.desc()).all()

    store_data = []
    total_revenue = 0
    expired_count = 0
    trial_count = 0
    active_count = 0

    for s in stores:
        days_left = None
        billing_status = 'unknown'

        if s.expires_at:
            delta = s.expires_at - now
            days_left = delta.days
            if delta.total_seconds() <= 0:
                billing_status = 'expired'
                expired_count += 1
            elif s.payment_status == 'trial':
                billing_status = 'trial'
                trial_count += 1
            else:
                billing_status = 'active'
                active_count += 1
        else:
            billing_status = 'trial' if s.payment_status == 'trial' else 'unknown'

        # 이달 결제 합계
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_revenue = db.session.query(db.func.sum(Subscription.amount))\
            .filter(Subscription.store_id == s.id,
                    Subscription.paid_at >= month_start,
                    Subscription.method != 'free')\
            .scalar() or 0
        total_revenue += month_revenue

        store_data.append({
            'store': s,
            'days_left': days_left,
            'billing_status': billing_status,
            'month_revenue': month_revenue
        })

    return render_template('admin/admin_billing.html',
        store_data=store_data,
        total_revenue=total_revenue,
        expired_count=expired_count,
        trial_count=trial_count,
        active_count=active_count,
        now=now
    )

# ─── Admin: 회원 승인 대기 ───
@portal_bp.route('/admin/users/pending')
@admin_required
def admin_users_pending():
    from models import SystemConfig
    pending_users = User.query.filter_by(is_approved=False).all()
    all_users = User.query.order_by(User.created_at.desc()).limit(50).all()
    return render_template('admin/admin_users.html', pending_users=pending_users, all_users=all_users)

# ─── Admin: 사용자 승인 API ───
@portal_bp.route('/api/admin/users/<int:user_id>/approve', methods=['POST'])
@admin_required
def approve_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    user.is_approved = True
    db.session.commit()
    return jsonify({'status': 'success', 'message': f'{user.full_name or user.username} 승인 완료'})

# ─── Admin: 사용자 삭제 API ───
@portal_bp.route('/api/admin/users/<int:user_id>', methods=['DELETE'])
@admin_required
def delete_user(user_id):
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'status': 'error', 'message': 'User not found'}), 404
    db.session.delete(user)
    db.session.commit()
    return jsonify({'status': 'success'})

# ─── Admin: 시스템 설정 ───
@portal_bp.route('/admin/settings')
@admin_required
def admin_settings_page():
    from models import SystemConfig
    config = SystemConfig.query.first()
    if not config:
        config = SystemConfig(id=1)
        db.session.add(config)
        db.session.commit()
    return render_template('admin/admin_settings.html', config=config)
