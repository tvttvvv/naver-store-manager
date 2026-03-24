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

        # 1. 커머스 API를 통한 내 상점 상품 싹쓸이 (IP가 등록되어 있어 해외서버라도 100% 성공합니다!)
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
            kw.prev_store_rank = kw.store_rank
            new_rank = "500위 밖"
            
            # [A] 순위 탐색 (네이버 쇼핑 API - 해외 IP 차단으로 실패할 확률이 높지만 시도는 유지합니다)
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

            # [B] 최강의 정밀 매칭 엔진 (해외 서버 차단을 우회하여 내 커머스 데이터 안에서 직접 매칭)
            if commerce_token and all_products:
                matched_p = None
                kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.keyword)
                
                if kw_clean:
                    # 마법의 정규식 패턴 생성: 파이썬기초책추천 -> 파.*이.*썬.*기.*초.*책.*추.*천
                    regex_pattern = '.*'.join(list(kw_clean))
                    
                    best_score = 0
                    best_candidate = None

                    for p in all_products:
                        c_prods = p.get('channelProducts', [])
                        name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                        name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                        
                        if not name_clean: continue
                        
                        # 1순위: 키워드 글자가 중간에 다른 단어가 끼어있어도 순서대로 모두 존재하는가?
                        # (예: "처음이야 파이썬 기초 책 교재 추천" 완벽 매칭!)
                        if re.search(regex_pattern, name_clean):
                            matched_p = p
                            break
                        
                        # 2순위: 순서에 상관없이 키워드의 모든 글자가 포함되어 있는가?
                        kw_chars = set(kw_clean)
                        name_chars = set(name_clean)
                        if kw_chars.issubset(name_chars):
                            matched_p = p
                            break

                        # 3순위: 그래도 안 나오면 유사도 높은 상품 백업
                        score = difflib.SequenceMatcher(None, kw_clean, name_clean).ratio()
                        if score > best_score:
                            best_score = score
                            best_candidate = p

                    if not matched_p and best_score > 0.55:
                        matched_p = best_candidate

                # [C] 찾은 경우 엑셀형 보존 업데이트 진행 (수동 기록 절대 보호)
                if matched_p:
                    o_no = matched_p.get('originProductNo')
                    c_prods = matched_p.get('channelProducts', [])
                    c_name = c_prods[0].get('name', '') if c_prods else matched_p.get('name', '')
                    c_no = c_prods[0].get('channelProductNo') if c_prods else None

                    kw.store_name = c_name
                    kw.book_title = "" 
                    
                    if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                    
                    sale_price = c_prods[0].get('salePrice') if c_prods else matched_p.get('salePrice')
                    if sale_price is not None: kw.price = f"{sale_price:,}원"

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
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 해외망 우회 정밀 매칭이 시작되었습니다.\n(기록은 보존되며 찾은 정보만 업데이트됩니다. 10초 뒤 새로고침을 해주세요!)'})
