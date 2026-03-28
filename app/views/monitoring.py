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
    elif 'MAIN' in grade_str: grade_char = 'MAIN'
    
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
    return jsonify({'success': True, 'data': [{'id': k.id, 'keyword': k.keyword or '-', 'search_volume': k.search_volume or 0, 'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C', 'MAIN'] else 'A'), 'link': k.link or '#', 'publisher': k.publisher or '-', 'supply_rate': k.supply_rate or '-', 'isbn': k.isbn or '-', 'price': k.price or '-', 'shipping_fee': k.shipping_fee or '-', 'store_name': k.store_name or '-', 'book_title': k.book_title or '-', 'product_link': k.product_link or '-', 'store_rank': k.store_rank or '-', 'prev_store_rank': k.prev_store_rank or '-'} for k in keywords]})

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
        new_isbn = request.form.get('isbn', '-').strip()
        
        if new_isbn and new_isbn != '-':
            duplicate = MonitoredKeyword.query.filter(
                MonitoredKeyword.user_id == current_user.id,
                MonitoredKeyword.isbn == new_isbn,
                MonitoredKeyword.id != kw.id
            ).first()
            
            if duplicate:
                return jsonify({
                    'success': False, 
                    'message': f'🚨 경고: 이미 등록된 ISBN입니다!\n\n입력하신 ISBN은 이미 [{duplicate.keyword}] 항목에 등록되어 있습니다.'
                })

        kw.publisher = request.form.get('publisher', '-')
        kw.supply_rate = request.form.get('supply_rate', '-')
        kw.isbn = new_isbn
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

def get_html_with_bot_spoofing(url):
    bots = [
        ("Naver Yeti", {
            "User-Agent": "Mozilla/5.0 (compatible; Yeti/1.1; +http://naver.me/spd)",
            "Accept": "*/*",
            "X-Forwarded-For": f"125.209.{random.randint(1, 255)}.{random.randint(1, 255)}"
        }),
        ("Googlebot", {
            "User-Agent": "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "X-Forwarded-For": f"66.249.{random.randint(64, 95)}.{random.randint(1, 255)}"
        })
    ]
    for name, headers in bots:
        try:
            print(f"[CCTV] 🛡️ Requesting URL with {name}: {urllib.parse.unquote(url)}", flush=True)
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                html = res.text
                if len(html) > 5000: return html
        except Exception as e:
            print(f"[CCTV] ⚠️ Bot Spoofing Error ({name}): {e}", flush=True)
    return ""

def get_naver_shopping_info(queries, target_mall):
    result = {}
    for q in queries:
        if not q: continue
        url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(q)}"
        html = get_html_with_bot_spoofing(url)
        
        if not html: continue
        
        match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
        if match:
            try:
                data = json.loads(match.group(1))
                book_list = data.get('props', {}).get('pageProps', {}).get('initialState', {}).get('book', {}).get('list', [])
                
                if not book_list: continue

                first_item = book_list[0].get('item', book_list[0])
                result['general_title'] = first_item.get('bookTitle', first_item.get('productTitle', ''))
                result['general_publisher'] = first_item.get('publisher', '')
                
                gp = str(first_item.get('lowPrice', first_item.get('price', 0)))
                result['general_price'] = f"{int(gp):,}원" if gp.isdigit() and gp != '0' else "-"
                
                cat_id = first_item.get('catalogId', first_item.get('id', ''))
                if cat_id:
                    result['general_link'] = f"https://search.shopping.naver.com/book/catalog/{cat_id}"
                else:
                    result['general_link'] = first_item.get('productUrl', first_item.get('mallProductUrl', '-'))
                
                for idx, item in enumerate(book_list):
                    prod = item.get('item', item)
                    mall = prod.get('mallName', '')
                    
                    if target_mall in mall:
                        result['rank'] = str(idx + 1)
                        p = str(prod.get('lowPrice', prod.get('price', 0)))
                        result['my_price'] = f"{int(p):,}원" if p.isdigit() else "-"
                        
                        df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                        if str(df) == '0': result['my_shipping'] = '무료'
                        elif str(df).isdigit(): result['my_shipping'] = f"{int(df):,}원"
                        else: result['my_shipping'] = str(df)
                        
                        result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('crUrl', '-')))
                        
                        # ✨ 스터디박스에서 실제로 판매하는 진짜 "상품명"을 가져옴!
                        result['my_title'] = prod.get('productTitle', prod.get('bookTitle', ''))
                        return result 
                
                return result 
            except Exception as e:
                print(f"[CCTV] JSON Parsing Error: {e}", flush=True)
                
    return result

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] STRICT ISBN SCRAPING ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            db.session.commit()
        except Exception: db.session.rollback()

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
                    'publisher': '-',
                    'store_name': '-',
                    'book_title': '⚠️ 매칭 실패'
                }

                print(f"\n[CCTV] [1단계] 오직 '키워드({keyword_text})'로 순위만 파악합니다.", flush=True)
                kw_info = get_naver_shopping_info([keyword_text], target_mall_name)
                
                if kw_info.get('rank'):
                    updates['store_rank'] = kw_info['rank']
                    updates['store_name'] = target_mall_name
                else:
                    if api_headers and search_client_id:
                        found_rank = False
                        try:
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}", headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    items = api_res.json().get('items', [])
                                    if not items: break
                                    for idx, item in enumerate(items):
                                        if target_mall_name in item.get('mallName', ''):
                                            updates['store_rank'] = str(start_idx + idx)
                                            updates['store_name'] = item.get('mallName')
                                            found_rank = True
                                            break
                        except Exception: pass

                # ✨ 가장 핵심! 오직 ISBN(판매자상품코드)으로 상품 정보를 추출합니다.
                if target_isbn:
                    print(f"[CCTV] [2단계] 키워드 무시! 오직 'ISBN({target_isbn})'으로 진짜 상품 정보를 털어옵니다.", flush=True)
                    isbn_info = get_naver_shopping_info([target_isbn], target_mall_name)
                    
                    if isbn_info.get('general_publisher'): updates['publisher'] = isbn_info['general_publisher']
                    if isbn_info.get('general_title'): updates['book_title'] = isbn_info['general_title']
                    if isbn_info.get('general_price'): updates['price'] = isbn_info['general_price']
                    if isbn_info.get('general_link'): updates['product_link'] = isbn_info['general_link']

                    # 스터디박스 전용 정보가 매칭되었다면 무조건 스터디박스 정보로 덮어쓰기
                    if isbn_info.get('my_title'): updates['book_title'] = isbn_info['my_title']
                    if isbn_info.get('my_price'): updates['price'] = isbn_info['my_price']
                    if isbn_info.get('my_shipping'): updates['shipping_fee'] = isbn_info['my_shipping']
                    if isbn_info.get('my_link'): updates['product_link'] = isbn_info['my_link']
                    
                    # ISBN 도서 탭에서 스터디박스를 못 찾았다면, API를 통해 확실하게 스터디박스 정보를 뜯어옵니다.
                    if not isbn_info.get('rank') and api_headers and search_client_id:
                        print(f"[CCTV] ISBN 도서탭에서 상점을 못 찾음. 공식 API를 ISBN으로 검색합니다.", flush=True)
                        try:
                            api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(target_isbn)}&display=100", headers=api_headers, timeout=3)
                            if api_res.status_code == 200:
                                items = api_res.json().get('items', [])
                                for item in items:
                                    if target_mall_name in item.get('mallName', ''):
                                        updates['book_title'] = re.sub(r'<[^>]*>', '', item.get('title', ''))
                                        raw_link = item.get('link', '-')
                                        updates['product_link'] = raw_link.replace('http://', 'https://') if raw_link != '-' else '-'
                                        p = item.get('lprice', '0')
                                        if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                        break
                        except Exception: pass
                else:
                    # ISBN이 아예 비어있으면 어쩔 수 없이 키워드 정보를 보조로 씁니다.
                    if kw_info.get('my_title'): updates['book_title'] = kw_info['my_title']
                    elif kw_info.get('general_title'): updates['book_title'] = kw_info['general_title']
                    if kw_info.get('general_publisher'): updates['publisher'] = kw_info['general_publisher']
                    if kw_info.get('my_price'): updates['price'] = kw_info['my_price']
                    elif kw_info.get('general_price'): updates['price'] = kw_info['general_price']
                    if kw_info.get('my_shipping'): updates['shipping_fee'] = kw_info['my_shipping']
                    if kw_info.get('my_link'): updates['product_link'] = kw_info['my_link']
                    elif kw_info.get('general_link'): updates['product_link'] = kw_info['general_link']

                # DB 확실하게 업데이트 (기존 오타 정보 강제 삭제)
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if updates['book_title'] not in ['-', '⚠️ 매칭 실패']: kw.book_title = updates['book_title']
                    if updates['publisher'] != '-': kw.publisher = updates['publisher']
                    if updates['price'] != '-': kw.price = updates['price']
                    if updates['product_link'] != '-': kw.product_link = updates['product_link']
                    
                    kw.store_rank = updates['store_rank']
                    kw.shipping_fee = updates['shipping_fee']
                    if updates.get('store_name') != '-': kw.store_name = updates['store_name']
                    
                    db.session.commit()
                    print(f"[CCTV] ✅ DB Update Success. Rank: {updates['store_rank']} / Title: {updates['book_title']}", flush=True)

            except Exception as e:
                db.session.rollback()
                print(f"[CCTV] ❌ Fatal Error: {e}", flush=True)
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    db.session.commit()
            
            time.sleep(0.5) 
            
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
    return jsonify({'success': True, 'message': f'✅ 도서검색 탭 기준 데이터 수집을 시작합니다. 잠시 후 새로고침 해주세요.'})
