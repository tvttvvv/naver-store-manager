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
                kw = db.session.get(MonitoredKeyword, k_id)
                if not kw: 
                    db.session.commit()
                    continue
                    
                keyword_text = kw.keyword or ""
                target_isbn = str(kw.isbn).strip().replace('-', '') if kw.isbn and kw.isbn != '-' else ""
                db.session.commit()

                if not keyword_text: continue

                new_rank = "1000위 밖"
                updates = {}
                matched_mall_pid = None

                # ✨ 1단계: 순위 탐색 (1위 ~ 1000위까지 샅샅이 뒤집니다!)
                if api_headers and search_client_id:
                    try:
                        found_rank = False
                        # 100개씩 10번 스캔 = 1000개 탐색 완료
                        for start_idx in [1, 101, 201, 301, 401, 501, 601, 701, 801, 901]:
                            api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                            api_res = requests.get(api_url, headers=api_headers, timeout=5)
                            if api_res.status_code == 200:
                                items = api_res.json().get('items', [])
                                if not items: break # 검색 결과가 더 없으면 중단
                                for idx, item in enumerate(items):
                                    if target_mall_name in item.get('mallName', ''):
                                        new_rank = str(start_idx + idx)
                                        matched_mall_pid = item.get('mallProductId')
                                        found_rank = True
                                        break
                            if found_rank: break
                            time.sleep(0.1) # 안전한 통신을 위해 잠깐 대기
                    except: pass

                    # 1000위 밖이라 못 찾았다면, 이름+상점명 조합으로 강제 색출합니다!
                    if not matched_mall_pid:
                        try:
                            targeted_query = f"{keyword_text} {target_mall_name}"
                            api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=50&start=1"
                            api_res = requests.get(api_url, headers=api_headers, timeout=5)
                            if api_res.status_code == 200:
                                for item in api_res.json().get('items', []):
                                    if target_mall_name in item.get('mallName', ''):
                                        matched_mall_pid = item.get('mallProductId')
                                        break
                        except: pass

                # ✨ 2단계: 알아낸 고유 상품 번호로 커머스 정보를 싹쓸이합니다.
                matched_data = None
                if commerce_token:
                    # 완벽한 루트: 앞서 찾은 상점 전용 고유번호로 바로 꽂기
                    if matched_mall_pid:
                        try:
                            cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{matched_mall_pid}"
                            cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                            if cp_res.status_code == 200:
                                cp_data = cp_res.json()
                                o_no = cp_data.get('originProductNo')
                                op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}", headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    matched_data = (cp_data, op_res.json())
                        except: pass

                    # 보험 루트: 그래도 못 찾았다면 커머스 API에 ISBN이나 이름으로 물어보기
                    if not matched_data:
                        candidate_products = []
                        if target_isbn:
                            try:
                                payload = {"page": 1, "size": 10, "searchKeywordType": "SELLER_MANAGEMENT_CODE", "sellerManagementCode": target_isbn}
                                c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                                if c_res.status_code == 200:
                                    candidate_products.extend(c_res.json().get('contents', []))
                            except: pass

                        if not candidate_products and keyword_text:
                            try:
                                payload = {"page": 1, "size": 20, "searchKeywordType": "NAME", "searchKeyword": keyword_text}
                                c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                                if c_res.status_code == 200:
                                    candidate_products.extend(c_res.json().get('contents', []))
                            except: pass

                        for p in candidate_products:
                            o_no = p.get('originProductNo')
                            if not o_no: continue
                            try:
                                op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}", headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    matched_data = (p, op_res.json())
                                    break
                            except: pass

                    # ✨ 3단계: 가져온 정보를 화면에 맞게 예쁘게 정리해서 저장
                    if matched_data:
                        fp, fop = matched_data
                        c_no = fp.get('channelProductNo')
                        if not c_no: c_no = matched_mall_pid
                        
                        updates['store_name'] = str(fop.get('name', fp.get('name', '-')))
                        updates['product_link'] = f"https://smartstore.naver.com/main/products/{c_no}" if c_no else "-"
                        
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
                        
                        updates['book_title'] = "" # 완료!
                    else:
                        updates['book_title'] = "⚠️ 상점에 해당 상품 없음"
                else:
                    updates['book_title'] = "⚠️ 커머스 토큰 에러 (API 설정 확인)"

                # DB 저장
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = new_rank
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()

            except Exception as e:
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 서버 시스템 에러"
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
        if "갱신중" not in str(kw.store_rank) and "매칭중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 데이터 수집중..."
        target_ids.append(kw.id)
            
    db.session.commit()
    
    if not target_ids:
        return jsonify({'success': False, 'message': '⚠️ 선택한 항목 중에 업데이트할 항목이 없습니다.'})
        
    thread = Thread(target=async_refresh_by_isbn, args=(app, user_id, search_id, search_pw, target_ids))
    thread.start()
    return jsonify({'success': True, 'message': f'✅ 선택하신 {len(target_ids)}개 항목의 정밀 데이터 수집을 시작합니다.'})
