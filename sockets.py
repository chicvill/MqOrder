import uuid
import random
from datetime import datetime, timedelta
from MQutils.payment import auto_issue_cash_receipt
from flask_socketio import join_room
from models import db, Order, OrderItem, Customer, PointTransaction, Store

def register_socketio_events(socketio):
    @socketio.on('join')
    def on_join(data):
        sid = data.get('store_id')
        if sid:
            join_room(sid)

    @socketio.on('place_order')
    def on_place_order(data):
        try:
            slug = data.get('store_id')
            items = data.get('items')
            table_id = data.get('table_id')
            session_id = data.get('session_id')
            total_price = data.get('total_price')
            phone = data.get('phone')
            depositor_name = data.get('depositor_name')

            # [보안] 0. 테이블 점유 확인 (장난 주문 및 타인 주문 방지)
            active_at_table = Order.query.filter_by(
                store_id=slug, 
                table_id=table_id, 
                status='pending' 
            ).filter(Order.status.in_(['pending', 'ready', 'served'])).first()

            if active_at_table and active_at_table.session_id != session_id:
                # 이미 다른 사람이 이용 중인 테이블인 경우
                print(f"🚨 [경고] 테이블 {table_id} 중복 주문 시도 차단 (기존:{active_at_table.session_id}, 신규:{session_id})")
                socketio.emit('order_failed', {
                    'message': '현재 다른 손님이 이용 중인 테이블입니다. 자리를 이동하셨다면 직원에게 문의해 주세요.'
                }, room=request.sid)
                return

            # [고도화] 동일 세션의 미결제 주문이 있는지 먼저 확인 (추가 주문 처리)
            existing_order = Order.query.filter_by(
                store_id=slug, 
                session_id=session_id, 
                status='pending' # 조리 중이거나 아직 결제 안 된 주문
            ).first()

            if not existing_order:
                # 조리 대기 중인 주문이 없더라도 'ready'(조리완료) 상태인 주문이 있다면 그쪽으로 합칠 수도 있음
                existing_order = Order.query.filter_by(
                    store_id=slug, session_id=session_id, table_id=table_id
                ).filter(Order.status.in_(['pending', 'ready', 'served'])).first()

            if existing_order:
                # 기존 주문에 아이템 추가
                order_id = existing_order.id
                order_no = existing_order.order_no
                existing_order.total_price += total_price
                print(f"➕ [추가 주문] {slug} 테이블 {table_id} - 기존 주문 {order_no}에 병합")
            else:
                # 신규 주문 생성
                order_id = str(uuid.uuid4())
                order_no = str(random.randint(1000, 9999))
                new_order = Order(
                    id=order_id, 
                    order_no=order_no, 
                    store_id=slug, 
                    table_id=table_id, 
                    session_id=session_id, 
                    total_price=total_price, 
                    phone=phone, 
                    depositor_name=depositor_name,
                    payment_method=data.get('payment_method'),
                    is_prepaid=data.get('is_prepaid', False),
                    cash_receipt_type=data.get('cash_receipt_type'),
                    cash_receipt_number=data.get('cash_receipt_number')
                )
                db.session.add(new_order)
            
            # 공통: 아이템 추가
            for item in items:
                m_id = item.get('id', 0)
                oi = OrderItem(order_id=order_id, menu_id=m_id, name=item['name'], price=item['price'], quantity=item['quantity'])
                db.session.add(oi)
            
            # [신규] 선결제(카드 등) 주문이면서 영수증 신청 정보가 있으면 자동 발급 (신규 주문일 때만 혹은 금액 합산 대비 필요)
            if data.get('is_prepaid') and data.get('cash_receipt_type'):
                from models import TaxInvoice
                # 기존 영수증이 있다면 업데이트, 없다면 생성 (여기선 단순화하여 추가분 발행 고려 가능)
                ti = TaxInvoice(order_id=order_id, store_id=slug, amount=total_price, status='issued')
                db.session.add(ti)
            
            db.session.commit()
            
            # UI 알림 처리
            current_order = existing_order if existing_order else new_order
            
            # 주문을 넣은 손님에게 성공 알림 전송
            from flask import request
            store_obj = db.session.get(Store, slug)
            socketio.emit('order_success', {
                'order_id': order_id,
                'order_no': order_no, 
                'total_price': current_order.total_price,
                'is_additional': True if existing_order else False,
                'store_name': store_obj.name if store_obj else slug
            }, room=request.sid)

            # 매장에 새 주문/업데이트 알림
            socketio.emit('new_order', current_order.to_dict(), room=slug)
        except Exception as e:
            db.session.rollback()
            err_msg = str(e)
            print(f"❌ [주문 처리 오류] {err_msg}")
            socketio.emit('order_error', {'message': f'주문 처리 중 서버 오류가 발생했습니다: {err_msg}'})

    @socketio.on('set_ready')
    def on_set_ready(data):
        try:
            oid = data.get('order_id')
            if not oid: return
            order = db.session.get(Order, oid)
            if order:
                order.status = 'ready'
                db.session.commit()
                # 매장 내 모든 관련 대시보드와 손님에게 상태 변경 알림
                socketio.emit('order_status_update', order.to_dict(), room=order.store_id)
                print(f"✅ [주방] 주문 {oid} 조리 완료 처리됨")
        except Exception as e:
            db.session.rollback()
            print(f"❌ [주방 오류] 조리 완료 처리 중 에러: {e}")

    @socketio.on('set_served')
    def on_set_served(data):
        sid = data.get('session_id')
        slug = data.get('store_id')
        # [개선] ready 뿐만 아니라 조리 중(pending)인 주문도 일괄 서빙 완료 처리 지원
        orders = Order.query.filter(Order.store_id == slug, Order.session_id == sid, Order.status.in_(['ready', 'pending'])).all()
        
        if not orders:
            # 이미 모든 주문이 served인 경우에도 UI 갱신 이벤트를 다시 쏘아줌
            fallback = Order.query.filter_by(store_id=slug, session_id=sid).first()
            if fallback:
                socketio.emit('table_status_update', {'store_id': slug, 'session_id': sid, 'table_id': fallback.table_id, 'status': 'served'}, room=slug)
            return

        tid = orders[0].table_id
        for o in orders:
            o.status = 'served'
        db.session.commit()
        socketio.emit('table_status_update', {'store_id': slug, 'session_id': sid, 'table_id': tid, 'status': 'served'}, room=slug)

    @socketio.on('set_paid')
    def on_set_paid(data):
        slug = data.get('store_id')
        sid = data.get('session_id')
        phone = data.get('phone')
        use_points = data.get('use_points', 0)
        
        orders = Order.query.filter_by(store_id=slug, session_id=sid, status='served').all()
        if not orders: return
        
        # 테이블 번호 추출
        tid = orders[0].table_id
        total_sum = sum(o.total_price for o in orders)
        
        if phone:
            cust = Customer.query.filter_by(store_id=slug, phone=phone).first()
            if cust:
                # Check Expiration (Final accumulation + 1 year)
                if cust.last_accumulation_at and cust.last_accumulation_at < datetime.utcnow() - timedelta(days=365):
                    cust.points = 0
                
                # Point Usage (Check >= 10,000 condition in UI, but enforce here)
                if use_points > 0 and cust.points >= 10000:
                    actual_use = min(cust.points, use_points)
                    cust.points -= actual_use
                    db.session.add(PointTransaction(customer_id=cust.id, store_id=slug, amount=-actual_use, description="포인트 사용 포인트 감면"))
                
                # [수정] 포인트 적립률 동적화 (사장님이 0으로 설정하면 적립 안 함, 초기 미설정 시 기본 1%)
                store_for_ratio = db.session.get(Store, slug)
                ratio = store_for_ratio.point_ratio if (store_for_ratio and store_for_ratio.point_ratio is not None) else 0.01
                acc_amount = int(total_sum * ratio)
                
                cust.visit_count += 1
                cust.total_spent += total_sum
                
                # [신규] 단골 우대 정책: 10회 방문 시 보너스 5,000점 지급
                is_anniversary = False
                if cust.visit_count % 10 == 0:
                    bonus = 5000
                    cust.points += bonus
                    db.session.add(PointTransaction(customer_id=cust.id, store_id=slug, amount=bonus, description=f"{cust.visit_count}회 방문 기념 단골 보너스"))
                    is_anniversary = True

                if acc_amount > 0:
                    cust.points += acc_amount
                    cust.last_accumulation_at = datetime.utcnow()
                    db.session.add(PointTransaction(customer_id=cust.id, store_id=slug, amount=acc_amount, description="식비 적립"))
                
                # 안내를 위한 정보 보관
                point_info = {
                    'acc_amount': acc_amount,
                    'total_points': cust.points,
                    'is_anniversary': is_anniversary
                }
                
                # 단골 방문 알림을 매장 대시보드로 전송
                if is_anniversary or cust.visit_count >= 5:
                    socketio.emit('vip_notice', {
                        'phone': phone[-4:], # 끝자리만 표시
                        'visit_count': cust.visit_count,
                        'is_anniversary': is_anniversary
                    }, room=slug)
        
        for o in orders:
            o.status = 'paid'
            o.paid_at = datetime.utcnow()
            
            # [신규] 무통장/현금 결제 시 영수증 신청 내역이 있으면 자동 발급 처리
            if o.payment_method in ['bank', 'cash', 'postpaid'] and o.cash_receipt_type:
                from models import TaxInvoice
                # 이미 발급된 영수증이 있는지 확인 (중복 발급 방지)
                existing = TaxInvoice.query.filter_by(order_id=o.id).first()
                if not existing:
                    ti = TaxInvoice(order_id=o.id, store_id=slug, amount=o.total_price, status='issued')
                    db.session.add(ti)
                    print(f"🧾 [자동발급] 주문 {o.id} 현금영수증 발행 완료")
        
        db.session.commit()
        
        # [고도화] 결제 완료 정보를 상세히 전송 (음성 안내용)
        socketio.emit('table_status_update', {
            'store_id': slug, 
            'session_id': sid, 
            'table_id': tid, 
            'status': 'paid',
            'total_price': total_sum,
            'point_info': point_info if 'point_info' in locals() else None
        }, room=slug)

        # [제안 반영] 고객 브라우저에 세션 종료(자동 로그아웃) 신호 전송
        socketio.emit('order_paid', {
            'session_id': sid,
            'message': '안녕히 가세요! 결제가 완료되어 세션이 종료되었습니다.'
        }, room=slug) # 매장 룸으로 보내면 해당 세션을 가진 브라우저가 반응함

        # [고도화] 현금영수증 신청이 있는 경우 즉시 자동 발행 (API 연동)
        for o in orders:
            if o.cash_receipt_type and o.payment_method in ['bank', 'cash', 'postpaid']:
                try:
                    # 1. 즉시 발행 API 호출
                    res = auto_issue_cash_receipt(o.total_price, o.cash_receipt_type, o.cash_receipt_number)
                    
                    if res['status'] == 'success':
                        # 2. TaxInvoice 레코드 생성 및 승인번호 저장
                        ti = TaxInvoice(
                            order_id=o.id, 
                            store_id=slug, 
                            amount=o.total_price, 
                            status='issued',
                            # 괄호 안에 승인번호 저장 (models.py에 컬럼이 없을 경우 비고란 활용 등)
                        )
                        # 임시로 order 테이블에도 메모 기록 (고객 확인용)
                        o.depositor_name = f"{o.depositor_name or ''} (현금영수증 승인:{res['confirm_no']})"
                        db.session.add(ti)
                        print(f"✅ [자동발행 성공] 주문 {o.id} 승인번호: {res['confirm_no']}")

                        # 3. 점주에게는 알림만 발송 (확인용)
                        store = db.session.get(Store, slug)
                        if store.business_email:
                            from MQutils.messenger import SolapiMessenger
                            messenger = SolapiMessenger()
                            messenger.send_tax_invoice_notice(store.business_email, store.name, o.total_price, {
                                "type": o.cash_receipt_type, "number": o.cash_receipt_number, "method": f"{o.payment_method} (자동발생완료)"
                            })
                except Exception as e:
                    print(f"⚠️ [자동발행 오류] {e}")

    @socketio.on('cancel_order')
    def on_cancel_order(data):
        try:
            oid = data.get('order_id')
            if not oid: return
            order = db.session.get(Order, oid)
            if order:
                order.status = 'cancelled'
                order.total_price = 0
                # 모든 아이템도 취소 처리
                for item in order.items:
                    item.status = 'cancelled'
                db.session.commit()
                # 상태 변경 알림 (동적으로 삭제되도록)
                socketio.emit('order_status_update', order.to_dict(), room=order.store_id)
                print(f"✅ [취소] 주문 {oid} 전체 취소됨")
        except Exception as e:
            db.session.rollback()
            print(f"❌ [취소 오류] 주문 취소 중 에러: {e}")

    @socketio.on('cancel_order_item')
    def on_cancel_order_item(data):
        try:
            item_id = data.get('item_id')
            if not item_id: return
            item = db.session.get(OrderItem, item_id)
            if item:
                order = item.order
                item.status = 'cancelled'
                
                # 주문 총액 재계산
                active_items = [i for i in order.items if i.status != 'cancelled']
                order.total_price = sum(i.price * i.quantity for i in active_items)
                
                # 만약 남은 아이템이 하나도 없으면 주문 자체를 취소 처리
                if not active_items:
                    order.status = 'cancelled'
                
                db.session.commit()
                socketio.emit('order_status_update', order.to_dict(), room=order.store_id)
                print(f"✅ [일부 취소] 아이템 {item_id} 취소됨, 주문 {order.id} 총액 갱신")
        except Exception as e:
            db.session.rollback()
            print(f"❌ [일부 취소 오류] 아이템 취소 중 에러: {e}")
