import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# 확장 모듈 초기화
db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "로그인이 필요한 페이지입니다."

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-change-in-production')
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)

    # 모델 불러오기 및 로그인 매니저 설정
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 기능별 Blueprint 등록 (새로운 기능이 생기면 여기에 추가)
    from app.views.auth import auth_bp
    from app.views.keys import keys_bp
    from app.views.store import store_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(keys_bp)
    app.register_blueprint(store_bp)

    # 데이터베이스 테이블 자동 생성
    with app.app_context():
        db.create_all()

    return app
