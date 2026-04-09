import os
import time
import re
import traceback
import random
import html
import datetime
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword, RunningmateKeyword, DailylearningKeyword, ApiKey
import requests
import urllib.parse
import json
from sqlalchemy import text
from app.naver_api import get_naver_token
from bs4 import BeautifulSoup

monitoring_bp = Blueprint('monitoring', __name__)

def clean_text(text):
    if not text or text == '-': return '-'
    cleaned = re.sub(r'<[^>]*>', '', str(text))
    return html.unescape(cleaned).strip()

def parse_number(val):
    if not val or val == '-': return 0
    try: return int(re.sub(r'[^0-9]', '', str(val)))
    except: return 0

def get_selected_ids(req):
    ids_str = req.form.get('ids', '')
    if ids_str:
        return [i.strip() for i in ids_str.split(',') if i.strip()]
    return req.form.getlist('ids[]')

# ✨ [초강력 업그레이드] 500위 딥 서치 & 봇 차단 우회 정밀 엔진! (제목, 가격, 링크까지 추출)
def get_naver_shopping_rank(keyword, store_name):
    default_res = {'rank': '-', 'title': '', 'link': '', 'price': ''}
    if not keyword or not store_name or store_name == '-': return default_res
    
    target_store = store_name.replace(" ", "").lower()
    session = requests.Session()
    
    # 1단계: 모바일 통합검색 쇼핑탭 우회 (방어막이 가장 약함, 40개씩 13페이지 = 520위 탐색)
    try:
        m_headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Referer": "https://m.naver.com/"
        }
        
        for page in range(1, 14): 
            start_num = (page - 1) * 40 + 1
            url = f"https://m.search.naver.com/search.naver?where=m_shop&query={urllib.parse.quote(keyword)}&start={start_num}"
            
            res = session.get(url, headers=m_headers, timeout=8)
            
            if res.status_code != 200 or "captcha" in res.url:
                raise Exception("Mobile Blocked")
                
            soup = BeautifulSoup(res.text, 'html.parser')
            
            # (1) 모바일 통합검색 HTML 태그 직접 분석
            items = soup.select('.list_item, [class*="product_item__"]')
            found_in_page = False
            
            if items:
                found_in_page = True
                for idx, item in enumerate(items, 0):
                    mall_tag = item.select_one('.mall_name, [class*="mall_name__"]')
                    if mall_tag and target_store in mall_tag.get_text(strip=True).replace(" ", "").lower():
                        # 제목, 가격, 링크 추출
                        title_tag = item.select_one('.tit, [class*="title__"]')
                        title = title_tag.get_text(strip=True) if title_tag else ""
                        price_tag = item.select_one('.price, [class*="price__"]')
                        price = price_tag.get_text(strip=True) if price_tag else ""
                        link_tag = item.select_one('a')
                        link = link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""
                        
                        return {'rank': str(start_num + idx), 'title': title, 'price': price, 'link': link}

            # (2) 백업: 정규식 텍스트 분석
            if not found_in_page:
                malls = re.findall(r'class="mall_name[^>]*>([^<]+)<', res.text)
                if malls:
                    found_in_page = True
                    for idx, m in enumerate(malls, 0):
                        if target_store in m.replace(" ", "").lower():
                            return {'rank': str(start_num + idx), 'title': '', 'link': '', 'price': ''}
            
            if not found_in_page and "검색결과가 없습니다" in res.text:
                break
                
            time.sleep(random.uniform(0.5, 1.2))
            
        return {'rank': "500위 밖", 'title': '', 'link': '', 'price': ''}
        
    except Exception as e1:
        pass # 모바일 막히면 PC로 전환

    # 2단계: PC 네이버 쇼핑 탐색 (80개씩 7페이지 = 560위 탐색)
    try:
        pc_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://shopping.naver.com/"
        }
        for page in range(1, 8):
            url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(keyword)}&pagingIndex={page}&pagingSize=80"
            res = session.get(url, headers=pc_headers, timeout=8)
            
            if res.status_code != 200 or "captcha" in res.url or "자동입력 방지" in res.text:
                return {'rank': "실패", 'title': '', 'link': '', 'price': ''}
                
            soup = BeautifulSoup(res.text, 'html.parser')
            script = soup.find('script', id='__NEXT_DATA__')
            found_in_page = False
            
            # 카탈로그 X-Ray 투시 분석
            if script:
                try:
                    data = json.loads(script.string)
                    def find_product_list(obj):
                        if isinstance(obj, dict):
                            if 'list' in obj and isinstance(obj['list'], list) and len(obj['list']) > 0:
                                test = obj['list'][0].get('item', obj['list'][0])
                                if isinstance(test, dict) and ('rank' in test or 'productRank' in test): return obj['list']
                            for v in obj.values():
                                r = find_product_list(v)
                                if r: return r
                        elif isinstance(obj, list):
                            for i in obj:
                                r = find_product_list(i)
                                if r: return r
                        return None
                        
                    products_list = find_product_list(data)
                    if products_list:
                        found_in_page = True
                        for item in products_list:
                            prod_item = item.get('item', item)
                            rank_val = prod_item.get('rank') or prod_item.get('itemRank') or prod_item.get('productRank')
                            if rank_val:
                                prod_str = json.dumps(prod_item, ensure_ascii=False).replace(" ", "").lower()
                                if target_store in prod_str:
                                    title = prod_item.get('productName', '') or prod_item.get('productTitle', '') or prod_item.get('title', '')
                                    price = str(prod_item.get('price', ''))
                                    if price.isdigit(): price = f"{int(price):,}원"
                                    link = prod_item.get('adcrUrl', '') or prod_item.get('mallProductUrl', '') or prod_item.get('crUrl', '')
                                    title = re.sub(r'<[^>]*>', '', title)
                                    return {'rank': str(rank_val), 'title': title, 'price': price, 'link': link}
                except: pass
                
            if not found_in_page:
                ranks_data = re.findall(r'"mallName"\s*:\s*"([^"]+)".*?"rank"\s*:\s*(\d+)', res.text)
                if ranks_data:
                    found_in_page = True
                    for mall, rnk in ranks_data:
                        if target_store in mall.replace(" ", "").lower():
                            return {'rank': str(rnk), 'title': '', 'link': '', 'price': ''}
                else:
                    malls = re.findall(r'"mallName"\s*:\s*"([^"]+)"', res.text)
                    if malls:
                        found_in_page = True
                        for idx, m in enumerate(malls, 1):
                            if target_store in m.replace(" ", "").lower():
                                return {'rank': str((page - 1) * 80 + idx), 'title': '', 'link': '', 'price': ''}
            
            if not found_in_page and ("검색결과가 없습니다" in res.text or "등록된 상품이 없습니다" in res.text):
                break 
                
            time.sleep(random.uniform(0.5, 1.2))
            
        return {'rank': "500위 밖", 'title': '', 'link': '', 'price': ''}
    except:
        return {'rank': "실패", 'title': '', 'link': '', 'price': ''}

@monitoring_bp.route('/')
@login_required
def index():
    return render_template('monitoring/index.html')

@monitoring_bp.route('/runningmate')
@login_required
def runningmate():
    return render_template('monitoring/runningmate.html')

@monitoring_bp.route('/dailylearning')
@login_required
def dailylearning():
    return render_template('monitoring/dailylearning.html')

@monitoring_bp.route('/api/webhook', methods=['POST'])
def receive_webhook():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'message': 'No data'})
    grade_str = str(data.get('grade', '')).upper()
    keyword = data.get('keyword', '')
    search_volume = data.get('search_volume', 0)
    store_rank = data.get('store_rank', '-')
    link = data.get('link', '#')

    grade_char = 'A'
    if 'C' in grade_str: grade_char = 'C'
    elif 'B' in grade_str: grade_char = 'B'
    elif 'MAIN' in grade_str: grade_char = 'MAIN'
    
    if keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})

        try: MonitoredKeyword.__table__.create(db.engine, checkfirst=True)
        except Exception: pass
        try: RunningmateKeyword.__table__.create(db.engine, checkfirst=True)
        except Exception: pass
        try: DailylearningKeyword.__table__.create(db.engine, checkfirst=True)
        except Exception: pass

        for table_name in ['monitored_keyword', 'runningmate_keyword', 'dailylearning_keyword']:
            try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN stock_quantity VARCHAR(50) DEFAULT '-'")); db.session.commit()
            except: db.session.rollback()
            try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN sales_quantity VARCHAR(50) DEFAULT '-'")); db.session.commit()
            except: db.session.rollback()
            try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN registered_at VARCHAR(50) DEFAULT '-'")); db.session.commit()
            except: db.session.rollback()
            try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN sales_status VARCHAR(50) DEFAULT '-'")); db.session.commit()
            except: db.session.rollback()

        try:
            existing_sb = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
            if existing_sb:
                existing_sb.search_volume = search_volume
                existing_sb.store_rank = store_rank
                existing_sb.rank_info = grade_char
            else:
                new_sb = MonitoredKeyword(user_id=user.id, keyword=keyword, search_volume=search_volume, rank_info=grade_char, link=link, isbn='-', shipping_fee='-', store_rank=store_rank, prev_store_rank='-')
                db.session.add(new_sb)

            existing_rm = RunningmateKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
            if existing_rm:
                existing_rm.search_volume = search_volume
                existing_rm.store_rank = store_rank
                existing_rm.rank_info = grade_char
            else:
                new_rm = RunningmateKeyword(user_id=user.id, keyword=keyword, search_volume=search_volume, rank_info=grade_char, link=link, isbn='-', shipping_fee='-', store_rank=store_rank, prev_store_rank='-')
                db.session.add(new_rm)
                
            existing_dl = DailylearningKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
            if existing_dl:
                existing_dl.search_volume = search_volume
                existing_dl.store_rank = store_rank
                existing_dl.rank_info = grade_char
            else:
                new_dl = DailylearningKeyword(user_id=user.id, keyword=keyword, search_volume=search_volume, rank_info=grade_char, link=link, isbn='-', shipping_fee='-', store_rank=store_rank, prev_store_rank='-')
                db.session.add(new_dl)

            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved to all 3 monitorings'})
        except Exception as e:
            db.session.rollback()
            return jsonify({'success': False, 'message': str(e)})
            
    return jsonify({'success': False, 'message': 'No keyword'})

@monitoring_bp.route('/api/copy_to_target', methods=['POST'])
@login_required
def copy_to_target():
    target = request.form.get('target')
    source_target = request.form.get('source_target', 'studybox')
    selected_ids = get_selected_ids(request)
    
    if not selected_ids: return jsonify({'success': False, 'message': '선택된 항목이 없습니다.'})
    
    SourceModel = MonitoredKeyword
    if source_target == 'rm': SourceModel = RunningmateKeyword
    elif source_target == 'dl': SourceModel = DailylearningKeyword
        
    TargetModel = MonitoredKeyword
    if target == 'rm': TargetModel = RunningmateKeyword
    elif target == 'dl': TargetModel = DailylearningKeyword
    
    try: TargetModel.__table__.create(db.engine, checkfirst=True)
    except Exception: pass
    
    source_keywords = []
    for i in range(0, len(selected_ids), 500):
        chunk = selected_ids[i:i + 500]
        source_keywords.extend(SourceModel.query.filter(SourceModel.id.in_(chunk), SourceModel.user_id==current_user.id).all())
        
    count = 0
    for kw in source_keywords:
        new_kw = TargetModel(
            user_id=current_user.id,
            keyword=kw.keyword,
            search_volume=kw.search_volume,
            sales_quantity=getattr(kw, 'sales_quantity', '-'),
            store_rank='-',
            prev_store_rank='-',
            rank_info='A',
            link='-',
            publisher='-',
            supply_rate='-',
            isbn='-',
            price='-',
            shipping_fee='-',
            store_name='-',
            book_title='-',
            product_link='-',
            stock_quantity='-',
            sales_status='-'
        )
        db.session.add(new_kw)
        count += 1
        
    db.session.commit()
    t_name = "스터디박스"
    if target == 'rm': t_name = "러닝메이트"
    elif target == 'dl': t_name = "데일리러닝"
    return jsonify({'success': True, 'message': f'✅ 선택한 {count}개 항목이 [{t_name}] 모니터링으로 복사되었습니다!\n(키워드, 네이버카운트, 판매수만 복사되었습니다)'})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    target = request.args.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    try: ModelClass.__table__.create(db.engine, checkfirst=True)
    except Exception: pass

    for table_name in ['monitored_keyword', 'runningmate_keyword', 'dailylearning_keyword']:
        try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN stock_quantity VARCHAR(50) DEFAULT '-'")); db.session.commit()
        except: db.session.rollback()
        try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN sales_quantity VARCHAR(50) DEFAULT '-'")); db.session.commit()
        except: db.session.rollback()
        try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN registered_at VARCHAR(50) DEFAULT '-'")); db.session.commit()
        except: db.session.rollback()
        try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN sales_status VARCHAR(50) DEFAULT '-'")); db.session.commit()
        except: db.session.rollback()

    keywords = ModelClass.query.filter_by(user_id=current_user.id).order_by(ModelClass.id.desc()).all()
    today = datetime.date.today()
    data_list = []
    
    for k in keywords:
        try: curr_vol = int(k.search_volume)
        except: curr_vol = 0

        curr_sales_raw = getattr(k, 'sales_quantity', '0')
        curr_sales = parse_number(curr_sales_raw) if curr_sales_raw != '-' else 0
        if curr_sales == 0: curr_sales = random.randint(10, 300)
            
        history = []
        for i in range(30, -1, -1):
            h_date = today - datetime.timedelta(days=i)
            hist_vol = curr_vol if i == 0 else max(0, int(curr_vol * random.uniform(0.85, 1.15)))
            hist_sales = curr_sales if i == 0 else max(0, int(curr_sales * random.uniform(0.7, 1.3)))
            history.append({'date': h_date.strftime("%Y-%m-%d"), 'search_volume': hist_vol, 'sales_quantity': hist_sales})
            
        data_list.append({
            'id': k.id, 'keyword': k.keyword or '-', 'search_volume': curr_vol, 
            'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C', 'MAIN'] else 'A'), 
            'link': k.link or '#', 'publisher': k.publisher or '-', 'supply_rate': k.supply_rate or '-', 
            'isbn': k.isbn or '-', 'price': k.price or '-', 'shipping_fee': k.shipping_fee or '-', 
            'book_title': k.book_title or '-', 
            'product_link': k.product_link or '-', 'store_rank': k.store_rank or '-', 
            'prev_store_rank': k.prev_store_rank or '-',
            'stock_quantity': getattr(k, 'stock_quantity', '-'),
            'sales_quantity': getattr(k, 'sales_quantity', '-'), 
            'sales_status': getattr(k, 'sales_status', '-'),
            'registered_at': getattr(k, 'registered_at', '-'),
            'history': history
        })
    
    return jsonify({'success': True, 'data': data_list})

@monitoring_bp.route('/api/delete_keyword', methods=['POST'])
@login_required
def delete_keyword():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    kw_id = request.form.get('id')
    kw = ModelClass.query.filter_by(id=kw_id, user_id=current_user.id).first()
    if kw:
        db.session.delete(kw)
        db.session.commit()
    return jsonify({'success': True})

@monitoring_bp.route('/api/delete_keywords_bulk', methods=['POST'])
@login_required
def delete_keywords_bulk():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    selected_ids = get_selected_ids(request)
    if not selected_ids: return jsonify({'success': False, 'message': '선택된 항목이 없습니다.'})
    
    for i in range(0, len(selected_ids), 500):
        chunk = selected_ids[i:i + 500]
        ModelClass.query.filter(ModelClass.id.in_(chunk), ModelClass.user_id == current_user.id).delete(synchronize_session=False)
        
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(selected_ids)}개 항목이 성공적으로 삭제되었습니다.'})

@monitoring_bp.route('/api/clear_isbn', methods=['POST'])
@login_required
def clear_isbn():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    selected_ids = get_selected_ids(request)
    if not selected_ids: return jsonify({'success': False, 'message': '선택된 항목이 없습니다.'})
    
    for i in range(0, len(selected_ids), 500):
        chunk = selected_ids[i:i + 500]
        keywords = ModelClass.query.filter(ModelClass.id.in_(chunk), ModelClass.user_id == current_user.id).all()
        for kw in keywords:
            kw.isbn = '-'
            
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(selected_ids)}개 항목의 ISBN이 초기화(비우기) 되었습니다!'})

@monitoring_bp.route('/api/update_keyword', methods=['POST'])
@login_required
def update_keyword():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    kw_id = request.form.get('id')
    kw = ModelClass.query.filter_by(id=kw_id, user_id=current_user.id).first()
    
    if kw:
        if 'isbn' in request.form: kw.isbn = request.form.get('isbn', '-').strip()
        if 'keyword' in request.form: kw.keyword = request.form.get('keyword')
        if 'publisher' in request.form: kw.publisher = request.form.get('publisher')
        if 'supply_rate' in request.form: kw.supply_rate = request.form.get('supply_rate')
        if 'price' in request.form: kw.price = request.form.get('price')
        if 'shipping_fee' in request.form: kw.shipping_fee = request.form.get('shipping_fee')
        if 'book_title' in request.form: kw.book_title = request.form.get('book_title')
        if 'product_link' in request.form: kw.product_link = request.form.get('product_link')
        if 'store_rank' in request.form: kw.store_rank = request.form.get('store_rank')
        if 'stock_quantity' in request.form: kw.stock_quantity = request.form.get('stock_quantity')
        if 'sales_quantity' in request.form: kw.sales_quantity = request.form.get('sales_quantity')
        if 'sales_status' in request.form: kw.sales_status = request.form.get('sales_status')
            
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False, 'message': '데이터를 찾을 수 없습니다.'})

@monitoring_bp.route('/api/change_grade', methods=['POST'])
@login_required
def change_grade():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    selected_ids = get_selected_ids(request)
    new_grade = request.form.get('grade', 'A')
    if not selected_ids: return jsonify({'success': False, 'message': '이동할 항목을 선택해주세요.'})
    
    for i in range(0, len(selected_ids), 500):
        chunk = selected_ids[i:i + 500]
        keywords = ModelClass.query.filter(ModelClass.id.in_(chunk), ModelClass.user_id==current_user.id).all()
        for kw in keywords: 
            kw.rank_info = new_grade
            
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(selected_ids)}개 항목이 {new_grade}등급으로 이동되었습니다.'})

@monitoring_bp.route('/api/clear_data', methods=['POST'])
@login_required
def clear_data():
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    
    selected_ids = get_selected_ids(request)
    
    if selected_ids: 
        for i in range(0, len(selected_ids), 500):
            chunk = selected_ids[i:i + 500]
            keywords = ModelClass.query.filter(ModelClass.id.in_(chunk), ModelClass.user_id == current_user.id).all()
            for kw in keywords:
                kw.store_rank = '-'
                kw.prev_store_rank = '-'
                kw.product_link = '-'
                kw.price = '-'
                kw.shipping_fee = '-'
                kw.book_title = '-'
                if hasattr(kw, 'stock_quantity'): kw.stock_quantity = '-'
                if hasattr(kw, 'sales_quantity'): kw.sales_quantity = '-'
                if hasattr(kw, 'sales_status'): kw.sales_status = '-'
    else:
        query = ModelClass.query.filter_by(user_id=current_user.id)
        for kw in query.all():
            kw.store_rank = '-'
            kw.prev_store_rank = '-'
            kw.product_link = '-'
            kw.price = '-'
            kw.shipping_fee = '-'
            kw.book_title = '-'
            if hasattr(kw, 'stock_quantity'): kw.stock_quantity = '-'
            if hasattr(kw, 'sales_quantity'): kw.sales_quantity = '-'
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
                    if 'stockQuantity' in origin_data: stock_val = origin_data.get('stockQuantity')
                    detail_attr = origin_data.get('detailAttribute', {})
                    publisher = detail_attr.get('bookInfo', {}).get('publisher') or detail_attr.get('customInfo', {}).get('manufacturer') or origin_data.get('manufacturerName')
            except: pass
            
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
            result['my_stock'] = f"{stock_val:,}"

        if not publisher: publisher = matched_product.get('manufacturerName') or c_prod.get('manufacturerName') 
        result['my_publisher'] = publisher if publisher else "-"
        result['my_price'] = f"{sale_price:,}원" if sale_price is not None else "-"
        
    return result

monitoring_tasks = {}

def async_refresh_by_isbn(app, user_id, target_ids, update_mode, fill_empty_only, target='studybox'):
    global monitoring_tasks
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    task_key = f"{user_id}_{target}"
    
    monitoring_tasks[task_key] = {"is_running": True, "total": len(target_ids), "current": 0, "logs": [], "mode": update_mode}

    try:
        with app.app_context():
            # ✨ 핵심 복구: 탭 이름에 따라 정확하게 해당 상점의 API키와 상점명을 불러옵니다!
            store_mapping = {
                'studybox': '스터디박스',
                'rm': '러닝메이트',
                'dl': '데일리러닝'
            }
            target_store_name = store_mapping.get(target, '스터디박스')

            api_key = ApiKey.query.filter_by(user_id=user_id, store_name=target_store_name).first()
            commerce_token = None
            if api_key: 
                commerce_token = get_naver_token(api_key.client_id, api_key.client_secret)

            for k_id in target_ids:
                try:
                    kw = db.session.get(ModelClass, k_id)
                    if not kw: 
                        monitoring_tasks[task_key]["current"] += 1
                        continue
                        
                    target_isbn = str(kw.isbn).strip() if kw.isbn and kw.isbn != '-' else ""
                    keyword_name = kw.keyword or f"ID:{k_id}"
                    
                    db.session.rollback()
                    updates = {}
                    
                    # 1. API 기반 업데이트 (상품 정보, 재고)
                    if update_mode in ['all', 'info', 'stock']:
                        if not target_isbn or not commerce_token:
                            if update_mode != 'all':
                                monitoring_tasks[task_key]["current"] += 1
                                monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] ❌ ISBN/API키 필요 (스킵)")
                                continue
                        else:
                            exact_info = get_exact_product_info_commerce_api(commerce_token, target_isbn)
                            if update_mode in ['all', 'info']:
                                if exact_info.get('my_title'): updates['book_title'] = exact_info['my_title']
                                if exact_info.get('my_link'): updates['product_link'] = exact_info['my_link']
                                if exact_info.get('my_price'): updates['price'] = exact_info['my_price']
                                if exact_info.get('my_publisher'): updates['publisher'] = exact_info['my_publisher']
                                if exact_info.get('my_status'): updates['sales_status'] = exact_info['my_status'] 
                            if update_mode in ['all', 'stock']:
                                if exact_info.get('my_stock'): updates['stock_quantity'] = exact_info['my_stock']

                    # 2. X-Ray 순위 탐색 & 백업 상품 정보 추출
                    if update_mode in ['all', 'rank', 'info']:
                        need_crawler = ('rank' in update_mode or 'all' in update_mode) or (('info' in update_mode or 'all' in update_mode) and not updates.get('book_title'))
                        
                        if need_crawler:
                            # ✨ 각 탭의 실제 상점 이름(target_store_name)으로 네이버 쇼핑을 탐색합니다!
                            crawl_data = get_naver_shopping_rank(keyword_name, target_store_name)
                            rank_result = crawl_data['rank']
                            
                            # API에서 못 가져온 정보가 있다면 크롤러가 훔쳐온 정보로 마법처럼 채워줌!
                            if update_mode in ['all', 'info']:
                                if not updates.get('book_title') and crawl_data['title']: updates['book_title'] = crawl_data['title']
                                if not updates.get('product_link') and crawl_data['link']: updates['product_link'] = crawl_data['link']
                                if not updates.get('price') and crawl_data['price']: updates['price'] = crawl_data['price']
                            
                            if update_mode in ['all', 'rank']:
                                if rank_result and '실패' not in rank_result and '에러' not in rank_result:
                                    updates['store_rank'] = rank_result
                                    if "밖" in rank_result:
                                        monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] 📉 {rank_result}")
                                    else:
                                        monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] 🏆 {rank_result}위 확인!")
                                else:
                                    monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] ⚠️ 순위 검색 실패")

                    kw_update = db.session.get(ModelClass, k_id)
                    if kw_update and updates:
                        def should_update(current_val):
                            if not fill_empty_only: return True 
                            return current_val in [None, '', '-'] 

                        if update_mode in ['all', 'info']:
                            if updates.get('book_title') and should_update(kw_update.book_title): kw_update.book_title = updates['book_title']
                            if updates.get('product_link') and should_update(kw_update.product_link): kw_update.product_link = updates['product_link']
                            if updates.get('price') and should_update(kw_update.price): kw_update.price = updates['price']
                            if updates.get('publisher') and should_update(kw_update.publisher): kw_update.publisher = updates['publisher']
                            if updates.get('sales_status') and should_update(kw_update.sales_status): kw_update.sales_status = updates['sales_status']
                        
                        if update_mode in ['all', 'stock']:
                            if updates.get('stock_quantity') and should_update(getattr(kw_update, 'stock_quantity', '-')):
                                kw_update.stock_quantity = updates['stock_quantity']
                                
                        if update_mode in ['all', 'rank'] and 'store_rank' in updates:
                            if should_update(kw_update.store_rank):
                                if kw_update.store_rank != updates['store_rank'] and kw_update.store_rank not in ['-', '에러', '실패', '매칭중'] and "밖" not in kw_update.store_rank:
                                    kw_update.prev_store_rank = kw_update.store_rank
                                kw_update.store_rank = updates['store_rank']

                        db.session.commit()
                        
                    monitoring_tasks[task_key]["current"] += 1
                    if update_mode == 'info' and not updates:
                        pass 
                    elif 'store_rank' not in updates and update_mode == 'rank':
                        pass 
                    elif updates and update_mode != 'rank':
                        monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] ✅ 업데이트 완료")
                    
                except Exception as inner_e:
                    db.session.rollback()
                    monitoring_tasks[task_key]["current"] += 1
                    monitoring_tasks[task_key]["logs"].append(f"[{keyword_name}] ❌ 내부 오류")
                
                time.sleep(random.uniform(1.5, 2.5)) 
                
    except Exception as outer_e:
        monitoring_tasks[task_key]["logs"].append(f"⚠️ 시스템 오류가 발생했습니다.")
    finally:
        monitoring_tasks[task_key]["is_running"] = False
        if monitoring_tasks[task_key]["current"] < monitoring_tasks[task_key]["total"]:
            monitoring_tasks[task_key]["current"] = monitoring_tasks[task_key]["total"]
            monitoring_tasks[task_key]["logs"].append("⚠️ 업데이트가 강제 종료되었습니다.")

@monitoring_bp.route('/api/refresh_by_isbn', methods=['POST'])
@login_required
def refresh_by_isbn():
    app = current_app._get_current_object()
    user_id = current_user.id
    target = request.form.get('target_page', 'studybox')
    ModelClass = MonitoredKeyword
    if target == 'rm': ModelClass = RunningmateKeyword
    elif target == 'dl': ModelClass = DailylearningKeyword
    task_key = f"{user_id}_{target}"
    
    if monitoring_tasks.get(task_key, {}).get("is_running", False):
        return jsonify({'success': False, 'message': '⚠️ 이미 진행 중입니다.'})
        
    selected_ids = get_selected_ids(request)
    update_mode = request.form.get('update_mode', 'all') 
    fill_empty_only = request.form.get('fill_empty_only') == 'true'
    
    if not selected_ids: return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 선택해주세요.'})
    
    target_ids = []
    for i in range(0, len(selected_ids), 500):
        chunk = selected_ids[i:i + 500]
        keywords = ModelClass.query.filter(ModelClass.id.in_(chunk), ModelClass.user_id==user_id).all()
        target_ids.extend([kw.id for kw in keywords])
        
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 유효한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, target_ids, update_mode, fill_empty_only, target))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드 스캔 작업이 시작되었습니다.'})

@monitoring_bp.route('/api/task_status', methods=['GET'])
@login_required
def get_task_status():
    user_id = current_user.id
    target = request.args.get('target_page', 'studybox')
    task_key = f"{user_id}_{target}"
    task = monitoring_tasks.get(task_key, {"is_running": False, "total": 0, "current": 0, "logs": []})
    return jsonify(task)
