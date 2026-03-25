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
    grade_str = data.get('grade', '')
    keyword = data.get('keyword', '')
    
    # ✨ A, B, C 등급을 정확히 구별하여 저장
    grade_char = 'A'
    if 'C' in grade_str: grade_char = 'C'
    elif 'B' in grade_str: grade_char = 'B'

    if ('A' in grade_str or 'B' in grade_str or 'C' in grade_str) and keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        if not existing:
            new_kw = MonitoredKeyword(
                user_id=user.id, keyword=keyword, search_volume=data.get('search_volume', 0),
                # ✨ DB 수정을 피하기 위해 안 쓰던 rank_info 칸에 등급(A/B/C)을 몰래 저장합니다!
                rank_info=grade_char, 
                link=data.get('link', '#'), shipping_fee='-', 
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
            'id': k.id, 'keyword': k.keyword, 'search_volume': k.search_volume, 
            # ✨ 기존 데이터("최상단 노출")는 안전하게 모두 A등급으로 취급합니다!
            'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C'] else 'A'),
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

# ✨ [선택 항목 지우개] 체크된 항목들만 깔끔하게 비웁니다!
@monitoring_bp.route('/api/clear_data', methods=['POST'])
@login_required
def clear_data():
    user_id = current_user.id
    selected_ids = request.form.getlist('ids[]')
    
    query = MonitoredKeyword.query.filter_by(user_id=user_id)
    if selected_ids:
        query = query.filter(MonitoredKeyword.id.in_(selected_ids))
    keywords = query.all()

    if not keywords:
        return jsonify({'success': False, 'message': '초기화할 항목이 선택되지 않았습니다.'})

    for kw in keywords:
        kw.store_rank = '-'
        kw.prev_store_rank = '-'
        kw.product_link = '-'
        kw.price = '-'
        kw.shipping_fee = '-'
        kw.store_name = '-'
        kw.book_title = '-'
        # 🚨 수동 입력(키워드, ISBN, 출판사, 공급률)은 절대 건드리지 않습니다!
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목의 검색 정보가 초기화되었습니다.'})

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
        target_mall_name = api_key.store_name if api_key else "스터디박스"
        
        c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
        api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}

        for k_id in target_ids:
            kw = db.session.get(MonitoredKeyword, k_id)
            if not kw: 
                db.session.commit()
                continue
                
            keyword_text = kw.keyword
            target_isbn = kw.isbn
            db.session.commit()

            new_rank = "500위 밖"
            matched_mall_pid = None
            matched_origin_no = None
            updates = {}

            if api_headers and search_client_id:
                try:
                    found_rank = False
                    for start_idx in [1, 101, 201]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    new_rank = str(start_idx + idx)
                                    found_rank = True
                                    break
                        if found_rank: break
                except: pass

                try:
                    api_url = f"https://openapi.naver.com/v1/search/shop.json?query={target_isbn}&display=100&start=1"
                    api_res = requests.get(api_url, headers=api_headers, timeout=5)
                    if api_res.status_code == 200:
                        for item in api_res.json().get('items', []):
                            if target_mall_name in item.get('mallName', ''):
                                matched_mall_pid = item.get('mallProductId')
                                break
                except: pass

            if not matched_mall_pid and commerce_token:
                kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                short_kw = kw_clean[:3] if len(kw_clean) >= 3 else kw_clean
                
                candidate_products = []
                search_url = "https://api.commerce.naver.com/external/v1/products/search"
                if short_kw:
                    for page in range(1, 4):
                        payload = {"page": page, "size": 50, "name": short_kw}
                        try:
                            c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                            if c_res.status_code == 200:
                                candidate_products.extend(c_res.json().get('contents', []))
                        except: pass
                
                for p in candidate_products:
                    o_no = p.get('originProductNo')
                    if not o_no: continue
                    op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                    try:
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            book_isbn = op_data.get('detailAttribute', {}).get('bookInfo', {}).get('isbn', '')
                            
                            if target_isbn.replace('-','') in book_isbn.replace('-',''):
                                matched_origin_no = o_no
                                c_prods = p.get('channelProducts', [])
                                if c_prods: matched_mall_pid = c_prods[0].get('channelProductNo')
                                
                                updates['store_name'] = op_data.get('name', p.get('name'))
                                sale_price = op_data.get('salePrice')
                                if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                                fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                                break
                    except: pass

            if matched_mall_pid and not matched_origin_no and commerce_token:
                cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{matched_mall_pid}"
                try:
                    cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                    if cp_res.status_code == 200:
                        cp_data = cp_res.json()
                        matched_origin_no = cp_data.get('originProductNo')
                        updates['store_name'] = cp_data.get('name')
                        sale_price = cp_data.get('salePrice')
                        if sale_price is not None: updates['price'] = f"{sale_price:,}원"

                        if matched_origin_no:
                            op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{matched_origin_no}"
                            op_res = requests.get(op_url, headers=c_headers, timeout=5)
                            if op_res.status_code == 200:
                                op_data = op_res.json()
                                fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info and book_info.get('publisher'):
                                    updates['publisher'] = book_info.get('publisher')
                except: pass

            if matched_mall_pid or matched_origin_no:
                updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_mall_pid}"
            else:
                updates['store_name'] = "⚠️ 상점에 해당 ISBN 없음"

            kw = db.session.get(MonitoredKeyword, k_id)
            if kw:
                kw.store_rank = new_rank
                for key, val in updates.items():
                    if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                    setattr(kw, key, val)
                db.session.commit()

            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    return jsonify({'success': False, 'message': '체크박스로 항목을 선택한 뒤 ISBN 업데이트 버튼을 사용해주세요!'})

@monitoring_bp.route('/api/refresh_by_isbn', methods=['POST'])
@login_required
def refresh_by_isbn():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # ✨ 화면에서 체크(선택)된 항목들의 ID만 배열로 받아옵니다!
    selected_ids = request.form.getlist('ids[]')
    if not selected_ids:
        return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 먼저 체크박스로 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    target_ids = []
    
    for kw in keywords:
        if kw.isbn and kw.isbn != '-':
            if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
                kw.prev_store_rank = kw.store_rank
            kw.store_rank = "⏳ ISBN 매칭중..."
            target_ids.append(kw.id)
            
    db.session.commit()
    
    if not target_ids:
        return jsonify({'success': False, 'message': '⚠️ 선택한 항목 중에 ISBN이 입력된 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목의 ISBN 정밀 업데이트를 시작합니다.'})
