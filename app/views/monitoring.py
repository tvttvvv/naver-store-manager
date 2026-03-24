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
        commerce_token = None
        if api_key: commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        # ✨ 1단계: 스토어의 전체 상품을 미리 한 번에 가져와서 메모리에 저장 (최대 500개)
        all_products = []
        c_headers = {}
        if commerce_token:
            search_url = "https://api.commerce.naver.com/external/v1/products/search"
            c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
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
            # 2단계: 쇼핑 순위 탐색 (일반 API)
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
                        if found_rank: break
                        time.sleep(0.1)
                except: rank_result = "탐색 실패"
            
            kw.store_rank = rank_result

            # ✨ 3단계: 무조건 100% 일치할 때만 가져오는 엄격한 매칭
            if not commerce_token:
                kw.store_name = "API 연결 오류"
            elif not all_products:
                kw.store_name = "스토어 상품 0개"
            else:
                kw_c = re.sub(r'[^a-zA-Z0-9가-힣]', '', kw.keyword)
                matched_p = None

                for p in all_products:
                    c_prods = p.get('channelProducts', [])
                    name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                    name_c = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                    
                    if not name_c: continue
                    
                    # 키워드 글자가 스토어 상품명에 그대로 다 들어있을 때만 통과 (어설픈 유사도 검사 폐기)
                    if kw_c in name_c:
                        matched_p = p
                        break

                if matched_p:
                    c_prods = matched_p.get('channelProducts', [])
                    channel_name = c_prods[0].get('name', '') if c_prods else matched_p.get('name', '')
                    c_no = c_prods[0].get('channelProductNo') if c_prods else None
                    o_no = matched_p.get('originProductNo')

                    # '상점 책제목' 칸에 정확한 상품명을 넣습니다.
                    kw.store_name = channel_name
                    # [핵심] '관리' 칸 밀림 현상을 막기 위해 book_title은 반드시 비워둡니다.
                    kw.book_title = "" 
                    
                    if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                    
                    sale_price = c_prods[0].get('salePrice') if c_prods else matched_p.get('salePrice')
                    if sale_price is not None: kw.price = f"{sale_price:,}원"

                    # ✨ 4단계: 숨겨진 ISBN, 출판사, 택배비 끝까지 추적해서 긁어오기
                    if o_no:
                        op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                        try:
                            op_res = requests.get(op_url, headers=c_headers, timeout=5)
                            if op_res.status_code == 200:
                                op_data = op_res.json()
                                
                                # 택배비 추출
                                base_fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if base_fee is not None:
                                    kw.shipping_fee = "무료" if base_fee == 0 else f"{base_fee:,}원"

                                # ISBN 및 출판사 추출 (도서 전용 속성 깊은 곳)
                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info:
                                    isbn = book_info.get('isbn')
                                    publisher = book_info.get('publisher')
                                    if isbn: kw.isbn = isbn
                                    if publisher: kw.publisher = publisher
                                
                                # (보험) 도서 정보 속성에 출판사가 없을 경우, 상품제공고시에서 한 번 더 찾기
                                if kw.publisher == "-":
                                    notice = op_data.get('productInfoProvidedNotice', {}).get('book', {})
                                    pub_notice = notice.get('publisher')
                                    if pub_notice: kw.publisher = pub_notice
                        except: pass
                else:
                    # 일치하는 상품이 진짜로 없을 때만 표시
                    kw.store_name = "키워드가 포함된 상품 없음"
                    kw.book_title = "" # 밀림 방지

            db.session.commit()
            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # 버튼 클릭 즉시 화면 피드백
    keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
    for kw in keywords:
        kw.store_rank = "⏳ 순위 검색중..."
        kw.store_name = "⏳ 데이터 로딩중..." 
        kw.book_title = "" # 밀림 방지를 위해 무조건 비움
        kw.product_link = "-"
        kw.price = "-"
        kw.shipping_fee = "-"
        kw.isbn = "-"
        kw.publisher = "-"
    db.session.commit()
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드에서 정확도 100% 매칭 작업이 시작되었습니다.\n5초 뒤 새로고침을 해주세요.'})
