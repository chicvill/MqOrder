import threading
from .messenger import SolapiMessenger
from models import db, Waiting, Store

def send_waiting_sms(app, wait_id, notify_type='enter'):
    """대기 고객에게 상황별 SMS 발송을 통합 관리합니다."""
    with app.app_context():
        w = db.session.get(Waiting, wait_id)
        if not w or not w.phone or '미입력' in w.phone:
            return
        
        # 중복 발송 방지
        if notify_type == 'nearby' and w.nearby_notified:
            return
        if notify_type == 'enter' and w.enter_notified:
            return
        
        store = db.session.get(Store, w.store_id)
        if not store:
            return
        
        if notify_type == 'enter':
            msg = f"[{store.name}] 고객님, 지금 바로 입장해 주세요! 입구에서 대기해 주시면 안내해 드리겠습니다. 감사합니다."
        else: # nearby
            # 현재 몇 번째인지 다시 계산
            rank = Waiting.query.filter_by(store_id=w.store_id, status='waiting').filter(Waiting.created_at < w.created_at).count() + 1
            if rank == 1:
                msg = f"[{store.name}] 고객님, 곧 입장하실 차례입니다(대기 1순위)! 매장 근처에서 대기해 주세요."
            elif rank == 2:
                 msg = f"[{store.name}] 고객님, 대기 2순위입니다! 매장 근처로 이동해 주시면 곧 안내해 드리겠습니다."
            else:
                 msg = f"[{store.name}] 고객님, 현재 대기 {rank}순위입니다! 매장 근처에서 대기해 주시면 곧 입장 안내를 도와드리겠습니다."
            
        try:
            messenger = SolapiMessenger()
            clean_phone = w.phone.replace('-', '').replace(' ', '')
            
            if clean_phone.isdigit():
                # [고도화] 알림톡 템플릿 및 변수 구성
                template_id = "TPL_ENTER" if notify_type == 'enter' else "TPL_NEARBY"
                variables = {
                    "#{store}": store.name,
                    "#{name}": w.name or "고객",
                    "#{rank}": str(rank) if notify_type == 'nearby' else "0"
                }

                # 알림톡 발송 시도 (실패 시 SMS 자동 전환은 유틸리티 내부에서 처리 가능하나 명시적 처리)
                success = messenger.send_alimtalk(clean_phone, template_id, variables)
                
                if success:
                    if notify_type == 'enter':
                        w.enter_notified = True
                    else:
                        w.nearby_notified = True
                    db.session.commit()
                    print(f"✅ Alimtalk Sent ({notify_type}, WaitNo:{w.waiting_no}): {clean_phone}")
        except Exception as e:
            print(f"⚠️ Notification Error ({notify_type}): {e}")

def check_nearby_waiting(app, slug):
    """현재 대기열 상위 고객들을 체크하여 알림이 필요한 경우 자동으로 알림을 보냅니다."""
    # app_context 내에서 실행하거나 app 객체를 전달받아야 함.
    with app.app_context():
        waits = Waiting.query.filter_by(store_id=slug, status='waiting').order_by(Waiting.created_at.asc()).limit(3).all()
        
        for target in waits:
            if not target.nearby_notified:
                # 백그라운드 스레드로 발송 (app 객체 전달)
                threading.Thread(target=send_waiting_sms, args=(app, target.id, 'nearby')).start()
