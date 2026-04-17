from flask import Blueprint, request, jsonify, session, render_template, redirect, url_for, flash
from datetime import datetime, timedelta, timezone
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash
from models import db, User, Attendance, Store, Order
from MQutils import login_required, owner_only_required
from extensions import socketio

attendance_bp = Blueprint('attendance_bp', __name__)

@attendance_bp.route('/api/<slug>/attendance/check-in', methods=['POST'])
@login_required
def api_staff_check_in(slug):
    user_id = session.get('user_id')
    role = session.get('role')
    user = db.session.get(User, user_id)
    
    # [권한 체크] 현장 근로자(worker) 및 점장(manager)만 출퇴근 가능
    if role not in ['worker', 'manager']:
        return jsonify({'status': 'error', 'message': '현장 근로자 및 점장 계정 전용 기능입니다.'}), 403
    
    # [소속 체크]
    if not user or not user.store_id or user.store_id != slug:
        return jsonify({'status': 'error', 'message': '해당 매장에 등록되지 않은 근로자입니다.'}), 403

    # [계약 기간 체크]
    # 글로벌 현지 시간 동기화 (기본 Asia/Seoul)
    from zoneinfo import ZoneInfo
    store = db.session.get(Store, slug)
    try:
        tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
    except Exception:
        tz = ZoneInfo('Asia/Seoul')
        
    now_full = datetime.now(tz)
    today_date = now_full.date()
    if user.contract_start and today_date < user.contract_start:
        return jsonify({'status': 'error', 'message': f'근무 시작 전입니다. (시작일: {user.contract_start})'}), 400
    if user.contract_end and today_date > user.contract_end:
        return jsonify({'status': 'error', 'message': f'계약 기간이 종료되었습니다. (종료일: {user.contract_end})'}), 400

    # [요일별 시간 체크]
    days_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
    today_key = days_map[now_full.weekday()]
    
    if not user.work_schedule or today_key not in user.work_schedule:
        return jsonify({'status': 'error', 'message': '오늘은 근무일이 아닙니다.'}), 400
        
    sched = user.work_schedule[today_key]
    in_time_str = sched.get('in')
    if not in_time_str:
        return jsonify({'status': 'error', 'message': '정해진 출근 시간이 없습니다.'}), 400
    
    # [수정] 자정 전후 야간 근무자 출근 처리를 위해 어제/오늘/내일 세 가지 날짜를 모두 비교
    now_naive = now_full.replace(tzinfo=None)
    base_target = datetime.strptime(f"{today_date} {in_time_str}", "%Y-%m-%d %H:%M")
    
    candidates = [
        base_target - timedelta(days=1),
        base_target,
        base_target + timedelta(days=1)
    ]
    
    best_target = min(candidates, key=lambda t: abs((now_naive - t).total_seconds()))
    diff = abs((now_naive - best_target).total_seconds())
    
    if diff > 300: # 5분 = 300초 (계획서 기준)
        return jsonify({'status': 'error', 'message': f'출근 가능 시간이 아닙니다. (정해진 시간: {in_time_str} 전후 5분 이내 가능)'}), 400

    # 이미 출근 중인지 확인
    existing = Attendance.query.filter(Attendance.user_id==user_id, Attendance.store_id==slug, Attendance.status=='working').first()
    if existing:
        return jsonify({'status': 'error', 'message': '이미 업무 진행 중입니다.'}), 400
    
    # [자동 승인] 정해진 시간에 출근한 것으로 기록
    # DB는 UTC로 저장하므로 현지 타임존을 강제 지정 후 UTC로 변환하여 저장
    target_in_utc = best_target.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    
    new_att = Attendance(
        user_id=user_id, 
        store_id=slug, 
        check_in_at=target_in_utc, 
        status='working'
    )
    db.session.add(new_att)
    db.session.commit()
    
    return jsonify({'status': 'success', 'message': f'출근 처리되었습니다. (기록시간: {in_time_str})'})

@attendance_bp.route('/api/<slug>/attendance/check-out', methods=['POST'])
@login_required
def api_staff_check_out(slug):
    user_id = session.get('user_id')
    role = session.get('role')
    user = db.session.get(User, user_id)
    
    if role not in ['worker', 'manager']:
        return jsonify({'status': 'error', 'message': '현장 근로자 및 점장 계정 전용 기능입니다.'}), 403

    att = Attendance.query.filter_by(user_id=user_id, store_id=slug, status='working').first()
    if not att:
        return jsonify({'status': 'error', 'message': '업무 중인 상태가 아닙니다.'}), 400
    
    # [요일별 시간 체크]
    from zoneinfo import ZoneInfo
    store = db.session.get(Store, slug)
    try:
        tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
    except Exception:
        tz = ZoneInfo('Asia/Seoul')
        
    now_full = datetime.now(tz)
    today_date = now_full.date()
    days_map = {0: 'mon', 1: 'tue', 2: 'wed', 3: 'thu', 4: 'fri', 5: 'sat', 6: 'sun'}
    today_key = days_map[now_full.weekday()]
    
    if not user.work_schedule or today_key not in user.work_schedule:
        return jsonify({'status': 'error', 'message': '오늘은 근무 정해진 퇴근 시간이 없습니다.'}), 400
        
    sched = user.work_schedule[today_key]
    out_time_str = sched.get('out')
    if not out_time_str:
        return jsonify({'status': 'error', 'message': '정해진 퇴근 시간이 없습니다.'}), 400
    
    # [수정] 자정 전후 야간 근무자 퇴근 처리를 위해 어제/오늘/내일 비교
    now_naive = now_full.replace(tzinfo=None)
    base_target = datetime.strptime(f"{today_date} {out_time_str}", "%Y-%m-%d %H:%M")
    
    candidates = [
        base_target - timedelta(days=1),
        base_target,
        base_target + timedelta(days=1)
    ]
    
    best_target = min(candidates, key=lambda t: abs((now_naive - t).total_seconds()))
    diff = abs((now_naive - best_target).total_seconds())
    
    if diff > 300: # 5분 = 300초 (계획서 기준)
        return jsonify({'status': 'error', 'message': f'퇴근 가능 시간이 아닙니다. (정해진 시간: {out_time_str} 전후 5분 이내 가능)'}), 400

    # [자동 승인] 정해진 시간에 퇴근한 것으로 기록
    # DB는 UTC로 저장하므로 현지 타임존을 강제 지정 후 UTC로 변환하여 저장
    target_out_utc = best_target.replace(tzinfo=tz).astimezone(timezone.utc).replace(tzinfo=None)
    att.check_out_at = target_out_utc
    duration = att.check_out_at - att.check_in_at
    att.total_minutes = max(0, int(duration.total_seconds() / 60))
    att.status = 'completed'
    db.session.commit()
    
    return jsonify({'status': 'success', 'message': f'퇴근 처리되었습니다. (기록시간: {out_time_str})'})

@attendance_bp.route('/api/<slug>/attendance/pending', methods=['GET'])
@login_required
def api_get_pending_attendance(slug):
    if session.get('role') not in ['admin', 'owner']: return jsonify({'error': 'Forbidden'}), 403
    
    pending_list = Attendance.query.filter(Attendance.store_id==slug, Attendance.status.in_(['pending_in', 'pending_out'])).all()
    data = []
    for att in pending_list:
        data.append({
            'id': att.id,
            'user_name': att.user.full_name or att.user.username,
            'type': '출근' if att.status == 'pending_in' else '퇴근',
            'time': att.check_in_at.strftime('%H:%M') if att.status == 'pending_in' else (att.check_out_at.strftime('%H:%M') if att.check_out_at else '-')
        })
    return jsonify(data)

@attendance_bp.route('/api/<slug>/attendance/bulk-approve', methods=['POST'])
@login_required
def api_bulk_approve_attendance(slug):
    if session.get('role') not in ['admin', 'owner']: return jsonify({'error': 'Forbidden'}), 403
    
    data = request.json
    pin = data.get('pin')
    selected_ids = data.get('ids', []) # 사장님이 체크한 ID 리스트
    
    store = db.session.get(Store, slug)
    if not store or not check_password_hash(store.attendance_pin, pin):
        return jsonify({'status': 'error', 'message': '보안 코드가 일치하지 않습니다.'}), 400
    
    # 사장님이 선택한 ID들만 필터링하여 승인
    pending_list = Attendance.query.filter(Attendance.id.in_(selected_ids)).all()
    
    count = 0
    for att in pending_list:
        if att.status == 'pending_in':
            # [수정] 승인 시각(now) 대신 예정 출근 시각(scheduled_in) 기준으로 기록
            att.check_in_at = att.scheduled_in or att.check_in_at
            att.status = 'working'
            count += 1
        elif att.status == 'pending_out':
            # [수정] 승인 시각(now) 대신 예정 퇴근 시각(scheduled_out) 기준으로 기록
            att.check_out_at = att.scheduled_out or att.check_out_at
            diff = att.check_out_at - att.check_in_at
            att.total_minutes = max(0, int(diff.total_seconds() / 60))
            att.status = 'completed'
            count += 1
            
    db.session.commit()
    socketio.emit('attendance_approved', {'bulk': True}, room=slug)
    return jsonify({'status': 'success', 'count': count})

@attendance_bp.route('/api/<slug>/attendance/approve', methods=['POST'])
@login_required
def api_approve_attendance(slug):
    if session.get('role') not in ['admin', 'owner']: return jsonify({'error': 'Forbidden'}), 403
    
    data = request.json
    att_id = data.get('id')
    pin = data.get('pin')
    
    store = db.session.get(Store, slug)
    if not store or not check_password_hash(store.attendance_pin, pin):
        return jsonify({'status': 'error', 'message': '보안 코드가 일치하지 않습니다.'}), 400
        
    att = db.session.get(Attendance, att_id)
    if not att: return jsonify({'error': 'Not found'}), 404
    
    if att.status == 'pending_in':
        # [수정] 승인 시각 대신 예정 시각 기준으로 기록
        att.check_in_at = att.scheduled_in or att.check_in_at
        att.status = 'working'
    elif att.status == 'pending_out':
        att.check_out_at = att.scheduled_out or att.check_out_at
        diff = att.check_out_at - att.check_in_at
        att.total_minutes = max(0, int(diff.total_seconds() / 60))
        att.status = 'completed'
    
    db.session.commit()
    # 직원 화면 업데이트용 신호
    socketio.emit('attendance_approved', {'id': att_id, 'user_id': att.user_id}, room=slug)
    return jsonify({'status': 'success'})

@attendance_bp.route('/api/<slug>/attendance/update-pin', methods=['POST'])
@login_required
def api_update_attendance_pin(slug):
    if session.get('role') not in ['admin', 'owner']: return jsonify({'error': 'Forbidden'}), 403
    
    data = request.json
    old_pin = data.get('old_pin')
    new_pin = data.get('new_pin')
    
    store = db.session.get(Store, slug)
    if not store: return jsonify({'error': 'Not found'}), 404
    
    # [수정] 현재 PIN 해시 보안 비교
    if not check_password_hash(store.attendance_pin, old_pin):
        return jsonify({'status': 'error', 'message': '현재 보안 코드가 일치하지 않아 변경할 수 없습니다.'}), 400
        
    if not new_pin or len(new_pin) != 4 or not new_pin.isdigit():
        return jsonify({'status': 'error', 'message': '새 보안 코드는 4자리 숫자여야 합니다.'}), 400
        
    # [수정] 새 PIN을 bcrypt 해시로 저장
    store.attendance_pin = generate_password_hash(new_pin)
    db.session.commit()
    return jsonify({'status': 'success'})

@attendance_bp.route('/api/<slug>/attendance/staff-status')
@login_required
def api_get_attendance_status(slug):
    user_id = session.get('user_id')
    user = db.session.get(User, user_id)
    # [권한 체크] 현장 근로자(worker)만 이 화면 사용 가능
    if user.role != 'worker':
        return jsonify({'status': 'forbidden', 'message': '현장 근로자 계정 전용 기능입니다.'})

    att = Attendance.query.filter(Attendance.user_id==user_id, Attendance.store_id==slug, Attendance.status.in_(['working', 'pending_in', 'pending_out'])).first()
    
    # [급여 산출] 이번 달 1일부터 현재까지 정산된 금액
    now = datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total_mins = db.session.query(func.sum(Attendance.total_minutes))\
        .filter(Attendance.user_id == user_id, Attendance.store_id == slug, Attendance.check_in_at >= start_of_month)\
        .scalar() or 0
    current_wage = int((total_mins / 60) * (user.hourly_rate or 0))

    return jsonify({
        'status': att.status if att else 'none',
        'is_working': (att and att.status == 'working'),
        'current_wage': current_wage,
        'check_in_at': att.check_in_at.isoformat() if (att and att.check_in_at) else None
    })

@attendance_bp.route('/<slug>/attendance')
@login_required
def staff_attendance_view(slug):
    # 영업 파트너(staff)가 접근할 경우 리다이렉트 처리
    if session.get('role') == 'staff':
        flash("영업 파트너는 근로시간 정산 대상이 아닙니다.")
        return redirect(url_for('admin_dashboard'))
    store = db.session.get(Store, slug)
    return render_template('staff_attendance.html', store=store)

@attendance_bp.route('/admin/staff')
@login_required
def admin_staff_mgmt():
    user_id = session.get('user_id')
    role = session.get('role')
    user_store_id = session.get('store_id')
    
    if role not in ['admin', 'owner', 'manager']:
        return render_template('access_denied.html')

    # [임금 수정 권한] 오직 어드민과 사장님(owner)만 시급 수정 가능
    can_edit_wage = (role in ['admin', 'owner'])

    if role == 'admin':
        stores = Store.query.all()
        selected_slug = request.args.get('slug') or (stores[0].id if stores else None)
    else:
        selected_slug = user_store_id
        stores = Store.query.filter_by(id=selected_slug).all()

    store = db.session.get(Store, selected_slug) if selected_slug else None
    
    # [기간 설정] 기본값: 이번 달 1일부터 오늘까지
    from zoneinfo import ZoneInfo
    try:
        tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
    except Exception:
        tz = ZoneInfo('Asia/Seoul')

    now = datetime.now(tz)
    start_str = request.args.get('start_date') or now.replace(day=1).strftime('%Y-%m-%d')
    end_str = request.args.get('end_date') or now.strftime('%Y-%m-%d')

    # KST/현지 기준으로 받은 날짜를 UTC로 변환하여 DB 조회
    local_start = datetime.strptime(start_str, '%Y-%m-%d').replace(hour=0, minute=0, second=0, tzinfo=tz)
    local_end   = datetime.strptime(end_str,   '%Y-%m-%d').replace(hour=23, minute=59, second=59, tzinfo=tz)

    start_dt = local_start.astimezone(timezone.utc).replace(tzinfo=None)
    end_dt   = local_end.astimezone(timezone.utc).replace(tzinfo=None)

    # 현장 근로자(worker) 정밀 리포트 (일자별 내역 포함)
    workers = User.query.filter_by(store_id=selected_slug, role='worker').all()
    worker_reports = []
    for w in workers:
        attendances = Attendance.query.filter(
            Attendance.user_id == w.id,
            Attendance.store_id == selected_slug,
            Attendance.check_in_at >= start_dt,
            Attendance.check_in_at <= end_dt,
            Attendance.status == 'completed'
        ).order_by(Attendance.check_in_at).all()

        total_mins = sum((a.total_minutes or 0) for a in attendances)
        wage = int((total_mins / 60) * (w.hourly_rate or 0))

        daily_details = []
        for att in attendances:
            if att.check_in_at:
                daily_details.append({
                    'date':  att.check_in_at.strftime('%m-%d'),
                    'start': att.check_in_at.strftime('%H:%M'),
                    'end':   att.check_out_at.strftime('%H:%M') if att.check_out_at else '-',
                    'mins':  att.total_minutes or 0
                })

        worker_reports.append({
            'user': w,
            'minutes': total_mins,
            'hours': round(total_mins / 60, 1),
            'expected_wage': wage,
            'details': daily_details
        })

    return render_template('admin/staff_mgmt.html', stores=stores, selected_slug=selected_slug,
                           worker_reports=worker_reports,
                           store=store, start_date=start_str, end_date=end_str, now=now,
                           can_edit_wage=can_edit_wage)


@attendance_bp.route('/api/staff/<int:user_id>/update', methods=['POST'])
@owner_only_required # 사장님 전용 권한 데코레이터 적용
def api_update_staff_wage(user_id):
    
    data = request.json
    user = db.session.get(User, user_id)
    if user:
        user.hourly_rate = data.get('hourly_rate', user.hourly_rate)
        user.position = data.get('position', user.position)
        user.role = data.get('role', user.role)
        user.phone = data.get('phone', user.phone)
        user.full_name = data.get('full_name', user.full_name) # 성명 변경도 가능하게 추가
        
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
    return jsonify({'error': 'User not found'}), 404

# ─── 월별 급여 집계 API ───
@attendance_bp.route('/api/<slug>/payroll/monthly')
@login_required
def api_monthly_payroll(slug):
    """월별 급여 집계 API (년/월 파라미터로 조회)"""
    if session.get('role') not in ['admin', 'owner', 'manager']:
        return jsonify({'error': 'Forbidden'}), 403

    year  = int(request.args.get('year',  datetime.utcnow().year))
    month = int(request.args.get('month', datetime.utcnow().month))

    from zoneinfo import ZoneInfo
    store = db.session.get(Store, slug)
    try:
        tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
    except Exception:
        tz = ZoneInfo('Asia/Seoul')

    # 해당 월 시작/끝 (현지 시간 → UTC)
    from datetime import timezone as utc_tz
    local_start = datetime(year, month, 1, 0, 0, 0, tzinfo=tz)
    if month == 12:
        local_end = datetime(year + 1, 1, 1, 0, 0, 0, tzinfo=tz) - timedelta(seconds=1)
    else:
        local_end = datetime(year, month + 1, 1, 0, 0, 0, tzinfo=tz) - timedelta(seconds=1)

    start_utc = local_start.astimezone(utc_tz.utc).replace(tzinfo=None)
    end_utc   = local_end.astimezone(utc_tz.utc).replace(tzinfo=None)

    workers = User.query.filter_by(store_id=slug, role='worker').all()
    result = []

    for w in workers:
        attendances = Attendance.query.filter(
            Attendance.user_id == w.id,
            Attendance.store_id == slug,
            Attendance.check_in_at >= start_utc,
            Attendance.check_in_at <= end_utc,
            Attendance.status == 'completed'
        ).order_by(Attendance.check_in_at).all()

        total_mins = sum((a.total_minutes or 0) for a in attendances)
        wage = int((total_mins / 60) * (w.hourly_rate or 0))

        daily = []
        for a in attendances:
            daily.append({
                'date':  a.check_in_at.strftime('%m-%d'),
                'in':    a.check_in_at.strftime('%H:%M'),
                'out':   a.check_out_at.strftime('%H:%M') if a.check_out_at else '-',
                'mins':  a.total_minutes or 0,
                'hours': round((a.total_minutes or 0) / 60, 2)
            })

        result.append({
            'user_id':       w.id,
            'full_name':     w.full_name or w.username,
            'position':      w.position or '',
            'phone':         w.phone or '',
            'bank_name':     w.bank_name or '',
            'account_no':    w.account_no or '',
            'hourly_rate':   w.hourly_rate or 0,
            'total_minutes': total_mins,
            'total_hours':   round(total_mins / 60, 2),
            'total_wage':    wage,
            'daily_records': daily
        })

    return jsonify({
        'year': year, 'month': month,
        'store_name': store.name if store else slug,
        'staff': result
    })

# ─── 급여명세서 인쇄 페이지 ───
@attendance_bp.route('/admin/payslip/<slug>/<int:year>/<int:month>')
@login_required
def admin_payslip_print(slug, year, month):
    """월별 급여명세서 인쇄 전용 페이지"""
    if session.get('role') not in ['admin', 'owner', 'manager']:
        return render_template('access_denied.html'), 403
    store = db.session.get(Store, slug)
    if not store:
        return "매장 정보를 찾을 수 없습니다.", 404
    return render_template('admin/payslip_print.html', store=store, year=year, month=month, slug=slug)

# ─── 주민번호 암호화 저장 API ───
@attendance_bp.route('/api/staff/<int:user_id>/id-number', methods=['POST'])
@login_required
def api_save_id_number(user_id):
    """직원 주민번호 앞 7자리를 암호화하여 저장합니다. (개인정보보호법 제24조 준수)"""
    if session.get('role') not in ['admin', 'owner']:
        return jsonify({'error': 'Forbidden'}), 403

    data = request.json
    raw = data.get('id_number', '').replace('-', '').strip()

    # 입력 검증: 6자리(생년월일) + 1자리(성별) = 7자리만 허용
    if not raw or len(raw) < 7 or not raw[:7].isdigit():
        return jsonify({'status': 'error', 'message': '주민번호 앞 7자리(생년월일+성별코드)를 올바르게 입력해 주세요.'}), 400

    masked = raw[:7]  # 7자리만 저장

    from MQutils.crypto import crypto
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    user.id_number_enc = crypto.encrypt(masked)
    db.session.commit()
    print(f"🔐 [ID-Enc] 직원 {user.full_name or user.username}의 주민번호 앞 7자리 암호화 저장 완료")
    return jsonify({'status': 'success', 'masked': f"{masked[:6]}-{masked[6]}******"})

# ─── 주민번호 조회 API (복호화) ───
@attendance_bp.route('/api/staff/<int:user_id>/id-number', methods=['GET'])
@login_required
def api_get_id_number(user_id):
    """암호화된 주민번호 앞 7자리를 복호화하여 마스킹된 형태로 반환합니다."""
    if session.get('role') not in ['admin', 'owner']:
        return jsonify({'error': 'Forbidden'}), 403

    from MQutils.crypto import crypto
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404

    if not user.id_number_enc:
        return jsonify({'status': 'none', 'masked': '미등록'})

    plain = crypto.decrypt(user.id_number_enc)
    masked = f"{plain[:6]}-{plain[6]}******" if plain and len(plain) >= 7 else '복호화 오류'
    return jsonify({'status': 'ok', 'masked': masked})

# ─── 급여 정산 뷰 ───
@attendance_bp.route('/admin/payroll')
@login_required
def admin_payroll_view():
    user_id = session.get('user_id')
    role = session.get('role')
    store_id = session.get('store_id')

    if role not in ['admin', 'owner', 'manager']:
        return render_template('access_denied.html'), 403

    store = db.session.get(Store, store_id)
    if not store:
        return redirect(url_for('index'))

    now = datetime.utcnow()
    start_of_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    workers = User.query.filter_by(store_id=store_id, role='worker').all()
    staff_list = []

    for w in workers:
        total_mins = db.session.query(func.sum(Attendance.total_minutes))\
            .filter(Attendance.user_id == w.id, Attendance.store_id == store_id,
                    Attendance.check_in_at >= start_of_month).scalar() or 0
        wage = int((total_mins / 60) * (w.hourly_rate or 0))
        staff_list.append({
            'id': w.id,
            'full_name': w.full_name or w.username,
            'bank_name': w.bank_name,
            'account_no': w.account_no,
            'current_wage': wage
        })

    return render_template('admin/payroll.html', store=store, staff_list=staff_list,
                           year=now.year, month=now.month)

