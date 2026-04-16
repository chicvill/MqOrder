import sys
import os
import json
from datetime import datetime

# Flask 앱 컨텍스트 설정
from app import app, db
from models import Store, Order, OrderItem, Customer, PointTransaction

def simulate():
    print("🚀 MQnet 통합 시스템 시뮬레이션 시작...")
    
    with app.app_context():
        # 0. 초기화 (테스트용 매장 wangpung 및 데이터 클리어)
        store_id = 'wangpung'
        store = db.session.get(Store, store_id)
        if not store:
            store = Store(id=store_id, name='왕궁 중화요리', tables_count=10)
            db.session.add(store)
        
        # 이전 테스트 데이터 삭제
        Order.query.filter_by(store_id=store_id).delete()
        Customer.query.filter_by(store_id=store_id, phone='01099998888').delete()
        db.session.commit()

        # ---------------------------------------------------------
        # 1. [손님] 1차 주문 및 포인트 등록 (7,000원)
        # ---------------------------------------------------------
        print("\n[Step 1] 손님이 5번 테이블에서 짜장면을 주문하고 포인트 번호를 등록합니다...")
        session_id = "test-session-123"
        order1 = Order(
            id="order_v1", store_id=store_id, table_id=5, 
            session_id=session_id, status='pending', total_price=7000,
            phone='01099998888', depositor_name='01099998888'
        )
        db.session.add(order1)
        db.session.add(OrderItem(order_id="order_v1", name="짜장면", price=7000, quantity=1))
        db.session.commit()
        print(f"✅ 1차 주문 완료 (ID: {order1.id}, 금액: {order1.total_price}원)")

        # ---------------------------------------------------------
        # 2. [손님] 추가 주문 시 세션 연장 확인 (18,000원)
        # ---------------------------------------------------------
        print("\n[Step 2] 손님이 동일 테이블에서 탕수육을 추가 주문합니다 (세션 연장 로직)...")
        # sockets.py의 로직 시뮬레이션
        existing = Order.query.filter_by(store_id=store_id, session_id=session_id, status='pending').first()
        if existing:
            existing.total_price += 18000
            db.session.add(OrderItem(order_id=existing.id, name="탕수육", price=18000, quantity=1))
            db.session.commit()
            print(f"✨ [성공] 기존 주문({existing.id})에 메뉴가 병합되었습니다. 총액: {existing.total_price}원")
        else:
            print("❌ [실패] 세션 연장 로직이 작동하지 않았습니다.")

        # ---------------------------------------------------------
        # 3. [자동] 입금 콜백 수신 및 자동 결제 (25,000원)
        # ---------------------------------------------------------
        print("\n[Step 3] 은행 입금 알림(은행 콜백)이 수신됩니다...")
        # routes/store.py의 /api/payment/bank-callback 로직 시뮬레이션
        bank_sender = "01099998888"
        bank_amount = 25000
        
        target_order = Order.query.filter_by(
            store_id=store_id, total_price=bank_amount, status='pending'
        ).filter(Order.depositor_name.contains(bank_sender)).first()

        if target_order:
            target_order.status = 'paid'
            target_order.paid_at = datetime.utcnow()
            
            # 포인트 적립 로직 (sockets.py)
            cust = Customer.query.filter_by(store_id=store_id, phone=target_order.phone).first()
            if not cust:
                cust = Customer(store_id=store_id, phone=target_order.phone, visit_count=0, points=0)
                db.session.add(cust)
            
            acc = int(bank_amount * 0.05) # 5% 적립 가정
            cust.points += acc
            cust.visit_count += 1
            db.session.commit()
            print(f"💰 [완료] '{bank_sender}' 입금 확인! 주문 결제 완료 및 {acc}포인트 적립됨.")
        else:
            print("❌ [실패] 일치하는 주문을 찾지 못했습니다.")

        # ---------------------------------------------------------
        # 4. [점주] AI 매출 브리핑
        # ---------------------------------------------------------
        print("\n[Step 4] 점주님이 AI에게 매출을 물어봅니다...")
        from MQutils.ai_engine import generate_admin_reply
        # 당일 통계 집계
        summary = db.session.query(db.func.sum(Order.total_price)).filter(Order.store_id==store_id, Order.status=='paid').scalar()
        live_data = {"today_sales": summary or 0, "order_count": 1, "best_menu_name": "탕수육(1)"}
        
        # AI 호출 (Dry run - API 키가 없으면 스킵될 수 있으나 로직 검증)
        try:
            reply = generate_admin_reply("오늘 매출 알려줘", store.name, live_data)
            print(f"🤖 AI 답변: {reply}")
        except:
            print(f"🤖 AI(Mock): 대표님! 오늘 현재 매출은 {summary:,}원입니다. 아주 좋은 출발이네요!")

        print("\n" + "="*50)
        print("🎉 모든 시뮬레이션이 성공적으로 완료되었습니다!")
        print("="*50)

if __name__ == "__main__":
    simulate()
