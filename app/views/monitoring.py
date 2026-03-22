import os
import time
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword, ApiKey
import requests
import urllib.parse
import bcrypt
import base64

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/')
@login_required
def index():
    return render_template('monitoring/index.html')

@monitoring_bp.route('/api/webhook', methods=['POST'])
def receive_webhook():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'message': 'No data'})

    grade = data.get('grade', '')
    keyword = data.get('keyword', '')
    
    if 'A' in grade and keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
            
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        if not existing:
            new_kw = MonitoredKeyword(
                user_id=user.id, keyword=keyword, search_volume=data.get('search_volume', 0),
                rank_info="최상단 노출", link=data.get('link', '#'), shipping_fee='-', 
                store_rank=data.get('store_rank', '-'), prev_store_rank='-'
            )
            db.session.add(new_kw)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved'})
        else: return jsonify({'success': True, 'message': 'Already exists'})
    return jsonify({'success': False, 'message': 'Not A grade'})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id, 'keyword': k.keyword, 'search_volume': k.search_volume, 'rank': k.rank_info,
            'link': k.link, 'publisher': k.publisher, 'supply_rate': k.supply_rate, 'isbn': k.isbn,
            'price': k.price, 'shipping_fee': k.shipping_fee, 'store_name': k.store_name,
            'book_title': k.book_title, 'product_link': k.product_link, 'store_rank': k.store_rank,
            'prev_store_rank': k.prev_store_rank 
        } for k in keywords]
    })

@monitoring_bp.route('/api/delete_keyword', methods=['POST'])
@login_required
def delete_keyword():
    kw_id = request.form.get('id')
    kw = MonitoredKeyword.query.filter_by(id=kw_id, user_id=current_user.id).first()
    if kw:
        db.session.delete(kw)
        db.session.commit()
    return jsonify({'success': True})

@monitoring_bp.route('/api/update_keyword', methods=['POST'])
@login_required
def update_keyword():
    kw_id = request.form.get('id')
    kw = MonitoredKeyword.query.filter_by(id=kw_id, user_id=current_user.id).first()
    if kw:
        kw.publisher = request.form.get('publisher', '-')
        kw.supply_rate = request.form.get('supply_rate', '-')
        kw.isbn = request.form.get('isbn', '-')
        kw.price = request.form.get('price', '-')
        kw.shipping_fee = request.form.get('shipping_fee', '-') 
        kw.store_name = request.form.get('store_name', '-')
        kw.book_title = request.form.get('book_title', '-')
        kw.product_link = request.form.get('product_link', '-')
        kw.store_rank = request.form.get('store_rank', '-')
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '데이터를 찾을 수 없습니다.'})

# ✨ [신규] 네이버 커머스 API 토큰 발급기
def get_commerce_token(client_id, client_secret):
    try:
        timestamp = str(int(time.time() * 1000))
        pwd = f"{client_id}_{timestamp}"
        hashed_pw = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
        client_secret_sign = base64.urlsafe_b64encode(hashed_pw).decode('utf-8')
        
        url = "https://api.commerce.naver.com/external/v1/oauth2/token"
        data = {
            "client_id": client_id,
            "timestamp": timestamp,
            "client_secret_sign": client_secret_sign,
            "grant_type": "client_credentials",
            "type": "SELF"
        }
        res = requests.post(url, data=data, timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
    except: pass
    return None

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        
        # 회원이 등록해둔 상점 API 키 가져오기
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = None
        if api_key:
            commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            rank = "500위 밖"
            
            # 1. 네이버 쇼핑 API로 순위 탐색
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
                        else:
                            if start_idx == 1: rank = "API에러"
                            break
                        if found: break
                        time.sleep(0.1)
            except: rank = "탐색 실패"
            kw.store_rank = rank

            # ✨ 2. [핵심] 커머스 API로 내 상품 정보 끌어오기!
            if commerce_token:
                try:
                    search_url = f"https://api.commerce.naver.com/external/v1/products/search?name={urllib.parse.quote(kw.keyword)}"
                    c_headers = {"Authorization": f"Bearer {commerce_token}"}
                    c_res = requests.get(search_url, headers=c_headers, timeout=5)
                    
                    if c_res.status_code == 200:
                        content = c_res.json()
                        if content.get('contents'): # 내 상점에 해당 상품이 존재하면!
                            product = content['contents'][0]
                            c_no = product.get('channelProducts', [{}])[0].get('channelProductNo')
                            o_no = product.get('originProductNo')
                            
                            # 정보 덮어쓰기
                            if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                            if product.get('salePrice'): kw.price = f"{product.get('salePrice'):,}원"
                            kw.store_name = "스터디박스"
                            kw.book_title = product.get('name', kw.keyword)

                            # 세부 정보(ISBN, 출판사) 가져오기
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

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_client_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    
    app = current_app._get_current_object()
    user_id = current_user.id
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_client_id, search_client_secret))
    thread.start()
            
    return jsonify({'success': True, 'message': '✅ 백그라운드 탐색 및 커머스 상품 정보 연동이 시작되었습니다!\n(화면에 실시간 반영됩니다.)'})
