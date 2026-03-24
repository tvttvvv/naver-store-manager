import os
import time
import re
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
        commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
        target_mall_name = api_key.store_name if api_key else "스터디박스"

        c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
        api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}

        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            
            # 기존 데이터를 유지하기 위해 초기화하지 않습니다. (엑셀 보존 모드)
            found_rank = "500위 밖"
            mall_product_id = None
            new_title = None
            new_price = None
            new_link = None

            if api_headers:
                # ✨ 1단계: 순위 1~500위 정밀 스캔
                try:
                    is_found_in_top_500 = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    found_rank = str(start_idx + idx)
                                    mall_product_id = item.get('mallProductId') # 핵심 고유번호 획득!
                                    new_title = re.sub(r'<[^>]*>', '', item.get('title', ''))
                                    new_price = f"{int(item.get('lprice', 0)):,}원"
                                    new_link = item.get('link', '')
                                    is_found_in_top_500 = True
                                    break
                        if is_found_in_top_500: break
                        time.sleep(0.1)
                except: pass

                kw.store_rank = found_rank

                # ✨ 2단계: 500위 밖이라서 못 찾았다면? 네이버 검색엔진 강제 소환 (회원님 아이디어)
                if not mall_product_id:
                    try:
                        # 키워드 + 내 상점명으로 네이버에 직접 검색! (예: 파이썬기초책추천 스터디박스)
                        targeted_query = f"{kw.keyword} {target_mall_name}"
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=10&start=1"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for item in api_res.json().get('items', []):
                                if target_mall_name in item.get('mallName', ''):
                                    mall_product_id = item.get('mallProductId') # 무조건 찾아서 고유번호 획득!
                                    new_title = re.sub(r'<[^>]*>', '', item.get('title', ''))
                                    new_price = f"{int(item.get('lprice', 0)):,}원"
                                    new_link = item.get('link', '')
                                    break
                    except: pass

            # ✨ 3단계: 찾아낸 고유번호로 겉으로 드러난 정보 업데이트
            if mall_product_id:
                kw.store_name = new_title # 상점 책제목 칸에 예쁘게 배치
                kw.book_title = "" # 관리칸 밀림 방지
                kw.price = new_price
                kw.product_link = new_link
                
                # ✨ 4단계: 커머스 전산망 뚫고 숨겨진 ISBN, 배송비, 출판사 가져오기
                if commerce_token:
                    try:
                        cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{mall_product_id}"
                        cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                        if cp_res.status_code == 200:
                            origin_no = cp_res.json().get('originProductNo')
                            if origin_no:
                                op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{origin_no}"
                                op_res = requests.get(op_url, headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    op_data = op_res.json()
                                    
                                    # 택배비 추출
                                    fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                    if fee is not None:
                                        kw.shipping_fee = "무료" if fee == 0 else f"{fee:,}원"

                                    # 출판사, ISBN 추출 (도서 전용 속성)
                                    book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                    if book_info:
                                        if book_info.get('isbn'): kw.isbn = book_info.get('isbn')
                                        if book_info.get('publisher'): kw.publisher = book_info.get('publisher')
                                    
                                    # (보험) 출판사가 비어있으면 상품제공고시에서 한 번 더 추출
                                    if kw.publisher == "-" or not kw.publisher:
                                        pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                        if pub_notice: kw.publisher = pub_notice
                    except: pass

            db.session.commit()
            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # 🚨 기존 데이터를 지우는 악성 코드를 완전히 삭제했습니다!
    # 데이터는 화면에 그대로 안전하게 유지되며, 백그라운드에서 찾은 새 정보만 살짝 덮어씁니다.
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 안전한 업데이트가 시작되었습니다.\n(기존 기록은 보존되며 새로운 정보만 덮어씁니다. 잠시 후 새로고침을 해주세요!)'})
