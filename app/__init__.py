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
    # Flask 앱 객체 생성
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-change-in-production')
    
    # ---------------------------------------------------------
    # 데이터베이스 영구 저장(Volume)을 위한 경로 설정
    # Railway에서 마운트한 '/app/data' 경로를 사용합니다.
    # (로컬 PC 환경에서는 폴더 위치에 'data' 폴더가 자동 생성됩니다)
    # ---------------------------------------------------------
    db_dir = os.environ.get('DB_DIR', '/app/data')
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    db_path = os.path.join(db_dir, 'database.db')
    
    # SQLite 절대 경로는 'sqlite:////경로/database.db' 형태가 됩니다.
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 앱에 모듈 연동
    db.init_app(app)
    login_manager.init_app(app)

    # DB 모델 및 로그인 매니저 설정
    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 기능별 라우팅(블루프린트) 등록
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
