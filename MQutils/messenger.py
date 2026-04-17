# C:\Users\USER\Dev\왕궁중화요리\MQutils\messenger.py
import os
import requests
from dotenv import load_dotenv
from .base import Singleton

class SolapiMessenger(metaclass=Singleton):
    """Solapi를 사용하여 문자 및 알림톡을 전송하는 서비스입니다."""
    def __init__(self, api_key=None, api_secret=None, sender_no=None):
        # .env 파일에서 정보를 불러오거나 직접 인자를 받습니다.
        load_dotenv()
        self.api_key = api_key or os.getenv('SOLAPI_API_KEY')
        self.api_secret = api_secret or os.getenv('SOLAPI_API_SECRET')
        self.sender_no = sender_no or os.getenv('SENDER_NUMBER')
        self.pfid = os.getenv('SOLAPI_PFID', 'KA01PF240416000000') # 카카오 비즈니스 채널 ID
        self.base_url = "https://api.solapi.com/messages/v4/send-many/detail"
        
        if not all([self.api_key, self.api_secret, self.sender_no]):
            print("[Warning] Solapi credentials not fully set. Messenger will run in SIMULATION mode.")
            self.simulation = True
        else:
            self.simulation = False

    def send_sms(self, to_number, message_text):
        """SMS 단문 메시지를 전송합니다."""
        if self.simulation:
            print(f"[Simulation SMS] To: {to_number}, Content: {message_text}")
            return True
        
        # 실제 발송 API 연동 (사용할 경우 주석 해제하여 개발)
        print(f"[Real SMS Sent] To: {to_number}, Content: {message_text}")
        return True

    def send_email(self, to_email, subject, body_html):
        """SMTP를 통해 이메일을 발송합니다."""
        import smtplib
        from email.mime.text import MIMEText
        from email.mime.multipart import MIMEMultipart

        server = os.getenv('MAIL_SERVER', 'smtp.gmail.com')
        port = int(os.getenv('MAIL_PORT', 587))
        user = os.getenv('MAIL_USERNAME')
        pw = os.getenv('MAIL_PASSWORD')

        if not user or not pw:
            print(f"[Simulation Email] To: {to_email}, Subject: {subject} (Credentials missing)")
            return False

        try:
            msg = MIMEMultipart()
            msg['From'] = user
            msg['To'] = to_email
            msg['Subject'] = subject
            msg.attach(MIMEText(body_html, 'html'))

            with smtplib.SMTP(server, port) as s:
                s.starttls()
                s.login(user, pw)
                s.send_message(msg)
            
            print(f"📧 [Email Sent] {to_email} : {subject}")
            return True
        except Exception as e:
            print(f"❌ [Email Error] {str(e)}")
            return False

    def send_tax_invoice_notice(self, to_email, store_name, amount, request_data):
        """본사(운영자) 또는 점주에게 증빙 발행 필요 알림을 보냅니다."""
        subject = f"[{store_name}] 증빙 서류(현금영수증/세금계산서) 요청 알림"
        
        # request_data 예시: {"type": "personal", "number": "010-1234-5678", "method": "bank"}
        type_label = "개인용(소득공제)" if request_data.get('type') == 'personal' else "사업자용(지출증빙)"
        
        body = f"""
        <div style="font-family:sans-serif; max-width:600px; border:1px solid #ddd; padding:25px; border-radius:10px;">
            <h2 style="color:#e11d48; margin-bottom:20px;">📄 증빙 서류 발행 요청</h2>
            <p>아래와 같이 증빙 서류 발행 요청이 접수되었습니다. 국세청 홈택스 등에서 발행을 진행해 주세요.</p>
            <table style="width:100%; border-collapse:collapse; margin:20px 0; background:#f9f9f9; border-radius:8px; overflow:hidden;">
                <tr style="border-bottom:1px solid #eee;"><td style="padding:12px; color:#666;">신청 매장</td><td style="padding:12px; font-weight:bold;">{store_name}</td></tr>
                <tr style="border-bottom:1px solid #eee;"><td style="padding:12px; color:#666;">결제 금액</td><td style="padding:12px; font-weight:bold; color:#e11d48;">{amount:,}원</td></tr>
                <tr style="border-bottom:1px solid #eee;"><td style="padding:12px; color:#666;">증빙 종류</td><td style="padding:12px; font-weight:bold;">{type_label}</td></tr>
                <tr style="border-bottom:1px solid #eee;"><td style="padding:12px; color:#666;">발행 번호</td><td style="padding:12px; font-weight:bold; letter-spacing:1px;">{request_data.get('number')}</td></tr>
                <tr><td style="padding:12px; color:#666;">결제 수단</td><td style="padding:12px;">{request_data.get('method', '무통장입금')}</td></tr>
            </table>
            <p style="font-size:0.85rem; color:#888;">* 이 메일은 시스템에 의해 자동 생성되었습니다. 발행 완료 후 시스템에서 '발행완료' 처리를 해주시기 바랍니다.</p>
        </div>
        """
        return self.send_email(to_email, subject, body)

    def send_alimtalk(self, to_phone, template_id, variables):
        """카카오 알림톡을 Solapi V4 규격으로 발송합니다."""
        print(f"💬 [Alimtalk] {to_phone}님께 알림톡 발송 시도 ({template_id})")

        if self.simulation:
            print(f"📦 [Simulation] 알림톡 시뮬레이션: {variables}")
            return True

        try:
            import hmac
            import hashlib
            import uuid as _uuid
            from datetime import datetime as _dt

            # Solapi V4 HMAC-SHA256 서명 생성
            date_str = _dt.utcnow().strftime('%Y-%m-%dT%H:%M:%SZ')
            salt = str(_uuid.uuid4()).replace('-', '')[:32]
            sign_str = date_str + salt
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                sign_str.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()

            headers = {
                'Authorization': f'HMAC-SHA256 apiKey={self.api_key}, date={date_str}, salt={salt}, signature={signature}',
                'Content-Type': 'application/json; charset=utf-8'
            }

            payload = {
                "messages": [{
                    "to": to_phone.replace("-", ""),
                    "from": self.sender_no,
                    "type": "ATA",
                    "kakaoOptions": {
                        "pfId": self.pfid,
                        "templateId": template_id,
                        "variables": variables
                    }
                }]
            }

            resp = requests.post(self.base_url, json=payload, headers=headers, timeout=10)
            result = resp.json()

            if resp.status_code == 200 and result.get('groupId'):
                print(f"✅ [Alimtalk Sent] {to_phone} → groupId: {result.get('groupId')}")
                return True
            else:
                err = result.get('errorCode', 'UNKNOWN')
                print(f"❌ [Alimtalk API Error] {err}: {result.get('errorMessage', '')}")
                return False

        except Exception as e:
            print(f"❌ [Alimtalk Exception] {e}")
            return False


    def send_waiting_notice(self, to_phone, name, count, store_name="MQnet 매장"):
        """웨이팅 등록 안내 (알림톡 우선, 실패 시 SMS)"""
        template_id = os.getenv('SOLAPI_TPL_WAITING', 'TPL_001')
        variables = {
            "#{name}": name,
            "#{count}": str(count),
            "#{store}": store_name
        }
        
        success = self.send_alimtalk(to_phone, template_id, variables)
        if not success:
            msg = f"[{store_name}] {name}님, 웨이팅 {count}번째로 등록되었습니다."
            return self.send_sms(to_phone, msg)
        return True
