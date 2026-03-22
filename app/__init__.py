import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager

db = SQLAlchemy()
login_manager = LoginManager()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'my-super-secret-key')
    
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        if os.path.exists('/app/data'):
            db_url = 'sqlite:////app/data/app.db'
        else:
            basedir = os.path.abspath(os.path.dirname(__file__))
            db_url = 'sqlite:///' + os.path.join(basedir, 'app.db')
            
    app.config['SQLALCHEMY_DATABASE_URI'] = db_url
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    db.init_app(app)
    login_manager.init_app(app)
    
    login_manager.login_view = 'auth.login'
    login_manager.login_message = '로그인이 필요한 서비스입니다.'

    from app.models import User
    
    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    with app.app_context():
        if db_url and db_url.startswith('sqlite:////'):
            db_path = db_url.replace('sqlite:///', '')
            os.makedirs(os.path.dirname(db_path), exist_ok=True)

        db.create_all()
        
        try:
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN publisher VARCHAR(100) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN supply_rate VARCHAR(50) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN isbn VARCHAR(50) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN price VARCHAR(50) DEFAULT '-'"))
            # ✨ 배송비 기본값을 '무료'에서 '-'로 수정 ✨
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN shipping_fee VARCHAR(50) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN store_name VARCHAR(100) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN book_title VARCHAR(200) DEFAULT '-'"))
        except Exception:
            db.session.rollback()

        try:
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN product_link VARCHAR(500) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN store_rank VARCHAR(50) DEFAULT '1'"))
            db.session.commit()
        except Exception:
            db.session.rollback()

    from app.views.auth import auth_bp
    from app.views.store import store_bp
    from app.views.monitoring import monitoring_bp
    from app.views.kyobo import kyobo_bp
    from app.views.keys import keys_bp 

    app.register_blueprint(auth_bp)
    app.register_blueprint(store_bp, url_prefix='/store')
    app.register_blueprint(monitoring_bp, url_prefix='/monitoring')
    app.register_blueprint(kyobo_bp, url_prefix='/kyobo')
    app.register_blueprint(keys_bp, url_prefix='/keys') 

    @app.route('/')
    def index():
        return redirect(url_for('store.index'))

    return app
