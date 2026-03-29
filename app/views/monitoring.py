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
    bots = [
        ("Normal Chrome", {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7",
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
                            result['general_title'] = clean_text(info.get('bookTitle', info.get('productName', '')))
                            result['general_publisher'] = clean_text(info.get('publisher', '-'))
                            gp = str(info.get('lowestPrice', info.get('lowPrice', info.get('price', 0))))
                            result['general_price'] = f"{int(gp):,}원" if gp.isdigit() and gp != '0' else "-"
                            cat_id = info.get('id', '')
                            result['general_link'] = f"https://search.shopping.naver.com/book/catalog/{cat_id}" if cat_id else "-"

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
                                return result
                        
                        if not find_rank: return result 
                        else: break 

                    book_list = state.get('book', {}).get('list', [])
                    if not book_list: break 

                    if page == 1 and not result.get('general_title'):
                        first_item = book_list[0].get('item', book_list[0])
                        result['general_title'] = clean_text(first_item.get('bookTitle', first_item.get('productTitle', '')))
                        result['general_publisher'] = clean_text(first_item.get('publisher', '-'))
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
                            
                            pc = prod.get('purchaseCnt', prod.get('keepCnt', prod.get('reviewCount', '-')))
                            if str(pc) != '0' and str(pc) != '-': result['my_purchase'] = str(pc)
                            
                            result['my_link'] = prod.get('mallPcUrl', prod.get('mallProductUrl', prod.get('pcUrl', '-')))
                            result['my_title'] = clean_text(prod.get('productTitle', prod.get('bookTitle', '')))
                            return result
                            
                except Exception: break
            if find_rank: time.sleep(0.1) 
    return result

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids, update_mode):
    with app.app_context():
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
                    'store_rank': kw.store_rank,
                    'purchase_count': getattr(kw, 'purchase_count', '-'),
                    'book_title': kw.book_title,
                    'product_link': kw.product_link,
                    'price': kw.price,
                    'shipping_fee': kw.shipping_fee,
                    'publisher': kw.publisher,
                    'store_name': kw.store_name
                }

                search_queries = []
                if target_isbn: search_queries.append(target_isbn)
                if keyword_text: search_queries.append(keyword_text)

                kw_info = {}
                if update_mode in ['all', 'rank', 'purchase']:
                    kw_info = get_naver_shopping_info(search_queries, target_mall_name, find_rank=True)

                if update_mode in ['all', 'rank']:
                    if kw_info.get('rank'):
                        updates['store_rank'] = kw_info['rank']
                        updates['store_name'] = target_mall_name
                    else:
                        updates['store_rank'] = '500위 밖'
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
                                                updates['store_name'] = item.get('mallName')
                                                found_rank = True
                                                break
                            except Exception: pass

                if update_mode in ['all', 'purchase']:
                    if kw_info.get('my_purchase'):
                        updates['purchase_count'] = kw_info['my_purchase']
                    else:
                        updates['purchase_count'] = '-'

                if update_mode == 'all':
                    if kw_info.get('my_title'): updates['book_title'] = kw_info['my_title']
                    elif kw_info.get('general_title'): updates['book_title'] = kw_info['general_title']
                    
                    if kw_info.get('my_price'): updates['price'] = kw_info['my_price']
                    elif kw_info.get('general_price'): updates['price'] = kw_info['general_price']
                    
                    if kw_info.get('my_shipping'): updates['shipping_fee'] = kw_info['my_shipping']
                    
                    if kw_info.get('my_link') and kw_info['my_link'] != '-': updates['product_link'] = kw_info['my_link']
                    elif kw_info.get('general_link'): updates['product_link'] = kw_info['general_link']

                    if kw_info.get('general_publisher'): updates['publisher'] = kw_info['general_publisher']
                    updates['store_name'] = target_mall_name

                    if api_headers and search_client_id:
                        api_found = False
                        for sq in search_queries:
                            if api_found: break
                            try:
                                api_res = requests.get(f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(sq)}&display=100", headers=api_headers, timeout=3)
                                if api_res.status_code == 200:
                                    for item in api_res.json().get('items', []):
                                        if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                            clean_t = clean_text(item.get('title', ''))
                                            if clean_t: updates['book_title'] = clean_t
                                            
                                            p = item.get('lprice', '0')
                                            if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                            
                                            api_found = True
                                            break
                            except Exception: pass

                        if target_isbn:
                            try:
                                book_res = requests.get(f"https://openapi.naver.com/v1/search/book.json?d_isbn={urllib.parse.quote(target_isbn)}", headers=api_headers, timeout=3)
                                if book_res.status_code == 200 and book_res.json().get('items'):
                                    b_item = book_res.json()['items'][0]
                                    updates['publisher'] = clean_text(b_item.get('publisher', '-'))
                            except Exception: pass

                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if 'store_rank' in updates: kw.store_rank = updates['store_rank']
                    if hasattr(kw, 'purchase_count') and 'purchase_count' in updates: 
                        kw.purchase_count = updates['purchase_count']
                    
                    if update_mode == 'all':
                        if updates['book_title']: kw.book_title = updates['book_title']
                        if updates['publisher']: kw.publisher = updates['publisher']
                        if updates['price']: kw.price = updates['price']
                        if updates['product_link'] and updates['product_link'] != '-': kw.product_link = updates['product_link']
                        if updates['shipping_fee']: kw.shipping_fee = updates['shipping_fee']
                        kw.store_name = updates['store_name']
                    
                    db.session.commit()

            except Exception as e:
                db.session.rollback()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if update_mode in ['all', 'rank']: kw.store_rank = "에러"
                    db.session.commit()
            
            # API 보호를 위한 딜레이
            time.sleep(1.5) 

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
