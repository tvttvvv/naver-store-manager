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
        ("Normal Chrome", {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
        }),
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
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                html = res.text
                if len(html) > 5000: return html
        except Exception: pass
    return ""

def get_naver_shopping_info(queries, target_mall, find_rank=False):
    result = {}
    safe_target = target_mall.lower().replace(" ", "")

    for q in queries:
        if not q: continue
        
        max_pages = 10 if find_rank else 1 

        for page in range(1, max_pages + 1):
            url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(q)}&pagingIndex={page}&pagingSize=40"
            if find_rank:
                print(f"[CCTV] 🔎 Searching Page {page} for Keyword [{q}]...", flush=True)
            
            html = get_html_with_bot_spoofing(url)
            if not html: break
            
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    state = data.get('props', {}).get('pageProps', {}).get('initialState', {})
                    
                    if 'catalog' in state and state['catalog'].get('info'):
                        info = state['catalog']['info']
                        
                        if not result.get('general_title'):
                            result['general_title'] = info.get('bookTitle', info.get('productName', ''))
                            result['general_publisher'] = info.get('publisher', '')
                            gp = str(info.get('lowestPrice', info.get('price', 0)))
                            result['general_price'] = f"{int(gp):,}원" if gp.isdigit() and gp != '0' else "-"
                            cat_id = info.get('id', '')
                            result['general_link'] = f"https://search.shopping.naver.com/book/catalog/{cat_id}" if cat_id else "-"
                        
                        products = state['catalog'].get('products', [])
                        
                        # CCTV 생중계: 카탈로그 안에는 어떤 상점들이 있나?
                        if page == 1 and find_rank:
                            sample_malls = [p.get('mallName', '') for p in products][:10]
                            print(f"[CCTV] 📊 Catalog Page 1 Sample Malls: {sample_malls}", flush=True)

                        for idx, prod in enumerate(products):
                            mall = prod.get('mallName', '')
                            if safe_target in mall.lower().replace(" ", ""):
                                result['rank'] = str(idx + 1) 
                                p = str(prod.get('price', 0))
                                result['my_price'] = f"{int(p):,}원" if p.isdigit() else "-"
                                df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                                result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                                result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('crUrl', '-')))
                                result['my_title'] = prod.get('productTitle', prod.get('bookTitle', ''))
                                print(f"[CCTV] 🎯 TARGET FOUND IN CATALOG! Rank: {result['rank']}", flush=True)
                                return result
                        
                        if not find_rank: return result 
                        else: break 

                    book_list = state.get('book', {}).get('list', [])
                    if not book_list: break 

                    # CCTV 생중계: 리스트에는 어떤 상점들이 있나?
                    if page == 1 and find_rank:
                        sample_malls = [item.get('item', item).get('mallName', '') for item in book_list if item.get('item', item).get('mallName')]
                        print(f"[CCTV] 📊 Search List Page 1 Sample Malls: {sample_malls[:10]}...", flush=True)

                    if page == 1 and not result.get('general_title'):
                        first_item = book_list[0].get('item', book_list[0])
                        result['general_title'] = first_item.get('bookTitle', first_item.get('productTitle', ''))
                        result['general_publisher'] = first_item.get('publisher', '')
                        gp = str(first_item.get('lowPrice', first_item.get('price', 0)))
                        result['general_price'] = f"{int(gp):,}원" if gp.isdigit() and gp != '0' else "-"
                        cat_id = first_item.get('catalogId', first_item.get('id', ''))
                        result['general_link'] = f"https://search.shopping.naver.com/book/catalog/{cat_id}" if cat_id else first_item.get('productUrl', '-')
                    
                    for idx, item in enumerate(book_list):
                        prod = item.get('item', item)
                        mall = prod.get('mallName', '')
                        
                        if safe_target in mall.lower().replace(" ", ""):
                            result['rank'] = str((page - 1) * 40 + idx + 1)
                            p = str(prod.get('lowPrice', prod.get('price', 0)))
                            result['my_price'] = f"{int(p):,}원" if p.isdigit() else "-"
                            df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                            result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                            result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('crUrl', '-')))
                            result['my_title'] = prod.get('productTitle', prod.get('bookTitle', ''))
                            print(f"[CCTV] 🎯 TARGET FOUND at Rank: {result['rank']} (Page {page})", flush=True)
                            return result
                            
                except Exception as e:
                    print(f"[CCTV] JSON Parse Error on page {page}: {e}", flush=True)
                    break
            else:
                # JSON을 못 찾았을 경우 최후의 수단: HTML 텍스트 정규식 강제 파싱!
                print(f"[CCTV] JSON NOT FOUND on page {page}. Trying Regex Fallback...", flush=True)
                malls = re.findall(r'"mallName":"([^"]+)"', html)
                if not malls:
                    malls = re.findall(r'class="[^"]*mall_name[^"]*"[^>]*>([^<]+)<', html)
                
                if page == 1 and find_rank:
                    print(f"[CCTV] 📊 Regex Sample Malls: {malls[:10]}...", flush=True)

                for idx, mall in enumerate(malls):
                    if safe_target in mall.lower().replace(" ", ""):
                        result['rank'] = str((page - 1) * 40 + idx + 1)
                        print(f"[CCTV] 🎯 Regex Fallback Found at Rank: {result['rank']} (Page {page})", flush=True)
                        return result
            
            if find_rank: time.sleep(0.2) 
            
    return result

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] RANK & INFO SCRAPING ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            db.session.commit()
            print(f"[CCTV] My Target Store Name: [{target_mall_name}]", flush=True)
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

                print(f"\n[CCTV] --- [1단계] 순위 파악 (Keyword: {keyword_text}) ---", flush=True)
                kw_info = get_naver_shopping_info([keyword_text], target_mall_name, find_rank=True)
                
                if kw_info.get('rank'):
                    updates['store_rank'] = kw_info['rank']
                    updates['store_name'] = target_mall_name
                else:
                    if api_headers and search_client_id:
                        found_rank = False
                        safe_target = target_mall_name.lower().replace(" ", "")
                        try:
                            print(f"[CCTV] 도서 탭 10페이지 탐색 실패. 공식 API 500위 스캔 시작...", flush=True)
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}", headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    items = api_res.json().get('items', [])
                                    if not items: break
                                    for idx, item in enumerate(items):
                                        if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                            updates['store_rank'] = str(start_idx + idx)
                                            updates['store_name'] = item.get('mallName')
                                            print(f"[CCTV] API 500위 굴착 성공! Rank: {updates['store_rank']}", flush=True)
                                            found_rank = True
                                            break
                        except Exception: pass

                api_info = {}
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    try:
                        book_res = requests.get(f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}", headers=api_headers, timeout=3)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            item = book_res.json()['items'][0]
                            api_info['title'] = re.sub(r'\(.*?\)', '', re.sub(r'<[^>]*>', '', item.get('title', ''))).strip()
                            api_info['publisher'] = item.get('publisher', '-')
                            price = item.get('discount', item.get('price', 0))
                            api_info['price'] = f"{int(price):,}원" if price else "-"
                            api_info['link'] = item.get('link', '-').replace('http://', 'https://')
                    except Exception: pass

                if target_isbn:
                    print(f"[CCTV] --- [2단계] 상품 정보 파싱 (ISBN: {target_isbn}) ---", flush=True)
                    isbn_info = get_naver_shopping_info([target_isbn], target_mall_name, find_rank=False)
                    
                    if isbn_info.get('general_publisher'): updates['publisher'] = isbn_info['general_publisher']
                    if isbn_info.get('general_title'): updates['book_title'] = isbn_info['general_title']
                    if isbn_info.get('general_price'): updates['price'] = isbn_info['general_price']
                    if isbn_info.get('general_link'): updates['product_link'] = isbn_info['general_link']

                    if isbn_info.get('my_title'): updates['book_title'] = isbn_info['my_title']
                    if isbn_info.get('my_price'): updates['price'] = isbn_info['my_price']
                    if isbn_info.get('my_shipping'): updates['shipping_fee'] = isbn_info['my_shipping']
                    if isbn_info.get('my_link'): updates['product_link'] = isbn_info['my_link']
                    
                    if not isbn_info.get('general_title') and api_info:
                        updates['book_title'] = api_info.get('title', '⚠️ 매칭 실패')
                        updates['publisher'] = api_info.get('publisher', '-')
                        updates['price'] = api_info.get('price', '-')
                        updates['product_link'] = api_info.get('link', '-')
                else:
                    if kw_info.get('my_title'): updates['book_title'] = kw_info['my_title']
                    elif kw_info.get('general_title'): updates['book_title'] = kw_info['general_title']
                    if kw_info.get('general_publisher'): updates['publisher'] = kw_info['general_publisher']
                    if kw_info.get('my_price'): updates['price'] = kw_info['my_price']
                    elif kw_info.get('general_price'): updates['price'] = kw_info['general_price']
                    if kw_info.get('my_shipping'): updates['shipping_fee'] = kw_info['my_shipping']
                    if kw_info.get('my_link'): updates['product_link'] = kw_info['my_link']
                    elif kw_info.get('general_link'): updates['product_link'] = kw_info['general_link']

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
            
            time.sleep(1) # ✨ 서버 과부하 방지 및 차단 회피를 위해 1초 휴식!
            
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
    return jsonify({'success': True, 'message': f'✅ 도서검색 탭 기준 데이터 수집을 시작합니다. (시간이 조금 걸릴 수 있습니다.)'})
