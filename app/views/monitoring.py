import os
import time
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
        else: return jsonify({'success': True, 'message': 'Already exists'})
    return jsonify({'success': False, 'message': 'Not A grade'})

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
        data = {
            "client_id": client_id,
            "timestamp": timestamp,
            "client_secret_sign": client_secret_sign,
            "grant_type": "client_credentials",
            "type": "SELF"
        }
        res = requests.post(url, data=data, timeout=5)
        if res.status_code == 200:
            return res.json().get("access_token")
    except Exception as e:
        print(f"🚨 [디버그] 커머스 토큰 발급 에러: {e}")
    return None

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = None
        if api_key:
            commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            rank = "500위 밖"
            
            # 1. 쇼핑 순위 탐색
            try:
                if search_client_id and search_client_secret:
                    api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                    found = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    rank = str(start_idx + idx)
                                    found = True
                                    break
                        else:
                            if start_idx == 1: 
                                rank = "API에러"
                            break
                        if found: break
                        time.sleep(0.1)
            except Exception as e:
                rank = "탐색 실패"
            kw.store_rank = rank

            # ✨ 2. 커머스 API 상세 추적 모드
            if commerce_token:
                print(f"\n=========================================")
                print(f"🔍 [{kw.keyword}] 커머스 내 상품 검색 시작...")
                try:
                    search_url = "https://api.commerce.naver.com/external/v1/products/search"
                    c_headers = {
                        "Authorization": f"Bearer {commerce_token}",
                        "Content-Type": "application/json"
                    }
                    payload = {"page": 1, "size": 50, "orderType": "NO", "name": kw.keyword}
                    c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                    
                    if c_res.status_code == 200:
                        content = c_res.json()
                        products = content.get('contents', [])
                        print(f"📦 검색된 상품 총 개수: {len(products)}개")
                        
                        target_kw = kw.keyword.replace(" ", "").lower()
                        matched_product = None
                        
                        for p in products:
                            prod_name = p.get('name', '')
                            clean_prod_name = prod_name.replace(" ", "").lower()
                            print(f"   👉 발견된 스토어 상품명: '{prod_name}'")
                            
                            if target_kw in clean_prod_name:
                                matched_product = p
                                print(f"   ✅ [매칭 성공!] 표에 반영합니다.")
                                break
                        
                        if not matched_product:
                            print(f"   ❌ [매칭 실패] '{kw.keyword}' 글자가 포함된 상품이 스토어에 없습니다.")
                            
                        if matched_product:
                            c_no = matched_product.get('channelProducts', [{}])[0].get('channelProductNo')
                            o_no = matched_product.get('originProductNo')
                            
                            if c_no: kw.product_link = f"https://smartstore.naver.com/main/products/{c_no}"
                            sale_price = matched_product.get('salePrice')
                            if sale_price is not None: kw.price = f"{sale_price:,}원"
                            
                            kw.store_name = api_key.store_name if api_key else "스터디박스"
                            kw.book_title = matched_product.get('name', kw.keyword)

                            if o_no:
                                detail_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{o_no}"
                                detail_res = requests.get(detail_url, headers=c_headers, timeout=5)
                                if detail_res.status_code == 200:
                                    origin_data = detail_res.json()
                                    delivery_fee = origin_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                                    if delivery_fee is not None:
                                        kw.shipping_fee = "무료" if delivery_fee == 0 else f"{delivery_fee:,}원"
                                        
                                    book_info = origin_data.get('detailAttribute', {}).get('bookInfo', {})
                                    if book_info:
                                        if book_info.get('isbn'): kw.isbn = book_info.get('isbn')
                                        if book_info.get('publisher'): kw.publisher = book_info.get('publisher')
                                    print(f"   🎉 세부 정보(가격, ISBN 등) 업데이트 완료!")
                    else:
                        print(f"🚨 [{kw.keyword}] 검색 실패 (에러코드): {c_res.text}")
                except Exception as e:
                    print(f"🚨 [{kw.keyword}] 통신 중 파이썬 에러: {e}")
                print(f"=========================================\n")

            time.sleep(0.5)
            db.session.commit() 

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_client_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    
    app = current_app._get_current_object()
    user_id = current_user.id
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_client_id, search_client_secret))
    thread.start()
            
    return jsonify({'success': True, 'message': '✅ 백그라운드 탐색이 시작되었습니다!\n(화면에 실시간 반영됩니다.)'})
