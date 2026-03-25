import os
import time
import re
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword, ApiKey
import requests
import urllib.parse
import bcrypt
import base64

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/')
@login_required
def index():
    return render_template('monitoring/index.html')

@monitoring_bp.route('/api/webhook', methods=['POST'])
def receive_webhook():
    data = request.get_json()
    if not data: return jsonify({'success': False, 'message': 'No data'})
    grade_str = data.get('grade', '')
    keyword = data.get('keyword', '')
    
    grade_char = 'A'
    if 'C' in grade_str: grade_char = 'C'
    elif 'B' in grade_str: grade_char = 'B'

    if ('A' in grade_str or 'B' in grade_str or 'C' in grade_str) and keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        if not existing:
            new_kw = MonitoredKeyword(
                user_id=user.id, keyword=keyword, search_volume=data.get('search_volume', 0),
                rank_info=grade_char, 
                link=data.get('link', '#'), shipping_fee='-', 
                store_rank=data.get('store_rank', '-'), prev_store_rank='-'
            )
            db.session.add(new_kw)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved'})
    return jsonify({'success': False})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id, 'keyword': k.keyword, 'search_volume': k.search_volume, 
            'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C'] else 'A'),
            'link': k.link, 'publisher': k.publisher, 'supply_rate': k.supply_rate, 'isbn': k.isbn,
            'price': k.price, 'shipping_fee': k.shipping_fee, 'store_name': k.store_name,
            'book_title': k.book_title, 'product_link': k.product_link, 'store_rank': k.store_rank,
            'prev_store_rank': k.prev_store_rank 
        } for k in keywords]
    })

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

def get_commerce_token(client_id, client_secret):
    try:
        timestamp = str(int(time.time() * 1000))
        pwd = f"{client_id}_{timestamp}"
        hashed_pw = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
        client_secret_sign = base64.urlsafe_b64encode(hashed_pw).decode('utf-8')
        url = "https://api.commerce.naver.com/external/v1/oauth2/token"
        data = {"client_id": client_id, "timestamp": timestamp, "client_secret_sign": client_secret_sign, "grant_type": "client_credentials", "type": "SELF"}
        res = requests.post(url, data=data, timeout=5)
        if res.status_code == 200: return res.json().get("access_token")
    except: pass
    return None

@monitoring_bp.route('/api/clear_data', methods=['POST'])
@login_required
def clear_data():
    user_id = current_user.id
    selected_ids = request.form.getlist('ids[]')
    
    query = MonitoredKeyword.query.filter_by(user_id=user_id)
    if selected_ids:
        query = query.filter(MonitoredKeyword.id.in_(selected_ids))
    keywords = query.all()

    if not keywords:
        return jsonify({'success': False, 'message': '초기화할 항목이 선택되지 않았습니다.'})

    for kw in keywords:
        kw.store_rank = '-'
        kw.prev_store_rank = '-'
        kw.product_link = '-'
        kw.price = '-'
        kw.shipping_fee = '-'
        kw.store_name = '-'
        kw.book_title = '-'
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목의 검색 정보가 초기화되었습니다.'})

# ✨ [완전히 새로운 방식] ISBN 역추적 -> 도서명 추출 -> 상점 정밀 검색 엔진!
def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
        target_mall_name = api_key.store_name if api_key else "스터디박스"
        
        c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
        api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}

        for k_id in target_ids:
            kw = db.session.get(MonitoredKeyword, k_id)
            if not kw: 
                db.session.commit()
                continue
                
            keyword_text = kw.keyword
            # ISBN을 숫자만 깔끔하게 추출합니다.
            target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
            db.session.commit()

            if not target_isbn:
                continue

            new_rank = "500위 밖"
            matched_mall_pid = None
            matched_origin_no = None
            updates = {}

            # 1. 키워드로 내 상점의 현재 '순위'만 확인 (순위는 검색어로만 알 수 있으므로)
            if api_headers and search_client_id:
                try:
                    found_rank = False
                    for start_idx in [1, 101, 201]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    new_rank = str(start_idx + idx)
                                    found_rank = True
                                    break
                        if found_rank: break
                except: pass

            # ✨ 2. [핵심 1] 네이버 도서 API를 찔러서 ISBN에 해당하는 '진짜 책 제목'을 알아냅니다.
            real_book_title = ""
            if api_headers and search_client_id:
                try:
                    # 네이버 공식 책 검색 API 사용
                    book_url = f"https://openapi.naver.com/v1/search/book.json?query={target_isbn}"
                    book_res = requests.get(book_url, headers=api_headers, timeout=5)
                    if book_res.status_code == 200 and book_res.json().get('items'):
                        raw_title = book_res.json()['items'][0].get('title', '')
                        # 제목에서 HTML 태그와 (양장본) 같은 괄호 내용을 깔끔하게 제거합니다.
                        clean_title = re.sub(r'<[^>]*>', '', raw_title)
                        clean_title = re.sub(r'\(.*?\)', '', clean_title).strip()
                        
                        # 내 상점에서 검색하기 좋게 핵심 단어 2개만 뽑아냅니다. (예: "위버맨쉬 니체" -> "위버맨쉬")
                        words = clean_title.split()
                        real_book_title = f"{words[0]} {words[1]}" if len(words) >= 2 else clean_title
                except: pass

            # ✨ 3. [핵심 2] 알아낸 진짜 책 제목으로 커머스 창고에서 '정밀 검색'을 돌립니다.
            if commerce_token:
                candidate_products = []
                search_url = "https://api.commerce.naver.com/external/v1/products/search"
                
                # API로 책 제목을 알아냈다면 그 제목으로 검색하고, 실패했다면 그냥 내 상점 최신 상품 150개를 가져옵니다.
                for page in range(1, 4):
                    payload = {"page": page, "size": 50}
                    if real_book_title:
                        payload["name"] = real_book_title
                        
                    try:
                        c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                        if c_res.status_code == 200:
                            candidate_products.extend(c_res.json().get('contents', []))
                    except: pass
                
                # 4. [핵심 3] 가져온 상품들의 속을 까서 '바코드(ISBN)'가 100% 일치하는지 최종 확인합니다.
                for p in candidate_products:
                    o_no = p.get('originProductNo')
                    if not o_no: continue
                    
                    op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                    try:
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            book_isbn = op_data.get('detailAttribute', {}).get('bookInfo', {}).get('isbn', '')
                            book_isbn_clean = book_isbn.replace('-', '').strip()
                            
                            # 타겟 ISBN과 책의 ISBN이 서로 포함관계인지(완벽 일치) 확인!
                            if target_isbn in book_isbn_clean or (book_isbn_clean and book_isbn_clean in target_isbn):
                                matched_origin_no = o_no
                                c_prods = p.get('channelProducts', [])
                                if c_prods: matched_mall_pid = c_prods[0].get('channelProductNo')
                                
                                updates['store_name'] = op_data.get('name', p.get('name'))
                                updates['book_title'] = "" # 에러 메시지 삭제
                                sale_price = op_data.get('salePrice')
                                if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                                fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                                
                                # 수동입력 출판사가 없을 경우만 채우기
                                book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                                if book_info and book_info.get('publisher'): 
                                    updates['publisher'] = book_info.get('publisher')
                                elif 'publisher' not in updates:
                                    pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                    if pub_notice: updates['publisher'] = pub_notice
                                
                                break # 완벽한 책을 찾았으니 검사 종료!
                    except: pass

            # 5. 최종 데이터 정리 및 저장
            if matched_mall_pid or matched_origin_no:
                updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_mall_pid}"
            else:
                updates['book_title'] = "⚠️ 상점에 해당 ISBN 없음"

            # DB에 안전하게 덮어쓰기
            kw = db.session.get(MonitoredKeyword, k_id)
            if kw:
                kw.store_rank = new_rank
                for key, val in updates.items():
                    if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                    setattr(kw, key, val)
                db.session.commit()

            time.sleep(0.3)

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
    if not selected_ids:
        return jsonify({'success': False, 'message': '⚠️ 업데이트할 항목을 먼저 체크박스로 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    target_ids = []
    
    for kw in keywords:
        if kw.isbn and kw.isbn != '-':
            if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
                kw.prev_store_rank = kw.store_rank
            kw.store_rank = "⏳ ISBN 매칭중..."
            target_ids.append(kw.id)
            
    db.session.commit()
    
    if not target_ids:
        return jsonify({'success': False, 'message': '⚠️ 선택한 항목 중에 ISBN이 입력된 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목의 강력한 ISBN 역추적 업데이트를 시작합니다.'})
