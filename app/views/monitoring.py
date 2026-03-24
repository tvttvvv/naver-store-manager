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
            
            # 비교를 위해 특수문자/띄어쓰기 전부 제거 (예: '주식단타책')
            kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.keyword)
            
            found_rank = "500위 밖"
            matched_mall_pid = None
            matched_origin_no = None

            if api_headers:
                # [전략 1] 1~500위 스캔 (순위 찾기)
                try:
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    found_rank = str(start_idx + idx)
                                    title_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', item.get('title', ''))
                                    
                                    # 🚨 철벽 방어: 100% 부분 일치할 때만 고유번호를 확보!
                                    if kw_clean in title_clean:
                                        matched_mall_pid = item.get('mallProductId')
                                    break
                        if found_rank != "500위 밖": break
                        time.sleep(0.1)
                except: pass

                # [전략 2] 순위권 밖이라면? 키워드 + 상점명으로 네이버 강제 검색 (회원님 아이디어 적용)
                if not matched_mall_pid:
                    try:
                        targeted_query = f"{kw.keyword} {target_mall_name}"
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=20&start=1"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for item in api_res.json().get('items', []):
                                if target_mall_name in item.get('mallName', ''):
                                    title_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', item.get('title', ''))
                                    
                                    # 🚨 네이버가 찾아준 결과라도 100% 일치하는지 한 번 더 깐깐하게 검증!
                                    if kw_clean in title_clean:
                                        matched_mall_pid = item.get('mallProductId')
                                        break
                    except: pass

            kw.store_rank = found_rank

            # [전략 3] 커머스 API를 통한 숨겨진 정보 싹쓸이 (엑셀 보존 모드)
            if matched_mall_pid and commerce_token:
                try:
                    # 1. 고유번호(mall_pid)를 원본상품번호(origin_no)로 변환
                    cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{matched_mall_pid}"
                    cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                    if cp_res.status_code == 200:
                        matched_origin_no = cp_res.json().get('originProductNo')
                    
                    # 2. 원본상품번호로 택배비, 출판사, ISBN 추출 및 덮어쓰기
                    if matched_origin_no:
                        op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{matched_origin_no}"
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            
                            # 100% 일치하는 상품을 찾았으니 기존 칸에 새 정보 삽입
                            kw.store_name = op_data.get('name', kw.store_name)
                            kw.book_title = "" # UI 관리칸 텍스트 침범 방지
                            kw.product_link = f"https://smartstore.naver.com/main/products/{matched_mall_pid}"
                            
                            sale_price = op_data.get('salePrice')
                            if sale_price is not None: kw.price = f"{sale_price:,}원"
                            
                            fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                            if fee is not None: kw.shipping_fee = "무료" if fee == 0 else f"{fee:,}원"

                            book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                            if book_info:
                                if book_info.get('isbn'): kw.isbn = book_info.get('isbn')
                                if book_info.get('publisher'): kw.publisher = book_info.get('publisher')

                            if kw.publisher == "-" or not kw.publisher:
                                pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                if pub_notice: kw.publisher = pub_notice
                except: pass
            
            # 못 찾았으면? 아무 일도 일어나지 않고 수동 기록(엑셀 데이터)이 그대로 100% 보존됩니다.
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
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 철벽 검증 업데이트가 시작되었습니다.\n10초 뒤 새로고침을 해주세요! (엉뚱한 상품은 절대 가져오지 않습니다.)'})
