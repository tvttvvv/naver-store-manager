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

def get_real_title_via_proxy(isbn):
    isbn = isbn.replace('-', '').strip()
    if not isbn: return ""
    try:
        aladin_url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord={isbn}"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(aladin_url)}"
        res = requests.get(proxy_url, timeout=3)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    return ""

def get_html_with_proxy(url):
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        print(f"[CCTV] Trying direct request to {url}", flush=True)
        res = requests.get(url, headers=headers, timeout=3)
        print(f"[CCTV] Direct request status: {res.status_code}", flush=True)
        if res.status_code == 200 and "captcha" not in res.text.lower():
            return res.text
    except Exception as e:
        print(f"[CCTV] Direct request failed: {e}", flush=True)

    try:
        print(f"[CCTV] Trying proxy request...", flush=True)
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
        res = requests.get(proxy_url, timeout=5)
        print(f"[CCTV] Proxy request status: {res.status_code}", flush=True)
        if res.status_code == 200:
            return res.json().get('contents', '')
    except Exception as e:
        print(f"[CCTV] Proxy request failed: {e}", flush=True)
    return ""

def get_naver_book_shopping_info(queries, target_mall):
    for q in queries:
        if not q: continue
        print(f"\n[CCTV] --- Scraping Naver Book Search for: '{q}' ---", flush=True)
        url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(q)}"
        html = get_html_with_proxy(url)
        
        if not html:
            print("[CCTV] Failed to get any HTML from Naver.", flush=True)
            continue
            
        print(f"[CCTV] HTML loaded. Length: {len(html)} characters.", flush=True)
        
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            print("[CCTV] Found __NEXT_DATA__ script block.", flush=True)
            try:
                data = json.loads(match.group(1))
                book_list = data.get('props', {}).get('pageProps', {}).get('initialState', {}).get('book', {}).get('list', [])
                print(f"[CCTV] Found {len(book_list)} items in JSON data.", flush=True)
                if book_list:
                    for idx, item in enumerate(book_list):
                        prod = item.get('item', item)
                        mall = prod.get('mallName', '')
                        print(f"[CCTV] Rank {idx+1} | Mall: '{mall}' | Title: '{prod.get('bookTitle', '')[:15]}...'", flush=True)
                        if target_mall in mall:
                            rank = str(idx + 1)
                            price = str(prod.get('lowPrice', prod.get('price', 0)))
                            price_formatted = f"{int(price):,}원" if price.isdigit() else "-"
                            link = prod.get('mallProductUrl', prod.get('crUrl', '-'))
                            print(f"[CCTV] 🎯 TARGET FOUND! Rank: {rank}, Price: {price_formatted}", flush=True)
                            return rank, price_formatted, link
            except Exception as e:
                print(f"[CCTV] Error parsing JSON: {e}", flush=True)
        else:
            print("[CCTV] Warning: __NEXT_DATA__ script NOT found in HTML.", flush=True)
        
        mall_tags = re.findall(r'class="[^"]*mall_name[^"]*">([^<]+)<', html)
        if mall_tags:
            print(f"[CCTV] Found raw HTML mall tags: {mall_tags[:5]}...", flush=True)
            for idx, mall in enumerate(mall_tags):
                if target_mall in mall:
                    print(f"[CCTV] 🎯 TARGET FOUND in HTML! Rank: {idx+1}", flush=True)
                    return str(idx + 1), "-", "-"
        else:
            print("[CCTV] No raw HTML mall tags found either.", flush=True)

    return None, "-", "-"

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] PUBLIC SEARCH LOGGING ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            print(f"[CCTV] Target Mall Name: {target_mall_name}", flush=True)
        except Exception as e: 
            print(f"[CCTV] Setup Error: {e}", flush=True)

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: continue
                    
                keyword_text = str(kw.keyword or "")
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                print(f"\n[CCTV] ---- Processing: '{keyword_text}' ----", flush=True)

                updates = {
                    'store_rank': '500위 밖',
                    'price': '-',
                    'product_link': '-',
                    'shipping_fee': '-',
                    'book_title': '⚠️ 매칭 실패'
                }

                # 1. Book API
                real_book_title = ""
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    print(f"[CCTV] Requesting Open API (Book) for: {search_query}", flush=True)
                    try:
                        book_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}"
                        book_res = requests.get(book_url, headers=api_headers, timeout=3)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            item = book_res.json()['items'][0]
                            title_clean = re.sub(r'<[^>]*>', '', item.get('title', ''))
                            real_book_title = re.sub(r'\(.*?\)', '', title_clean).strip()
                            print(f"[CCTV] Open API Title found: {real_book_title}", flush=True)
                            
                            if not target_isbn:
                                raw_isbn = item.get('isbn', '')
                                for cand in reversed(raw_isbn.split()):
                                    if cand.startswith('9') or cand.startswith('8'):
                                        updates['isbn'] = cand
                                        break
                            if item.get('publisher'): updates['publisher'] = item.get('publisher')
                    except Exception as e: print(f"[CCTV] Open API Book Error: {e}", flush=True)
                
                if not real_book_title and target_isbn:
                    real_book_title = get_real_title_via_proxy(target_isbn)
                if real_book_title: updates['book_title'] = real_book_title

                # 2. Public Search Scan
                book_queries = [keyword_text, real_book_title]
                if target_isbn: book_queries.insert(0, target_isbn) # ISBN 검색도 추가
                
                book_rank, book_price, book_link = get_naver_book_shopping_info(book_queries, target_mall_name)
                
                if book_rank:
                    updates['store_rank'] = book_rank
                    updates['price'] = book_price if book_price != "-" else updates['price']
                    updates['product_link'] = book_link if book_link != "-" else updates['product_link']
                    updates['store_name'] = target_mall_name
                else:
                    print(f"\n[CCTV] --- Scanning Official Shop API (1~500) ---", flush=True)
                    if api_headers and search_client_id:
                        try:
                            found_rank = False
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                                api_res = requests.get(api_url, headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    items = api_res.json().get('items', [])
                                    print(f"[CCTV] Shop API Page {start_idx} loaded {len(items)} items.", flush=True)
                                    if not items: break
                                    for idx, item in enumerate(items):
                                        if target_mall_name in item.get('mallName', ''):
                                            updates['store_rank'] = str(start_idx + idx)
                                            updates['price'] = f"{int(item.get('lprice', 0)):,}원"
                                            updates['product_link'] = item.get('link')
                                            updates['store_name'] = item.get('mallName')
                                            print(f"[CCTV] 🎯 TARGET FOUND in Shop API! Rank: {updates['store_rank']}", flush=True)
                                            found_rank = True
                                            break
                        except Exception as e: print(f"[CCTV] Shop API Scan Error: {e}", flush=True)

                # DB 업데이트
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        if key == 'isbn' and kw.isbn and kw.isbn != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()
                    print(f"[CCTV] Database updated for '{keyword_text}'.", flush=True)

            except Exception as e:
                traceback.print_exc()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 시스템 에러"
                    db.session.commit()
            
            time.sleep(0.1)
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
    return jsonify({'success': True, 'message': f'✅ 진단용 CCTV 모드로 매칭을 시작합니다. 잠시 후 새로고침 해주세요.'})
