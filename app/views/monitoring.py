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
    return jsonify({'success': False})

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

def get_commerce_token(client_id, client_secret):
    try:
        timestamp = str(int(time.time() * 1000))
        pwd = f"{client_id}_{timestamp}"
        hashed_pw = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
        client_secret_sign = base64.urlsafe_b64encode(hashed_pw).decode('utf-8')
        url = "https://api.commerce.naver.com/external/v1/oauth2/token"
        data = {"client_id": client_id, "timestamp": timestamp, "client_secret_sign": client_secret_sign, "grant_type": "client_credentials", "type": "SELF"}
        res = requests.post(url, data=data, timeout=5)
        if res.status_code == 200: return res.json().get("access_token")
    except: pass
    return None

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = None
        if api_key: commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        for kw in keywords:
            # 새로고침 시 기존 데이터 초기화 (공급률 제외)
            kw.prev_store_rank = kw.store_rank
            kw.store_rank = "로딩중..."
            kw.book_title = "데이터 수집중..."
            kw.store_name = "-"
            kw.product_link = "-"
            kw.price = "-"
            kw.shipping_fee = "-"
            kw.isbn = "-"
            kw.publisher = "-"
            
            # 1. 네이버 쇼핑 일반 API 검색 (순위)
            if not search_client_id or not search_client_secret:
                kw.store_rank = "검색API키 누락"
            else:
                kw.store_rank = "500위 밖"
                try:
                    api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    kw.store_rank = str(start_idx + idx)
                                    found_rank = True
                                    break
                        else:
                            kw.store_rank = "API 오류/한도초과"
                            break
                        if found_rank: break
                        time.sleep(0.1)
                except:
                    kw.store_rank = "탐색 실패"

            # 2. 커머스 API 상세 정보 로드
            if not commerce_token:
                kw.book_title = "커머스 토큰/IP 오류"
            else:
                try:
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
                    
                    # 내 상점의 상품 50개를 불러와서 직접 대조합니다.
                    payload = {"page": 1, "size": 50}
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    
                    if c_res.status_code == 200:
                        contents = c_res.json().get('contents', [])
                        if not contents:
                            kw.book_title = "상점에 등록된 상품 없음"
                        else:
                            target_kw_clean = kw.keyword.replace(" ", "").lower()
                            matched = False
                            
                            for p in contents:
                                c_prods = p.get('channelProducts', [])
                                channel_name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                                clean_channel_name = channel_name.replace(" ", "").lower()
                                
                                # 키워드가 상점 상품명에 포함되어 있는지 띄어쓰기 무시하고 검사
                                if target_kw_clean in clean_channel_name:
                                    matched = True
                                    o_no = p.get('originProductNo')
                                    
                                    if o_no:
                                        detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                                        d_res = requests.get(detail_url, headers=c_headers, timeout=5)
                                        
                                        if d_res.status_code == 200:
                                            d_data = d_res.json()
                                            
                                            kw.book_title = d_data.get('name', channel_name)
                                            kw.store_name = api_key.store_name if api_key else "스터디박스"
                                            
                                            c_no = c_prods[0].get('channelProductNo') if c_prods else None
                                            if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                                            
                                            sale_price = d_data.get('salePrice')
                                            if sale_price is not None: kw.price = f"{sale_price:,}원"
                                            
                                            base_fee = d_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                            if base_fee is not None:
                                                kw.shipping_fee = "무료" if base_fee == 0 else f"{base_fee:,}원"
                                            
                                            book_info = d_data.get('detailAttribute', {}).get('bookInfo', {})
                                            if book_info:
                                                kw.isbn = book_info.get('isbn', '-')
                                                kw.publisher = book_info.get('publisher', '-')
                                    break 
                                    
                            if not matched:
                                kw.book_title = "이름 불일치 (검색실패)"
                    else:
                        kw.book_title = f"커머스 연결 거절 ({c_res.status_code})"
                except Exception as e:
                    kw.book_title = "시스템 에러 발생"

            db.session.commit()
            time.sleep(0.2)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 전체 순위 및 최신 상품 정보 조회가 시작되었습니다!\n새로고침 시 에러 원인이 표시됩니다.'})
