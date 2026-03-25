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
    
    if not selected_ids: return jsonify({'success': False, 'message': '이동할 항목을 선택해주세요.'})
        
    keywords = MonitoredKeyword.query.filter(MonitoredKeyword.id.in_(selected_ids), MonitoredKeyword.user_id==user_id).all()
    for kw in keywords: kw.rank_info = new_grade
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
    if selected_ids: query = query.filter(MonitoredKeyword.id.in_(selected_ids))
    keywords = query.all()
    for kw in keywords:
        kw.store_rank = '-'
        kw.prev_store_rank = '-'
        kw.product_link = '-'
        kw.price = '-'
        kw.shipping_fee = '-'
        kw.store_name = '-'
        kw.book_title = '-'
    db.session.commit()
    return jsonify({'success': True, 'message': f'✅ 선택한 {len(keywords)}개 항목이 초기화되었습니다.'})

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
            api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}
        except:
            pass

        for k_id in target_ids:
            try:
                # 1. 정보 가져오기 및 DB 연결 해제
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: 
                    db.session.commit()
                    continue
                    
                keyword_text = kw.keyword or ""
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                # ✨ 에러 요인 1: ISBN을 안 적고(또는 저장 안 하고) 눌렀을 때의 경고 처리
                if not target_isbn:
                    kw = db.session.get(MonitoredKeyword, k_id)
                    if kw:
                        kw.store_rank = "500위 밖"
                        kw.book_title = "⚠️ ISBN 미입력 (✔저장버튼 확인)"
                        db.session.commit()
                    continue

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

                # [2] 커머스 API 연동 확인
                if commerce_token:
                    candidate_products = []
                    
                    # 1순위: ISBN 판매자 관리코드로 정밀 검색 시도
                    try:
                        payload = {"page": 1, "size": 10, "searchKeywordType": "SELLER_MANAGEMENT_CODE", "sellerManagementCode": target_isbn}
                        c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                        if c_res.status_code == 200:
                            candidate_products.extend(c_res.json().get('contents', []))
                    except: pass

                    # 2순위: 검색 API가 못 찾으면 내 상점 최신 상품 250개를 통째로 긁어와서 무식하게 눈으로 검사!
                    if not candidate_products:
                        for page in range(1, 6): # 50개씩 5페이지 = 250개
                            try:
                                res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json={"page": page, "size": 50}, timeout=5)
                                if res.status_code == 200:
                                    contents = res.json().get('contents', [])
                                    if not contents: break
                                    
                                    # 키워드와 이름이 조금이라도 겹치면 후보에 넣음
                                    k_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                                    for p in contents:
                                        p_name = re.sub(r'[^a-zA-Z0-9가-힣]', '', str(p.get('name', '')))
                                        if k_clean and k_clean in p_name:
                                            candidate_products.append(p)
                                        # 이름이 안 겹치더라도 일단 다 가져와서 바코드 검사할 수 있도록 할 수도 있지만, 속도를 위해 이름 겹치는 것만 필터.
                            except: pass

                    # 진단 1
                    if not candidate_products:
                        updates['book_title'] = f"⚠️ 일치상품 없음 (키워드: {keyword_text})"
                    else:
                        best_match = None
                        fallback_match = None
                        
                        for p in candidate_products:
                            o_no = p.get('originProductNo')
                            if not o_no: continue
                            try:
                                op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}", headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    op_data = op_res.json()
                                    book_isbn = str(op_data.get('detailAttribute', {}).get('bookInfo', {}).get('isbn', '')).replace('-', '').strip()
                                    
                                    if target_isbn and book_isbn and (target_isbn in book_isbn or book_isbn in target_isbn):
                                        best_match = (p, op_data)
                                        break
                                    
                                    p_name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', str(op_data.get('name', p.get('name', ''))))
                                    k_name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                                    if k_name_clean and k_name_clean in p_name_clean:
                                        if not fallback_match: fallback_match = (p, op_data)
                            except: pass
                        
                        final_match = best_match or fallback_match
                        if final_match:
                            fp, fop = final_match
                            c_prods = fp.get('channelProducts', [{}])
                            matched_c_no = c_prods[0].get('channelProductNo') if c_prods else fp.get('channelProductNo')
                            
                            updates['store_name'] = str(fop.get('name', fp.get('name', '-')))
                            updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_c_no}" if matched_c_no else "-"
                            
                            sale_price = fop.get('salePrice')
                            if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                            
                            fee = fop.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                            if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                            
                            book_info = fop.get('detailAttribute', {}).get('bookInfo', {})
                            if book_info and book_info.get('publisher'): 
                                updates['publisher'] = str(book_info.get('publisher'))
                            elif 'publisher' not in updates:
                                pub_notice = fop.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                if pub_notice: updates['publisher'] = str(pub_notice)
                            
                            if best_match:
                                updates['book_title'] = "" 
                            else:
                                updates['book_title'] = "⚠️ 이름 강제 매칭 (스마트스토어 ISBN 누락)"
                        else:
                            updates['book_title'] = "⚠️ 상품은 찾았으나 ISBN 불일치"
                else:
                    updates['book_title'] = "⚠️ 커머스 토큰 에러 (API 설정 확인)"

                # 최종 저장
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = new_rank
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()

            # ✨ 강력한 에어백: 파이썬이 쓰러지기 직전에 원인을 화면에 남깁니다!
            except Exception as e:
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 파이썬 에러: {str(e)[:20]}"
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
        # 매칭중 상태 표기
        if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ ISBN 매칭중..."
        target_ids.append(kw.id)
            
    db.session.commit()
    
    if not target_ids:
        return jsonify({'success': False, 'message': '⚠️ 선택한 항목 중에 업데이트할 데이터가 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목 업데이트를 시작합니다. (10초 후 확인하세요)'})
