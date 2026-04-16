import os, uuid, time
from flask import request, session, render_template, redirect, url_for, flash, jsonify
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timedelta
from sqlalchemy import func, desc, or_
from models import db, User, Store, SystemConfig, Order, OrderItem
from MQutils import (
    login_required, admin_required, staff_required, store_access_required, 
    get_staff_performance, get_ai_recommended_menu, extract_menu_from_image,
    extract_business_info_from_image
)

def init_admin_routes(app):
    @app.route('/admin/')
    @app.route('/admin')
    @login_required
    def admin_dashboard():
        """종합 대시보드 대신 실적 분석 페이지로 즉시 이동"""
        return redirect(url_for('admin_performance'))

    @app.route('/admin/manual/staff')
    @staff_required
    def staff_manual_page():
        try:
            with open('manuals/staff_manual.md', 'r', encoding='utf-8') as f:
                content = f.read()
            return render_template('admin/staff_manual_view.html', content=content)
        except: return "매뉴얼 파일을 찾을 수 없습니다.", 404

    @app.route('/admin/stores', methods=['GET'])
    @staff_required
    def admin_stores():
        user_id = session.get('user_id')
        role = session.get('role')
        
        if role == 'admin':
            stores = Store.query.order_by(Store.created_at.desc()).all()
        else:
            # 직원은 본인이 담당한 매장 + 공개 샘플 매장 리스팅
            stores = Store.query.filter(or_(Store.recommended_by == user_id, Store.is_public == True)).order_by(Store.created_at.desc()).all()
        return render_template('admin/stores.html', stores=stores)

    @app.route('/admin/stores/add', methods=['GET', 'POST'])
    @staff_required
    def admin_store_add():
        role = session.get('role')
        user_id = session.get('user_id')

        if request.method == 'POST':
            sid = request.form.get('id', '').strip()
            name = request.form.get('name', '').strip()
            tables = int(request.form.get('tables', 20))
            
            # [신규] 초기 메뉴 데이터 처리
            menu_json = request.form.get('menu_data', '').strip()
            menu_data = {}
            if menu_json:
                try:
                    import json
                    menu_data = json.loads(menu_json)
                except: pass

            if not sid or not name:
                flash("매장 ID와 이름을 모두 입력해 주세요.")
                return redirect(url_for('admin_store_add'))
                
            if Store.query.get(sid):
                flash(f"이미 존재하거나 사용 중인 매장 ID(Slug)입니다: {sid}")
                return redirect(url_for('admin_store_add'))
                
            # 신규 매장 인스턴스 생성
            # 영업 파트너(staff)가 등록한 경우 본인을 담당 직원으로 자동 지정
            rec_by = user_id if role == 'staff' else None
            new_store = Store(
                id=sid, 
                name=name, 
                tables_count=tables, 
                menu_data=menu_data, 
                recommended_by=rec_by,
                # [추가] 계좌 정보
                bank_name=request.form.get('bank_name', '').strip(),
                account_no=request.form.get('account_no', '').strip(),
                account_holder=request.form.get('account_holder', '').strip()
            )
            db.session.add(new_store)
            db.session.commit()
            
            flash(f"🚀 새로운 가맹점[{name}]이 시스템에 정식으로 등록되어 전개되었습니다.")
            return redirect(url_for('admin_stores'))

        return render_template('admin/store_add.html')

    @app.route('/admin/stores/<slug>/delete', methods=['POST'])
    @staff_required
    def admin_store_delete(slug):
        user_id = session.get('user_id')
        role = session.get('role')
        
        store = Store.query.get_or_404(slug)
        
        # 권한 체크: 관리자거나, 해당 매장을 등록한 담당자여야 함
        if role != 'admin' and store.recommended_by != user_id:
            flash("해당 매장에 대한 삭제 권한이 없습니다.")
            return redirect(url_for('admin_stores'))
        
        try:
            # [연쇄 정리] 삭제 전 매장 관련 데이터 모두 업데이트/삭제
            from models import Attendance, Waiting, PointTransaction, Customer
            
            # 1. 해당 매장 소속 유저들 무소속으로 업데이트
            User.query.filter_by(store_id=slug).update({User.store_id: None})
            
            # 2. 관련 데이터 일괄 삭제
            Order.query.filter_by(store_id=slug).delete()
            Attendance.query.filter_by(store_id=slug).delete()
            Waiting.query.filter_by(store_id=slug).delete()
            PointTransaction.query.filter_by(store_id=slug).delete()
            Customer.query.filter_by(store_id=slug).delete()

            # 3. 매장 본체 삭제
            db.session.delete(store)
            db.session.commit()
            flash(f"✅ 매장 [{store.name}] 및 관련 모든 데이터가 영구 삭제되었습니다.")
        except Exception as e:
            db.session.rollback()
            flash(f"❌ 삭제 중 오류가 발생했습니다: {e}")
            
        return redirect(url_for('admin_stores'))

    @app.route('/admin/stores/<slug>/config', methods=['GET', 'POST'])
    @store_access_required
    def admin_store_config(slug):
        store = db.session.get(Store, slug)
        user_id = session.get('user_id')
        role = session.get('role')
        user_store_id = session.get('store_id')

        # 보안 체크
        can_access = False
        if role == 'admin':
            can_access = True
        elif role == 'staff' and store.recommended_by == user_id:
            can_access = True
        elif role in ['owner', 'manager'] and slug == user_store_id:
            can_access = True
            
        if not can_access:
            flash("해당 업소에 대한 관리 권한이 없습니다.")
            return redirect(url_for('index'))
        
        if request.method == 'POST':
            # 매장 기본 정보 업데이트
            store.name = request.form.get('name')
            store.business_no = request.form.get('business_no')
            store.ceo_name = request.form.get('ceo_name')
            store.business_email = request.form.get('business_email')
            store.business_type = request.form.get('business_type')  # [추가] 업종 저장
            store.theme_color = request.form.get('theme_color', store.theme_color)
            store.contact_phone = request.form.get('contact_phone', store.contact_phone)
            store.point_ratio = float(request.form.get('point_ratio', 0))
            store.waiting_sms_no = request.form.get('waiting_sms_no', store.waiting_sms_no)
            store.disable_auto_logout = 'disable_auto_logout' in request.form

            # [신규] 계좌 정보 저장
            store.bank_name = request.form.get('bank_name')
            store.account_no = request.form.get('account_no')
            store.account_holder = request.form.get('account_holder')
            
            # 담당 직원 및 공개 설정은 최고 관리자(Admin)만 변경 가능
            if role == 'admin':
                store.recommended_by = request.form.get('recommended_by')
                store.is_public = 'is_public' in request.form
            
            # 월 회비는 관리자나 영업 파트너만 수정 가능 (점주는 불가)
            if role in ['admin', 'staff']:
                store.monthly_fee = int(request.form.get('monthly_fee', 50000))
            
            # 메뉴 데이터 저장 (JSON 포맷)
            raw_menu = request.form.get('menu_data', '{}')
            try:
                import json
                store.menu_data = json.loads(raw_menu)
                print(f"DEBUG: [{store.id}] 메뉴판 데이터 저장 시도 -> {len(store.menu_data)} 카테고리 감지")
            except Exception as e:
                print(f"ERROR: [{store.id}] 메뉴 JSON 파싱 실패: {e}")
                
            db.session.commit()
            flash(f"매장 '{store.name}'의 모든 설정이 안전하게 저장되었습니다.")
            
            # 점주는 메인으로, 관리/직원은 목록으로 리다이렉트
            if role in ['owner', 'manager']:
                return redirect(url_for('index'))
            return redirect(url_for('admin_stores'))

        # 담당 직원 선택 목록 (Admin용)
        staffs = User.query.filter(User.role.in_(['staff', 'admin', 'owner'])).all()
        return render_template('admin/store_config.html', store=store, staffs=staffs, role=role)

    @app.route('/admin/performance')
    @staff_required
    def admin_performance():
        user_id = session.get('user_id')
        role = session.get('role')
        
        # 분석 대상 선정
        if role == 'admin':
            staffs = User.query.filter(User.role.in_(['staff', 'admin', 'owner'])).all()
        else:
            staffs = User.query.filter_by(id=user_id).all()
        
        # 실적 데이터 합산 (MQutils 유틸리티 활용)
        performance_data = get_staff_performance(staffs, Store, Order)
        
        return render_template('admin/performance.html', data=performance_data, role=role)

    @app.route('/profile', methods=['GET', 'POST'])
    @login_required
    def profile():
        """개인정보 수정 페이지 (본인 인증 필수)"""
        user = User.query.get(session['user_id'])
        
        if request.method == 'POST':
            data = request.json
            current_pw = data.get('current_password', '').strip()
            new_pw = data.get('new_password', '').strip()
            
            # 🛡️ 보안: 현재 비밀번호가 일치하는지 먼저 확인
            if not check_password_hash(user.password, current_pw):
                return jsonify({'status': 'error', 'message': '현재 비밀번호가 일치하지 않습니다.'}), 401
                
            # 정보 업데이트
            user.full_name = data.get('full_name', user.full_name)
            user.phone = data.get('phone', user.phone)
            
            # 새 비밀번호가 입력된 경우에만 해싱하여 저장
            if new_pw:
                user.password = generate_password_hash(new_pw)
                
            db.session.commit()
            return jsonify({'status': 'success', 'message': '개인정보가 안전하게 수정되었습니다.'})
            
        return render_template('profile.html', user=user)

    @app.route('/admin/users', methods=['GET', 'POST'])
    @admin_required
    def admin_users():
        if request.method == 'POST':
            username = request.form.get('username')
            password = request.form.get('password')
            role = request.form.get('role', 'owner')
            sid = request.form.get('store_id')
            if User.query.filter_by(username=username).first(): flash("이미 존재하는 아이디입니다.")
            else:
                # 관리자가 직접 생성하는 계정은 즉시 승인 상태로 생성
                new_user = User(username=username, password=generate_password_hash(password), role=role, store_id=sid if sid != 'null' else None, is_approved=True)
                db.session.add(new_user)
                db.session.commit()
                flash(f"{username} 계정이 생성 및 승격되었습니다.")
            return redirect(url_for('admin_users'))
        users = User.query.all()
        stores = Store.query.all()
        return render_template('admin/users.html', users=users, stores=stores)

    @app.route('/admin/users/<int:user_id>/approve', methods=['POST'])
    @login_required
    def admin_user_approve(user_id):
        current_role = session.get('role')
        current_user_store = session.get('store_id')
        
        user_to_approve = db.session.get(User, user_id)
        if not user_to_approve:
            flash("사용자를 찾을 수 없습니다.")
            return redirect(request.referrer or url_for('index'))

        # 권한 체크
        # 1. 최고 관리자는 모든 승인 가능
        # 2. 사장님(owner)과 점장(manager)은 본인 매장 소속이면서 파트너(staff)가 아닌 경우만 승인 가능
        can_approve = False
        if current_role == 'admin':
            can_approve = True
        elif current_role in ['owner', 'manager']:
            if user_to_approve.store_id == current_user_store and user_to_approve.role != 'staff':
                can_approve = True

        if not can_approve:
            flash("해당 사용자를 승인할 권한이 없습니다.")
            return redirect(request.referrer or url_for('index'))

        user_to_approve.is_approved = True
        db.session.commit()
        flash(f"{user_to_approve.username} 님의 가입 신청이 승인되었습니다.")
        return redirect(request.referrer or url_for('index'))

    @app.route('/admin/users/<int:user_id>/delete', methods=['POST'])
    @admin_required
    def admin_user_delete(user_id):
        user = db.session.get(User, user_id)
        if user:
            if user.username == session.get('username'): flash("본인 계정은 삭제할 수 없습니다.")
            else:
                db.session.delete(user)
                db.session.commit()
                flash("계정이 삭제되었습니다.")
        return redirect(url_for('admin_users'))

    @app.route('/admin/users/<int:user_id>/update', methods=['POST'])
    @admin_required
    def admin_user_update(user_id):
        """승인된 사용자 정보 수정 API"""
        user = db.session.get(User, user_id)
        if not user:
            return jsonify({'status': 'error', 'message': '사용자를 찾을 수 없습니다.'}), 404
        
        data = request.json
        
        # 비밀번호 (입력된 경우만 변경)
        new_pw = data.get('password', '').strip()
        if new_pw:
            user.password = generate_password_hash(new_pw)
        
        # 요일별 시간, 계약 기간
        if 'work_schedule' in data:
            user.work_schedule = data['work_schedule']
        
        if data.get('contract_start'):
            user.contract_start = datetime.strptime(data['contract_start'], '%Y-%m-%d').date()
        else:
            user.contract_start = None
            
        if data.get('contract_end'):
            user.contract_end = datetime.strptime(data['contract_end'], '%Y-%m-%d').date()
        else:
            user.contract_end = None
        
        db.session.commit()
        return jsonify({'status': 'success'})

    @app.route('/admin/billing')
    @staff_required
    def admin_billing():
        user_id = session.get('user_id')
        role = session.get('role')
        
        if role == 'admin':
            stores = Store.query.all()
        elif role == 'staff':
            # 파트너는 본인이 추천한 매장 + 공개 샘플 매장만 조회 가능
            stores = Store.query.filter(or_(Store.recommended_by == user_id, Store.is_public == True)).all()
        else:
            # 일반 점주/매니저는 본인 매장 정보만
            current_store_id = session.get('store_id')
            stores = Store.query.filter_by(id=current_store_id).all() if current_store_id else []

        unpaid = len([s for s in stores if s.payment_status == 'unpaid'])
        sus = len([s for s in stores if s.status == 'suspended'])
        
        return render_template('admin/billing.html', 
                               stores=stores, 
                               unpaid_count=unpaid, 
                               suspended_count=sus, 
                               total_stores=len(stores),
                               role=role,
                               now=datetime.utcnow())

    @app.route('/partner/recruit-qr')
    @staff_required
    def partner_recruit_qr():
        return render_template('admin/recruit_qr.html')

    @app.route('/api/admin/store/clone', methods=['POST'])
    @staff_required
    def api_clone_store():
        data = request.json
        source_id = data.get('source_id')
        user_id = session.get('user_id')
        
        source = db.session.get(Store, source_id)
        if not source: return jsonify({'status': 'error', 'message': '원본 매장을 찾을 수 없습니다.'}), 404
        
        # 닉네임 + 타임스탬프로 유니크한 데모 ID 생성
        demo_id = f"demo_{source_id}_{int(time.time()) % 10000}"
        
        new_store = Store(
            id=demo_id,
            name=f"[DEMO] {source.name}",
            menu_data=source.menu_data,
            theme_color=source.theme_color,
            recommended_by=user_id,
            status='active',
            # [약관준수] 원본 업소의 인적사항 및 사업자 정보는 복사하지 않음
            business_no=None,
            ceo_name=None,
            business_email=None,
            business_type=None,
            business_item=None,
            signature_owner=None,
            signature_partner=None,
            monthly_fee=50000 # 기보급형 기본값
        )
        db.session.add(new_store)
        
        # 데모 매장용 점주 계정도 자동 생성 (시연용 - 비번 1111 고정)
        demo_owner = User(
            username=f"owner_{demo_id}",
            password=generate_password_hash('1111'),
            role='owner',
            store_id=demo_id,
            is_approved=True
        )
        db.session.add(demo_owner)
        db.session.commit()
        
        return jsonify({
            'status': 'success', 
            'demo_id': demo_id, 
            'owner_id': demo_owner.username,
            'message': f'시연용 매장({demo_id})이 생성되었습니다. 점주 ID: {demo_owner.username} / PW: 1111'
        })

    @app.route('/signup/new-store', methods=['GET', 'POST'])
    def signup_new_store():
        # 파트너가 점주에게 보여준 QR을 통해 접속한 경우
        partner_id = request.args.get('partner_id') or request.form.get('partner_id')
        
        if request.method == 'POST':
            slug = request.form.get('slug').strip()
            name = request.form.get('name').strip()
            username = request.form.get('username').strip()
            password = request.form.get('password').strip()
            
            # [데이터 보정] partner_id가 비어있거나 문자열일 경우를 대비해 숫자로 변환
            raw_partner_id = request.form.get('partner_id')
            try:
                partner_id_int = int(raw_partner_id) if raw_partner_id and str(raw_partner_id).isdigit() else None
            except:
                partner_id_int = None
                
            # monthly_fee 숫자 변환
            try:
                monthly_fee_int = int(request.form.get('monthly_fee', 50000))
            except:
                monthly_fee_int = 50000
            
            # 중복 체크
            if Store.query.get(slug):
                flash(f"이미 사용 중인 업소 영문 코드({slug})입니다. 다른 코드를 사용해 주세요.")
                return redirect(url_for('signup_new_store', partner_id=partner_id))
            if User.query.filter_by(username=username).first():
                flash(f"이미 존재하는 계정 아이디({username})입니다. 다른 아이디를 사용해 주세요.")
                return redirect(url_for('signup_new_store', partner_id=partner_id))

            try:
                # AI 메뉴 자동 추천 로직 적용
                business_type = request.form.get('business_type', '').strip()
                ai_menu = get_ai_recommended_menu(business_type)

                # 1. 업소 생성 (Pending 상태)
                new_store = Store(
                    id=slug,
                    name=name,
                    menu_data=ai_menu, # [AI] 업종에 맞는 메뉴 자동 생성
                    business_no=request.form.get('business_no'),
                    ceo_name=request.form.get('ceo_name'),
                    business_type=business_type,
                    business_item=request.form.get('business_item'),
                    business_email=request.form.get('business_email'),
                    monthly_fee=monthly_fee_int,
                    recommended_by=partner_id_int,
                    signature_owner=request.form.get('sig_owner'),
                    signature_partner=request.form.get('sig_partner'),
                    # [추가] 계좌 정보 등록
                    bank_name=request.form.get('bank_name', '').strip(),
                    account_no=request.form.get('account_no', '').strip(),
                    account_holder=request.form.get('account_holder', '').strip(),
                    status='pending',
                    payment_status='paid',
                    expires_at=datetime.utcnow() + timedelta(days=31)
                )
                db.session.add(new_store)
                db.session.flush() # [핵심] DB에 매장 정보를 먼저 밀어넣어 외래키 제약조건 충족
                
                # 2. 점주 계정 생성 (Pending 상태)
                new_owner = User(
                    username=username,
                    password=generate_password_hash(password),
                    role='owner',
                    store_id=slug,
                    is_approved=False
                )
                db.session.add(new_owner)
                db.session.commit()
                
                print(f"✅ [계약 성공] 신규 가맹점({slug}) 및 점주({username}) 등록 완료!")
                
                # [추가] 가계약 완료 후 자동 로그인 처리 (상세 설정 즉시 진입용)
                session['user_id'] = new_owner.id
                session['username'] = new_owner.username
                session['role'] = new_owner.role
                session['store_id'] = new_owner.store_id
                
                flash("🎉 가계약이 체결되었습니다! 매장의 메뉴와 상세 정보를 설정해 주세요.")
                return redirect(url_for('admin_store_config', slug=slug))

            except Exception as e:
                db.session.rollback()
                print(f"❌ [계약 실패] 오류 발생: {e}")
                flash(f"가계약 체결 중 오류가 발생했습니다: {str(e)}")
                return redirect(url_for('signup_new_store', partner_id=partner_id))

        return render_template('signup/new_store.html', partner_id=partner_id)

    @app.route('/admin/stores/setup/<slug>', methods=['GET', 'POST'])
    @login_required
    def admin_store_setup(slug):
        store = db.session.get(Store, slug)
        if not store: return "Store not found", 404
        
        if request.method == 'POST':
            store.theme_color = request.form.get('theme_color')
            store.contact_phone = request.form.get('contact_phone')
            store.point_ratio = float(request.form.get('point_ratio', 0))
            store.waiting_sms_no = request.form.get('waiting_sms_no')
            db.session.commit()
            
            flash("매장 맞춤 설정이 저장되었습니다. 어드민이 확인 후 원격 승인 시 운영이 개시됩니다.")
            return redirect(url_for('index'))
            
        return render_template('admin/store_setup.html', store=store)

    @app.route('/admin/billing/payouts')
    @admin_required
    def admin_payout_list():
        # 정산 대상에 관리자(admin) 및 사장님(owner)도 포함하도록 수정
        partners = User.query.filter(User.role.in_(['staff', 'admin', 'owner']), User.is_approved == True).all()
        payout_data = []
        now = datetime.utcnow()
        
        for p in partners:
            # 해당 파트너가 담당하는 매장들 조회
            stores = Store.query.filter_by(recommended_by=p.id).all()
            total_payout = 0
            billable_stores_count = 0
            
            for s in stores:
                if s.payment_status == 'paid':
                    # 가입 후 2개월(60일) 이상 경과한 매장만 정산 대상 (가입월 + 무료지원월 제외)
                    delta = now - s.created_at
                    total_months = delta.days // 30
                    if total_months >= 2:
                        total_payout += (s.monthly_fee or 50000)
                        billable_stores_count += 1
            
            # 정산할 금액이 있거나 매장이 있는 경우 리스트 업
            if total_payout > 0 or len(stores) > 0:
                payout_data.append({
                    'name': p.full_name or p.username,
                    'phone': p.phone or '연락처 미기재',
                    'amount': total_payout,
                    'store_count': len(stores),
                    'billable_count': billable_stores_count
                })
                
        # 매월 25일 기준으로 표시
        display_date = now.strftime('%Y년 %m월 25일')
        return render_template('admin/payout_print.html', payout_data=payout_data, date=display_date)

    @app.route('/admin/settings', methods=['GET', 'POST'])
    @admin_required
    def admin_settings():
        config = SystemConfig.query.first()
        if request.method == 'POST':
            if not config:
                config = SystemConfig()
                db.session.add(config)
            config.site_name = request.form.get('site_name', 'MQnet Central')
            config.maintenance_mode = 'maintenance_mode' in request.form
            db.session.commit()
            flash("시스템 설정이 저장되었습니다.")
            return redirect(url_for('admin_settings'))
        return render_template('admin/settings.html', config=config)

    @app.route('/api/admin/billing/toggle', methods=['POST'])
    @admin_required
    def api_billing_toggle():
        data = request.json
        sid = data.get('store_id')
        store = db.session.get(Store, sid)
        if store:
            store.payment_status = 'paid' if store.payment_status == 'unpaid' else 'unpaid'
            if store.payment_status == 'paid':
                now = datetime.utcnow()
                if not store.expires_at or store.expires_at < now: store.expires_at = now + timedelta(days=30)
            db.session.commit()
            return jsonify({'status': 'success', 'new_status': store.payment_status})
        return jsonify({'status': 'error'}), 404

    @app.route('/api/admin/store/status-toggle', methods=['POST'])
    @admin_required
    def api_status_toggle():
        data = request.json
        sid = data.get('store_id')
        store = db.session.get(Store, sid)
        if store:
            # 'active'면 'unregistered'로, 그 외엔 'active'로 토글
            store.status = 'unregistered' if store.status == 'active' else 'active'
            db.session.commit()
            return jsonify({'status': 'success', 'new_status': store.status})
        return jsonify({'status': 'error'}), 404

    @app.route('/api/admin/upload', methods=['POST'])
    @staff_required
    def api_upload_image():
        ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
        file = request.files.get('file')
        if not file: return jsonify({'error': 'No file'}), 400
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
        if ext not in ALLOWED_EXTENSIONS:
            return jsonify({'error': f'허용되지 않는 파일 형식입니다. ({ext}). 허용: {ALLOWED_EXTENSIONS}'}), 400
        filename = str(uuid.uuid4()) + '.' + ext  # 원본 파일명을 UUID로 완전 대체 (Path Traversal 방지)
        file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))
        return jsonify({'status': 'success', 'url': f'/static/images/{filename}'})

    @app.route('/api/admin/menu-analyze', methods=['POST'])
    @staff_required
    def api_menu_analyze():
        file = request.files.get('file')
        if not file:
            return jsonify({'status': 'error', 'message': '파일이 없습니다.'}), 400
        
        # 임시 저장
        temp_filename = f"temp_analyze_{uuid.uuid4()}.jpg"
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        file.save(temp_path)
        
        try:
            # AI 분석 시작
            raw_result = extract_menu_from_image(temp_path)
            
            # 분석 완료 후 임시 파일 삭제
            if os.path.exists(temp_path):
                os.remove(temp_path)
                
            if "error" in raw_result:
                return jsonify({'status': 'error', 'message': raw_result['error']}), 500
            
            # [변환] List 기반 AI 응답을 Dict 기반 UI 데이터로 변환
            # AI: { "menu_data": [ { "category": "C", "items": [...] } ] }
            # UI: { "C": [...], "D": [...] }
            transformed_menu = {}
            if "menu_data" in raw_result:
                for cat_group in raw_result["menu_data"]:
                    cat_name = cat_group.get("category", "기타")
                    items = cat_group.get("items", [])
                    # 이미지 경로는 비워둠 (추후 개별 업로드)
                    for item in items:
                        if "image" not in item:
                            item["image"] = ""
                    transformed_menu[cat_name] = items
            
            if not transformed_menu:
                return jsonify({'status': 'error', 'message': '메뉴 데이터를 추출하지 못했습니다. 선명한 사진으로 다시 시도해 주세요.'}), 422
                
            return jsonify({'status': 'success', 'menu_data': transformed_menu})
        except Exception as e:
            return jsonify({'status': 'error', 'message': str(e)}), 500

    @app.route('/api/admin/biz-analyze', methods=['POST'])
    @login_required
    def api_biz_analyze():
        """사업자등록증 사진을 AI로 분석하여 업장·점주 정보를 반환합니다."""
        file = request.files.get('file')
        if not file:
            return jsonify({'status': 'error', 'message': '파일이 없습니다.'}), 400

        # 확장자 검증
        ALLOWED = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'heic', 'heif'}
        ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else 'jpg'
        if ext not in ALLOWED:
            return jsonify({'status': 'error', 'message': f'허용되지 않는 파일 형식입니다. ({ext})'}), 400

        # 임시 저장
        temp_filename = f"temp_biz_{uuid.uuid4()}.{ext}"
        temp_path = os.path.join(app.config['UPLOAD_FOLDER'], temp_filename)
        file.save(temp_path)

        try:
            biz_info = extract_business_info_from_image(temp_path)
        except Exception as e:
            biz_info = {'error': str(e)}
        finally:
            if os.path.exists(temp_path):
                os.remove(temp_path)

        if 'error' in biz_info:
            return jsonify({'status': 'error', 'message': biz_info['error']}), 500

        return jsonify({'status': 'success', 'biz_info': biz_info})
