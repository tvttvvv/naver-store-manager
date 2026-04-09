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
import urllib.request
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

# ✨ [차단 완벽 우회] 다중 통신망 + 4중 스텔스 탐색 엔진!
def get_naver_shopping_rank(keyword, store_name):
    default_res = {'rank': '-', 'title': '', 'link': '', 'price': ''}
    if not keyword or not store_name or store_name == '-': return default_res
    
    target_store = store_name.replace(" ", "").lower()
    
    user_agents = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0"
    ]
    
    # 통신망 이중화: urllib가 막히면 requests로 뚫는 마법의 함수
    def fetch_html(url, is_mobile=False):
        headers = {
            "User-Agent": "Mozilla/5.0 (Linux; Android 13; SM-G981B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/116.0.0.0 Mobile Safari/537.36" if is_mobile else random.choice(user_agents),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
            "Accept-Language": "ko-KR,ko;q=0.9,en-US;q=0.8",
            "Referer": "https://m.naver.com/" if is_mobile else "https://shopping.naver.com/"
        }
        try:
            req = urllib.request.Request(url, headers=headers)
            res = urllib.request.urlopen(req, timeout=10)
            html_data = res.read().decode('utf-8', 'ignore')
            if "captcha" in res.url or "자동입력 방지" in html_data:
                return None
            return html_data
        except:
            try:
                res = requests.get(url, headers=headers, timeout=10)
                if res.status_code == 200 and "captcha" not in res.url and "자동입력 방지" not in res.text:
                    return res.text
            except: pass
        return None

    # 1단계: 가장 차단율이 낮은 "모바일 통합검색" (쇼핑탭) 타격 (1~200위 탐색)
    try:
        for page in range(1, 6):
            start_num = (page - 1) * 40 + 1
            url = f"https://m.search.naver.com/search.naver?where=m_shop&query={urllib.parse.quote(keyword)}&start={start_num}"
            html_data = fetch_html(url, True)
            
            if html_data:
                soup = BeautifulSoup(html_data, 'html.parser')
                items = soup.select('.list_item, [class*="product_item__"], .product_list_item')
                
                found_in_page = False
                for idx, item in enumerate(items, 0):
                    found_in_page = True
                    mall_tag = item.select_one('.mall_name, [class*="mall_name__"], .mall_title')
                    if mall_tag:
                        m_name = mall_tag.get_text(strip=True).replace(" ", "").lower()
                        if target_store in m_name:
                            title_tag = item.select_one('.tit, [class*="title__"], .product_title')
                            title = title_tag.get_text(strip=True) if title_tag else ""
                            price_tag = item.select_one('.price, [class*="price__"]')
                            price = price_tag.get_text(strip=True) if price_tag else ""
                            link_tag = item.select_one('a')
                            link = link_tag['href'] if link_tag and 'href' in link_tag.attrs else ""
                            return {'rank': str(start_num + idx), 'title': title, 'price': price, 'link': link}
                
                if not found_in_page:
                    malls = re.findall(r'class="[^"]*mall_name[^"]*"[^>]*>([^<]+)<', html_data)
                    if malls:
                        for idx, m in enumerate(malls, 0):
                            if target_store in m.replace(" ", "").lower():
                                return {'rank': str(start_num + idx), 'title': '', 'link': '', 'price': ''}
                
                if "검색결과가 없습니다" in html_data:
                    break
                    
            time.sleep(random.uniform(0.4, 0.9))
    except: pass

    # 2단계: PC 네이버 쇼핑 카탈로그 X-Ray 탐색 (1~400위)
    try:
        for page in range(1, 6):
            url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(keyword)}&pagingIndex={page}&pagingSize=80"
            html_data = fetch_html(url, False)
            
            if html_data:
                soup = BeautifulSoup(html_data, 'html.parser')
                script = soup.find('script', id='__NEXT_DATA__')
                
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
                    
                ranks_data = re.findall(r'"mallName"\s*:\s*"([^"]+)".*?"rank"\s*:\s*(\d+)', html_data)
                if ranks_data:
                    for mall, rnk in ranks_data:
                        if target_store in mall.replace(" ", "").lower():
                            return {'rank': str(rnk), 'title': '', 'link': '', 'price': ''}
                else:
                    malls = re.findall(r'"mallName"\s*:\s*"([^"]+)"', html_data)
                    if malls:
                        for idx, m in enumerate(malls, 1):
                            if target_store in m.replace(" ", "").lower():
                                return {'rank': str((page - 1) * 80 + idx), 'title': '', 'link': '', 'price': ''}
            
            time.sleep(random.uniform(0.4, 0.9))
    except: pass
    
    # 3단계: 모바일 네이버 쇼핑 우회 탐색 (1~200위)
    try:
        for page in range(1, 6):
            url = f"https://msearch.shopping.naver.com/search/all?query={urllib.parse.quote(keyword)}&pagingIndex={page}&pagingSize=40"
            html_data = fetch_html(url, True)
            
            if html_data:
                soup = BeautifulSoup(html_data, 'html.parser')
                script = soup.find('script', id='__NEXT_DATA__')
                
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
                
                malls = re.findall(r'"mallName"\s*:\s*"([^"]+)"', html_data)
                if malls:
                    for idx, m in enumerate(malls, 1):
                        if target_store in m.replace(" ", "").lower():
                            return {'rank': str((page - 1) * 40 + idx), 'title': '', 'link': '', 'price': ''}

            time.sleep(random.uniform(0.4, 0.9))
    except: pass
    
    return {'rank': "500위 밖", 'title': '', 'link': '', 'price': ''}

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
        try: db.session.execute(text(f"ALTER TABLE {table_name} ADD COLUMN sales_status
