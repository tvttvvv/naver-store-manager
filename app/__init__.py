import os
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()
login_manager.login_view = 'auth.login'
login_manager.login_message = "로그인이 필요한 페이지입니다."

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-change-in-production')
    
    db_dir = os.environ.get('DB_DIR', '/app/data')
    if not os.path.exists(db_dir):
        os.makedirs(db_dir, exist_ok=True)
        
    db_path = os.path.join(db_dir, 'database.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f'sqlite:///{db_path}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)

    from app.models import User
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # 블루프린트 등록 (여기 들여쓰기가 중요합니다!)
    from app.views.auth import auth_bp
    from app.views.keys import keys_bp
    from app.views.store import store_bp
    from app.views.kyobo import kyobo_bp
    from app.views.studybox import studybox_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(keys_bp)
    app.register_blueprint(store_bp)
    app.register_blueprint(kyobo_bp)
    app.register_blueprint(studybox_bp)

    with app.app_context():
        db.create_all()

    return app
