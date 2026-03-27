import os
import time
import re
import traceback
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword, ApiKey
import requests
import urllib.parse

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

def get_real_title_via_proxy(isbn):
    isbn = isbn.replace('-', '').strip()
    if not isbn: return ""
    try:
        aladin_url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord={isbn}"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(aladin_url)}"
        res = requests.get(proxy_url, timeout=5)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    return ""

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [DEBUG START] PURE API UPDATE (User: {user_id}) ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
        except Exception as e:
            print(f"[DEBUG ERROR] Setup Failed: {e}", flush=True)

        for k_id in target_ids:
            try:
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: continue
                    
                keyword_text = str(kw.keyword or "")
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                print(f"\n[DEBUG] Processing: '{keyword_text}' | Target ISBN: '{target_isbn}'", flush=True)

                updates = {
                    'store_rank': '1000위 밖',
                    'price': '-',
                    'product_link': '-',
                    'store_name': '-',
                    'shipping_fee': '-', # API는 택배비를 제공하지 않으므로 기본값 처리
                    'book_title': '⚠️ 매칭 실패'
                }

                # ✨ [1] 네이버 도서 API로 정확한 책 정보(이름, 출판사, ISBN)만 쏙 빼오기
                real_book_title = ""
                if api_headers and search_client_id:
                    search_query = target_isbn if target_isbn else keyword_text
                    try:
                        print(f"[DEBUG] Requesting Book API with query: '{search_query}'", flush=True)
                        book_url = f"https://openapi.naver.com/v1/search/book.json?query={urllib.parse.quote(search_query)}"
                        book_res = requests.get(book_url, headers=api_headers, timeout=5)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            item = book_res.json()['items'][0]
                            
                            raw_title = item.get('title', '')
                            title_clean = re.sub(r'<[^>]*>', '', raw_title)
                            real_book_title = re.sub(r'\(.*?\)', '', title_clean).strip()
                            
                            if not target_isbn:
                                raw_isbn = item.get('isbn', '')
                                for cand in reversed(raw_isbn.split()):
                                    if cand.startswith('9') or cand.startswith('8'):
                                        updates['isbn'] = cand
                                        break
                            
                            if item.get('publisher'): 
                                updates['publisher'] = item.get('publisher')
                    except Exception as e: 
                        print(f"[DEBUG] Book API Error: {e}", flush=True)
                
                if not real_book_title and target_isbn:
                    real_book_title = get_real_title_via_proxy(target_isbn)

                # ✨ [2] 네이버 쇼핑 API로 1위부터 1000위까지 스캔하여 순위, 가격, 링크 찾기
                print(f"[DEBUG] Searching Shop API for rank and link...", flush=True)
                if api_headers and search_client_id:
                    try:
                        found_rank = False
                        for start_idx in range(1, 1001, 100): # 1, 101, 201... 901
                            if found_rank: break
                            api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                            api_res = requests.get(api_url, headers=api_headers, timeout=5)
                            
                            if api_res.status_code == 200:
                                items = api_res.json().get('items', [])
                                if not items: break # 더 이상 상품이 없으면 스캔 종료
                                
                                for idx, item in enumerate(items):
                                    if target_mall_name in item.get('mallName', ''):
                                        updates['store_rank'] = str(start_idx + idx)
                                        updates['store_name'] = item.get('mallName')
                                        updates['price'] = f"{int(item.get('lprice', 0)):,}원"
                                        updates['product_link'] = item.get('link')
                                        updates['book_title'] = real_book_title # 성공 시 찾은 진짜 책 이름 기록
                                        print(f"[DEBUG] ✅ SUCCESS! Found '{target_mall_name}' at rank {updates['store_rank']}", flush=True)
                                        found_rank = True
                                        break
                    except Exception as e: 
                        print(f"[DEBUG] Shop API Error: {e}", flush=True)

                # DB 저장 로직
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        if key == 'isbn' and kw.isbn and kw.isbn != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()

            except Exception as e:
                traceback.print_exc()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 시스템 에러"
                    db.session.commit()
            
            time.sleep(0.3)
        print("========== [DEBUG END] ==========\n", flush=True)

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
    return jsonify({'success': True, 'message': f'✅ 네이버 공식 검색 API를 이용해 데이터 매칭을 시작합니다.'})
