import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

# 데이터베이스 및 로그인 매니저 초기화
db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    
    # 보안 및 DB 설정 (환경변수 또는 기본값)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'my-super-secret-key')
    
    # SQLite 기본 설정 (실제 배포 환경의 DATABASE_URL이 있으면 우선 적용)
    basedir = os.path.abspath(os.path.dirname(__file__))
    app.config['SQLALCHEMY_DATABASE_URI'] = os.environ.get('DATABASE_URL', 'sqlite:///' + os.path.join(basedir, 'app.db'))
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    # 앱에 DB 및 로그인 매니저 연동
    db.init_app(app)
    login_manager.init_app(app)
    
    # 로그인이 필요할 때 튕겨낼 페이지 경로 설정
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '로그인이 필요한 서비스입니다.'

    # 모델 임포트 및 유저 로더 설정
    from app.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 앱 컨텍스트 내에서 데이터베이스 테이블 자동 생성
    with app.app_context():
        db.create_all()

    # =========================================================
    # ✨ 블루프린트(라우터) 등록 (반드시 return app 바로 위에 위치!)
    # =========================================================
    from app.views.auth import auth_bp
    from app.views.store import store_bp
    from app.views.monitoring import monitoring_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(store_bp, url_prefix='/store')
    app.register_blueprint(monitoring_bp, url_prefix='/monitoring')

    return app
