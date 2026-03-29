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

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids, update_mode):
    with app.app_context():
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
            safe_target = target_mall_name.lower().replace(" ", "")
            print(f"[CCTV-DEBUG] 🚀 스나이퍼 API 엔진 가동! (대상: {len(target_ids)}개)", flush=True)
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
                print(f"\n[CCTV-DEBUG] ⚡ 타겟 록온: ID={k_id}, 키워드=[{keyword_text}], ISBN=[{target_isbn}]", flush=True)
                db.session.commit()

                updates = {}
                
                # 사전 검증: API 키가 없으면 실행 불가
                if not api_headers or not search_client_id:
                    print(f"[CCTV-DEBUG] ❌ 경고: 네이버 검색 API 키가 설정되지 않아 수집을 스킵합니다.", flush=True)
                    updates['store_rank'] = "API설정필요"
                    continue

                # ========================================================
                # 1. ⚡ 초고속 순위 추적 (Open API 400위 스캔 - 단 0.3초 소요)
                # ========================================================
                if update_mode in ['all', 'rank']:
                    updates['store_rank'] = '500위 밖'
                    found_rank = False
                    
                    # 1위부터 400위까지 100개씩 딱 4번만 찔러봅니다.
                    for start_idx in range(1, 402, 100):
                        if found_rank: break
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        try:
                            api_res = requests.get(api_url, headers=api_headers, timeout=3)
                            if api_res.status_code == 200:
                                items = api_res.json().get('items', [])
                                for idx, item in enumerate(items):
                                    if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                        updates['store_rank'] = str(start_idx + idx)
                                        updates['store_name'] = item.get('mallName')
                                        found_rank = True
                                        
                                        # 순위 찾은 김에 상품 정보도 같이 주워옵니다 (1타 2피)
                                        updates['book_title'] = clean_text(item.get('title', ''))
                                        p = item.get('lprice', '0')
                                        if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                        raw_link = item.get('link', '-')
                                        if raw_link != '-': updates['product_link'] = raw_link.replace('http://', 'https://')
                                        
                                        print(f"[CCTV-DEBUG] 🎯 순위 명중! {updates['store_rank']}위", flush=True)
                                        break
                        except Exception as e:
                            print(f"[CCTV-DEBUG] ⚠️ API 순위 추적 중 에러: {e}", flush=True)
                            break

                # ========================================================
                # 2. ⚡ 초고속 상품 정보(링크, 가격, 제목) 보완 (ISBN 다이렉트 검색)
                # ========================================================
                if update_mode == 'all':
                    # 순위 검색에서 정보를 다 못 구했을 경우에만 ISBN으로 다이렉트 타격
                    if 'book_title' not in updates or updates.get('product_link', '-') == '-':
                        search_target = target_isbn if target_isbn else keyword_text
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(search_target)}&display=10"
                        try:
                            api_res = requests.get(api_url, headers=api_headers, timeout=3)
                            if api_res.status_code == 200:
                                for item in api_res.json().get('items', []):
                                    if safe_target in item.get('mallName', '').lower().replace(" ", ""):
                                        if updates.get('book_title', '-') == '-':
                                            updates['book_title'] = clean_text(item.get('title', ''))
                                        if updates.get('price', '-') == '-':
                                            p = item.get('lprice', '0')
                                            if p.isdigit() and p != '0': updates['price'] = f"{int(p):,}원"
                                        if updates.get('product_link', '-') == '-':
                                            raw_link = item.get('link', '-')
                                            if raw_link != '-': updates['product_link'] = raw_link.replace('http://', 'https://')
                                        updates['store_name'] = target_mall_name
                                        break
                        except Exception: pass

                    # 출판사 정보만 도서 API로 쏙 빼오기
                    if target_isbn:
                        try:
                            book_url = f"https://openapi.naver.com/v1/search/book.json?d_isbn={urllib.parse.quote(target_isbn)}"
                            book_res = requests.get(book_url, headers=api_headers, timeout=3)
                            if book_res.status_code == 200 and book_res.json().get('items'):
                                updates['publisher'] = clean_text(book_res.json()['items'][0].get('publisher', '-'))
                        except Exception: pass
                
                # 오픈 API에서는 '구매수'를 제공하지 않으므로 깔끔하게 처리
                if update_mode in ['all', 'purchase']:
                    updates['purchase_count'] = '-'

                # ========================================================
                # DB 초고속 저장
                # ========================================================
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if 'store_rank' in updates: kw.store_rank = updates['store_rank']
                    if 'purchase_count' in updates: kw.purchase_count = updates['purchase_count']
                    
                    if update_mode == 'all':
                        if updates.get('book_title') and updates['book_title'] != '-': kw.book_title = updates['book_title']
                        if updates.get('publisher') and updates['publisher'] != '-': kw.publisher = updates['publisher']
                        if updates.get('price') and updates['price'] != '-': kw.price = updates['price']
                        if updates.get('product_link') and updates['product_link'] != '-': kw.product_link = updates['product_link']
                        kw.store_name = updates.get('store_name', target_mall_name)
                    
                    print(f"[CCTV-DEBUG] ✅ DB 반영: Rank={kw.store_rank}, Title={kw.book_title}", flush=True)
                    db.session.commit()

            except Exception as e:
                db.session.rollback()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    if update_mode in ['all', 'rank']: kw.store_rank = "에러"
                    db.session.commit()
            
            # API 제한(초당 10회)을 넘지 않도록 가벼운 0.2초 휴식! (풀스캔처럼 몇 분씩 안 걸립니다)
            time.sleep(0.2) 

        print(f"[CCTV-DEBUG] 🏁 스나이퍼 타겟팅 업데이트 완료!", flush=True)

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
            kw.store_rank = "⚡ 스캔중..."
        
        if update_mode in ['all', 'purchase'] and hasattr(kw, 'purchase_count'):
            kw.purchase_count = "-" # API에선 제공 안함
            
        target_ids.append(kw.id)
            
    db.session.commit()
    if not target_ids: return jsonify({'success': False, 'message': '⚠️ 선택한 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids, update_mode))
    thread.start()
    
    return jsonify({'success': True, 'message': f'⚡ 광속 수집을 시작합니다. 1~2초 뒤에 새로고침을 눌러주세요.'})
