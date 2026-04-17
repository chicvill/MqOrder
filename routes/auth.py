from flask import request, session, render_template, redirect, url_for, flash, jsonify
from werkzeug.security import check_password_hash, generate_password_hash
from datetime import datetime, timedelta
from models import db, User, Store, Subscription
import re
import base64
from MQutils.ai_engine import analyze_business_registration

def init_auth_routes(app):

    # ─── 로그인 ───
    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if 'user_id' in session:
            return redirect(url_for('index'))
        if request.method == 'POST':
            try:
                username = request.form.get('username', '').strip()
                password = request.form.get('password', '').strip()
                if not username or not password:
                    flash('아이디와 비밀번호를 모두 입력해 주세요.', 'error')
                    return redirect(url_for('login'))
                user = User.query.filter_by(username=username).first()
                if user and check_password_hash(user.password, password):
                    remember_me = request.form.get('remember_me') == 'yes'
                    
                    # [신규] 매장 설정에서 자동 로그아웃 방지가 켜져 있으면 강제로 permanent 설정
                    if user.store_id:
                        store_cfg = db.session.get(Store, user.store_id)
                        if store_cfg and store_cfg.disable_auto_logout:
                            remember_me = True
                            print(f"🔒 [보안] {user.store_id} 매장의 자동 로그아웃 방지 설정이 감지되었습니다.")

                    session.permanent = remember_me
                    if remember_me:
                        # 30일간 로그인 유지 (SaaS 정책에 따라 기간 조정 가능)
                        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=365) # 1년으로 대폭 상향
                    else:
                        # 기본 브라우저 종료 시 종료 또는 짧은 기간
                        app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(hours=2)

                    session.update({'user_id': user.id, 'username': user.username,
                                    'role': user.role, 'store_id': user.store_id})
                    next_url = request.args.get('next') or request.form.get('next')
                    if next_url and next_url.startswith('/'):
                        return redirect(next_url)
                    return redirect(url_for('index'))
                else:
                    flash('⚠️ 아이디 또는 비밀번호를 확인해주세요.', 'error')
            except Exception:
                import traceback; traceback.print_exc()
                flash('시스템 처리 중 오류가 발생했습니다.', 'error')
        return render_template('login.html')

    # ─── 로그아웃 ───
    @app.route('/logout')
    def logout():
        session.clear()
        return redirect(url_for('index'))

    # ─── Slug 중복 체크 API ───
    @app.route('/api/check-slug')
    def check_slug():
        slug = request.args.get('slug', '').strip().lower()
        if not slug:
            return jsonify({'available': False, 'reason': 'empty'})
        if not re.match(r'^[a-z0-9\-]{2,30}$', slug):
            return jsonify({'available': False, 'reason': 'invalid'})
        exists = db.session.get(Store, slug)
        return jsonify({'available': exists is None})

    # ─── 셀프 온보딩 가입 ───
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if 'user_id' in session:
            return redirect(url_for('portal.home'))

        if request.method == 'POST':
            full_name  = request.form.get('full_name', '').strip()
            phone      = request.form.get('phone', '').strip()
            username   = request.form.get('username', '').strip()
            password   = request.form.get('password', '').strip()
            confirm_pw = request.form.get('confirm_password', '').strip()
            store_name   = request.form.get('store_name', '').strip()
            store_id     = request.form.get('store_id', '').strip().lower()
            tables_count = int(request.form.get('tables_count', 10))
            theme_color  = request.form.get('theme_color', '#3b82f6')
            agree_terms   = 'agree_terms'   in request.form
            agree_privacy = 'agree_privacy' in request.form
            agree_age     = 'agree_age'     in request.form

            errors = []
            if not all([full_name, phone, username, password, store_name, store_id]):
                errors.append('모든 항목을 입력해 주세요.')
            if password != confirm_pw:
                errors.append('비밀번호가 일치하지 않습니다.')
            if len(password) < 8:
                errors.append('비밀번호는 8자 이상이어야 합니다.')
            if not re.match(r'^[a-z0-9\-]{2,30}$', store_id):
                errors.append('매장 URL 코드 형식이 올바르지 않습니다.')
            if not all([agree_terms, agree_privacy, agree_age]):
                errors.append('필수 약관에 모두 동의해 주세요.')
            if User.query.filter_by(username=username).first():
                errors.append('이미 사용 중인 아이디입니다.')
            if db.session.get(Store, store_id):
                errors.append('이미 사용 중인 매장 URL입니다.')

            if errors:
                for e in errors:
                    flash(e, 'error')
                return redirect(url_for('register'))

            # 사용자 생성
            new_user = User(
                username=username,
                password=generate_password_hash(password),
                role='owner',
                full_name=full_name,
                phone=phone,
                is_approved=True
            )
            db.session.add(new_user)
            db.session.flush()

            # 매장 생성 (30일 무료 체험 - 계획서 기준)
            trial_expires = datetime.utcnow() + timedelta(days=30)
            new_store = Store(
                id=store_id,
                name=store_name,
                tables_count=tables_count,
                theme_color=theme_color,
                ceo_name=full_name,
                status='active',
                payment_status='trial',
                expires_at=trial_expires
            )
            db.session.add(new_store)
            db.session.flush()

            new_user.store_id = store_id

            # 7일 체험 구독 내역
            db.session.add(Subscription(
                store_id=store_id,
                plan='trial',
                amount=0,
                method='free',
                status='active',
                period_start=datetime.utcnow(),
                period_end=trial_expires,
                paid_at=datetime.utcnow()
            ))
            db.session.commit()

            session.permanent = True
            session.update({
                'user_id': new_user.id,
                'username': new_user.username,
                'role': 'owner',
                'store_id': store_id
            })
            flash(f'환영합니다, {full_name}님! 30일 무료 체험이 시작되었습니다. 만료 전에 구독을 시작하시면 서비스가 중단 없이 이어집니다.', 'success')
            return redirect(url_for('portal.home'))

        return render_template('register.html')

    # ─── 사업자등록증 OCR 분석 API ───
    @app.route('/api/auth/ocr-business', methods=['POST'])
    def ocr_business():
        if 'biz_image' not in request.files:
            return jsonify({'success': False, 'message': '파일이 없습니다.'}), 400
        
        file = request.files['biz_image']
        if file.filename == '':
            return jsonify({'success': False, 'message': '선택된 파일이 없습니다.'}), 400
        
        try:
            # 파일을 base64로 변환
            img_bytes = file.read()
            img_b64 = base64.b64encode(img_bytes).decode('utf-8')
            
            # AI 분석 호출
            result = analyze_business_registration(img_b64)
            
            if 'error' in result:
                return jsonify({'success': False, 'message': result['error']}), 500
                
            return jsonify({'success': True, 'data': result})
        except Exception as e:
            return jsonify({'success': False, 'message': str(e)}), 500
