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

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret, kw_ids=None):
    with app.app_context():
        # ✨ 1단계: 필요한 ID만 빨리 가져오고 DB 잠금을 즉시 해제합니다! (Database is locked 에러 완벽 해결)
        if kw_ids:
            target_ids = kw_ids
        else:
            kws = MonitoredKeyword.query.filter_by(user_id=user_id).all()
            target_ids = [k.id for k in kws]
            
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
        target_mall_name = api_key.store_name if api_key else "스터디박스"
        
        db.session.commit() # 🔥 여기서 DB 접속을 닫아서 다른 작업이 막히지 않게 합니다.

        if not target_ids: return

        c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
        api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}

        for k_id in target_ids:
            # 작업할 키워드 정보만 딱 0.1초 열어서 가져오고 다시 닫습니다.
            kw = db.session.get(MonitoredKeyword, k_id)
            if not kw: 
                db.session.commit()
                continue
                
            keyword_text = kw.keyword
            db.session.commit() # 🔥 DB 잠금 즉시 해제

            new_rank = "500위 밖"
            matched_mall_pid = None

            # [전략 1] 네이버 쇼핑 1~500위 스캔
            if api_headers and search_client_id:
                try:
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    new_rank = str(start_idx + idx)
                                    matched_mall_pid = item.get('mallProductId')
                                    found_rank = True
                                    break
                        if found_rank: break
                        time.sleep(0.1)
                except: pass

            # [전략 2] 못 찾았으면 네이버 강제 검색 (키워드 + 상점명)
            if not matched_mall_pid and api_headers and search_client_id:
                try:
                    targeted_query = f"{keyword_text} {target_mall_name}"
                    api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=20&start=1"
                    api_res = requests.get(api_url, headers=api_headers, timeout=5)
                    if api_res.status_code == 200:
                        for item in api_res.json().get('items', []):
                            if target_mall_name in item.get('mallName', ''):
                                matched_mall_pid = item.get('mallProductId')
                                break
                except: pass

            # [전략 3] 커머스 API 상세 정보 추출
            updates = {}
            if commerce_token:
                matched_origin_no = None
                matched_channel_name = None
                matched_sale_price = None
                matched_c_no = None

                if matched_mall_pid:
                    cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{matched_mall_pid}"
                    try:
                        cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                        if cp_res.status_code == 200:
                            cp_data = cp_res.json()
                            matched_origin_no = cp_data.get('originProductNo')
                            matched_channel_name = cp_data.get('name')
                            matched_sale_price = cp_data.get('salePrice')
                            matched_c_no = matched_mall_pid
                    except: pass

                # 네이버 검색망도 못 뚫었다면 커머스 내부 필터링 발동
                if not matched_origin_no:
                    kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                    short_kw = kw_clean[:4] if len(kw_clean) >= 4 else kw_clean
                    
                    candidate_products = []
                    if short_kw:
                        search_url = "https://api.commerce.naver.com/external/v1/products/search"
                        for page in range(1, 4):
                            payload = {"page": page, "size": 50, "name": short_kw}
                            try:
                                c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                                if c_res.status_code == 200:
                                    contents = c_res.json().get('contents', [])
                                    candidate_products.extend(contents)
                                    if len(contents) < 50: break
                                else: break
                            except: break
                        
                        regex_pattern = '.*'.join(list(kw_clean))
                        best_score = 0
                        best_p = None
                        
                        for p in candidate_products:
                            c_prods = p.get('channelProducts', [])
                            name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                            name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                            if not name_clean: continue
                            
                            if re.search(regex_pattern, name_clean):
                                best_p = p
                                break
                                
                            score = difflib.SequenceMatcher(None, kw_clean, name_clean).ratio()
                            if score > best_score:
                                best_score = score
                                best_p = p
                                
                        if best_p and (best_p == candidate_products[0] or best_score > 0.45):
                            c_prods = best_p.get('channelProducts', [])
                            matched_origin_no = best_p.get('originProductNo')
                            matched_channel_name = c_prods[0].get('name', '') if c_prods else best_p.get('name', '')
                            matched_sale_price = c_prods[0].get('salePrice') if c_prods else best_p.get('salePrice')
                            matched_c_no = c_prods[0].get('channelProductNo') if c_prods else None

                if matched_origin_no:
                    op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{matched_origin_no}"
                    try:
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            
                            updates['store_name'] = matched_channel_name
                            updates['book_title'] = "" 
                            
                            if matched_c_no: updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_c_no}"
                            if matched_sale_price is not None: updates['price'] = f"{matched_sale_price:,}원"
                                
                            fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                            if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"

                            book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                            if book_info:
                                if book_info.get('isbn'): updates['isbn'] = book_info.get('isbn')
                                if book_info.get('publisher'): updates['publisher'] = book_info.get('publisher')

                            # 출판사 보험 추출
                            if 'publisher' not in updates:
                                pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                if pub_notice: updates['publisher'] = pub_notice
                    except: pass

            # ✨ 4단계: 업데이트할 데이터가 준비되면 딱 0.1초만 DB를 열어 저장하고 즉시 닫습니다.
            kw = db.session.get(MonitoredKeyword, k_id)
            if kw:
                kw.store_rank = new_rank
                for key, val in updates.items():
                    setattr(kw, key, val)
                db.session.commit() # 🔥 최종 저장 및 DB 잠금 즉시 해제

            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
    for kw in keywords:
        if "갱신중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 갱신중..."
    db.session.commit()
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw, None))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 전체 갱신이 시작되었습니다. (약 5~10초 뒤 완료됩니다)'})

@monitoring_bp.route('/api/refresh_keyword', methods=['POST'])
@login_required
def refresh_keyword():
    kw_id = request.form.get('id')
    if not kw_id: return jsonify({'success': False})
    
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    kw = MonitoredKeyword.query.filter_by(id=kw_id, user_id=user_id).first()
    if kw:
        if "갱신중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 갱신중..."
        db.session.commit()
        
        thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw, [kw.id]))
        thread.start()
        return jsonify({'success': True, 'message': f'✅ [{kw.keyword}] 개별 업데이트 명령이 전송되었습니다.'})
    return jsonify({'success': False})
