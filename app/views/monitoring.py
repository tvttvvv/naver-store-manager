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
from sqlalchemy import text
from app.naver_api import get_naver_token

monitoring_bp = Blueprint('monitoring', __name__)

def clean_text(text):
    if not text or text == '-': return '-'
    cleaned = re.sub(r'<[^>]*>', '', str(text))
    return html.unescape(cleaned).strip()

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
    try:
        db.session.execute(text("ALTER TABLE monitored_keyword ADD COLUMN purchase_count VARCHAR(50) DEFAULT '-'"))
        db.session.commit()
    except Exception:
        db.session.rollback()

    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({'success': True, 'data': [{
        'id': k.id, 
        'keyword': k.keyword or '-', 
        'search_volume': k.search_volume or 0, 
        'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C', 'MAIN'] else 'A'), 
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
        'prev_store_rank': k.prev_store_rank or '-',
        'purchase_count': getattr(k, 'purchase_count', '-')
    } for k in keywords]})

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
                return jsonify({'success': False, 'message': f'🚨 경고: 이미 등록된 ISBN입니다!\n\n입력하신 ISBN은 이미 [{duplicate.keyword}] 항목에 등록되어 있습니다.'})

        if request.form.get('keyword'): kw.keyword = request.form.get('keyword')
        kw.publisher = request.form.get('publisher', '-')
        kw.supply_rate = request.form.get('supply_rate', '-')
        kw.isbn = new_isbn
        kw.price = request.form.get('price', '-')
        kw.shipping_fee = request.form.get('shipping_fee', '-') 
        kw.book_title = request.form.get('book_title', '-')
        kw.product_link = request.form.get('product_link', '-')
        kw.store_rank = request.form.get('store_rank', '-')
        
        pc_val = request.form.get('purchase_count', '-')
        if hasattr(kw, 'purchase_count'):
            kw.purchase_count = pc_val
            
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
        if hasattr(kw, 'purchase_count'): kw.purchase_count = '-'
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 항목의 검색 정보가 초기화되었습니다.'})

def get_html_with_bot_spoofing(url):
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
        "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200: return res.text
        else:
            print(f"[CCTV-DEBUG] ❌ [웹 스크래핑] 네이버 차단됨 (HTTP {res.status_code}) - {url}", flush=True)
    except Exception as e:
        print(f"[CCTV-DEBUG] ❌ [웹 스크래핑] 통신 에러: {e}", flush=True)
    return ""

def get_naver_shopping_info(queries, target_mall, find_rank=False):
    result = {}
    safe_target = target_mall.lower().replace(" ", "")
    print(f"\n[CCTV-DEBUG] 🌐 [웹 스크래핑] 시작 - 검색어: {queries}, 대상쇼핑몰: [{target_mall}]", flush=True)

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
                        products = state['catalog'].get('products', [])
                        for idx, prod in enumerate(products):
                            mall = prod.get('mallName', '')
                            if safe_target in mall.lower().replace(" ", ""):
                                result['rank'] = str((page - 1) * 40 + idx + 1)
                                p = str(prod.get('price', 0))
                                result['my_price'] = f"{int(p):,}원" if p.isdigit() and p != '0' else "-"
                                df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                                result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                                pc = prod.get('purchaseCnt', prod.get('keepCnt', prod.get('reviewCount', '-')))
                                if str(pc) != '0' and str(pc) != '-': result['my_purchase'] = str(pc)
                                result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('pcUrl', '-')))
                                result['my_title'] = clean_text(prod.get('productTitle', prod.get('bookTitle', '')))
                                print(f"[CCTV-DEBUG] 🎯 [웹 스크래핑] 매칭 성공 (카탈로그)! 추출된 데이터: {result}", flush=True)
                                return result
                        if not find_rank: return result 
                        else: break 

                    book_list = state.get('book', {}).get('list', [])
                    if not book_list: break 
                    for idx, item in enumerate(book_list):
                        prod = item.get('item', item)
                        mall = prod.get('mallName', '')
                        if safe_target in mall.lower().replace(" ", ""):
                            result['rank'] = str((page - 1) * 40 + idx + 1)
                            p = str(prod.get('lowPrice', prod.get('price', 0)))
                            result['my_price'] = f"{int(p):,}원" if p.isdigit() and p != '0' else "-"
                            df = prod.get('deliveryFeeContent', prod.get('deliveryFee', '-'))
                            result['my_shipping'] = '무료' if str(df) == '0' else (f"{int(df):,}원" if str(df).isdigit() else str(df))
                            pc = prod.get('purchaseCnt', prod.get('keepCnt', prod.get('reviewCount', '-')))
                            if str(pc) != '0' and str(pc) != '-': result['my_purchase'] = str(pc)
                            result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('pcUrl', '-')))
                            result['my_title'] = clean_text(prod.get('productTitle', prod.get('bookTitle', '')))
                            print(f"[CCTV-DEBUG] 🎯 [웹 스크래핑] 매칭 성공 (일반리스트)! 추출된 데이터: {result}", flush=True)
                            return result
                except Exception as e:
                    print(f"[CCTV-DEBUG] ❌ [웹 스크래핑] JSON 파싱 에러: {e}", flush=True)
            if find_rank: time.sleep(0.5) 
    
    print(f"[CCTV-DEBUG] ⚠️ [웹 스크래핑] '{target_mall}' 상점의 상품을 발견하지 못했습니다.", flush=True)
    return result

def get_exact_product_info_commerce_api(token, keyword, isbn):
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    matched_product = None
    
    print(f"\n[CCTV-DEBUG] 🟢 [커머스 API] 내 상점 데이터 다이렉트 검색 시작! (Target ISBN: [{isbn}], Target Keyword: [{keyword}])", flush=True)

    # 1순위: 무조건 ISBN으로 내 상점 상품 검색
    if isbn and isbn != '-':
        try:
            print(f"[CCTV-DEBUG] 🟢 [커머스 API] 1순위: ISBN({isbn})으로 검색 요청 중...", flush=True)
            res = requests.post(url, headers=headers, json={"page": 1, "size": 50, "sellerManagementCode": isbn}, timeout=5)
            print(f"[CCTV-DEBUG] 🟢 [커머스 API] ISBN 검색 응답 코드: {res.status_code}", flush=True)
            if res.status_code == 200 and res.json().get('contents'): 
                matched_product = res.json()['contents'][0]
                print(f"[CCTV-DEBUG] 🎯 [커머스 API] ISBN 매칭 성공! 찾은 상품명: [{matched_product.get('name')}]", flush=True)
            else:
                print(f"[CCTV-DEBUG] ❌ [커머스 API] ISBN으로 내 상점에서 상품을 찾을 수 없음 (등록된 관리코드가 없거나 다름)", flush=True)
        except Exception as e:
            print(f"[CCTV-DEBUG] 💥 [커머스 API] ISBN 검색 중 에러: {e}", flush=True)
        
    # 2순위: ISBN으로 못 찾았을 경우에만 키워드(상품명)로 검색
    if not matched_product and keyword:
        try:
            print(f"[CCTV-DEBUG] 🟢 [커머스 API] 2순위: 키워드({keyword})로 검색 요청 중...", flush=True)
            res = requests.post(url, headers=headers, json={"page": 1, "size": 50, "productName": keyword}, timeout=5)
            print(f"[CCTV-DEBUG] 🟢 [커머스 API] 키워드 검색 응답 코드: {res.status_code}", flush=True)
            if res.status_code == 200 and res.json().get('contents'): 
                matched_product = res.json()['contents'][0]
                print(f"[CCTV-DEBUG] 🎯 [커머스 API] 키워드 매칭 성공! 찾은 상품명: [{matched_product.get('name')}]", flush=True)
            else:
                print(f"[CCTV-DEBUG] ❌ [커머스 API] 키워드로 내 상점에서 상품을 찾을 수 없음", flush=True)
        except Exception as e:
            print(f"[CCTV-DEBUG] 💥 [커머스 API] 키워드 검색 중 에러: {e}", flush=True)
        
    result = {}
    if matched_product:
        c_no = matched_product.get('channelProducts', [{}])[0].get('channelProductNo')
        o_no = matched_product.get('originProductNo')
        
        if c_no: result['my_link'] = f"https://smartstore.naver.com/main/products/{c_no}"
        
        sale_price = matched_product.get('salePrice')
        if sale_price is not None: result['my_price'] = f"{sale_price:,}원"
        
        result['my_title'] = matched_product.get('channelProducts', [{}])[0].get('name', matched_product.get('name'))
        
        if o_no:
            try:
                detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                detail_res = requests.get(detail_url, headers=headers, timeout=5)
                if detail_res.status_code == 200:
                    origin_data = detail_res.json()
                    delivery_fee = origin_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                    if delivery_fee is not None:
                        result['my_shipping'] = "무료" if delivery_fee == 0 else f"{delivery_fee:,}원"
                    book_info = origin_data.get('detailAttribute', {}).get('bookInfo', {})
                    if book_info and book_info.get('publisher'):
                        result['my_publisher'] = book_info.get('publisher')
            except Exception as e: 
                print(f"[CCTV-DEBUG] 💥 [커머스 API] 상세 속성(배송비/출판사) 조회 실패: {e}", flush=True)
        
        print(f"[CCTV-DEBUG] 📦 [커머스 API 최종 추출 데이터]: {result}", flush=True)
    return result

def scrape_smartstore_purchase_count(product_link):
    if not product_link or "smartstore.naver.com" not in product_link: return "-"
    print(f"[CCTV-DEBUG] 🛒 [구매수 직접 추적] 상점 링크 접속 중... ({product_link})", flush=True)
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}
        res = requests.get(product_link, headers=headers, timeout=5)
        if res.status_code == 200:
            sell_match = re.search(r'"sellCount"\s*:\s*(\d+)', res.text)
            if sell_match: 
                print(f"[CCTV-DEBUG] 🛒 [구매수 획득 성공] sellCount: {sell_match.group(1)}", flush=True)
                return sell_match.group(1)
            review_match = re.search(r'"reviewCount"\s*:\s*(\d+)', res.text)
            if review_match: 
                print(f"[CCTV-DEBUG] 🛒 [구매수 획득(리뷰대체)] reviewCount: {review_match.group(1)}", flush=True)
                return review_match.group(1)
        print(f"[CCTV-DEBUG] 🛒 [구매수 추적 실패] 응답코드: {res.status_code}, 정규식 매칭 실패", flush=True)
    except Exception as e: 
        print(f"[CCTV-DEBUG] 🛒 [구매수 추적 에러] {e}", flush=True)
    return "-"

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids, update_mode):
    with app.app_context():
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            safe_target = target_mall_name.lower().replace(" ", "")
            
            commerce_token = None
            if api_key:
                commerce_token = get_naver_token(api_key.client_id, api_key.client_secret)
                
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
                
                print(f"\n============================================================")
                print(f"[CCTV-DEBUG] 🚀 [모니터링 단일 업데이트 시작] ID: {k_id}")
                print(f"[CCTV-DEBUG] 🚀 저장된 키워드: [{keyword_text}] / 저장된 ISBN: [{target_isbn}]")
                print(f"============================================================", flush=True)
                
                db.session.commit()

                updates = {}

                # ========================================================
                # 1. 순위 파악
                # ========================================================
                kw_info_web = {}
                if update_mode in ['all', 'rank']:
                    kw_info_web = get_naver_shopping_info([keyword_text], target_mall_name, find_rank=True)
                    updates['store_rank'] = kw_info_web.get('rank', '500위 밖')
                    print(f"[CCTV-DEBUG] 📊 [순위] 스크래핑 결과: {updates['store_rank']}", flush=True)
                    
                    if updates['store_rank'] == '500위 밖' and api_headers:
                        found_rank = False
                        try:
                            print(f"[CCTV-DEBUG] 📊 [순위] 500위 밖이거나 차단됨. Search API 비상 탐색 시작...", flush=True)
                            for start_idx in range(1, 402, 100):
                                if found_rank: break
                                api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}", headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    for idx, item in enumerate(api_res.json().get('items', [])):
                                        if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                            updates['store_rank'] = str(start_idx + idx)
                                            found_rank = True
                                            print(f"[CCTV-DEBUG] 📊 [순위] Search API로 찾음! 순위: {updates['store_rank']}", flush=True)
                                            break
                        except Exception as e: 
                            print(f"[CCTV-DEBUG] ❌ [순위] Search API 탐색 중 에러: {e}", flush=True)

                # ========================================================
                # 2. 완벽한 상품 정보 덮어쓰기
                # ========================================================
                search_list = []
                # 사용자의 핵심 요청: ISBN을 우선순위로!
                if target_isbn: search_list.append(target_isbn)
                if keyword_text: search_list.append(keyword_text)
                
                purchase_info_web = {}
                
                if update_mode in ['all', 'purchase']:
                    purchase_info_web = get_naver_shopping_info(search_list, target_mall_name, find_rank=False)

                if update_mode == 'all':
                    exact_info = {}
                    if commerce_token:
                        exact_info = get_exact_product_info_commerce_api(commerce_token, keyword_text, target_isbn)

                    print(f"[CCTV-DEBUG] ⚖️ [통합 전 데이터 비교]")
                    print(f"[CCTV-DEBUG] - Commerce API (다이렉트): {exact_info}")
                    print(f"[CCTV-DEBUG] - Web Scraping (검색결과): {purchase_info_web}")
                    print(f"[CCTV-DEBUG] - Search API (순위검색겸용): {kw_info_web}", flush=True)

                    updates['product_link'] = exact_info.get('my_link') or purchase_info_web.get('my_link') or kw_info_web.get('my_link') or '-'
                    updates['price'] = exact_info.get('my_price') or purchase_info_web.get('my_price') or kw_info_web.get('my_price') or '-'
                    updates['shipping_fee'] = exact_info.get('my_shipping') or purchase_info_web.get('my_shipping') or kw_info_web.get('my_shipping') or '-'
                    updates['book_title'] = exact_info.get('my_title') or purchase_info_web.get('my_title') or kw_info_web.get('my_title') or '-'
                    updates['publisher'] = exact_info.get('my_publisher') or '-'
                    updates['store_name'] = target_mall_name

                    # 그래도 비어있다면, Search API 로 보완
                    if updates['book_title'] == '-' or updates['price'] == '-' or updates['product_link'] == '-':
                        if api_headers:
                            print(f"[CCTV-DEBUG] 🔧 [보완] 여전히 빈칸이 있어 Search API 로직 호출...", flush=True)
                            for sq in search_list:
                                try:
                                    api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(sq)}&display=100", headers=api_headers, timeout=3)
                                    if api_res.status_code == 200:
                                        for item in api_res.json().get('items', []):
                                            if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                                if updates['book_title'] == '-':
                                                    clean_t = clean_text(item.get('title', ''))
                                                    if clean_t: updates['book_title'] = clean_t
                                                if updates['price'] == '-':
                                                    p = item.get('lprice', '0')
                                                    if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                                if updates['product_link'] == '-':
                                                    raw_link = item.get('link', '-')
                                                    if raw_link != '-': updates['product_link'] = raw_link.replace('http://', 'https://')
                                                break
                                except: pass

                    if updates['publisher'] == '-' and target_isbn and api_headers:
                        try:
                            book_res = requests.get(f"https://openapi.naver.com/v1/search/book.json?d_isbn={urllib.parse.quote(target_isbn)}", headers=api_headers, timeout=3)
                            if book_res.status_code == 200 and book_res.json().get('items'):
                                b_item = book_res.json()['items'][0]
                                updates['publisher'] = clean_text(b_item.get('publisher', '-'))
                        except: pass

                # ========================================================
                # 3. 구매수 획득
                # ========================================================
                if update_mode in ['all', 'purchase']:
                    pc = purchase_info_web.get('my_purchase', '-')
                    if pc == '-' and 'product_link' in updates and updates['product_link'] != '-':
                        pc = scrape_smartstore_purchase_count(updates['product_link'])
                    elif pc == '-' and kw.product_link and kw.product_link != '-':
                        pc = scrape_smartstore_purchase_count(kw.product_link)
                    updates['purchase_count'] = pc
                    print(f"[CCTV-DEBUG] 🛒 [최종 구매수 판정] : {pc}", flush=True)

                # DB 저장 전 최종 내역 확인
                print(f"[CCTV-DEBUG] ✅ [최종 DB 덮어쓰기 데이터] : {updates}", flush=True)
                
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if 'store_rank' in updates: kw.store_rank = updates['store_rank']
                    if hasattr(kw, 'purchase_count') and 'purchase_count' in updates: 
                        kw.purchase_count = updates['purchase_count']
                    if update_mode == 'all':
                        if updates.get('book_title') and updates['book_title'] != '-': kw.book_title = updates['book_title']
                        if updates.get('publisher') and updates['publisher'] != '-': kw.publisher = updates['publisher']
                        if updates.get('price') and updates['price'] != '-': kw.price = updates['price']
                        if updates.get('product_link') and updates['product_link'] != '-': kw.product_link = updates['product_link']
                        if updates.get('shipping_fee') and updates['shipping_fee'] != '-': kw.shipping_fee = updates['shipping_fee']
                        kw.store_name = updates.get('store_name', target_mall_name)
                    
                    db.session.commit()

            except Exception as e:
                print(f"[CCTV-DEBUG] 💥 [치명적 에러 발생] : {e}", traceback.format_exc(), flush=True)
                db.session.rollback()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if update_mode in ['all', 'rank']: kw.store_rank = "에러"
                    db.session.commit()
            
            time.sleep(random.uniform(2.5, 4.0))

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    return jsonify({'success': False, 'message': '체크박스로 항목을 선택한 뒤 업데이트 버튼을 사용해주세요!'})

@monitoring_bp.route('/api/refresh_by_isbn', methods=['POST'])
@login_required
def refresh_by_isbn():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    selected_ids = request.form.getlist('ids[]')
    update_mode = request.form.get('update_mode', 'all') 
    
    if not selected_ids: return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    target_ids = []
    
    for kw in keywords:
        if update_mode in ['all', 'rank']:
            if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
                kw.prev_store_rank = kw.store_rank
            kw.store_rank = "⏳ 수집중..."
        
        if update_mode in ['all', 'purchase'] and hasattr(kw, 'purchase_count'):
            kw.purchase_count = "⏳ 수집중..."
            
        target_ids.append(kw.id)
            
    db.session.commit()
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 선택한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids, update_mode))
    thread.start()
    
    msg = "데이터 수집을 시작합니다."
    if update_mode == 'rank': msg = "순위 수집을 시작합니다."
    elif update_mode == 'purchase': msg = "구매수 수집을 시작합니다."
    
    return jsonify({'success': True, 'message': f'✅ {msg} 잠시 후 새로고침 해주세요.'})
