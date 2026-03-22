import os
from flask import Flask, redirect, url_for
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from apscheduler.schedulers.background import BackgroundScheduler
import time
import requests
import urllib.parse
import bcrypt
import base64

db = SQLAlchemy()
login_manager = LoginManager()

def get_commerce_token(client_id, client_secret):
    try:
        timestamp = str(int(time.time() * 1000))
        pwd = f"{client_id}_{timestamp}"
        hashed_pw = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
        client_secret_sign = base64.urlsafe_b64encode(hashed_pw).decode('utf-8')
        url = "https://api.commerce.naver.com/external/v1/oauth2/token"
        data = {
            "client_id": client_id, "timestamp": timestamp,
            "client_secret_sign": client_secret_sign, "grant_type": "client_credentials", "type": "SELF"
        }
        res = requests.post(url, data=data, timeout=5)
        if res.status_code == 200: return res.json().get("access_token")
    except: pass
    return None

def update_ranks_job(app):
    with app.app_context():
        from app.models import MonitoredKeyword, ApiKey
        search_client_id = os.environ.get("NAVER_CLIENT_ID", "")
        search_client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
        
        api_key = ApiKey.query.first()
        commerce_token = None
        if api_key: commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)
        
        keywords = MonitoredKeyword.query.all()
        for kw in keywords:
            kw.prev_store_rank = kw.store_rank 
            rank = "500위 밖"
            
            try:
                if search_client_id and search_client_secret:
                    api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                    found = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    rank = str(start_idx + idx)
                                    found = True
                                    break
                        if found: break
                        time.sleep(0.1) 
            except: rank = "탐색 실패"
            kw.store_rank = rank

            if commerce_token:
                try:
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
                    payload = {"page": 1, "size": 10, "orderType": "NO", "name": kw.keyword}
                    
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    if c_res.status_code == 200:
                        content = c_res.json()
                        if content.get('contents'):
                            product = content['contents'][0]
                            c_no = product.get('channelProducts', [{}])[0].get('channelProductNo')
                            o_no = product.get('originProductNo')
                            if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                            if product.get('salePrice'): kw.price = f"{product.get('salePrice'):,}원"
                            kw.store_name = "스터디박스"
                            kw.book_title = product.get('name', kw.keyword)
                            if o_no:
                                detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                                detail_res = requests.get(detail_url, headers=c_headers, timeout=5)
                                if detail_res.status_code == 200:
                                    book_info = detail_res.json().get('detailAttribute', {}).get('bookInfo', {})
                                    if book_info:
                                        if book_info.get('isbn'): kw.isbn = book_info.get('isbn')
                                        if book_info.get('publisher'): kw.publisher = book_info.get('publisher')
                except: pass

            time.sleep(0.5)
        db.session.commit()

def create_app():
    app = Flask(__name__)
    app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'my-super-secret-key')
    
    db_url = os.environ.get('DATABASE_URL')
    if not db_url:
        if os.path.exists('/app/data'): db_url = 'sqlite:////app/data/app.db'
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
    def load_user(user_id): return User.query.get(int(user_id))

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
        except:
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
    def index(): return redirect(url_for('store.index'))

    return app
