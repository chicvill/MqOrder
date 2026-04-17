from functools import wraps
from flask import session, redirect, url_for, flash, render_template, request

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            # [수정] full_path 대신 path를 사용하여 ? 문제를 방지
            return redirect(url_for('login', next=request.path))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @login_required
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get('role') != 'admin':
            return render_template('access_denied.html')
        return f(*args, **kwargs)
    return decorated_function


def manager_required(f):
    @login_required
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 점장(manager)급 이상 (admin, owner 포함)
        if session.get('role') not in ['admin', 'owner', 'manager']:
            return render_template('access_denied.html')
        return f(*args, **kwargs)
    return decorated_function

def owner_only_required(f):
    @login_required
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # 오직 사장님(owner)과 최고 관리자(admin)만 가능
        if session.get('role') not in ['admin', 'owner']:
            return render_template('access_denied.html')
        return f(*args, **kwargs)
    return decorated_function

def store_access_required(f):
    @wraps(f)
    def decorated_function(slug, *args, **kwargs):
        # [현황판/주방 API 개방] 로그인이 없어도 특정 API는 허용
        from flask import request
        # /orders, /waiting/list, /service_requests 는 상시 허용 (카운터 동기화용)
        path = request.path
        if path.endswith('/orders') or path.endswith('/waiting/list') or path.endswith('/service_requests'):
            return f(slug, *args, **kwargs)

        if 'user_id' not in session:
            return redirect(url_for('login'))
            
        role = session.get('role')
        user_id = session.get('user_id')
        
        # 어드민은 프리패스
        if role == 'admin':
            return f(slug, *args, **kwargs)

        # 사장님(owner)과 점장(manager)은 본인 소속 매장(slug)인지만 체크
        if role in ['owner', 'manager']:
            if session.get('store_id') != slug:
                if request.path.startswith('/api/'):
                    from flask import jsonify
                    return jsonify({'error': 'Access denied', 'reply': '해당 매장에 대한 접근 권한이 없습니다.'}), 403
                return render_template('access_denied.html')
            return f(slug, *args, **kwargs)
            
        if request.path.startswith('/api/'):
            from flask import jsonify
            return jsonify({'error': 'Access denied', 'reply': '접근 권한이 없습니다.'}), 403
        return render_template('access_denied.html')
    return decorated_function
