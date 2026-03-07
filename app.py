import os
import time
import bcrypt
import pyjwt
import requests
from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
# Railway 환경변수에서 SECRET_KEY를 가져오거나 기본값 사용
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'super-secret-key-change-in-production')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///database.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = "로그인이 필요한 페이지입니다."

# --- 데이터베이스 모델 ---
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    api_keys = db.relationship('ApiKey', backref='owner', lazy=True)

class ApiKey(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    store_name = db.Column(db.String(100), nullable=False)
    client_id = db.Column(db.String(200), nullable=False)
    client_secret = db.Column(db.String(200), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# --- 네이버 커머스 API 연동 함수 ---
def get_naver_token(client_id, client_secret):
    """네이버 커머스 API 인증 토큰 발급"""
    timestamp = str(int((time.time() - 3) * 1000))
    pwd = f"{client_id}_{timestamp}"
    hashed_pwd = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
    client_secret_sign = pyjwt.encode({"client_id": client_id, "timestamp": timestamp}, client_secret, algorithm="HS256")
    
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': client_id,
        'timestamp': timestamp,
        'client_secret_sign': client_secret_sign,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    response = requests.post('https://api.commerce.naver.com/external/v1/oauth2/token', headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    return None

def find_product_by_isbn(access_token, isbn):
    """ISBN으로 네이버 스마트스토어 상품 ID 조회 (예시 로직)"""
    headers = {'Authorization': f'Bearer {access_token}'}
    # 네이버 커머스 API의 상품 검색 엔드포인트를 활용 (실제 API 명세에 맞게 URL 조정 필요)
    search_url = f'https://api.commerce.naver.com/external/v1/products/search?keyword={isbn}'
    response = requests.get(search_url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        if data.get('content'):
            return data['content'][0].get('channelProducts', [{}])[0].get('channelProductNo')
    return None

def delete_product(access_token, product_id):
    """상품 삭제 (또는 판매중지)"""
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    # 네이버 커머스 API 상품 삭제/판매중지 엔드포인트
    delete_url = 'https://api.commerce.naver.com/external/v1/products'
    data = {"channelProductNos": [product_id], "statusType": "DELETED"}
    
    response = requests.put(delete_url, headers=headers, json=data)
    return response.status_code == 200

# --- 라우팅 ---
@app.route('/', methods=['GET', 'POST'])
@login_required
def dashboard():
    results = []
    if request.method == 'POST':
        store_id = request.form.get('selected_store')
        isbn_input = request.form.get('isbn_list', '')
        
        selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        if not selected_key:
            flash('유효하지 않은 상점입니다.', 'danger')
            return redirect(url_for('dashboard'))
            
        isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
        
        # 1. API 토큰 발급
        token = get_naver_token(selected_key.client_id, selected_key.client_secret)
        if not token:
            flash('API 인증에 실패했습니다. Client ID와 Secret을 확인해주세요.', 'danger')
            return redirect(url_for('dashboard'))
            
        # 2. ISBN 순회하며 처리
        for isbn in isbn_list:
            product_id = find_product_by_isbn(token, isbn)
            if product_id:
                success = delete_product(token, product_id)
                status = "삭제 성공" if success else "삭제 실패 (API 오류)"
            else:
                status = "실패 (상품을 찾을 수 없음)"
            
            results.append({'isbn': isbn, 'status': status})
            
    return render_template('dashboard.html', api_keys=current_user.api_keys, results=results)

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'danger')
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if User.query.filter_by(username=username).first():
            flash('이미 존재하는 아이디입니다.', 'warning')
            return redirect(url_for('register'))
            
        hashed_password = generate_password_hash(password, method='pbkdf2:sha256')
        new_user = User(username=username, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        
        flash('회원가입이 완료되었습니다. 로그인해주세요.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/manage_keys', methods=['GET', 'POST'])
@login_required
def manage_keys():
    if request.method == 'POST':
        store_name = request.form.get('store_name')
        client_id = request.form.get('client_id')
        client_secret = request.form.get('client_secret')
        
        new_key = ApiKey(store_name=store_name, client_id=client_id, client_secret=client_secret, owner=current_user)
        db.session.add(new_key)
        db.session.commit()
        flash(f'{store_name} 상점의 API 키가 등록되었습니다.', 'success')
        return redirect(url_for('manage_keys'))
        
    return render_template('manage_keys.html', api_keys=current_user.api_keys)

@app.route('/delete_key/<int:key_id>')
@login_required
def delete_key(key_id):
    key_to_delete = ApiKey.query.get_or_404(key_id)
    if key_to_delete.owner != current_user:
        flash('권한이 없습니다.', 'danger')
        return redirect(url_for('manage_keys'))
        
    db.session.delete(key_to_delete)
    db.session.commit()
    flash('API 키가 삭제되었습니다.', 'info')
    return redirect(url_for('manage_keys'))

# 앱 실행 시 DB 파일 자동 생성
with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
