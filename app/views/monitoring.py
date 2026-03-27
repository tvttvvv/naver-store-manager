import os
import time
import re
import traceback
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword, ApiKey
import requests
import urllib.parse
import bcrypt
import base64
import json

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/')
@login_required
def index():
    return render_template('monitoring/index.html')

@monitoring_bp.route('/api/webhook', methods=['POST'])
def receive_webhook():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'message': 'No data'})
    grade_str = str(data.get('grade', '')).upper()
    keyword = data.get('keyword', '')
    grade_char = 'A'
    if 'C' in grade_str: grade_char = 'C'
    elif 'B' in grade_str: grade_char = 'B'
    if keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        if not existing:
            new_kw = MonitoredKeyword(user_id=user.id, keyword=keyword, search_volume=data.get('search_volume', 0), rank_info=grade_char, link=data.get('link', '#'), shipping_fee='-', store_rank=data.get('store_rank', '-'), prev_store_rank='-')
            db.session.add(new_kw)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved'})
    return jsonify({'success': False})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({'success': True, 'data': [{'id': k.id, 'keyword': k.keyword or '-', 'search_volume': k.search_volume or 0, 'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C'] else 'A'), 'link': k.link or '#', 'publisher': k.publisher or '-', 'supply_rate': k.supply_rate or '-', 'isbn': k.isbn or '-', 'price': k.price or '-', 'shipping_fee': k.shipping_fee or '-', 'store_name': k.store_name or '-', 'book_title': k.book_title or '-', 'product_link': k.product_link or '-', 'store_rank': k.store_rank or '-', 'prev_store_rank': k.prev_store_rank or '-'} for k in keywords]})

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

@monitoring_bp.route('/api/change_grade', methods=['POST'])
@login_required
def change_grade():
    user_id = current_user.id
    selected_ids = request.form.getlist('ids[]')
    new_grade = request.form.get('grade', 'A')
    if not selected_ids: return jsonify({'success': False, 'message': '이동할 항목을 선택해주세요.'})
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    for kw in keywords: kw.rank_info = new_grade
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목이 {new_grade}등급으로 이동되었습니다.'})

@monitoring_bp.route('/api/clear_data', methods=['POST'])
@login_required
def clear_data():
    user_id = current_user.id
    selected_ids = request.form.getlist('ids[]')
    query = MonitoredKeyword.query.filter_by(user_id=user_id)
    if selected_ids: query = query.filter(MonitoredKeyword.id.in_(selected_ids))
    for kw in query.all():
        kw.store_rank = '-'
        kw.prev_store_rank = '-'
        kw.product_link = '-'
        kw.price = '-'
        kw.shipping_fee = '-'
        kw.store_name = '-'
        kw.book_title = '-'
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 항목의 검색 정보가 초기화되었습니다.'})

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

def get_real_title_via_proxy(isbn):
    isbn = isbn.replace('-', '').strip()
    if not isbn: return ""
    try:
        aladin_url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord={isbn}"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(aladin_url)}"
        res = requests.get(proxy_url, timeout=5)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    return ""

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] DETAILED LOGGING (User: {user_id}) ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            
            print(f"[CCTV] Commerce Token Exists: {bool(commerce_token)}", flush=True)
            print(f"[CCTV] Naver API Key Exists: {bool(search_client_id)}", flush=True)
            print(f"[CCTV] Target Mall Name: {target_mall_name}", flush=True)

        except Exception as e:
            print(f"[CCTV ERROR] Setup Failed: {e}", flush=True)

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: continue
                    
                keyword_text = str(kw.keyword or "")
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                print(f"\n[CCTV] Processing Keyword: '{keyword_text}' | ISBN: '{target_isbn}'", flush=True)

                updates = {
                    'store_rank': '500위 밖',
                    'price': '-',
                    'product_link': '-',
                    'shipping_fee': '-',
                    'book_title': '⚠️ 매칭 실패'
                }

                # 1. Book API Test
                real_book_title = ""
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    print(f"[CCTV] 1. Requesting Book API with query: {search_query}", flush=True)
                    book_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}"
                    book_res = requests.get(book_url, headers=api_headers, timeout=5)
                    print(f"[CCTV] 1. Book API Status: {book_res.status_code}", flush=True)
                    
                    if book_res.status_code == 200 and book_res.json().get('items'):
                        item = book_res.json()['items'][0]
                        raw_title = item.get('title', '')
                        title_clean = re.sub(r'<[^>]*>', '', raw_title)
                        real_book_title = re.sub(r'\(.*?\)', '', title_clean).strip()
                        print(f"[CCTV] 1. Found Real Title: {real_book_title}", flush=True)
                        updates['book_title'] = real_book_title
                        
                        if item.get('publisher'): updates['publisher'] = item.get('publisher')

                # 2. Shop API Targeting Test
                matched_mall_pid = None
                print(f"[CCTV] 2. Requesting Shop API Targeting...", flush=True)
                if api_headers and search_client_id:
                    search_queries = [f"{keyword_text} {target_mall_name}", f"{real_book_title} {target_mall_name}"]
                    for q in search_queries:
                        if matched_mall_pid or not q.strip() or q == f" {target_mall_name}": continue
                        print(f"[CCTV] 2. Querying Shop API: '{q}'", flush=True)
                        url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(q)}&display=10"
                        res = requests.get(url, headers=api_headers, timeout=5)
                        print(f"[CCTV] 2. Shop API Status: {res.status_code}", flush=True)
                        if res.status_code == 200:
                            items = res.json().get('items', [])
                            print(f"[CCTV] 2. Shop API returned {len(items)} items", flush=True)
                            for item in items:
                                print(f"[CCTV] 2. Inspecting Item Mall: '{item.get('mallName')}'", flush=True)
                                if target_mall_name in item.get('mallName', ''):
                                    matched_mall_pid = item.get('mallProductId')
                                    updates['product_link'] = item.get('link')
                                    updates['price'] = f"{int(item.get('lprice', 0)):,}원"
                                    updates['store_name'] = item.get('mallName')
                                    print(f"[CCTV] 2. -> MATCHED! PID: {matched_mall_pid}", flush=True)
                                    break
                
                # 3. Commerce API Search Fallback
                if not matched_mall_pid and commerce_token:
                    print(f"[CCTV] 3. Shop API Targeting failed. Trying Commerce API NAME Search...", flush=True)
                    term = real_book_title if real_book_title else keyword_text
                    payload = {"page": 1, "size": 20, "searchKeywordType": "NAME", "searchKeyword": term}
                    c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                    print(f"[CCTV] 3. Commerce Search Status: {c_res.status_code}", flush=True)
                    if c_res.status_code == 200:
                        contents = c_res.json().get('contents', [])
                        print(f"[CCTV] 3. Commerce Search found {len(contents)} items.", flush=True)
                        for p in contents:
                            o_no = p.get('originProductNo')
                            print(f"[CCTV] 3. Inspecting OriginNo: {o_no}", flush=True)
                            if o_no:
                                op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}", headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    op_data = op_res.json().get('originProduct', op_res.json())
                                    p_name = str(op_data.get('name', ''))
                                    print(f"[CCTV] 3. -> Name: '{p_name}'", flush=True)
                                    if term.replace(" ","") in p_name.replace(" ","") or keyword_text.replace(" ","") in p_name.replace(" ",""):
                                        c_prods = p.get('channelProducts', [{}])
                                        c_no = c_prods[0].get('channelProductNo') if c_prods else o_no
                                        matched_mall_pid = c_no
                                        updates['price'] = f"{op_data.get('salePrice', 0):,}원"
                                        updates['store_name'] = target_mall_name
                                        updates['product_link'] = f"https://smartstore.naver.com/main/products/{c_no}"
                                        print(f"[CCTV] 3. -> EXACT MATCH BY NAME! Link Set.", flush=True)
                                        break

                # 4. Commerce Details Fetch (Shipping Fee)
                if commerce_token and matched_mall_pid:
                    print(f"[CCTV] 4. Fetching Details for Shipping Fee using PID {matched_mall_pid}...", flush=True)
                    op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/{matched_mall_pid}", headers=c_headers, timeout=5)
                    print(f"[CCTV] 4. Details Fetch Status: {op_res.status_code}", flush=True)
                    if op_res.status_code == 200:
                        op_data = op_res.json().get('originProduct', op_res.json())
                        fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                        updates['shipping_fee'] = "무료" if fee == 0 else (f"{fee:,}원" if fee else "-")
                        print(f"[CCTV] 4. Extracted Shipping Fee: {updates['shipping_fee']}", flush=True)

                # 5. Rank Scan
                print(f"[CCTV] 5. Scanning for Rank...", flush=True)
                if api_headers and search_client_id:
                    found_rank = False
                    for start_idx in range(1, 402, 100):
                        if found_rank: break
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            items = api_res.json().get('items', [])
                            for idx, item in enumerate(items):
                                if target_mall_name in item.get('mallName', ''):
                                    updates['store_rank'] = str(start_idx + idx)
                                    print(f"[CCTV] 5. -> Rank Found: {updates['store_rank']}위", flush=True)
                                    found_rank = True
                                    break

                # DB Save
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        if key == 'isbn' and kw.isbn and kw.isbn != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()
                    print(f"[CCTV] Finished Processing '{keyword_text}'. Status saved.", flush=True)

            except Exception as e:
                print(f"[CCTV ERROR] Exception during processing '{k_id}': {e}", flush=True)
                traceback.print_exc()
            
            time.sleep(0.3)
            
        print("========== [CCTV END] ==========\n", flush=True)

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
    if not selected_ids: return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    target_ids = []
    
    for kw in keywords:
        if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 데이터 수집중..."
        target_ids.append(kw.id)
            
    db.session.commit()
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 선택한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 디버그 로그 기록 모드로 매칭을 시작합니다. 잠시 후 새로고침 해주세요.'})
