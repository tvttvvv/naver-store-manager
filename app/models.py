from app import db
from flask_login import UserMixin
from datetime import datetime

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    api_keys = db.relationship('ApiKey', backref='owner', lazy=True, cascade="all, delete-orphan")
    monitored_keywords = db.relationship('MonitoredKeyword', backref='owner', lazy=True, cascade="all, delete-orphan")

class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(100), nullable=False)
    client_id = db.Column(db.String(200), nullable=False)
    client_secret = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class MonitoredKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    search_volume = db.Column(db.Integer, default=0)
    rank_info = db.Column(db.String(50))
    link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    publisher = db.Column(db.String(100), default="-")
    supply_rate = db.Column(db.String(50), default="-")
    isbn = db.Column(db.String(50), default="-")
    price = db.Column(db.String(50), default="-")
    shipping_fee = db.Column(db.String(50), default="무료")
    store_name = db.Column(db.String(100), default="-")
    book_title = db.Column(db.String(200), default="-")
    
    # ✨ [신규 추가] 상품 홈페이지 링크 및 스터디박스 상점 순위
    product_link = db.Column(db.String(500), default="-")
    store_rank = db.Column(db.String(50), default="1")
