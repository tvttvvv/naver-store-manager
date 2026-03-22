from app import db
from flask_login import UserMixin
from datetime import datetime

# 1. 사용자 계정 모델
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(256), nullable=False)
    
    # 관계 설정
    api_keys = db.relationship('ApiKey', backref='owner', lazy=True, cascade="all, delete-orphan")
    monitored_keywords = db.relationship('MonitoredKeyword', backref='owner', lazy=True, cascade="all, delete-orphan")

# 2. 네이버 상점 API 키 모델
class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(100), nullable=False)
    client_id = db.Column(db.String(200), nullable=False)
    client_secret = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

# 3. ✨ [신규] 스터디박스 황금 키워드 보관함 모델
class MonitoredKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    search_volume = db.Column(db.Integer, default=0)
    rank_info = db.Column(db.String(50))
    link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
