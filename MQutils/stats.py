from datetime import datetime
from sqlalchemy import func
# Circular import 방지를 위해 함수 내부에서 필요한 모델을 import 하거나 db를 인자로 받음

def calculate_commission(store, now=None):
    """매장별 수당 계산 (첫 달 무료, 2개월차부터 매출 인정 10%)"""
    if not now: now = datetime.utcnow()
    if store.payment_status != 'paid': return 0
    
    delta = now - store.created_at
    total_months = delta.days // 30
    # "첫달 무료, 다음달 입금 시 매출 0" -> 즉, 가입 2개월(60일) 후부터 수당 발생
    commissionable_months = max(0, total_months - 2) 
    return commissionable_months * (store.monthly_fee or 50000) * 0.1

def get_staff_performance(staff_list, Store, Order):
    """스태프 목록에 대한 실적 데이터 패키지 생성"""
    performance_data = []
    now = datetime.utcnow()
    
    for staff in staff_list:
        stores = Store.query.filter_by(recommended_by=staff.id).all()
        total_rev = 0
        for s in stores:
            if s.payment_status == 'paid':
                delta = now - s.created_at
                total_months = delta.days // 30
                commissionable_months = max(0, total_months - 2) 
                total_rev += (commissionable_months * (s.monthly_fee or 50000))
        
        performance_data.append({
            'staff_name': staff.username, 
            'id': staff.id, 
            'store_count': len(stores),
            'paid_count': len([s for s in stores if s.payment_status == 'paid']),
            'revenue': total_rev, 
            'commission': int(total_rev * 0.1), 
            'stores': stores
        })
    return performance_data
