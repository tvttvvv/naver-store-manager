import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler

db = SQLAlchemy()
login_manager = LoginManager()

# ✨ [신규] 매일 밤 9시에 실행될 '순위 자동 점검' 매크로 함수
def update_ranks_job(app):
    with app.app_context():
        from app.models import MonitoredKeyword
        import requests, urllib.parse
        
        client_id = os.environ.get("NAVER_CLIENT_ID", "")
        client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
        if not client_id or not client_secret: 
            print("[스케줄러 에러] 네이버 API 변수가 없습니다.")
            return
            
        keywords = MonitoredKeyword.query.all()
        for kw in keywords:
            try:
                headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
                url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100"
                res = requests.get(url, headers=headers, timeout=5)
                if res.status_code == 200:
                    items = res.json().get('items', [])
                    rank = "-"
                    for idx, item in enumerate(items):
                        if "스터디박스" in item.get('mallName', ''):
                            rank = str(idx + 1)
                            break
                    kw.store_rank = rank
            except:
                pass
        db.session.commit()
        print("[System] 밤 9시 스터디박스 순위 자동 업데이트가 완료되었습니다!")

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

    # ✨ [신규] 파이썬 백그라운드 스케줄러 가동 (한국 시간 기준)
    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
    # 매일 밤 21시 00분에 update_ranks_job 함수 실행
    scheduler.add_job(func=update_ranks_job, args=[app], trigger="cron", hour=21, minute=0)
    scheduler.start()

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
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN shipping_fee VARCHAR(50) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN store_name VARCHAR(100) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN book_title VARCHAR(200) DEFAULT '-'"))
        except Exception:
            db.session.rollback()

        try:
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN product_link VARCHAR(500) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN store_rank VARCHAR(50) DEFAULT '-'"))
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
