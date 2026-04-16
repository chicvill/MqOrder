import os
import io
import csv
import smtplib
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

def send_daily_backup(app, db, models_to_backup):
    """시스템 자정 정기 DB 백업 및 이메일 발송"""
    print("⏰ [MQutils.backup] 자정 정기 DB 백업을 시작합니다...")
    with app.app_context():
        try:
            output = io.StringIO()
            writer = csv.writer(output)
            
            for label, model in models_to_backup:
                writer.writerow([f"=== {label} ({model.__tablename__}) ==="])
                records = model.query.all()
                if records:
                    columns = [c.name for c in model.__table__.columns]
                    writer.writerow(columns)
                    for r in records:
                        writer.writerow([getattr(r, col) for col in columns])
                writer.writerow([])

            # 이메일 설정
            sender_email = "mqnet@gmail.com"
            receiver_email = "mqnet@gmail.com"
            password = os.environ.get('EMAIL_PASSWORD')
            
            if not password:
                print("⚠️ [백업 실패] EMAIL_PASSWORD가 설정되지 않았습니다.")
                return

            msg = MIMEMultipart()
            msg['From'] = f"MQnet Backup <{sender_email}>"
            msg['To'] = receiver_email
            msg['Subject'] = f"🚀 [MQnet] {datetime.now().strftime('%Y-%m-%d')} 주간 정기 데이터 백업"
            
            body = f"안녕하세요.\n\n{datetime.now().strftime('%Y-%m-%d')} 월요일 자정 기준 MQnet 주간 자동 백업 파일입니다."
            msg.attach(MIMEText(body, 'plain'))
            
            filename = f"MQnet_Weekly_Backup_{datetime.now().strftime('%Y%m%d')}.csv"
            attachment = MIMEBase('application', 'octet-stream')
            attachment.set_payload(output.getvalue().encode('utf-8-sig'))
            encoders.encode_base64(attachment)
            attachment.add_header('Content-Disposition', f"attachment; filename= {filename}")
            msg.attach(attachment)
            
            server = smtplib.SMTP('smtp.gmail.com', 587)
            server.starttls()
            server.login(sender_email, password)
            server.send_message(msg)
            server.quit()
            
            print(f"✅ [주간 백업 성공] {receiver_email}로 전송 완료!")
        except Exception as e:
            print(f"❌ [주간 백업 실패] 오류 발생: {e}")
