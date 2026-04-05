from app import db
from flask_login import UserMixin
from datetime import datetime

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    api_keys = db.relationship('ApiKey', backref='owner', lazy=True, cascade="all, delete-orphan")
    monitored_keywords = db.relationship('MonitoredKeyword', backref='owner', lazy=True, cascade="all, delete-orphan")
    runningmate_keywords = db.relationship('RunningmateKeyword', backref='owner', lazy=True, cascade="all, delete-orphan")
    # ✨ 스터디박스 키워드 관계 추가
    studybox_keywords = db.relationship('StudyboxKeyword', backref='owner', lazy=True, cascade="all, delete-orphan")

class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(100), nullable=False)
    client_id = db.Column(db.String(200), nullable=False)
    client_secret = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class MonitoredKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(255), nullable=False)
    search_volume = db.Column(db.Integer, default=0)
    rank_info = db.Column(db.String(50), default='A')
    link = db.Column(db.String(500), default='#')
    publisher = db.Column(db.String(255), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    isbn = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    store_name = db.Column(db.String(255), default='-') 
    book_title = db.Column(db.String(255), default='-')
    product_link = db.Column(db.String(500), default='-')
    store_rank = db.Column(db.String(50), default='-')
    prev_store_rank = db.Column(db.String(50), default='-')
    stock_quantity = db.Column(db.String(50), default='-')
    sales_status = db.Column(db.String(50), default='-')
    registered_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d'))

class RunningmateKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(255), nullable=False)
    search_volume = db.Column(db.Integer, default=0)
    rank_info = db.Column(db.String(50), default='A')
    link = db.Column(db.String(500), default='#')
    publisher = db.Column(db.String(255), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    isbn = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    store_name = db.Column(db.String(255), default='-') 
    book_title = db.Column(db.String(255), default='-')
    product_link = db.Column(db.String(500), default='-')
    store_rank = db.Column(db.String(50), default='-')
    prev_store_rank = db.Column(db.String(50), default='-')
    stock_quantity = db.Column(db.String(50), default='-')
    sales_status = db.Column(db.String(50), default='-')
    registered_at = db.Column(db.String(50), default=lambda: datetime.now().strftime('%Y-%m-%d'))

# ==============================================================================
# ✨ 스터디박스 모니터링 및 변화율 추적을 위한 전용 테이블
# ==============================================================================
class StudyboxKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(255), nullable=False)
    naver_count = db.Column(db.Integer, default=0)
    stock_quantity = db.Column(db.Integer, default=0)  # 재고수 추가
    shop_rank = db.Column(db.String(50), default='-')
    link = db.Column(db.String(500), default='#')
    publisher = db.Column(db.String(255), default='-')
    supply_rate = db.Column(db.String(50), default='-')
    isbn = db.Column(db.String(50), default='-')
    price = db.Column(db.String(50), default='-')
    shipping_fee = db.Column(db.String(50), default='-')
    shop_title = db.Column(db.String(255), default='-')
    registered_at = db.Column(db.DateTime, default=datetime.now)

    # 1:N 관계로 해당 키워드의 과거 변화량 기록을 전부 가져옵니다
    histories = db.relationship('StudyboxHistory', backref='studybox_keyword', lazy=True, cascade="all, delete-orphan", order_by="StudyboxHistory.record_date")

class StudyboxHistory(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    keyword_id = db.Column(db.Integer, db.ForeignKey('studybox_keyword.id'), nullable=False)
    record_date = db.Column(db.Date, nullable=False)
    naver_count = db.Column(db.Integer, default=0)
    stock_quantity = db.Column(db.Integer, default=0)
