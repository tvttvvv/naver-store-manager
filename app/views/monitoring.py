import os
import time
import re
import traceback
import random
import html
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
        })
    ]
    for name, headers in bots:
        try:
            res = requests.get(url, headers=headers, timeout=5)
            if res.status_code == 200:
                html_text = res.text
                if len(html_text) > 5000: return html_text
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
            html_text = get_html_with_bot_spoofing(url)
            if not html_text: break
            
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html_text, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    state = data.get('props', {}).get('pageProps', {}).get('initialState', {})
                    
                    if 'catalog' in state and state['catalog'].get('info'):
                        info = state['catalog']['info']
                        if not result.get('general_title'):
                            raw_t = info.get('bookTitle', info.get('productName', ''))
                            result['general_title'] = html.unescape(raw_t)
                            result['general_publisher'] = info.get('publisher', '')
                            gp = str(info.get('lowestPrice', info.get('lowPrice', info.get('price', 0))))
                            result['general_price'] = f"{int(gp):,}원" if gp.isdigit() and gp != '0' else "-"
                            cat_id = info.get('id', '')
                            result['general_link'] = f"https://search.shopping.naver.com/book/catalog/{cat_id}" if cat_id else "-"
                        
                        products = state['catalog'].get('products', [])
                        for idx, prod in enumerate(products):
                            mall = prod.get('mallName', '')
                            if safe_target in mall.lower().replace(" ", ""):
                                result['rank'] = str(idx + 1) 
                                p = str(prod.get('price', 0))
                                result['my_price'] = f"{int(p):,}원" if p.isdigit() and p != '0' else "-"
                                df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                                result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                                result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('crUrl', '-')))
                                raw_my_t = prod.get('productTitle', prod.get('bookTitle', ''))
                                result['my_title'] = html.unescape(raw_my_t)
                                return result
                        
                        if not find_rank: return result 
                        else: break 

                    book_list = state.get('book', {}).get('list', [])
                    if not book_list: break 

                    if page == 1 and not result.get('general_title'):
                        first_item = book_list[0].get('item', book_list[0])
                        raw_t = first_item.get('bookTitle', first_item.get('productTitle', ''))
                        result['general_title'] = html.unescape(raw_t)
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
                            result['my_price'] = f"{int(p):,}원" if p.isdigit() and p != '0' else "-"
                            df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                            result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                            result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('crUrl', '-')))
                            raw_my_t = prod.get('productTitle', prod.get('bookTitle', ''))
                            result['my_title'] = html.unescape(raw_my_t)
                            return result
                            
                except Exception:
                    break
            
            if find_rank: time.sleep(0.1) 
            
    return result

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [CCTV START] ULTIMATE ISBN EXACT SCRAPING ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            safe_target = target_mall_name.lower().replace(" ", "")
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
                    'store_name': target_mall_name,
                    'book_title': '⚠️ 매칭 실패'
                }

                # ========================================================
                # [1단계] 순위 찾기: 무조건 '키워드'로만 찾음! (상품 정보는 무시)
                # ========================================================
                print(f"[CCTV] 1. 순위 탐색 (Keyword: {keyword_text})", flush=True)
                kw_info = get_naver_shopping_info([keyword_text], target_mall_name, find_rank=True)
                
                if kw_info.get('rank'):
                    updates['store_rank'] = kw_info['rank']
                else:
                    if api_headers and search_client_id:
                        found_rank = False
                        try:
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}", headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    for idx, item in enumerate(api_res.json().get('items', [])):
                                        if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                            updates['store_rank'] = str(start_idx + idx)
                                            found_rank = True
                                            break
                        except Exception: pass

                # ========================================================
                # [2단계] 상품 정보 추출: ✨오직 ISBN만 취급합니다✨
                # ========================================================
                if target_isbn:
                    print(f"[CCTV] 2. 오직 ISBN({target_isbn})으로만 상품 정보를 털어옵니다.", flush=True)
                    
                    # 1) 도서 전용 API (d_isbn 검색으로 100% 정확한 원본 책 정보 가져오기)
                    if api_headers and search_client_id:
                        try:
                            book_res = requests.get(f"https://openapi.naver.com/v1/search/book.json?d_isbn={urllib.parse.quote(target_isbn)}", headers=api_headers, timeout=3)
                            if book_res.status_code == 200 and book_res.json().get('items'):
                                b_item = book_res.json()['items'][0]
                                raw_title = re.sub(r'<[^>]*>', '', b_item.get('title', ''))
                                updates['book_title'] = html.unescape(raw_title).strip()
                                updates['publisher'] = html.unescape(b_item.get('publisher', '-'))
                                
                                p = b_item.get('discount', b_item.get('price', 0))
                                if p and str(p) != '0': updates['price'] = f"{int(p):,}원"
                                
                                raw_link = b_item.get('link', '-')
                                updates['product_link'] = raw_link.replace('http://', 'https://') if raw_link != '-' else '-'
                                print(f"[CCTV] 📘 Book API 매칭 성공! 제목: {updates['book_title']}", flush=True)
                        except Exception: pass

                    # 2) 네이버 쇼핑 도서탭 크롤링 (ISBN 검색) -> 내 상점 직링크, 택배비 확보
                    isbn_info = get_naver_shopping_info([target_isbn], target_mall_name, find_rank=False)
                    
                    if updates['book_title'] in ['-', '⚠️ 매칭 실패'] and isbn_info.get('general_title'):
                        updates['book_title'] = isbn_info['general_title']
                    if updates['publisher'] == '-' and isbn_info.get('general_publisher'):
                        updates['publisher'] = isbn_info['general_publisher']
                    if updates['price'] == '-' and isbn_info.get('general_price'):
                        updates['price'] = isbn_info['general_price']
                    if updates['product_link'] == '-' and isbn_info.get('general_link'):
                        updates['product_link'] = isbn_info['general_link']

                    # 만약 ISBN 카탈로그 안에 내 상점이 있다면 덮어쓰기!
                    if isbn_info.get('my_link'):
                        updates['product_link'] = isbn_info['my_link']
                        if isbn_info.get('my_price'): updates['price'] = isbn_info['my_price']
                        if isbn_info.get('my_shipping'): updates['shipping_fee'] = isbn_info['my_shipping']
                        if isbn_info.get('my_title'): updates['book_title'] = isbn_info['my_title']
                        print(f"[CCTV] 🎯 카탈로그에서 내 상점(스터디박스) ISBN 상품 매칭 완료!", flush=True)
                    
                    # 3) 카탈로그에도 없으면 마지막으로 Shop API에 ISBN으로 내 상점 스캔!
                    if not isbn_info.get('my_link') and api_headers and search_client_id:
                        try:
                            shop_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(target_isbn)}&display=100", headers=api_headers, timeout=3)
                            if shop_res.status_code == 200:
                                for item in shop_res.json().get('items', []):
                                    if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                        raw_title = re.sub(r'<[^>]*>', '', item.get('title', ''))
                                        updates['book_title'] = html.unescape(raw_title).strip()
                                        raw_link = item.get('link', '-')
                                        updates['product_link'] = raw_link.replace('http://', 'https://') if raw_link != '-' else '-'
                                        p = item.get('lprice', '0')
                                        if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                        print(f"[CCTV] 🎯 Shop API에서 내 상점(스터디박스) ISBN 상품 매칭 완료!", flush=True)
                                        break
                        except Exception: pass

                # ========================================================
                # [3단계] 만약 ISBN이 표에 아예 비어있다면? 어쩔 수 없이 키워드 정보 활용
                # ========================================================
                else:
                    print(f"[CCTV] ⚠️ ISBN이 비어있어, 어쩔 수 없이 키워드({keyword_text}) 검색 결과를 상품 정보로 사용합니다.", flush=True)
                    if kw_info.get('my_title'): updates['book_title'] = kw_info['my_title']
                    elif kw_info.get('general_title'): updates['book_title'] = kw_info['general_title']
                    
                    if kw_info.get('general_publisher'): updates['publisher'] = kw_info['general_publisher']
                    
                    if kw_info.get('my_price'): updates['price'] = kw_info['my_price']
                    elif kw_info.get('general_price'): updates['price'] = kw_info['general_price']
                    
                    if kw_info.get('my_link'): updates['product_link'] = kw_info['my_link']
                    elif kw_info.get('general_link'): updates['product_link'] = kw_info['general_link']
                    
                    if kw_info.get('my_shipping'): updates['shipping_fee'] = kw_info['my_shipping']

                # DB 업데이트
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    # 빈칸 보호막을 해제하고 무조건 덮어씁니다!
                    if updates['book_title'] not in ['-', '⚠️ 매칭 실패']: kw.book_title = updates['book_title']
                    if updates['publisher'] != '-': kw.publisher = updates['publisher']
                    if updates['price'] != '-': kw.price = updates['price']
                    if updates['product_link'] != '-': kw.product_link = updates['product_link']
                    
                    kw.store_rank = updates['store_rank']
                    kw.shipping_fee = updates['shipping_fee']
                    kw.store_name = updates['store_name']
                    
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
    return jsonify({'success': True, 'message': f'✅ 도서검색 탭 기준 데이터 수집을 시작합니다. (시간이 조금 걸릴 수 있습니다.)'})
