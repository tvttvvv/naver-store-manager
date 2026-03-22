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
            kw.prev_store_rank = kw.store_rank
            
            # 1. 네이버 쇼핑 일반 API로 순위 검색
            kw.store_rank = "500위 밖"
            try:
                if search_client_id and search_client_secret:
                    api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    kw.store_rank = str(start_idx + idx); found_rank = True; break
                        if found_rank: break
                        time.sleep(0.1)
            except: kw.store_rank = "탐색 실패"

            # 2. 커머스 API로 상점 상세 데이터 긁어오기 (이름 매칭 필터링 적용)
            if commerce_token:
                try:
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
                    # 키워드가 포함된 내 상품 리스트를 먼저 가져옴
                    payload = {"page": 1, "size": 30, "name": kw.keyword}
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    
                    if c_res.status_code == 200:
                        contents = c_res.json().get('contents', [])
                        target_kw_clean = kw.keyword.replace(" ", "").lower()
                        
                        for p in contents:
                            o_no = p.get('originProductNo') # 원본 상품 번호
                            if not o_no: continue
                            
                            # 상세 조회 API를 호출하여 진짜 데이터(배송비, ISBN 등)를 가져옴
                            detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                            d_res = requests.get(detail_url, headers=c_headers, timeout=5)
                            
                            if d_res.status_code == 200:
                                d_data = d_res.json()
                                real_name = d_data.get('name', '')
                                clean_real_name = real_name.replace(" ", "").lower()
                                
                                # ✨ [필터] 키워드가 상품명에 정확히 포함되어 있을 때만 데이터 수집
                                if target_kw_clean in clean_real_name:
                                    # 상품링크 (채널 상품번호 기반)
                                    c_prods = p.get('channelProducts', [])
                                    if c_prods:
                                        c_no = c_prods[0].get('channelProductNo')
                                        kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                                    
                                    # 상점 책제목 / 상점명 / 가격
                                    kw.book_title = real_name
                                    kw.store_name = api_key.store_name if api_key else "스터디박스"
                                    sale_price = d_data.get('salePrice')
                                    if sale_price is not None: kw.price = f"{sale_price:,}원"
                                    
                                    # 택배비 (기본 배송비 기준)
                                    delivery = d_data.get('deliveryInfo', {}).get('deliveryFee', {})
                                    base_fee = delivery.get('baseFee')
                                    if base_fee is not None:
                                        kw.shipping_fee = "무료" if base_fee == 0 else f"{base_fee:,}원"
                                    
                                    # ISBN / 출판사 (도서 정보 탭 데이터)
                                    book_info = d_data.get('detailAttribute', {}).get('bookInfo', {})
                                    if book_info:
                                        kw.isbn = book_info.get('isbn', '-')
                                        kw.publisher = book_info.get('publisher', '-')
                                    
                                    break # 정확한 매칭 상품을 찾았으므로 다음 키워드로 이동
                            time.sleep(0.2) # 네이버 API 호출 과부하 방지용 미세 지연
                except: pass

            # 매 키워드마다 즉시 저장해서 화면에 실시간 반영
            db.session.commit()
            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 전체 순위 및 상품 정보 동기화가 시작되었습니다!'})
