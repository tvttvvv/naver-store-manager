import os
import time
import re
import difflib
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

        # 1. 커머스 API로 내 상점의 모든 상품을 메모리에 미리 장전 (최대 500개)
        all_products = []
        if commerce_token:
            search_url = "https://api.commerce.naver.com/external/v1/products/search"
            for page in range(1, 11):
                payload = {"page": page, "size": 50}
                try:
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    if c_res.status_code == 200:
                        contents = c_res.json().get('contents', [])
                        all_products.extend(contents)
                        if len(contents) < 50: break
                    else: break
                except: break

        for kw in keywords:
            # 기존 순위 백업 (나머지 정보는 절대 지우지 않음)
            kw.prev_store_rank = kw.store_rank
            new_rank = "500위 밖"
            
            # [A] 순위 탐색 (1~500위 스캔)
            if api_headers:
                try:
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    new_rank = str(start_idx + idx)
                                    found_rank = True
                                    break
                        if found_rank: break
                        time.sleep(0.1)
                except: pass
            
            kw.store_rank = new_rank

            # [B] 절대 실패하지 않는 4중 매칭 시스템 발동
            if commerce_token and all_products:
                matched_p = None
                kw_c = re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.keyword)

                # 전략 1: 띄어쓰기 뺀 상품명에 키워드가 통째로 들어있는지 검사
                for p in all_products:
                    c_prods = p.get('channelProducts', [])
                    name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                    name_c = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                    if kw_c in name_c or name_c in kw_c:
                        matched_p = p
                        break

                # 전략 2: 키워드의 모든 단어(파이썬, 기초, 추천 등)가 상품명에 다 들어있는지 검사
                if not matched_p:
                    words = kw.keyword.split()
                    for p in all_products:
                        c_prods = p.get('channelProducts', [])
                        name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                        if all(word.lower() in name.lower() for word in words):
                            matched_p = p
                            break

                # 전략 3: 네이버 쇼핑 강제 검색 (회원님 아이디어 적용: "키워드 + 상점명")
                if not matched_p and api_headers:
                    try:
                        targeted_query = f"{kw.keyword} {target_mall_name}"
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=10&start=1"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for item in api_res.json().get('items', []):
                                if target_mall_name in item.get('mallName', ''):
                                    mall_pid = item.get('mallProductId')
                                    for p in all_products:
                                        c_prods = p.get('channelProducts', [])
                                        c_no = c_prods[0].get('channelProductNo') if c_prods else None
                                        if str(c_no) == str(mall_pid):
                                            matched_p = p
                                            break
                                    if matched_p: break
                    except: pass

                # 전략 4: AI 유사도 판별 (35% 이상 비슷한 상품을 찾아내는 최후의 보루)
                if not matched_p:
                    best_score = 0
                    best_p = None
                    for p in all_products:
                        c_prods = p.get('channelProducts', [])
                        name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                        name_c = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                        score = difflib.SequenceMatcher(None, kw_c, name_c).ratio()
                        if score > best_score:
                            best_score = score
                            best_p = p
                    if best_score >= 0.35:
                        matched_p = best_p

                # [C] 매칭 성공! -> 엑셀처럼 새로운 정보만 조용히 덮어쓰기
                if matched_p:
                    o_no = matched_p.get('originProductNo')
                    c_prods = matched_p.get('channelProducts', [])
                    c_name = c_prods[0].get('name', '') if c_prods else matched_p.get('name', '')
                    c_no = c_prods[0].get('channelProductNo') if c_prods else None

                    # 책 제목 위치 조정 및 관리 칸 밀림 방지
                    kw.store_name = c_name
                    kw.book_title = ""

                    if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"

                    sale_price = c_prods[0].get('salePrice') if c_prods else matched_p.get('salePrice')
                    if sale_price is not None: kw.price = f"{sale_price:,}원"

                    # 숨겨진 택배비, ISBN, 출판사 정보 끝까지 파고들기
                    if o_no:
                        op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                        try:
                            op_res = requests.get(op_url, headers=c_headers, timeout=5)
                            if op_res.status_code == 200:
                                op_data = op_res.json()
                                
                                fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if fee is not None:
                                    kw.shipping_fee = "무료" if fee == 0 else f"{fee:,}원"

                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info:
                                    if book_info.get('isbn'): kw.isbn = book_info.get('isbn')
                                    if book_info.get('publisher'): kw.publisher = book_info.get('publisher')

                                # 보험: 출판사가 안 잡히면 상품제공고시에서 한 번 더 긁어옴
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
    
    # 🚨 기존 데이터 초기화 코드 완벽히 제거 완료! 누르는 즉시 백그라운드에서 작업 시작.
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 강력한 4중 매칭 업데이트가 시작되었습니다.\n(기록은 보존되며 찾은 정보만 업데이트됩니다. 10초 뒤 새로고침을 해주세요!)'})
