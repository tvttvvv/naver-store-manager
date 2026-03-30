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
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    }
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200: return res.text
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
                        products = state['catalog'].get('products', [])
                        for idx, prod in enumerate(products):
                            mall = prod.get('mallName', '')
                            if safe_target in mall.lower().replace(" ", ""):
                                result['rank'] = str((page - 1) * 40 + idx + 1)
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
                            return result
                except Exception: pass
            if find_rank: time.sleep(0.5) 
    return result

# ✨ 1단계 핵심: 네이버 커머스 API 상품/링크 탐색 로직 (출판사, 배송비, 링크 버그 완벽 수정 적용됨)
def get_exact_product_info_commerce_api(token, keyword, isbn):
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    matched_product = None
    
    print(f"\n[CCTV-DEBUG] 🟢 [1단계: 상품/링크 탐색] 시작 - 타겟 ISBN: [{isbn}], 타겟 키워드: [{keyword}]", flush=True)

    clean_keyword = keyword.replace(" ", "").lower() if keyword and keyword != '-' else ""
    clean_isbn = str(isbn).strip() if isbn and isbn != '-' else ""
    
    # 1순위: ISBN 번호로 네이버에 다이렉트 검색
    if clean_isbn:
        try:
            payload = {"page": 1, "size": 50, "sellerManagementCode": clean_isbn}
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            if res.status_code == 200:
                for item in res.json().get('contents', []):
                    if str(item.get('sellerManagementCode', '')).strip() == clean_isbn:
                        matched_product = item
                        print(f"[CCTV-DEBUG] 🎯 [매칭 성공] 다이렉트 ISBN 검색망으로 즉시 검거 완료!", flush=True)
                        break
        except Exception as e:
            print(f"[CCTV-DEBUG] 💥 ISBN 검색 에러: {e}", flush=True)

    # 2순위: ISBN으로 못 찾았으면 상품명(키워드)으로 다이렉트 검색
    if not matched_product and clean_keyword:
        try:
            payload = {"page": 1, "size": 50, "productName": keyword}
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            if res.status_code == 200:
                for item in res.json().get('contents', []):
                    name = str(item.get('name', ''))
                    if clean_keyword in name.replace(" ", "").lower():
                        matched_product = item
                        print(f"[CCTV-DEBUG] 🎯 [매칭 성공] 다이렉트 키워드 검색망으로 즉시 검거 완료!", flush=True)
                        break
        except Exception as e:
            print(f"[CCTV-DEBUG] 💥 키워드 검색 에러: {e}", flush=True)

    # 3순위: 그래도 없으면 최근 50개 상품 중에서 유사한 이름/ISBN 필터링 (Fallback)
    if not matched_product:
        try:
            payload = {"page": 1, "size": 50, "orderType": "NO"}
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            if res.status_code == 200:
                for item in res.json().get('contents', []):
                    name = str(item.get('name', '')).replace(" ", "").lower()
                    if (clean_keyword and clean_keyword in name) or (clean_isbn and clean_isbn in name):
                        matched_product = item
                        print(f"[CCTV-DEBUG] 🎯 [매칭 성공] 최근 등록 목록에서 매칭 완료!", flush=True)
                        break
        except Exception:
            pass

    result = {}
    if matched_product:
        name = matched_product.get('name', '이름 없음')
        # 버그 수정: channelProductNo는 channelProducts 리스트 안에 있습니다.
        c_no = matched_product.get('channelProducts', [{}])[0].get('channelProductNo')
        o_no = matched_product.get('originProductNo')
        sale_price = matched_product.get('salePrice')
        
        result['my_title'] = name
        result['my_link'] = f"https://smartstore.naver.com/main/products/{c_no}" if c_no else "-"
        result['my_price'] = f"{sale_price:,}원" if sale_price is not None else "-"
        
        # 누락되었던 상세 데이터(출판사, 배송비) 조회를 위해 원본 상품 상세 API 호출 추가!
        if o_no:
            try:
                detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                detail_res = requests.get(detail_url, headers=headers, timeout=5)
                if detail_res.status_code == 200:
                    origin_data = detail_res.json()
                    delivery_fee = origin_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                    if delivery_fee is not None:
                        result['my_shipping_fee'] = "무료" if delivery_fee == 0 else f"{delivery_fee:,}원"
                        
                    book_info = origin_data.get('detailAttribute', {}).get('bookInfo', {})
                    if book_info:
                        if book_info.get('publisher'): result['my_publisher'] = book_info.get('publisher')
                        if book_info.get('isbn'): result['my_isbn'] = book_info.get('isbn')
            except Exception as e:
                print(f"[CCTV-DEBUG] 💥 상세 데이터 조회 에러: {e}", flush=True)
        
        print(f"[CCTV-DEBUG] 📦 [데이터 추출] 상품명: {result.get('my_title')}", flush=True)
        print(f"[CCTV-DEBUG] 📦 [데이터 추출] 직링크: {result.get('my_link')}", flush=True)
    else:
        print(f"[CCTV-DEBUG] ❌ [매칭 실패] 상점에 해당 상품이 존재하지 않거나 네이버 검색망에 잡히지 않습니다.", flush=True)

    return result

def scrape_smartstore_purchase_count(product_link):
    if not product_link or "smartstore.naver.com" not in product_link: return "-"
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"
        }
        res = requests.get(product_link, headers=headers, timeout=5)
        if res.status_code == 200:
            sell_match = re.search(r'"sellCount"\s*:\s*(\d+)', res.text)
            if sell_match: return sell_match.group(1)
            review_match = re.search(r'"reviewCount"\s*:\s*(\d+)', res.text)
            if review_match: return review_match.group(1)
    except Exception: pass
    return "-"

# ✨ 수집 실행 엔진 (DB에 출판사, 배송비 업데이트 반영 적용됨)
def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids, update_mode):
    with app.app_context():
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            
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
                
                db.session.commit()
                updates = {}

                # 순위 스크래핑 (418 차단 중이면 500위 밖 처리)
                if update_mode in ['all', 'rank']:
                    kw_info_web = get_naver_shopping_info([keyword_text], target_mall_name, find_rank=True)
                    updates['store_rank'] = kw_info_web.get('rank', '500위 밖')

                # ✨ 1단계 핵심: 상품 정보(이름, 링크, 가격, 배송비, 출판사) 즉시 매칭 적용
                if update_mode == 'all':
                    exact_info = {}
                    if commerce_token:
                        exact_info = get_exact_product_info_commerce_api(commerce_token, keyword_text, target_isbn)

                    # API에서 가져온 값이 있으면 업데이트 준비
                    if exact_info.get('my_title'): updates['book_title'] = exact_info['my_title']
                    if exact_info.get('my_link'): updates['product_link'] = exact_info['my_link']
                    if exact_info.get('my_price'): updates['price'] = exact_info['my_price']
                    if exact_info.get('my_publisher'): updates['publisher'] = exact_info['my_publisher']
                    if exact_info.get('my_shipping_fee'): updates['shipping_fee'] = exact_info['my_shipping_fee']
                    updates['store_name'] = target_mall_name

                # 구매수 직접 추적
                if update_mode in ['all', 'purchase']:
                    current_link = updates.get('product_link') or kw.product_link
                    updates['purchase_count'] = scrape_smartstore_purchase_count(current_link)

                # DB 저장 (기존 데이터가 비어있지 않으면 덮어씀)
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if 'store_rank' in updates: kw.store_rank = updates['store_rank']
                    if 'purchase_count' in updates: kw.purchase_count = updates['purchase_count']
                    
                    if update_mode == 'all':
                        if updates.get('book_title') and updates['book_title'] != '-': kw.book_title = updates['book_title']
                        if updates.get('product_link') and updates['product_link'] != '-': kw.product_link = updates['product_link']
                        if updates.get('price') and updates['price'] != '-': kw.price = updates['price']
                        if updates.get('publisher') and updates['publisher'] != '-': kw.publisher = updates['publisher']
                        if updates.get('shipping_fee') and updates['shipping_fee'] != '-': kw.shipping_fee = updates['shipping_fee']
                        kw.store_name = updates.get('store_name', target_mall_name)
                    
                    db.session.commit()
                    print(f"[CCTV-DEBUG] ✅ DB 업데이트 성공 (ID: {k_id})", flush=True)

            except Exception as e:
                print(f"[CCTV-DEBUG] 💥 작업 처리 중 에러 발생: {e}", flush=True)
                db.session.rollback()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if update_mode in ['all', 'rank']: kw.store_rank = "에러"
                    db.session.commit()
            
            # API 보호를 위한 짧은 딜레이
            time.sleep(1.0)

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
    return jsonify({'success': True, 'message': f'✅ {msg} 잠시 후 새로고침 해주세요.'})
