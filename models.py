# -*- coding: utf-8 -*-
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime

db = SQLAlchemy()

class User(db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default='owner') # admin, owner, staff
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=True)
    full_name = db.Column(db.String(100), nullable=True) # 파트너 실명
    phone = db.Column(db.String(20), nullable=True) # 파트너 연락처
    is_approved = db.Column(db.Boolean, default=False) # 관리자 승인 여부 (staff 전용)
    agreed_at = db.Column(db.DateTime, nullable=True) # 약관 동의 일시
    
    # [신규] 급여 지급용 계좌 정보
    bank_name = db.Column(db.String(50), nullable=True)
    account_no = db.Column(db.String(50), nullable=True)
    
    # [신규] 직원 관리용 필드
    hourly_rate = db.Column(db.Integer, default=10000) # 시급 기본값 10,000원
    position = db.Column(db.String(50), nullable=True) # 담당 (조리, 서빙 등)
    
    # [추가] 요일별 정해진 출퇴근 시간 및 계약 기간
    # work_schedule 예시: {"mon": {"in": "09:00", "out": "18:00"}, "tue": ...}
    work_schedule = db.Column(db.JSON, nullable=True)
    contract_start = db.Column(db.Date, nullable=True)
    contract_end = db.Column(db.Date, nullable=True)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Store(db.Model):
    __tablename__ = 'stores'
    id = db.Column(db.String(50), primary_key=True) # slug (e.g., 'suragol', 'wangpung')
    name = db.Column(db.String(100), nullable=False)
    tables_count = db.Column(db.Integer, default=20)
    menu_data = db.Column(db.JSON, nullable=True) # store individual menu
    
    # 관리 및 결제 상태 필드
    status = db.Column(db.String(20), default='active') 
    payment_status = db.Column(db.String(20), default='paid')
    monthly_fee = db.Column(db.Integer, default=50000) # Monthly subscription fee
    expires_at = db.Column(db.DateTime, nullable=True)
    
    # 사업자 정보 (세금계산서 발행용)
    business_no = db.Column(db.String(20))
    ceo_name = db.Column(db.String(50))
    business_no = db.Column(db.String(20)) # 사업자등록번호
    address = db.Column(db.Text)           # 사업장 주소
    business_type = db.Column(db.String(50))
    business_item = db.Column(db.String(100))
    business_email = db.Column(db.String(100))
    is_public = db.Column(db.Boolean, default=False) # 공개용 샘플 업소 여부
    
    # [신규] 전문 영업 및 계약용 필드
    signature_owner = db.Column(db.Text, nullable=True)   # 점주 서명 데이터 (Base64)
    signature_partner = db.Column(db.Text, nullable=True) # 파트너 서명 데이터
    theme_color = db.Column(db.String(20), default='#3b82f6') # 주문창 UI 색상
    contact_phone = db.Column(db.String(50), nullable=True)    # 예약/배달용 번호
    point_ratio = db.Column(db.Float, default=0.0)             # 포인트 적립 비율
    waiting_sms_no = db.Column(db.String(50), nullable=True)   # 웨이팅 발신 번호
    
    # [신규] 무통장 입금용 계좌 정보
    bank_name = db.Column(db.String(50), nullable=True)        # 예: 농협, 신한
    account_no = db.Column(db.String(50), nullable=True)       # 계좌번호
    account_holder = db.Column(db.String(50), nullable=True)   # 예금주명

    # [신규] 매장 WIFI 정보
    wifi_ssid = db.Column(db.String(100), nullable=True)
    wifi_pw = db.Column(db.String(100), nullable=True)

    # 영업 담당자 (직원)
    recommended_by = db.Column(db.Integer, db.ForeignKey('users.id'))

    # [글로벌] 매장별 타임존 (기본 대한민국)
    timezone = db.Column(db.String(50), default='Asia/Seoul')

    # 출퇴근 승인용 보안 PIN (bcrypt 해시 저장)
    attendance_pin = db.Column(db.String(255), default='0000')
    
    # [정산] 수수료율 (정산 시 활용)
    commission_rate = db.Column(db.Float, default=0.0)

    # [통계] 데이터 리셋 기준 시간
    stats_reset_at = db.Column(db.DateTime, nullable=True)
    
    # [설정] 자동 로그아웃 방지 여부
    disable_auto_logout = db.Column(db.Boolean, default=False)

    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    users = db.relationship('User', backref='store_ptr', lazy=True, foreign_keys=[User.store_id])
    manager = db.relationship('User', backref='managed_stores', lazy=True, foreign_keys=[recommended_by])

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'tables_count': self.tables_count,
            'menu_data': self.menu_data,
            'status': self.status,
            'payment_status': self.payment_status,
            'expires_at': (self.expires_at.isoformat() + 'Z') if self.expires_at else None,
            'business_no': self.business_no,
            'ceo_name': self.ceo_name,
            'business_email': self.business_email,
            'recommended_by': self.recommended_by,
            'wifi_ssid': self.wifi_ssid,
            'wifi_pw': self.wifi_pw
        }

class Order(db.Model):
    __tablename__ = 'orders'
    id = db.Column(db.String(50), primary_key=True)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    table_id = db.Column(db.Integer, nullable=False)
    total_price = db.Column(db.Integer, default=0)
    status = db.Column(db.String(20), default='pending')  # pending, ready, served, paid
    session_id = db.Column(db.String(50), nullable=True)
    order_no = db.Column(db.String(10), nullable=True) # [신규] 노출용 3자리 주문번호
    phone = db.Column(db.String(20), nullable=True) # For points
    depositor_name = db.Column(db.String(100), nullable=True) # [신규] 무통장 입금자명
    is_prepaid = db.Column(db.Boolean, default=False) # [신규] 선결제 완료 여부
    
    # [추가] 현금영수증 정보
    cash_receipt_type = db.Column(db.String(20), nullable=True)   # personal, business
    cash_receipt_number = db.Column(db.String(20), nullable=True) 
    payment_method = db.Column(db.String(20), nullable=True) # [신규] card, bank, cash
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    paid_at = db.Column(db.DateTime, nullable=True)
    items = db.relationship('OrderItem', backref='order', lazy=True, cascade="all, delete-orphan")

    def to_dict(self):
        return {
            'id': self.id,
            'store_id': self.store_id,
            'table_id': self.table_id,
            'total_price': self.total_price,
            'status': self.status,
            'session_id': self.session_id,
            'order_no': self.order_no,
            'phone': self.phone,
            'is_prepaid': self.is_prepaid,
            'cash_receipt_type': self.cash_receipt_type,
            'cash_receipt_number': self.cash_receipt_number,
            'payment_method': self.payment_method,
            'created_at': (self.created_at.isoformat() + 'Z') if self.created_at else None,
            'items': [item.to_dict() for item in self.items]
        }

class OrderItem(db.Model):
    __tablename__ = 'order_items'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), db.ForeignKey('orders.id'), nullable=False)
    menu_id = db.Column(db.Integer, nullable=False)
    name = db.Column(db.String(100), nullable=False)
    price = db.Column(db.Integer, nullable=False)
    quantity = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='pending') # pending, cancelled

    def to_dict(self):
        return { 
            'id': self.id, 
            'menu_id': self.menu_id, 
            'name': self.name, 
            'price': self.price, 
            'quantity': self.quantity,
            'status': self.status 
        }

class Waiting(db.Model):
    __tablename__ = 'waiting'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    waiting_no = db.Column(db.Integer, nullable=True)
    phone = db.Column(db.String(20), nullable=False)
    people = db.Column(db.Integer, default=1)
    status = db.Column(db.String(20), default='waiting')
    nearby_notified = db.Column(db.Boolean, default=False) # 3rd in line notification
    enter_notified = db.Column(db.Boolean, default=False)  # Entry notification
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'store_id': self.store_id,
            'waiting_no': self.waiting_no,
            'phone': self.phone,
            'people': self.people,
            'status': self.status,
            'nearby_notified': self.nearby_notified,
            'enter_notified': self.enter_notified,
            'created_at': self.created_at.isoformat() + 'Z'
        }

class SystemConfig(db.Model):
    __tablename__ = 'system_configs'
    id = db.Column(db.Integer, primary_key=True)
    site_name = db.Column(db.String(100), default='MQnet Central')
    maintenance_mode = db.Column(db.Boolean, default=False)
    
    # [본사 계좌] 정산 수취용
    hq_bank = db.Column(db.String(50))
    hq_account = db.Column(db.String(50))
    hq_holder = db.Column(db.String(50))

    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class TaxInvoice(db.Model):
    __tablename__ = 'tax_invoices'
    id = db.Column(db.Integer, primary_key=True)
    order_id = db.Column(db.String(50), db.ForeignKey('orders.id'), nullable=False)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False)
    status = db.Column(db.String(20), default='issued')
    issued_at = db.Column(db.DateTime, default=datetime.utcnow)
    store = db.relationship('Store', backref='invoices')

    def to_dict(self):
        return { 'id': self.id, 'order_id': self.order_id, 'amount': self.amount, 'status': self.status, 'issued_at': self.issued_at.isoformat() + 'Z' }

class ServiceRequest(db.Model):
    __tablename__ = 'service_requests'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    table_id = db.Column(db.Integer, nullable=False)
    content = db.Column(db.String(100), nullable=False) # e.g., "물", "반찬 더주세요", "앞접시"
    status = db.Column(db.String(20), default='pending') # pending, completed
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'store_id': self.store_id,
            'table_id': self.table_id,
            'content': self.content,
            'status': self.status,
            'created_at': self.created_at.isoformat() + 'Z'
        }

class Customer(db.Model):
    __tablename__ = 'customers'
    id = db.Column(db.Integer, primary_key=True)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    phone = db.Column(db.String(20), nullable=False)
    points = db.Column(db.Integer, default=0)
    visit_count = db.Column(db.Integer, default=0)
    total_spent = db.Column(db.Integer, default=0)
    last_accumulation_at = db.Column(db.DateTime, default=datetime.utcnow)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    __table_args__ = (db.UniqueConstraint('store_id', 'phone', name='_store_phone_uc'),)

    def to_dict(self):
        return {
            'id': self.id,
            'phone': self.phone,
            'points': self.points,
            'visit_count': self.visit_count,
            'total_spent': self.total_spent,
            'last_accumulation_at': (self.last_accumulation_at.isoformat() + 'Z') if self.last_accumulation_at else None
        }

class PointTransaction(db.Model):
    __tablename__ = 'point_transactions'
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey('customers.id'), nullable=False)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    amount = db.Column(db.Integer, nullable=False) # positive for accumulation, negative for usage
    description = db.Column(db.String(200))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Attendance(db.Model):
    __tablename__ = 'attendance'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    store_id = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    check_in_at = db.Column(db.DateTime, default=datetime.utcnow)
    check_out_at = db.Column(db.DateTime, nullable=True)
    scheduled_in = db.Column(db.DateTime, nullable=True)  # 예정된 출근 시각 (UTC)
    scheduled_out = db.Column(db.DateTime, nullable=True) # 예정된 퇴근 시각 (UTC)
    total_minutes = db.Column(db.Integer, default=0) # 자동 산출된 분 단위 근무시간
    status = db.Column(db.String(20), default='working') # working, completed
    
    user = db.relationship('User', backref='attendances')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.user.full_name or self.user.username,
            'check_in_at': (self.check_in_at.isoformat() + 'Z') if self.check_in_at else None,
            'check_out_at': (self.check_out_at.isoformat() + 'Z') if self.check_out_at else None,
            'total_minutes': self.total_minutes,
            'status': self.status
        }

class KnowledgeNote(db.Model):
    __tablename__ = 'knowledge_notes'
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(50), nullable=False)
    title = db.Column(db.String(100), nullable=False)
    content = db.Column(db.Text, nullable=False) # Purpose, Setup, Settings combined in Markdown
    links = db.Column(db.JSON, nullable=True) # List of URLs
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'category': self.category,
            'title': self.title,
            'content': self.content,
            'links': self.links,
            'updated_at': (self.updated_at.isoformat() + 'Z') if self.updated_at else None
        }

# ─────────────────────────────────────────────────────────────
# [SaaS] 구독 결제 내역 테이블
# ─────────────────────────────────────────────────────────────
class Subscription(db.Model):
    __tablename__ = 'subscriptions'
    id         = db.Column(db.Integer, primary_key=True)
    store_id   = db.Column(db.String(50), db.ForeignKey('stores.id'), nullable=False)
    plan       = db.Column(db.String(20), default='standard')   # standard / trial
    amount     = db.Column(db.Integer, default=50000)           # 결제 금액 (원)
    method     = db.Column(db.String(20), nullable=True)        # card / bank / free
    status     = db.Column(db.String(20), default='active')     # active / expired / cancelled
    period_start = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    period_end   = db.Column(db.DateTime, nullable=False)       # 이 날짜까지 유효
    paid_at    = db.Column(db.DateTime, nullable=True)          # 결제 완료 시각
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    store = db.relationship('Store', backref='subscriptions')

    def to_dict(self):
        return {
            'id': self.id,
            'store_id': self.store_id,
            'plan': self.plan,
            'amount': self.amount,
            'method': self.method,
            'status': self.status,
            'period_start': (self.period_start.isoformat() + 'Z') if self.period_start else None,
            'period_end': (self.period_end.isoformat() + 'Z') if self.period_end else None,
        }
