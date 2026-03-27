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
        res = requests.get(proxy_url, timeout=4)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    return ""

# ✨ 418 에러를 뚫어버리는 최강의 사람 위장술 및 3중 다중 우회 함수!
def get_html_with_proxy(url):
    # 실제 사람이 쓰는 크롬 브라우저와 100% 동일한 헤더 설정
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        "Referer": "https://search.shopping.naver.com/book/home",
        "Sec-Ch-Ua": '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        "Sec-Ch-Ua-Mobile": "?0",
        "Sec-Ch-Ua-Platform": '"Windows"',
        "Sec-Fetch-Dest": "document",
        "Sec-Fetch-Mode": "navigate",
        "Sec-Fetch-Site": "same-origin",
        "Upgrade-Insecure-Requests": "1"
    }

    print(f"\n[DEBUG] 🌐 Requesting: {urllib.parse.unquote(url)}", flush=True)

    # 1. 강력한 위장술로 직접 타격 (가장 빠름)
    try:
        res = requests.get(url, headers=headers, timeout=4)
        if res.status_code == 200 and "captcha" not in res.text.lower():
            print("[DEBUG] ✅ Direct fetch SUCCESS!", flush=True)
            return res.text
        else:
            print(f"[DEBUG] ⚠️ Direct fetch failed. Status: {res.status_code}", flush=True)
    except: pass

    # 2. 우회망 1번 (CORS Proxy)
    try:
        print("[DEBUG] 🔄 Trying Proxy 1 (corsproxy.io)...", flush=True)
        proxy_url = f"https://corsproxy.io/?{urllib.parse.quote(url)}"
        res = requests.get(proxy_url, headers=headers, timeout=6)
        if res.status_code == 200:
            print("[DEBUG] ✅ Proxy 1 SUCCESS!", flush=True)
            return res.text
    except: pass

    # 3. 우회망 2번 (CodeTabs)
    try:
        print("[DEBUG] 🔄 Trying Proxy 2 (CodeTabs)...", flush=True)
        proxy_url = f"https://api.codetabs.com/v1/proxy?quest={urllib.parse.quote(url)}"
        res = requests.get(proxy_url, timeout=6)
        if res.status_code == 200:
            print("[DEBUG] ✅ Proxy 2 SUCCESS!", flush=True)
            return res.text
    except: pass

    # 4. 우회망 3번 (AllOrigins - 기존 것, 타임아웃 10초로 대폭 늘림)
    try:
        print("[DEBUG] 🔄 Trying Proxy 3 (AllOrigins)...", flush=True)
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(url)}"
        res = requests.get(proxy_url, timeout=10)
        if res.status_code == 200:
            print("[DEBUG] ✅ Proxy 3 SUCCESS!", flush=True)
            return res.json().get('contents', '')
    except: pass

    print("[DEBUG] ❌ All fetch attempts failed.", flush=True)
    return ""

def get_naver_book_shopping_info(queries, target_mall):
    for q in queries:
        if not q: continue
        url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(q)}"
        html = get_html_with_proxy(url)
        
        if not html: continue
        
        # 방식 1: 숨겨진 JSON 데이터 분석 (가장 정확함)
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                book_list = data.get('props', {}).get('pageProps', {}).get('initialState', {}).get('book', {}).get('list', [])
                if book_list:
                    for idx, item in enumerate(book_list):
                        prod = item.get('item', item)
                        mall = prod.get('mallName', '')
                        if target_mall in mall:
                            rank = str(idx + 1)
                            price = str(prod.get('lowPrice', prod.get('price', 0)))
                            price_formatted = f"{int(price):,}원" if price.isdigit() else "-"
                            link = prod.get('mallProductUrl', prod.get('crUrl', '-'))
                            return rank, price_formatted, link
            except: pass
            
        # 방식 2: 생 HTML 소스 코드 텍스트 긁기 (보험용)
        mall_tags = re.findall(r'class="[^"]*mall_name[^"]*">([^<]+)<', html)
        if mall_tags:
            for idx, mall in enumerate(mall_tags):
                if target_mall in mall:
                    return str(idx + 1), "-", "-"

    return None, "-", "-"

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
        except Exception as e: pass

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: continue
                    
                keyword_text = str(kw.keyword or "")
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                updates = {
                    'store_rank': '500위 밖',
                    'price': '-',
                    'product_link': '-',
                    'shipping_fee': '-',
                    'book_title': '⚠️ 매칭 실패'
                }

                # ✨ 1. 네이버 퍼블릭 도서 API (이름, 출판사 확보)
                real_book_title = ""
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    try:
                        book_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}"
                        book_res = requests.get(book_url, headers=api_headers, timeout=3)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            item = book_res.json()['items'][0]
                            title_clean = re.sub(r'<[^>]*>', '', item.get('title', ''))
                            real_book_title = re.sub(r'\(.*?\)', '', title_clean).strip()
                            
                            if not target_isbn:
                                raw_isbn = item.get('isbn', '')
                                for cand in reversed(raw_isbn.split()):
                                    if cand.startswith('9') or cand.startswith('8'):
                                        updates['isbn'] = cand
                                        break
                            if item.get('publisher'): updates['publisher'] = item.get('publisher')
                    except: pass
                
                if not real_book_title and target_isbn:
                    real_book_title = get_real_title_via_proxy(target_isbn)
                if real_book_title: updates['book_title'] = real_book_title

                # ✨ 2. 도서 탭 정밀 스캔 (방어막 우회하여 가격/링크 싹쓸이)
                book_queries = [target_isbn, keyword_text, real_book_title] # ISBN 우선 스캔
                book_rank, book_price, book_link = get_naver_book_shopping_info(book_queries, target_mall_name)
                
                if book_rank:
                    updates['store_rank'] = book_rank
                    updates['price'] = book_price if book_price != "-" else updates['price']
                    updates['product_link'] = book_link if book_link != "-" else updates['product_link']
                    updates['store_name'] = target_mall_name
                else:
                    # ✨ 3. 백업용 쇼핑 API 스캔 (최대 500위)
                    if api_headers and search_client_id:
                        try:
                            found_rank = False
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                                api_res = requests.get(api_url, headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    items = api_res.json().get('items', [])
                                    if not items: break
                                    for idx, item in enumerate(items):
                                        if target_mall_name in item.get('mallName', ''):
                                            updates['store_rank'] = str(start_idx + idx)
                                            updates['price'] = f"{int(item.get('lprice', 0)):,}원"
                                            updates['product_link'] = item.get('link')
                                            updates['store_name'] = item.get('mallName')
                                            found_rank = True
                                            break
                        except: pass

                # DB 저장
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        if key == 'isbn' and kw.isbn and kw.isbn != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()

            except Exception as e:
                traceback.print_exc()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 시스템 에러"
                    db.session.commit()
            
            time.sleep(0.1)

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
    return jsonify({'success': True, 'message': f'✅ 네이버 방어벽 우회 매칭을 시작합니다. 잠시 후 새로고침 해주세요.'})
