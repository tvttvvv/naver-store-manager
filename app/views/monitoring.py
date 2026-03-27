import os
import time
import re
import traceback
import random
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

# ✨ 418 에러 무력화: 검색 엔진 봇(Yeti, Googlebot)으로 완벽하게 신분을 위장합니다!
def get_html_with_bot_spoofing(url):
    bots = [
        ("Naver Yeti", {
            "User-Agent": "Mozilla/5.0 (compatible; Yeti/1.1; +http://naver.me/spd)",
            "Accept": "*/*",
            "X-Forwarded-For": f"125.209.{random.randint(1, 255)}.{random.randint(1, 255)}" # 가짜 네이버 본사 IP
        }),
        ("Googlebot", {
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "X-Forwarded-For": f"66.249.{random.randint(64, 95)}.{random.randint(1, 255)}" # 가짜 구글 IP
        }),
        ("Bingbot", {
            "User-Agent": "Mozilla/5.0 (compatible; bingbot/2.0; +http://www.bing.com/bingbot.htm)",
            "Accept": "*/*"
        })
    ]

    for name, headers in bots:
        print(f"\n[CCTV] 🛡️ Trying VIP Bot Spoofing ({name}): {urllib.parse.unquote(url)}", flush=True)
        try:
            res = requests.get(url, headers=headers, timeout=5)
            print(f"[CCTV] 🌐 {name} Status Code: {res.status_code}", flush=True)
            
            if res.status_code == 200:
                html = res.text
                if len(html) > 5000:
                    print(f"[CCTV] ✅ {name} Bypass SUCCESS! Extracted Real HTML.", flush=True)
                    return html
                else:
                    print(f"[CCTV] ⚠️ Caught by Captcha despite bot disguise.", flush=True)
        except Exception as e:
            print(f"[CCTV] 🌐 {name} Request Error: {e}", flush=True)

    return ""

def get_naver_rank_only(queries, target_mall):
    for q in queries:
        if not q: continue
        print(f"\n[CCTV] --- Scanning Public Rank For: '{q}' ---", flush=True)
        
        # 봇 위장은 PC 버전이 가장 잘 뚫립니다.
        url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(q)}"
        html = get_html_with_bot_spoofing(url)
        
        if not html: continue
        
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                book_list = data.get('props', {}).get('pageProps', {}).get('initialState', {}).get('book', {}).get('list', [])
                for idx, item in enumerate(book_list):
                    prod = item.get('item', item)
                    mall = prod.get('mallName', '')
                    if target_mall in mall:
                        return str(idx + 1)
            except: pass
                
        mall_tags = re.findall(r'(?:class="[^"]*mall_name[^"]*"[^>]*>|"mallName":")([^<"]+)', html)
        if mall_tags:
            for idx, mall in enumerate(mall_tags):
                if target_mall in mall:
                    return str(idx + 1)
                    
        if target_mall in html:
            blocks = re.split(r'class="[^"]*bookListItem[^"]*"', html)
            if len(blocks) > 1:
                for idx, block in enumerate(blocks[1:]):
                    if target_mall in block:
                        return str(idx + 1)
    return None

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] BOT DISGUISE MODE ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            db.session.commit()
        except Exception as e:
            db.session.rollback()

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: 
                    db.session.commit()
                    continue
                    
                keyword_text = str(kw.keyword or "")
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                updates = {
                    'store_rank': '500위 밖',
                    'price': '-',
                    'product_link': '-',
                    'shipping_fee': '-',
                    'store_name': '-',
                    'book_title': '⚠️ 매칭 실패'
                }

                real_book_title = ""
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    try:
                        book_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}"
                        book_res = requests.get(book_url, headers=api_headers, timeout=3)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            item = book_res.json()['items'][0]
                            real_book_title = re.sub(r'\(.*?\)', '', re.sub(r'<[^>]*>', '', item.get('title', ''))).strip()
                            updates['book_title'] = real_book_title
                    except: pass
                
                # 봇 신분증을 들고 1순위 타격!
                book_queries = [keyword_text, real_book_title]
                if target_isbn: book_queries.insert(0, target_isbn) 
                
                book_rank = get_naver_rank_only(book_queries, target_mall_name)
                
                if book_rank:
                    updates['store_rank'] = book_rank
                    updates['store_name'] = target_mall_name
                else:
                    # 백업: 공식 쇼핑 API (1~500위) 탐색
                    print(f"\n[CCTV] Not found directly. Scanning Official API (1~500)...", flush=True)
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
                                            updates['store_name'] = item.get('mallName')
                                            print(f"[CCTV] 🎯 TARGET FOUND in Official API! Rank: {updates['store_rank']}", flush=True)
                                            found_rank = True
                                            break
                        except: pass

                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        if key == 'isbn' and kw.isbn and kw.isbn != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()
                    print(f"[CCTV] Database updated for '{keyword_text}'. Final Rank: {updates['store_rank']}", flush=True)

            except Exception as e:
                db.session.rollback()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 시스템 에러"
                    db.session.commit()
            
            time.sleep(0.2)
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
        kw.store_rank = "⏳ 순위 추적중..."
        target_ids.append(kw.id)
            
    db.session.commit()
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 선택한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 검색엔진 봇 위장 모드로 추적을 시작합니다. 잠시 후 새로고침 해주세요.'})
