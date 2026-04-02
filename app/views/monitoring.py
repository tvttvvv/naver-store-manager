import os
import time
import re
import traceback
import random
import html
from datetime import datetime
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

# ✨ 새로 추가된 러닝메이트 라우트(경로) 입니다 ✨
@monitoring_bp.route('/runningmate')
@login_required
def runningmate():
    return render_template('monitoring/runningmate.html')

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
        db.session.execute(text("ALTER TABLE monitored_keyword ADD COLUMN stock_quantity VARCHAR(50) DEFAULT '-'"))
        db.session.commit()
    except Exception: db.session.rollback()

    try:
        db.session.execute(text("ALTER TABLE monitored_keyword ADD COLUMN registered_at VARCHAR(50) DEFAULT '-'"))
        db.session.commit()
    except Exception: db.session.rollback()
    
    try:
        db.session.execute(text("ALTER TABLE monitored_keyword ADD COLUMN sales_status VARCHAR(50) DEFAULT '-'"))
        db.session.commit()
    except Exception: db.session.rollback()

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
        'stock_quantity': getattr(k, 'stock_quantity', '-'),
        'sales_status': getattr(k, 'sales_status', '-'),
        'registered_at': getattr(k, 'registered_at', '-')
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
        if 'isbn' in request.form:
            new_isbn = request.form.get('isbn', '-').strip()
            if new_isbn and new_isbn != '-':
                duplicate = MonitoredKeyword.query.filter(
                    MonitoredKeyword.user_id == current_user.id,
                    MonitoredKeyword.isbn == new_isbn,
                    MonitoredKeyword.id != kw.id
                ).first()
                if duplicate:
                    return jsonify({'success': False, 'message': f'🚨 경고: 이미 등록된 ISBN입니다!\n\n입력하신 ISBN은 이미 [{duplicate.keyword}] 항목에 등록되어 있습니다.'})
            kw.isbn = new_isbn

        if 'keyword' in request.form: kw.keyword = request.form.get('keyword')
        if 'publisher' in request.form: kw.publisher = request.form.get('publisher')
        if 'supply_rate' in request.form: kw.supply_rate = request.form.get('supply_rate')
        if 'price' in request.form: kw.price = request.form.get('price')
        if 'shipping_fee' in request.form: kw.shipping_fee = request.form.get('shipping_fee')
        if 'book_title' in request.form: kw.book_title = request.form.get('book_title')
        if 'product_link' in request.form: kw.product_link = request.form.get('product_link')
        if 'store_rank' in request.form: kw.store_rank = request.form.get('store_rank')
        if 'stock_quantity' in request.form: kw.stock_quantity = request.form.get('stock_quantity')
        if 'sales_status' in request.form: kw.sales_status = request.form.get('sales_status')
        if 'store_name' in request.form: kw.store_name = request.form.get('store_name') 
            
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
        if hasattr(kw, 'stock_quantity'): kw.stock_quantity = '-'
        if hasattr(kw, 'sales_status'): kw.sales_status = '-'
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 항목의 검색 정보가 초기화되었습니다.'})

def get_exact_product_info_commerce_api(token, isbn):
    if not token: return {}
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    matched_product = None
    pure_isbn = str(isbn).strip().replace('-', '') if isbn and isbn != '-' else ""
    if not pure_isbn: return {}

    try:
        payload = {"searchKeywordType": "SELLER_CODE", "sellerManagementCode": pure_isbn, "page": 1, "size": 50}
        res = requests.post(url, headers=headers, json=payload, timeout=5)
        if res.status_code == 200:
            contents = res.json().get('contents', [])
            for item in contents:
                c_prod = item.get('channelProducts', [{}])[0]
                item_code = str(c_prod.get('sellerManagementCode', '')).strip().replace('-', '')
                if item_code == pure_isbn:
                    matched_product = item
                    break
    except Exception: pass

    if not matched_product:
        try:
            payload = {"page": 1, "size": 50}
            res = requests.post(url, headers=headers, json=payload, timeout=5)
            if res.status_code == 200:
                contents = res.json().get('contents', [])
                for item in contents:
                    c_prod = item.get('channelProducts', [{}])[0]
                    item_code = str(c_prod.get('sellerManagementCode', '')).strip().replace('-', '')
                    item_name = str(c_prod.get('name', '')).replace('-', '')
                    if pure_isbn in item_code or pure_isbn in item_name:
                        matched_product = item
                        break
        except Exception: pass

    result = {}
    if matched_product:
        c_prod = matched_product.get('channelProducts', [{}])[0]
        c_no = c_prod.get('channelProductNo')
        o_no = matched_product.get('originProductNo')
        sale_price = c_prod.get('salePrice')
        
        result['my_title'] = c_prod.get('name', matched_product.get('name', '-'))
        result['my_link'] = f"https://smartstore.naver.com/main/products/{c_no}" if c_no else "-"
        publisher = ""
        stock_val = None
        
        status_raw = c_prod.get('statusType') or matched_product.get('statusType')
        status_kr = "-"
        if status_raw == 'SALE': status_kr = '판매중'
        elif status_raw == 'OUTOFSTOCK': status_kr = '품절'
        elif status_raw == 'SUSPENSION': status_kr = '판매중지'
        elif status_raw == 'CLOSE': status_kr = '판매종료'
        elif status_raw == 'PROHIBITION': status_kr = '판매금지'
        elif status_raw: status_kr = str(status_raw)
        result['my_status'] = status_kr
        
        if o_no:
            try:
                detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                detail_res = requests.get(detail_url, headers=headers, timeout=5)
                if detail_res.status_code == 200:
                    origin_data = detail_res.json()
                    if sale_price is None: sale_price = origin_data.get('salePrice') or origin_data.get('price')
                    
                    if 'stockQuantity' in origin_data:
                        stock_val = origin_data.get('stockQuantity')
                        
                    detail_attr = origin_data.get('detailAttribute', {})
                    publisher = detail_attr.get('bookInfo', {}).get('publisher') or detail_attr.get('customInfo', {}).get('manufacturer') or detail_attr.get('customInfo', {}).get('brand') or detail_attr.get('naverShoppingSearchInfo', {}).get('manufacturerName') or detail_attr.get('naverShoppingSearchInfo', {}).get('brandName') or origin_data.get('manufacturerName') or origin_data.get('brandName')
            except Exception: pass
            
        if stock_val is None and c_no:
            try:
                c_url = f"https://api.commerce.naver.com/external/v2/products/channel-products/{c_no}"
                c_res = requests.get(c_url, headers=headers, timeout=5)
                if c_res.status_code == 200:
                    c_data = c_res.json()
                    if 'stockQuantity' in c_data:
                        stock_val = c_data.get('stockQuantity')
            except Exception: pass

        if stock_val is None:
            stock_val = c_prod.get('stockQuantity') or matched_product.get('stockQuantity')

        if stock_val is not None:
            result['my_stock'] = f"{stock_val:,}개"

        if not publisher: publisher = matched_product.get('manufacturerName') or matched_product.get('brandName') or c_prod.get('manufacturerName') or c_prod.get('brandName')
        
        result['my_publisher'] = publisher if publisher else "-"
        result['my_price'] = f"{sale_price:,}원" if sale_price is not None else "-"
        
    return result

monitoring_tasks = {}

def async_refresh_by_isbn(app, user_id, target_ids, update_mode, fill_empty_only):
    global monitoring_tasks
    monitoring_tasks[user_id] = {
        "is_running": True,
        "total": len(target_ids),
        "current": 0,
        "logs": [],
        "mode": update_mode
    }

    with app.app_context():
        api_keys = ApiKey.query.filter_by(user_id=user_id).all()
        store_tokens = {}
        for key in api_keys:
            token = get_naver_token(key.client_id, key.client_secret)
            if token:
                store_tokens[key.store_name] = token

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: 
                    monitoring_tasks[user_id]["current"] += 1
                    continue
                    
                target_isbn = str(kw.isbn).strip() if kw.isbn and kw.isbn != '-' else ""
                keyword_name = kw.keyword or f"ID:{k_id}"
                
                if not target_isbn:
                    monitoring_tasks[user_id]["current"] += 1
                    monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ⏩ ISBN 없음 (초고속 스킵)")
                    continue 

                target_store = kw.store_name or '-'
                if target_store == '-':
                    monitoring_tasks[user_id]["current"] += 1
                    monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ⏩ 상점 미선택 (스킵)")
                    continue

                commerce_token = store_tokens.get(target_store)
                if not commerce_token:
                    monitoring_tasks[user_id]["current"] += 1
                    monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ❌ [{target_store}] 토큰 오류")
                    continue

                updates = {}

                if update_mode in ['all', 'info', 'stock']:
                    exact_info = {}
                    if commerce_token and target_isbn:
                        exact_info = get_exact_product_info_commerce_api(commerce_token, target_isbn)

                    if update_mode in ['all', 'info']:
                        if exact_info.get('my_title'): updates['book_title'] = exact_info['my_title']
                        if exact_info.get('my_link'): updates['product_link'] = exact_info['my_link']
                        if exact_info.get('my_price'): updates['price'] = exact_info['my_price']
                        if exact_info.get('my_publisher'): updates['publisher'] = exact_info['my_publisher']
                        if exact_info.get('my_status'): updates['sales_status'] = exact_info['my_status'] 

                    if update_mode in ['all', 'stock']:
                        if exact_info.get('my_stock'): 
                            updates['stock_quantity'] = exact_info['my_stock']

                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    def should_update(current_val):
                        if not fill_empty_only: return True 
                        return current_val in [None, '', '-'] 

                    if update_mode in ['all', 'info']:
                        if updates.get('book_title') and should_update(kw.book_title): kw.book_title = updates['book_title']
                        if updates.get('product_link') and should_update(kw.product_link): kw.product_link = updates['product_link']
                        if updates.get('price') and should_update(kw.price): kw.price = updates['price']
                        if updates.get('publisher') and should_update(kw.publisher): kw.publisher = updates['publisher']
                        if updates.get('sales_status') and should_update(kw.sales_status): kw.sales_status = updates['sales_status']
                    
                    if update_mode in ['all', 'stock']:
                        if updates.get('stock_quantity') and should_update(kw.stock_quantity):
                            kw.stock_quantity = updates['stock_quantity']
                    
                    db.session.commit()
                    
                monitoring_tasks[user_id]["current"] += 1
                store_label = f"({target_store})" if target_store and target_store != '-' else ""
                
                if update_mode in ['all', 'stock']:
                    stock_log_msg = updates.get('stock_quantity', '추출불가')
                    monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ✅ {store_label} (재고: {stock_log_msg})")
                else:
                    monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ✅ {store_label} 완료")

            except Exception as e:
                db.session.rollback()
                monitoring_tasks[user_id]["current"] += 1
                monitoring_tasks[user_id]["logs"].append(f"[{keyword_name}] ❌ 작업 중 오류 발생")
            
            time.sleep(1.0)
            
    monitoring_tasks[user_id]["is_running"] = False

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    return jsonify({'success': False, 'message': '체크박스로 항목을 선택한 뒤 업데이트 버튼을 사용해주세요!'})

@monitoring_bp.route('/api/refresh_by_isbn', methods=['POST'])
@login_required
def refresh_by_isbn():
    app = current_app._get_current_object()
    user_id = current_user.id
    
    if monitoring_tasks.get(user_id, {}).get("is_running", False):
        return jsonify({'success': False, 'message': '⚠️ 이미 다른 업데이트 작업이 진행 중입니다. 잠시만 기다려주세요.'})
        
    selected_ids = request.form.getlist('ids[]')
    update_mode = request.form.get('update_mode', 'all') 
    fill_empty_only = request.form.get('fill_empty_only') == 'true'
    
    if not selected_ids: return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    target_ids = [kw.id for kw in keywords]
            
    db.session.commit()
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 선택한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, target_ids, update_mode, fill_empty_only))
    thread.start()
    
    return jsonify({'success': True, 'message': '✅ 백그라운드 스캔 작업이 시작되었습니다.'})

@monitoring_bp.route('/api/task_status', methods=['GET'])
@login_required
def get_task_status():
    user_id = current_user.id
    task = monitoring_tasks.get(user_id, {
        "is_running": False,
        "total": 0,
        "current": 0,
        "logs": []
    })
    return jsonify(task)
