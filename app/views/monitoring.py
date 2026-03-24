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
        commerce_token = None
        if api_key: commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        # ✨ [핵심 해결책 1] 상점의 '모든' 상품을 먼저 파이썬 메모리로 다 가져옵니다!
        all_products = []
        c_headers = {}
        if commerce_token:
            search_url = "https://api.commerce.naver.com/external/v1/products/search"
            c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
            # 1페이지부터 5페이지까지 넉넉하게 스토어 전체 상품 로드
            for page in range(1, 6):
                payload = {"page": page, "size": 50}
                try:
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    if c_res.status_code == 200:
                        contents = c_res.json().get('contents', [])
                        all_products.extend(contents)
                        if len(contents) < 50: break
                    else: break
                except: break

        def clean_text(text):
            # 띄어쓰기, 특수문자 전부 날리고 순수 글자만 뭉칩니다.
            return re.sub(r'[^a-zA-Z0-9가-힣]', '', str(text))

        for kw in keywords:
            # 1. 네이버 쇼핑 일반 API 검색 (순위 탐색)
            rank_result = "500위 밖"
            if search_client_id and search_client_secret:
                try:
                    api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    rank_result = str(start_idx + idx)
                                    found_rank = True
                                    break
                        else:
                            rank_result = "API오류/한도초과"
                            break
                        if found_rank: break
                        time.sleep(0.1)
                except: rank_result = "탐색 실패"
            else:
                rank_result = "검색키 누락"
            
            kw.store_rank = rank_result

            # ✨ [핵심 해결책 2] 메모리에 있는 전체 상품과 키워드를 초정밀 대조
            if not commerce_token:
                kw.store_name = "커머스 연결 오류"
            elif not all_products:
                kw.store_name = "상점 내 상품 없음"
            else:
                kw_c = clean_text(kw.keyword)
                matched_p = None
                best_score = 0
                best_p = None

                for p in all_products:
                    c_prods = p.get('channelProducts', [])
                    name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                    name_c = clean_text(name)
                    if not name_c: continue

                    # 100% 포함 검사: "주도주매매법"이 "주도주매매법책" 안에 들어있으면 합격!
                    if name_c in kw_c or kw_c in name_c:
                        matched_p = p
                        break
                    
                    # 깐깐한 검사에 실패해도 가장 비슷한 상품(유사도)을 찾아서 보험으로 둡니다.
                    score = difflib.SequenceMatcher(None, kw_c, name_c).ratio()
                    if score > best_score:
                        best_score = score
                        best_p = p

                # 완벽하게 똑같은 글자가 없더라도, 35% 이상 비슷하면 그 책이라고 간주! (도배 방지)
                if not matched_p and best_score > 0.35:
                    matched_p = best_p

                # ✨ [핵심 해결책 3] 매칭 성공 시 데이터 채우기 (자리 꼬임 방지 적용)
                if matched_p:
                    o_no = matched_p.get('originProductNo')
                    c_prods = matched_p.get('channelProducts', [])
                    channel_name = c_prods[0].get('name', '') if c_prods else matched_p.get('name', '')
                    c_no = c_prods[0].get('channelProductNo') if c_prods else None

                    # 화면에서 '상점 책제목' 칸이 store_name과 연결되어 있으므로 여기에 책 제목을 넣습니다.
                    kw.store_name = channel_name
                    kw.book_title = channel_name 
                    
                    if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                    
                    sale_price = c_prods[0].get('salePrice') if c_prods else matched_p.get('salePrice')
                    if sale_price is not None: kw.price = f"{sale_price:,}원"

                    # 4. 상세 정보(택배비, ISBN 등) 개별 조회
                    if o_no:
                        op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                        try:
                            op_res = requests.get(op_url, headers=c_headers, timeout=5)
                            if op_res.status_code == 200:
                                op_data = op_res.json()
                                
                                base_fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if base_fee is not None:
                                    kw.shipping_fee = "무료" if base_fee == 0 else f"{base_fee:,}원"

                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info:
                                    kw.isbn = book_info.get('isbn', '-')
                                    kw.publisher = book_info.get('publisher', '-')
                        except: pass
                else:
                    kw.store_name = "키워드와 비슷한 상품 없음"

            db.session.commit()
            time.sleep(0.2)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # 누르는 즉시 화면 피드백을 주기 위해 전체 초기화 (공급률 제외)
    keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
    for kw in keywords:
        kw.store_rank = "⏳ 순위 탐색중..."
        kw.store_name = "⏳ 상품 조회중..." 
        kw.book_title = "-"
        kw.product_link = "-"
        kw.price = "-"
        kw.shipping_fee = "-"
        kw.isbn = "-"
        kw.publisher = "-"
    db.session.commit()
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 데이터 갱신이 시작되었습니다.\n5초마다 새로고침(F5)을 눌러 실시간 진행 상황을 확인하세요!'})
