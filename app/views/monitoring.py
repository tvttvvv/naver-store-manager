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
            'id': k.id, 'keyword': k.keyword or '-', 'search_volume': k.search_volume or 0, 
            'grade': 'A' if k.rank_info == '최상단 노출' else (k.rank_info if k.rank_info in ['A', 'B', 'C'] else 'A'),
            'link': k.link or '#', 'publisher': k.publisher or '-', 'supply_rate': k.supply_rate or '-', 'isbn': k.isbn or '-',
            'price': k.price or '-', 'shipping_fee': k.shipping_fee or '-', 'store_name': k.store_name or '-',
            'book_title': k.book_title or '-', 'product_link': k.product_link or '-', 'store_rank': k.store_rank or '-',
            'prev_store_rank': k.prev_store_rank or '-' 
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

@monitoring_bp.route('/api/change_grade', methods=['POST'])
@login_required
def change_grade():
    user_id = current_user.id
    selected_ids = request.form.getlist('ids[]')
    new_grade = request.form.get('grade', 'A')
    
    if not selected_ids:
        return jsonify({'success': False, 'message': '이동할 항목을 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    for kw in keywords:
        kw.rank_info = new_grade
    db.session.commit()
    
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목이 {new_grade}등급으로 이동되었습니다.'})

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

# ✨ [회원님 아이디어 적용] IP 차단 우회 프록시를 통한 무적의 책 이름 탈취 엔진!
def get_real_title_via_proxy(isbn):
    isbn = isbn.replace('-', '').strip()
    if not isbn: return ""
    
    # 1. 알라딘 우회 검색
    try:
        aladin_url = f"https://www.aladin.co.kr/search/wsearchresult.aspx?SearchWord={isbn}"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(aladin_url)}"
        res = requests.get(proxy_url, timeout=10)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="bo3".*?<strong>(.*?)</strong>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass
    
    # 2. 예스24 우회 검색
    try:
        yes24_url = f"https://www.yes24.com/Product/Search?domain=ALL&query={isbn}"
        proxy_url = f"https://api.allorigins.win/get?url={urllib.parse.quote(yes24_url)}"
        res = requests.get(proxy_url, timeout=10)
        if res.status_code == 200:
            html = res.json().get('contents', '')
            match = re.search(r'class="gd_name">(.*?)</a>', html)
            if match:
                title = re.sub(r'<[^>]*>', '', match.group(1))
                return re.sub(r'\(.*?\)', '', title).strip()
    except: pass

    return ""

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
            target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
            db.session.commit()

            if not target_isbn: continue

            new_rank = "500위 밖"
            updates = {}

            # [1] 순위 확인
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

            # ✨ [2] 프록시를 이용해 진짜 책 제목을 빼옵니다.
            real_book_title = get_real_title_via_proxy(target_isbn)

            if commerce_token:
                candidate_products = []
                candidate_origin_nos = set()
                
                # 검색어 조합 (알아낸 진짜 이름 or 수동 입력한 키워드)
                search_terms = []
                if real_book_title:
                    words = real_book_title.split()
                    search_terms.append(f"{words[0]} {words[1]}" if len(words) >= 2 else real_book_title)
                    search_terms.append(words[0])
                else:
                    search_terms.append(keyword_text)
                    kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                    if len(kw_clean) >= 2: search_terms.append(kw_clean[:2])

                # ✨ [3] 치명적 버그 수정! (이름으로 상점을 직접 정밀 타격합니다)
                for term in search_terms:
                    if len(candidate_products) >= 50: break
                    for page in range(1, 3):
                        payload = {
                            "page": page,
                            "size": 50,
                            "searchKeywordType": "NAME", # 이 부분이 빠져있어서 검색이 안 됐었습니다!
                            "searchKeyword": term
                        }
                        try:
                            c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                            if c_res.status_code == 200:
                                contents = c_res.json().get('contents', [])
                                if not contents: break
                                for p in contents:
                                    o_no = p.get('originProductNo')
                                    if o_no and o_no not in candidate_origin_nos:
                                        candidate_origin_nos.add(o_no)
                                        candidate_products.append(p)
                        except: pass

                best_match = None
                fallback_match = None

                # [4] 찾아온 후보군들의 바코드를 까서 완벽히 매칭합니다.
                for p in candidate_products:
                    o_no = p.get('originProductNo')
                    op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                    try:
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            book_isbn = op_data.get('detailAttribute', {}).get('bookInfo', {}).get('isbn', '')
                            book_isbn_clean = book_isbn.replace('-', '').strip() if book_isbn else ""
                            
                            # 1순위: ISBN이 100% 일치할 때
                            if target_isbn and book_isbn_clean and (target_isbn in book_isbn_clean or book_isbn_clean in target_isbn):
                                best_match = (p, op_data)
                                break
                            
                            # 2순위: ISBN을 안 적어두셨어도, 이름이 같으면 강제로 매칭!
                            p_name = op_data.get('name', p.get('name', ''))
                            p_name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', p_name)
                            check_term = re.sub(r'[^a-zA-Z0-9가-힣]', '', real_book_title if real_book_title else keyword_text)
                            
                            if check_term and check_term in p_name_clean:
                                if not fallback_match: fallback_match = (p, op_data)
                    except: pass

                final_p, final_op = best_match if best_match else (fallback_match if fallback_match else (None, None))

                if final_p and final_op:
                    c_prods = final_p.get('channelProducts', [{}])
                    matched_c_no = c_prods[0].get('channelProductNo') if c_prods else final_p.get('channelProductNo')
                    
                    updates['store_name'] = final_op.get('name', final_p.get('name', '-'))
                    
                    if best_match:
                        updates['book_title'] = "" 
                    else:
                        updates['book_title'] = "⚠️ 스마트스토어 ISBN 누락 (이름 매칭)"
                        
                    if matched_c_no:
                        updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_c_no}"
                    
                    sale_price = final_op.get('salePrice')
                    if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                    
                    fee = final_op.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                    if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                    
                    book_info = final_op.get('detailAttribute', {}).get('bookInfo', {})
                    if book_info and book_info.get('publisher'): 
                        updates['publisher'] = book_info.get('publisher')
                    elif 'publisher' not in updates:
                        pub_notice = final_op.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                        if pub_notice: updates['publisher'] = pub_notice
                else:
                    if not real_book_title:
                        updates['book_title'] = "⚠️ ISBN으로 책 이름 찾기 실패 (외부망 차단)"
                    else:
                        updates['book_title'] = f"⚠️ 상점에 상품 없음 ({real_book_title})"

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
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목에 대해 외부망 우회 매칭 엔진을 가동합니다.'})
