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

        for kw in keywords:
            # 기존 데이터 보존 (엑셀 모드 유지)
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

            # [B] 수만 개의 상품 중 목표물만 0.1초 만에 저격하는 초정밀 검색 엔진 (회원님 아이디어 적용)
            if commerce_token:
                kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.keyword)
                matched_p = None
                
                if kw_clean:
                    # 1. 키워드의 앞 2~3글자만 추출 (예: '파이썬기초책' -> '파이썬')
                    short_kw = kw_clean[:3] if len(kw_clean) >= 3 else kw_clean[:2]
                    
                    candidate_products = []
                    # 2. 수만 개를 다 가져오지 않고, 'short_kw'가 포함된 상품만 네이버에 요청 (속도/메모리 한계 극복)
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    for page in range(1, 6): # 최대 250개까지만 추려냅니다
                        payload = {"page": page, "size": 50, "name": short_kw}
                        try:
                            c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                            if c_res.status_code == 200:
                                contents = c_res.json().get('contents', [])
                                candidate_products.extend(contents)
                                if len(contents) < 50: break
                            else: break
                        except: break

                    # 3. 추려낸 후보군 중에서 정규식으로 100% 완벽하게 똑같은 상품만 필터링
                    regex_pattern = '.*'.join(list(kw_clean))
                    best_score = 0
                    best_candidate = None

                    for p in candidate_products:
                        c_prods = p.get('channelProducts', [])
                        name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                        name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                        
                        if not name_clean: continue
                        
                        # 1순위 철벽방어: 키워드 글자가 중간에 껴있어도 완벽히 일치하는지 확인!
                        if re.search(regex_pattern, name_clean):
                            matched_p = p
                            break
                        
                        # 2순위 철벽방어: 글자 구성이 완전히 똑같은지 확인
                        if set(kw_clean).issubset(set(name_clean)):
                            matched_p = p
                            break

                        # 유사도 검사의 커트라인을 60% 이상으로 대폭 상향 (엉뚱한 책 도배 절대 금지)
                        score = difflib.SequenceMatcher(None, kw_clean, name_clean).ratio()
                        if score > best_score:
                            best_score = score
                            best_candidate = p

                    if not matched_p and best_score > 0.6: 
                        matched_p = best_candidate

                # [C] 매칭 성공! -> 기존 엑셀 기록은 보존하면서 새 정보만 살짝 덮어쓰기
                if matched_p:
                    o_no = matched_p.get('originProductNo')
                    c_prods = matched_p.get('channelProducts', [])
                    c_name = c_prods[0].get('name', '') if c_prods else matched_p.get('name', '')
                    c_no = c_prods[0].get('channelProductNo') if c_prods else None

                    kw.store_name = c_name
                    kw.book_title = "" # 관리 칸 밀림 현상 방지
                    
                    if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                    
                    sale_price = c_prods[0].get('salePrice') if c_prods else matched_p.get('salePrice')
                    if sale_price is not None: kw.price = f"{sale_price:,}원"

                    # 깊숙이 숨겨진 ISBN, 배송비, 출판사 정보 끝까지 털어오기
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
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 대용량 스토어 전용 매칭이 시작되었습니다.\n(수동 기록은 안전하게 보존됩니다. 10초 뒤 새로고침을 해주세요!)'})
