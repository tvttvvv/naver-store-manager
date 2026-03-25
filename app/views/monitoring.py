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
    
    # ✨ 백엔드 철벽 방어: null 값이 하나라도 있으면 프론트엔드가 뻗으므로 무조건 '-'로 덮어서 보냅니다!
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id, 
            'keyword': k.keyword or '-', 
            'search_volume': k.search_volume or 0, 
            'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C'] else 'A'),
            'link': k.link or '#', 
            'publisher': k.publisher or '-', 
            'supply_rate': k.supply_rate or '-', 
            'isbn': k.isbn or '-',
            'price': k.price or '-', 
            'shipping_fee': k.shipping_fee or '-', 
            'store_name': k.store_name or '-',
            'book_title': k.book_title or '-', 
            'product_link': k.product_link or '-', 
            'store_rank': k.store_rank or '-',
            'prev_store_rank': k.prev_store_rank or '-' 
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
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목의 검색 정보가 초기화되었습니다.'})

def get_real_title_from_external_sites(isbn, api_headers):
    isbn = isbn.replace('-', '').strip()
    if not isbn: return ""
    
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    
    if api_headers:
        try:
            url = f"https://openapi.naver.com/v1/search/book.json?query={isbn}"
            res = requests.get(url, headers=api_headers, timeout=3)
            if res.status_code == 200 and res.json().get('items'):
                title = res.json()['items'][0].get('title', '')
                title = re.sub(r'<[^>]*>', '', title)
                return re.sub(r'\(.*?\)', '', title).strip()
        except: pass
        
    try:
        url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchTarget=All&SearchWord={isbn}"
        res = requests.get(url, headers=headers, timeout=3)
        match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', res.text)
        if match:
            title = re.sub(r'<[^>]*>', '', match.group(1))
            return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    
    try:
        url = f"https://search.kyobobook.co.kr/search?keyword={isbn}"
        res = requests.get(url, headers=headers, timeout=3)
        match = re.search(r'<span class="prod_name">(.*?)</span>', res.text)
        if match: return match.group(1).strip()
    except: pass
    
    try:
        url = f"https://www.googleapis.com/books/v1/volumes?q=isbn:{isbn}"
        res = requests.get(url, timeout=3)
        if res.status_code == 200 and res.json().get('items'):
            return res.json()['items'][0]['volumeInfo'].get('title', '').strip()
    except: pass
    return ""

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
            target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
            db.session.commit()

            if not target_isbn: continue

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

            real_book_title = get_real_title_from_external_sites(target_isbn, api_headers)

            if not real_book_title:
                updates['book_title'] = "⚠️ ISBN으로 책 이름 찾기 실패 (외부망 전체 차단)"
            elif commerce_token:
                words = real_book_title.split()
                short_title = f"{words[0]} {words[1]}" if len(words) >= 2 else real_book_title
                
                candidate_products = []
                search_url = "https://api.commerce.naver.com/external/v1/products/search"
                
                for page in range(1, 4):
                    payload = {"page": page, "size": 50, "name": short_title}
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
                            book_isbn_clean = book_isbn.replace('-', '').strip() if book_isbn else ""
                            
                            if target_isbn in book_isbn_clean or (book_isbn_clean and book_isbn_clean in target_isbn):
                                matched_origin_no = o_no
                                c_prods = p.get('channelProducts', [])
                                if c_prods: matched_mall_pid = c_prods[0].get('channelProductNo')
                                
                                updates['store_name'] = op_data.get('name', p.get('name', '-'))
                                updates['book_title'] = "" 
                                sale_price = op_data.get('salePrice')
                                if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                                fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                                
                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info and book_info.get('publisher'): 
                                    updates['publisher'] = book_info.get('publisher')
                                elif 'publisher' not in updates:
                                    pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                    if pub_notice: updates['publisher'] = pub_notice
                                break 
                    except: pass

                if matched_mall_pid or matched_origin_no:
                    updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_mall_pid}"
                else:
                    updates['book_title'] = f"⚠️ 상점에 상품 없음 (이름: {short_title})"

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
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목에 대해 외부 사이트를 통한 우회 매칭을 시작합니다.'})
