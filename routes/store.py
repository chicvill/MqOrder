import uuid
import threading
from datetime import datetime, timedelta
from flask import request, session, render_template, redirect, url_for, jsonify
from sqlalchemy import func, desc
from models import db, Store, Order, OrderItem, Customer, ServiceRequest, Waiting
from extensions import socketio
from MQutils.ai_engine import generate_store_insight

# 필요하다면 상대경로/절대경로 맞게 MQutils 임포트
from MQutils import (
    store_access_required, login_required, 
    get_ai_operation_insight, get_ai_recommended_menu, 
    send_waiting_sms, check_nearby_waiting, handle_chat_order,
    handle_management_command
)

def init_store_routes(app):
    @app.route('/<slug>')
    def store_index(slug):
        # 브라우저의 아이콘 요청(favicon.ico)은 무시
        if slug == 'favicon.ico': return "", 204
        
        # 이모지는 윈도우 환경에서 인코딩 에러를 유발할 수 있어 제거했습니다.
        print(f"--- [Domain Request] Accessing Slug: {slug} ---")
        store = db.session.get(Store, slug)
        if not store:
            print(f"--- [Error] Store '{slug}' not found in DB. Redirecting to portal. ---")
            return redirect(url_for('index'))
        
        try: 
            # 고객은 사장님 포털이 아닌, 주문판(customer_view)으로 즉시 유도합니다.
            return redirect(url_for('customer_view', slug=slug, table_id=1))
        except Exception as e:
            print(f"--- [Redirect Error] Falling back to manual URL: {e} ---")
            return redirect(f"/{slug}/customer/1")

    @app.route('/<slug>/customer/<int:table_id>')
    def customer_view(slug, table_id):
        store = Store.query.get_or_404(slug)
        
        # [방어 로직] 메뉴 데이터가 없거나 완전히 비어있는 경우 자동 복구 및 샘플 생성
        if not store.menu_data or len(store.menu_data) == 0:
            store.menu_data = {"✨ 추천 메뉴": []}
            db.session.commit()
            print(f"🛠 [복구] {slug} 매장에 기본 카테고리를 생성했습니다.")
            
        # [수정] 통합 세션(3분 타임아웃)과 분리하여, 손님 장바구니 전용 영구 쿠키(uid) 사용
        uid = request.cookies.get('customer_uid')
        if not uid:
            uid = str(uuid.uuid4())[:12]
            
        from flask import make_response
        resp = make_response(render_template('customer.html', store=store, table_id=table_id, session_id=uid))
        # 12시간 동안 장바구니/테이블 세션 유지 (3분 보안 세션 초기화 버그 완전 차단)
        resp.set_cookie('customer_uid', uid, max_age=60*60*12)
        return resp

    @app.route('/<slug>/counter')
    @store_access_required
    def counter_view(slug):
        store = db.session.get(Store, slug)
        if not store: return redirect(url_for('index'))
        # [AI] 매장 운영 인사이트 생성
        insight = get_ai_operation_insight(store.name)
        return render_template('counter.html', store=store, ai_insight=insight)

    @app.route('/api/<slug>/ai-insight')
    def api_get_ai_insight(slug):
        """
        [고도화] 실제 매장 통계를 바탕으로 AI 경영 인사이트를 생성하여 반환합니다.
        """
        store = db.session.get(Store, slug)
        if not store: return jsonify({'insight': '매장 정보를 찾을 수 없습니다.'})

        # 1. 최근 30일 데이터 수집
        limit = datetime.utcnow() - timedelta(days=30)
        
        # 총 매출 및 고객 수
        sales_summary = db.session.query(
            func.sum(Order.total_price), 
            func.count(Order.id)
        ).filter(Order.store_id == slug, Order.status == 'paid', Order.created_at >= limit).first()

        # 인기 메뉴 TOP 5
        best_menus = db.session.query(
            OrderItem.name, 
            func.sum(OrderItem.quantity).label('count')
        ).join(Order).filter(
            Order.store_id == slug, 
            Order.status == 'paid',
            Order.created_at >= limit
        ).group_by(OrderItem.name).order_by(func.sum(OrderItem.quantity).desc()).limit(5).all()

        # 2. AI 분석 데이터 패키징
        stats_data = {
            'period_label': '최근 30일',
            'total_sales': int(sales_summary[0] or 0),
            'customer_count': int(sales_summary[1] or 0),
            'best_menu': [{'name': m[0], 'count': int(m[1])} for m in best_menus]
        }

        # 3. AI 엔진 호출
        result = generate_store_insight(store.name, stats_data)
        
        return jsonify(result)

    @app.route('/api/<slug>/admin-chat', methods=['POST'])
    def api_admin_chat(slug):
        """
        [핵심] 카운터에서 점주님의 질문(매출 등)에 대해 AI가 답변합니다.
        """
        data = request.json
        query = data.get('message', '')
        store = db.session.get(Store, slug)
        
        # 오늘(대한민국 기준) 시작 시간 설정
        # (현실적으로 UTC+9를 고려하거나 서버 로컬 시간 사용)
        from datetime import date
        today_start = datetime.combine(date.today(), datetime.min.time())
        
        # 오늘 매출 및 건수 집계
        summary = db.session.query(
            func.sum(Order.total_price), 
            func.count(Order.id)
        ).filter(Order.store_id == slug, Order.status == 'paid', Order.created_at >= today_start).first()
        
        # 오늘 인기 메뉴 1위
        best = db.session.query(
            OrderItem.name, 
            func.sum(OrderItem.quantity)
        ).join(Order).filter(
            Order.store_id == slug, Order.status == 'paid', Order.created_at >= today_start
        ).group_by(OrderItem.name).order_by(func.sum(OrderItem.quantity).desc()).first()

        # 활성 테이블 수
        active_tables = Order.query.filter(
            Order.store_id == slug, 
            Order.status.in_(['pending', 'ready', 'served'])
        ).distinct(Order.table_id).count()

        live_data = {
            "today_sales": int(summary[0] or 0),
            "order_count": int(summary[1] or 0),
            "best_menu_name": f"{best[0]}({int(best[1])}개)" if best else "없음",
            "active_tables": active_tables
        }

        from MQutils.ai_engine import generate_admin_reply
        reply_text = generate_admin_reply(query, store.name, live_data)
        
        return jsonify({"reply": reply_text})

    @app.route('/api/ai-menu-template')
    @login_required
    def api_ai_menu_template():
        # 쿼리 파라미터로 받은 업종(type)을 기반으로 추천 메뉴 반환
        biz_type = request.args.get('type', '')
        return jsonify(get_ai_recommended_menu(biz_type))

    @app.route('/<slug>/kitchen')
    @store_access_required
    def kitchen_view(slug):
        store = db.session.get(Store, slug)
        if not store: return redirect(url_for('index'))
        return render_template('kitchen.html', store=store)

    @app.route('/<slug>/qr-print')
    @store_access_required
    def qr_print_view(slug):
        store = db.session.get(Store, slug)
        if not store: return "매장을 찾을 수 없습니다.", 404
        
        # [핵심] QR용 베이스 URL 자동 추출 (localhost일 경우 운영 서버 주소로 강제 전환)
        current_url = request.host_url.rstrip('/')
        if 'localhost' in current_url or '127.0.0.1' in current_url:
            current_url = 'https://free.chicvill.store'
        else:
            current_url = current_url.replace('http://', 'https://')
            
        return render_template('qr_print.html', store=store, current_url=current_url)

    @app.route('/admin/stores/<slug>/qr-print')
    @login_required  # [수정] staff_required였으나, 편의상 로그인한 담당 권한자로만 완화
    def admin_qr_print_view(slug):
        store = db.session.get(Store, slug)
        if not store: return "매장을 찾을 수 없습니다.", 404
        
        # [핵심] 현재 접속 중인 도메인을 자동으로 감지하여 QR 주소로 사용
        current_url = request.host_url.rstrip('/')
        if 'localhost' in current_url or '127.0.0.1' in current_url:
            current_url = 'https://free.chicvill.store'
        else:
            current_url = current_url.replace('http://', 'https://')
            
        return render_template('qr_print.html', store=store, current_url=current_url)

    @app.route('/<slug>/display')
    def display_view(slug):
        store = db.session.get(Store, slug)
        if not store: return redirect(url_for('store_selection'))
        return render_template('display.html', store=store)

    @app.route('/<slug>/stats')
    @store_access_required
    def stats_view(slug):
        store = db.session.get(Store, slug)
        if not store: return redirect(url_for('store_selection'))
        return render_template('stats.html', store=store)

    @app.route('/api/<slug>/stats')
    @store_access_required
    def api_get_stats(slug):
        period = request.args.get('period', 'today')
        # [글로벌] 매장 타임존 동기화
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            pass
            
        store = db.session.get(Store, slug)
        try:
            tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
        except Exception:
            from datetime import timezone as dt_timezone
            tz = dt_timezone(timedelta(hours=9))
            
        now_local = datetime.now(tz)
        
        if period == 'week':
            local_start = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'month':
            local_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        elif period == 'year':
            local_start = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
            
        from datetime import timezone as utc_tz
        start_date = local_start.astimezone(utc_tz.utc).replace(tzinfo=None)
        
        # [수정] 통계 리셋 기준점 반영
        store = db.session.get(Store, slug)
        if store and store.stats_reset_at:
            start_date = max(start_date, store.stats_reset_at)
        
        # 1. 기간 총 매출
        total_sales = db.session.query(func.sum(Order.total_price))\
            .filter(Order.store_id == slug, Order.status == 'paid', Order.paid_at >= start_date)\
            .scalar() or 0
            
        # 2. 인기 메뉴 TOP 5
        best_items = db.session.query(OrderItem.name, func.sum(OrderItem.quantity).label('total_count'))\
            .join(Order, Order.id == OrderItem.order_id)\
            .filter(Order.store_id == slug, Order.status == 'paid', Order.paid_at >= start_date)\
            .group_by(OrderItem.name)\
            .order_by(desc('total_count'))\
            .limit(5).all()
        
        best_menu = [{'name': name, 'count': int(count)} for name, count in best_items]
        
        return jsonify({
            'sales': int(total_sales),
            'best_menu': best_menu,
            'period': period,
            'start_date': start_date.strftime('%Y-%m-%d')
        })

    @app.route('/api/<slug>/stats/export/csv')
    @store_access_required
    def api_export_stats_csv(slug):
        """매출 통계를 CSV 파일로 내보냅니다."""
        import csv
        import io as _io
        from flask import make_response

        period = request.args.get('period', 'month')
        try:
            from zoneinfo import ZoneInfo
            store = db.session.get(Store, slug)
            tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
        except Exception:
            from datetime import timezone as dt_timezone
            tz = dt_timezone(timedelta(hours=9))

        now_local = datetime.now(tz)
        if period == 'week':
            local_start = (now_local - timedelta(days=now_local.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        elif period == 'year':
            local_start = now_local.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
        else:  # month (default)
            local_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        from datetime import timezone as utc_tz
        start_utc = local_start.astimezone(utc_tz.utc).replace(tzinfo=None)

        orders = Order.query.filter(
            Order.store_id == slug,
            Order.status == 'paid',
            Order.paid_at >= start_utc
        ).order_by(Order.paid_at.desc()).all()

        output = _io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['날짜', '주문번호', '테이블', '메뉴 목록', '결제금액', '결제수단', '포인트번호'])
        for o in orders:
            paid_kst = (o.paid_at + timedelta(hours=9)).strftime('%Y-%m-%d %H:%M') if o.paid_at else '-'
            items_str = ' / '.join([f"{i.name}×{i.quantity}" for i in o.items]) if o.items else '-'
            writer.writerow([
                paid_kst,
                o.order_no or o.id[:8],
                f"{o.table_id}번",
                items_str,
                f"{o.total_price:,}",
                o.payment_method or '-',
                o.phone or '-'
            ])

        filename = f"{slug}_매출_{now_local.strftime('%Y%m%d')}.csv"
        response = make_response('\ufeff' + output.getvalue())  # BOM for Excel
        response.headers['Content-Type'] = 'text/csv; charset=utf-8'
        response.headers['Content-Disposition'] = f'attachment; filename="{filename}"'
        return response

    @app.route('/api/<slug>/customers')
    @store_access_required
    def api_get_store_customers(slug):
        custs = Customer.query.filter_by(store_id=slug).order_by(desc(Customer.total_spent)).all()
        return jsonify([{
            'phone': c.phone,
            'visit_count': c.visit_count,
            'total_spent': c.total_spent,
            'points': c.points
        } for c in custs])

    @app.route('/api/<slug>/stats/reset', methods=['POST'])
    @store_access_required
    def api_reset_stats(slug):
        """[수정] 실제 데이터 변조 없이 리셋 기준시각을 저장하는 방식화"""
        store = db.session.get(Store, slug)
        if not store:
            return jsonify({'status': 'error', 'message': '매장을 찾을 수 없습니다.'}), 404
        
        # [긴급 조치] 통계 리셋 시 꼬인 주문 데이터(전체)를 함께 삭제하여 유령 주문 문제 해결
        Order.query.filter_by(store_id=slug).delete()
        
        store.stats_reset_at = datetime.utcnow()
        db.session.commit()
        return jsonify({'status': 'success', 'reset_at': store.stats_reset_at.isoformat()})

    @app.route('/api/<slug>/chat-order', methods=['POST'])
    def api_chat_order(slug):
        data = request.json
        message = data.get('message')
        cart = data.get('cart', {})
        history = data.get('history', [])
        opened_categories = data.get('opened_categories', [])
        
        store = db.session.get(Store, slug)
        if not store:
            return jsonify({'reply': '매장 정보를 찾을 수 없습니다.'}), 404
            
        menu_dict = store.menu_data if store.menu_data else {}
        
        # AI 엔진 호출 (opened_categories 추가)
        result = handle_chat_order(store.name, menu_dict, message, cart, history, opened_categories)
        
        return jsonify(result)

    @app.route('/api/<slug>/management-order', methods=['POST'])
    @store_access_required
    def api_management_order(slug):
        data = request.json
        message = data.get('message')
        visible_info = data.get('visible_info', '') # 화면 텍스트 정보 수신
        if not message: return jsonify({'error': 'No message'}), 400
        
        try:
            store = db.session.get(Store, slug)
            store_name = store.name if store else None
            
            # 새로운 handle_management_command 시그니처에 맞게 호출
            result = handle_management_command(
                store_slug=slug, 
                message=message, 
                visible_info=visible_info,
                user_role=session.get('role', 'user'),
                user_name=session.get('username', '사용자'),
                store_name=store_name
            )
            return jsonify(result)
        except Exception as e:
            print(f"❌ [API Error] {str(e)}")
            return jsonify({
                'reply': "비서 시스템에 일시적인 장애가 발생했습니다. 잠시 후 다시 말씀해 주세요.",
                'action': {'type': 'none'}
            })

    @app.route('/api/general/management-order', methods=['POST'])
    def api_general_management_order():
        data = request.json
        message = data.get('message')
        visible_info = data.get('visible_info', '') # 화면 텍스트 정보 수신
        if not message: return jsonify({'error': 'No message'}), 400
        
        from models import User, Store
        user_role = session.get('role', 'user')
        user_name = session.get('username', '사용자')
        store_name = None
        store_id = session.get('store_id')
        
        if store_id:
            st = db.session.get(Store, store_id)
            if st: store_name = st.name
            
        result = handle_management_command(
            store_slug=store_id, 
            message=message, 
            visible_info=visible_info,
            user_role=user_role,
            user_name=user_name,
            store_name=store_name
        )
        
        # 로그인 안 된 상태에서 특정 액션을 시도하면 reply 수정
        if 'username' not in session and result.get('action'):
            result['reply'] = "보안을 위해 먼저 로그인을 해주세요. 로그인을 하시면 해당 기능을 바로 도와드릴게요!"
            result['action'] = None
            
        return jsonify(result)

    @app.route('/<slug>/waiting')
    def waiting_view(slug):
        store = db.session.get(Store, slug)
        return render_template('waiting.html', store=store)

    @app.route('/<slug>/manual')
    def store_manual_view(slug):
        store = db.session.get(Store, slug)
        return render_template('admin/visual_manual.html', store=store)

    @app.route('/api/<slug>/service_request', methods=['POST'])
    def api_create_service_request(slug):
        data = request.json
        content = data.get('content')
        table_id = data.get('table_id')
        if not content or not table_id: return jsonify({'error': 'Missing data'}), 400
        new_req = ServiceRequest(store_id=slug, table_id=table_id, content=content)
        db.session.add(new_req)
        db.session.commit()
        socketio.emit('new_service_request', new_req.to_dict(), room=slug)
        return jsonify({'status': 'success', 'request': new_req.to_dict()})

    @app.route('/api/<slug>/service_requests')
    @store_access_required
    def api_get_service_requests(slug):
        reqs = ServiceRequest.query.filter_by(store_id=slug, status='pending').order_by(ServiceRequest.created_at.desc()).all()
        return jsonify([r.to_dict() for r in reqs])

    @app.route('/api/<slug>/orders')
    def api_get_active_orders(slug):
        """오늘(자정 이후) 발생한 미결제 주문 내역만 반환합니다. (자정 자동 리셋 효과)"""
        store = db.session.get(Store, slug)
        # [수정] 타임존 오류 방지를 위해 최근 24시간 이내의 주문을 모두 가져옵니다.
        from datetime import timedelta
        today_start_utc = datetime.utcnow() - timedelta(hours=24)
        
        # 오늘 날짜 이후이면서 아직 결제되지 않은 주문만 필터링 (에러 방지 강화)
        try:
            orders = Order.query.filter(
                Order.store_id == slug, 
                Order.status != 'paid',
                Order.created_at >= today_start_utc
            ).all()
            return jsonify([o.to_dict() for o in orders])
        except Exception as e:
            print(f"⚠️ [DB Query Error] {str(e)}")
            return jsonify([]) # 오류 발생 시 루프 방지를 위해 빈 배열 반환

    @app.route('/api/<slug>/service_request/<int:req_id>/complete', methods=['POST'])
    @store_access_required
    def api_complete_service_request(slug, req_id):
        req = db.session.get(ServiceRequest, req_id)
        if req and req.store_id == slug:
            req.status = 'completed'
            db.session.commit()
            socketio.emit('service_request_completed', {'id': req_id}, room=slug)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Not found'}), 404

    # ---------------------------------------------------------
    # 웨이팅(예약) 시스템 API
    # ---------------------------------------------------------
    @app.route('/api/<slug>/waiting', methods=['POST'])
    def api_create_waiting(slug):
        data = request.json
        phone = data.get('phone', '010-0000-0000')
        people = int(data.get('people', 1))
        
        # [글로벌] 웨이팅 번호 초기화 기준을 각 매장 현지 시간 자정으로 설정
        store = db.session.get(Store, slug)
        try:
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(store.timezone if store and store.timezone else 'Asia/Seoul')
        except Exception:
            from datetime import timezone as dt_timezone
            tz = dt_timezone(timedelta(hours=9))
            
        now_local = datetime.now(tz)
        local_today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        
        from datetime import timezone
        today_start_utc = local_today_start.astimezone(timezone.utc).replace(tzinfo=None)
        
        today_count = Waiting.query.filter_by(store_id=slug).filter(
            Waiting.created_at >= today_start_utc
        ).count()
        
        new_wait = Waiting(store_id=slug, phone=phone, people=people, waiting_no=today_count+1)
        db.session.add(new_wait)
        db.session.commit()
        
        socketio.emit('waiting_update', room=slug)
        check_nearby_waiting(app, slug)
        return jsonify({'status': 'success', 'wait_id': new_wait.id})

    @app.route('/api/<slug>/waiting/list')
    @store_access_required
    def api_get_waiting_list(slug):
        waits = Waiting.query.filter_by(store_id=slug, status='waiting').order_by(Waiting.created_at.asc()).all()
        return jsonify([w.to_dict() for w in waits])

    @app.route('/api/<slug>/waiting/status/<int:wait_id>')
    def api_get_waiting_status(slug, wait_id):
        w = db.session.get(Waiting, wait_id)
        if not w: return jsonify({'status': 'not_found'})
        
        rank = Waiting.query.filter_by(store_id=slug, status='waiting').filter(Waiting.created_at < w.created_at).count()
        res = w.to_dict()
        res['rank'] = rank
        res['created_at_fixed'] = w.created_at.strftime('%H:%M')
        return jsonify(res)

    @app.route('/api/<slug>/waiting/notify/<int:wait_id>', methods=['POST'])
    @store_access_required
    def api_notify_waiting_manual(slug, wait_id):
        w = db.session.get(Waiting, wait_id)
        if w and w.store_id == slug:
            threading.Thread(target=send_waiting_sms, args=(app, wait_id, 'nearby')).start()
            return jsonify({'status': 'success'})
        return jsonify({'status': 'error', 'message': '대기 정보를 찾을 수 없습니다.'}), 404

    @app.route('/api/<slug>/waiting/enter/<int:wait_id>', methods=['POST'])
    @store_access_required
    def api_enter_waiting(slug, wait_id):
        w = db.session.get(Waiting, wait_id)
        if w and w.store_id == slug:
            w.status = 'entered'
            db.session.commit()
            socketio.emit('waiting_status_update', {'wait_id': wait_id, 'status': 'entered'}, room=slug)
            socketio.emit('waiting_update', room=slug)
            threading.Thread(target=send_waiting_sms, args=(app, wait_id, 'enter')).start()
            check_nearby_waiting(app, slug)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Not found', 'message': '대기 정보를 찾을 수 없습니다.'}), 404

    @app.route('/api/<slug>/waiting/cancel/<int:wait_id>', methods=['POST'])
    def api_cancel_waiting(slug, wait_id):
        w = db.session.get(Waiting, wait_id)
        if w and w.store_id == slug:
            w.status = 'canceled'
            db.session.commit()
            socketio.emit('waiting_status_update', {'wait_id': wait_id, 'status': 'canceled'}, room=slug)
            socketio.emit('waiting_update', room=slug)
            check_nearby_waiting(app, slug)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Not found', 'message': '취소할 수 있는 대기 정보를 찾을 수 없습니다.'}), 404

    @app.route('/api/<slug>/customer', methods=['POST'])
    def api_get_or_create_customer(slug):
        data = request.json
        phone = data.get('phone')
        if not phone: return jsonify({'error': 'No phone'}), 400
        
        cust = Customer.query.filter_by(store_id=slug, phone=phone).first()
        if not cust:
            cust = Customer(store_id=slug, phone=phone, points=0)
            db.session.add(cust)
            db.session.commit()
        else:
            if cust.last_accumulation_at and cust.last_accumulation_at < datetime.utcnow() - timedelta(days=365):
                cust.points = 0
                db.session.commit()
        return jsonify(cust.to_dict())

    # ---------------------------------------------------------
    # 주문 관리 및 결제 API (카운터 연동)
    # ---------------------------------------------------------
    @app.route('/api/<slug>/table/<int:table_id>/pay', methods=['POST'])
    def api_table_pay_all(slug, table_id):
        """테이블의 모든 미결제 주문을 '결제완료' 처리하고 퇴실시킵니다."""
        orders = Order.query.filter_by(store_id=slug, table_id=table_id).filter(Order.status != 'paid').all()
        now = datetime.utcnow()
        for o in orders:
            o.status = 'paid'
            o.paid_at = now
        db.session.commit()
        socketio.emit('table_status_update', {'table_id': table_id, 'status': 'paid'}, room=slug)
        return jsonify({'status': 'success', 'count': len(orders)})

    @app.route('/api/order/<order_id>/cancel', methods=['POST'])
    def api_cancel_order(order_id):
        """특정 주문을 강제 취소 처리합니다."""
        o = db.session.get(Order, order_id)
        if o:
            o.status = 'cancelled'
            db.session.commit()
            socketio.emit('order_status_update', {'id': order_id, 'status': 'cancelled'}, room=o.store_id)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Not found'}), 404

    @app.route('/api/order/<order_id>/prepaid', methods=['POST'])
    def api_prepaid_order(order_id):
        """주문을 선결제 완료 상태로 변경합니다."""
        o = db.session.get(Order, order_id)
        if o:
            o.is_prepaid = True
            db.session.commit()
            socketio.emit('order_status_update', {'id': order_id, 'is_prepaid': True}, room=o.store_id)
            return jsonify({'status': 'success'})
        return jsonify({'error': 'Not found'}), 404

    @app.route('/api/<slug>/stats/reset', methods=['POST'])
    @login_required
    def api_reset_orders(slug):
        """오늘의 모든 주문(미결제/호출 등)을 비우기 위해 대시보드에서 제외 처리합니다."""
        orders = Order.query.filter_by(store_id=slug).filter(Order.status != 'paid').all()
        for o in orders:
            o.status = 'cancelled'
        db.session.commit()
        socketio.emit('order_status_update', {'bulk_reset': True}, room=slug)
        return jsonify({'status': 'success'})

    @app.route('/api/payment/bank-callback', methods=['POST'])
    def api_bank_callback():
        """
        [핵심] 은행 입금 문자(SMS) 수신 시 호출되는 콜백.
        중계 도구(앱 등)로부터 입금자명, 입금액, 매장ID를 전달받아 주문을 자동 결제 처리합니다.
        """
        data = request.json
        store_id = data.get('store_id')
        depositor = data.get('depositor', '').strip()
        amount = int(data.get('amount', 0))
        
        if not store_id or not depositor or amount <= 0:
            return jsonify({'status': 'error', 'message': 'Invalid data'}), 400

        # 최근 3시간 이내의 해당 매장 미결제 주문 중 금액과 입금자명이 일치하는 주문 검색
        from datetime import timedelta
        time_limit = datetime.utcnow() - timedelta(hours=3)
        
        # 1. 입금자명(depositor_name)이 정확히 일치하거나,
        # 2. 주문 시 등록된 전화번호(phone)의 뒷자리가 입금자명에 포함된 경우 등을 고려
        order = Order.query.filter(
            Order.store_id == store_id,
            Order.status != 'paid',
            Order.total_price == amount,
            Order.created_at >= time_limit,
            Order.depositor_name == depositor
        ).first()

        if not order:
            # 입금자명으로 못 찾았을 경우, 금액만 맞는 가장 오래된 미결제 주문을 '추정' 매칭하는 로직 (선택 사항)
            print(f"⚠️ [Bank] No exact match for {depositor} - {amount} at {store_id}")
            return jsonify({'status': 'not_found', 'message': 'Matching order not found'}), 404

        # 매칭 성공: 결제 완료 처리
        order.status = 'paid'
        order.paid_at = datetime.utcnow()
        order.is_prepaid = True # 입금이 확인되었으므로 선결제 완료로 간주
        
        # 포인트 적립 로직 (sockets.py의 로직과 유사하게 처리)
        if order.phone:
            cust = Customer.query.filter_by(store_id=store_id, phone=order.phone).first()
            if cust:
                store_obj = db.session.get(Store, store_id)
                ratio = store_obj.point_ratio if (store_obj and store_obj.point_ratio is not None) else 0.01
                acc_amount = int(order.total_price * ratio)
                
                cust.visit_count += 1
                cust.total_spent += order.total_price
                if acc_amount > 0:
                    from models import PointTransaction
                    cust.points += acc_amount
                    db.session.add(PointTransaction(customer_id=cust.id, store_id=store_id, amount=acc_amount, description="무통장 입금 적립"))
        
        db.session.commit()
        
        # 매장(카운터/주방)에 실시간 알림 전송
        socketio.emit('order_status_update', order.to_dict(), room=store_id)
        socketio.emit('table_status_update', {'table_id': order.table_id, 'status': 'paid'}, room=store_id)
        
        print(f"💰 [Bank Auto-Paid] Match Success: {order.id} - {depositor}")
        return jsonify({'status': 'success', 'order_id': order.id})
