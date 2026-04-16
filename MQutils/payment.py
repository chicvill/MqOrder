import random
import time

def auto_issue_cash_receipt(amount, receipt_type, receipt_number):
    """
    현금영수증을 국세청(또는 API 대행사)을 통해 즉시 발행합니다.
    실제 운영 시에는 PG사나 현금영수증 API(Toss, Popbill 등)를 호출합니다.
    """
    # 1. API 통신 시뮬레이션 (약 0.5초 대기)
    time.sleep(0.5)
    
    # 2. 승인 번호 생성 (랜덤 9자리)
    confirm_no = "".join([str(random.randint(0, 9)) for _ in range(9)])
    
    # 3. 결과 반환
    return {
        "status": "success",
        "confirm_no": confirm_no,
        "issued_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "message": "국세청 승인 완료"
    }
