# 기존 User, ApiKey 등의 모델 아래에 추가해 주세요!

from datetime import datetime

class MonitoredKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    keyword = db.Column(db.String(100), nullable=False)
    search_volume = db.Column(db.Integer, default=0)
    rank_info = db.Column(db.String(50))
    link = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
