import os
import time
import re
import difflib
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
    grade = data.get('grade', '')
    keyword = data.get('keyword', '')
    if 'A' in grade and keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        if not existing:
            new_kw = MonitoredKeyword(
                user_id=user.id, keyword=keyword, search_volume=data.get('search_volume', 0),
                rank_info="최상단 노출", link=data.get('link', '#'), shipping_fee='-', 
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
            'id': k.id, 'keyword': k.keyword, 'search_volume': k.search_volume, 'rank': k.rank_info,
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
        if res.status_code == 200: 
            return res.json().get("access_token")
    except Exception: pass
    return None

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret, kw_ids=None):
    with app.app_context():
        # 1단계: 아이디 확보 후 DB 잠금 즉시 해제
        if kw_ids:
            target_ids = kw_ids
        else:
            kws = MonitoredKeyword.query.filter_by(user_id=user_id).all()
            target_ids = [k.id for k in kws]
            
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
        target_mall_name = api_key.store_name if api_key else "스터디박스"
        
        db.session.commit() # 잠금 해제

        if not target_ids: return

        c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
        api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret} if search_client_id else {}

        for k_id in target_ids:
            kw = db.session.get(MonitoredKeyword, k_id)
            if not kw: 
                db.session.commit()
                continue
                
            keyword_text = kw.keyword
            db.session.commit()

            new_rank = "500위 밖"
            matched_mall_pid = None
            kw_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
            
            # 여기서부터 모든 상태/에러를 기록합니다.
            updates = {}

            # [전략 1 & 2] 순위 검색
            if api_headers and search_client_id:
                try:
                    found_rank = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if target_mall_name in item.get('mallName', ''):
                                    new_rank = str(start_idx + idx)
                                    title_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', item.get('title', ''))
                                    if kw_clean in title_clean:
                                        matched_mall_pid = item.get('mallProductId')
                                    found_rank = True
                                    break
                        if found_rank: break
                        time.sleep(0.1)
                        
                    if not matched_mall_pid:
                        targeted_query = f"{keyword_text} {target_mall_name}"
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(targeted_query)}&display=20&start=1"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for item in api_res.json().get('items', []):
                                if target_mall_name in item.get('mallName', ''):
                                    title_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', item.get('title', ''))
                                    if kw_clean in title_clean:
                                        matched_mall_pid = item.get('mallProductId')
                                        break
                except Exception as e:
                    new_rank = "검색 API 에러"
            else:
                new_rank = "검색 API 키 누락"

            # [전략 3] 커머스 API 상세 정보 추출 및 에러 피드백
            if commerce_token:
                matched_origin_no = None
                matched_channel_name = None
                matched_sale_price = None
                matched_c_no = None

                # 1) 쇼핑 API에서 고유번호 획득 성공 시
                if matched_mall_pid:
                    cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{matched_mall_pid}"
                    try:
                        cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                        if cp_res.status_code == 200:
                            cp_data = cp_res.json()
                            matched_origin_no = cp_data.get('originProductNo')
                            matched_channel_name = cp_data.get('name')
                            matched_sale_price = cp_data.get('salePrice')
                            matched_c_no = matched_mall_pid
                    except: pass

                # 2) 커머스 API 내부에서 직접 250개 추출해서 100% 매칭
                if not matched_origin_no:
                    candidate_products = []
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    for page in range(1, 6): # 최신 등록 250개 상품 확보
                        payload = {"page": page, "size": 50} 
                        try:
                            c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                            if c_res.status_code == 200:
                                contents = c_res.json().get('contents', [])
                                candidate_products.extend(contents)
                                if len(contents) < 50: break
                            else:
                                updates['book_title'] = f"⚠️ 커머스 에러 ({c_res.status_code})"
                                break
                        except Exception as e:
                            updates['book_title'] = "⚠️ 커머스 통신 타임아웃"
                            break
                    
                    if candidate_products and kw_clean:
                        regex_pattern = '.*'.join(list(kw_clean))
                        for p in candidate_products:
                            c_prods = p.get('channelProducts', [])
                            name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                            name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', name)
                            
                            if name_clean and re.search(regex_pattern, name_clean):
                                matched_origin_no = p.get('originProductNo')
                                matched_channel_name = name
                                matched_sale_price = c_prods[0].get('salePrice') if c_prods else p.get('salePrice')
                                matched_c_no = c_prods[0].get('channelProductNo') if c_prods else None
                                break
                                
                        if not matched_origin_no and 'book_title' not in updates:
                            updates['book_title'] = "⚠️ 상점 내 일치상품 없음"

                # 3) 찾은 정보 DB 업데이트 (기존 엑셀 기록 보존)
                if matched_origin_no:
                    op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{matched_origin_no}"
                    try:
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            
                            updates['store_name'] = matched_channel_name
                            updates['book_title'] = "" # 에러 메시지 초기화 (성공)
                            
                            if matched_c_no: updates['product_link'] = f"https://smartstore.naver.com/main/products/{matched_c_no}"
                            if matched_sale_price is not None: updates['price'] = f"{matched_sale_price:,}원"
                                
                            fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                            if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"

                            book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                            if book_info:
                                if book_info.get('isbn'): updates['isbn'] = book_info.get('isbn')
                                if book_info.get('publisher'): updates['publisher'] = book_info.get('publisher')

                            if 'publisher' not in updates:
                                pub_notice = op_data.get('productInfoProvidedNotice', {}).get('book', {}).get('publisher')
                                if pub_notice: updates['publisher'] = pub_notice
                        else:
                            updates['book_title'] = "⚠️ 상세정보 로드 실패"
                    except Exception as e:
                        updates['book_title'] = "⚠️ 상세정보 통신 에러"
            else:
                updates['book_title'] = "⚠️ 커머스 토큰 발급 실패 (API설정 확인)"

            # 데이터 저장할 때만 0.1초 잠시 DB 오픈!
            kw = db.session.get(MonitoredKeyword, k_id)
            if kw:
                kw.store_rank = new_rank
                for key, val in updates.items():
                    setattr(kw, key, val)
                db.session.commit()

            time.sleep(0.3)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
    for kw in keywords:
        if "갱신중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 갱신중..."
    db.session.commit()
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw, None))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 전체 갱신이 시작되었습니다. (잠시 후 새로고침 시 에러 원인이 표시됩니다)'})

@monitoring_bp.route('/api/refresh_keyword', methods=['POST'])
@login_required
def refresh_keyword():
    kw_id = request.form.get('id')
    if not kw_id: return jsonify({'success': False})
    
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    kw = MonitoredKeyword.query.filter_by(id=kw_id, user_id=user_id).first()
    if kw:
        if "갱신중" not in str(kw.store_rank):
            kw.prev_store_rank = kw.store_rank
        kw.store_rank = "⏳ 갱신중..."
        db.session.commit()
        
        thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw, [kw.id]))
        thread.start()
        return jsonify({'success': True, 'message': f'✅ [{kw.keyword}] 개별 업데이트 명령이 전송되었습니다.'})
    return jsonify({'success': False})
