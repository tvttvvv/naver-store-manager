import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
import time
import requests
import urllib.parse
import re

db = SQLAlchemy()
login_manager = LoginManager()

# ✨ 스크래핑 전용 함수
def get_real_store_rank_scraper(keyword, target_store="스터디박스"):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(keyword)}"
        res = requests.get(url, headers=headers, timeout=5)
        if target_store in res.text:
            items = res.text.split('class="product_item__')
            if len(items) > 1:
                for idx, item in enumerate(items[1:], start=1):
                    if target_store in item: return str(idx)
            names = re.findall(r'"mallName":"([^"]+)"', res.text)
            for idx, name in enumerate(names, start=1):
                if target_store in name: return str(idx)
    except:
        return "스크래핑 실패"
    return "순위 밖"

def update_ranks_job(app):
    with app.app_context():
        from app.models import MonitoredKeyword
        keywords = MonitoredKeyword.query.all()
        for kw in keywords:
            kw.prev_store_rank = kw.store_rank 
            kw.store_rank = get_real_store_rank_scraper(kw.keyword, "스터디박스")
            time.sleep(1) # 네이버 봇 차단 방지 1초 딜레이
        db.session.commit()

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

    scheduler = BackgroundScheduler(timezone="Asia/Seoul")
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
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN product_link VARCHAR(500) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN store_rank VARCHAR(50) DEFAULT '-'"))
            db.session.execute(db.text("ALTER TABLE monitored_keyword ADD COLUMN prev_store_rank VARCHAR(50) DEFAULT '-'"))
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
