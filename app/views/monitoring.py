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

def simplify(s):
    # 특수문자 띄어쓰기 전부 제거하고 글자만 추출
    return re.sub(r'[^a-zA-Z0-9가-힣]', '', str(s))

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
        if res.status_code == 200: return res.json().get("access_token")
    except: pass
    return None

def async_refresh_ranks(app, user_id, search_client_id, search_client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        api_key = ApiKey.query.filter_by(user_id=user_id).first()
        commerce_token = None
        if api_key: commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret)

        for kw in keywords:
            # ✨ 1단계: 개별 행 진행률 표시 시작
            kw.store_rank = "🔍 탐색중..."
            kw.store_name = "⏳ 데이터 로딩..." # 화면의 '상점 책제목' 자리에 표시
            kw.book_title = "" # 자리 밀림 방지를 위해 완전히 비움
            db.session.commit()
            time.sleep(0.1)

            mall_product_id = None
            clean_title_shopping = None
            
            # ✨ 2단계: 네이버 쇼핑에서 순위 및 진짜 '상품 번호' 캐내기
            if search_client_id and search_client_secret:
                api_headers = {"X-Naver-Client-Id": search_client_id, "X-Naver-Client-Secret": search_client_secret}
                kw.store_rank = "500위 밖"
                try:
                    found = False
                    for start_idx in [1, 101, 201, 301, 401]:
                        api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                        api_res = requests.get(api_url, headers=api_headers, timeout=5)
                        if api_res.status_code == 200:
                            for idx, item in enumerate(api_res.json().get('items', [])):
                                if "스터디박스" in item.get('mallName', ''):
                                    kw.store_rank = str(start_idx + idx)
                                    mall_product_id = item.get('mallProductId') # 핵심! 진짜 상품 번호 확보
                                    raw_title = item.get('title', '')
                                    clean_title_shopping = re.sub(r'<[^>]*>', '', raw_title)
                                    kw.price = f"{int(item.get('lprice', 0)):,}원"
                                    kw.product_link = item.get('link', '')
                                    found = True
                                    break
                        if found: break
                        time.sleep(0.1)
                except:
                    kw.store_rank = "API 에러"
            else:
                kw.store_rank = "검색키 누락"
                
            db.session.commit()

            # ✨ 3단계: 획득한 상품 번호로 커머스 API에서 숨겨진 세부 정보(택배비, ISBN 등) 가져오기
            if commerce_token:
                try:
                    c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"}
                    matched_origin_no = None
                    matched_channel_name = None
                    matched_c_no = None
                    matched_price = None
                    
                    # [상황 A] 쇼핑 검색에서 100% 일치하는 상품을 찾은 경우 (정밀 타격)
                    if mall_product_id:
                        cp_url = f"https://api.commerce.naver.com/external/v1/products/channel-products/{mall_product_id}"
                        cp_res = requests.get(cp_url, headers=c_headers, timeout=5)
                        if cp_res.status_code == 200:
                            cp_data = cp_res.json()
                            matched_origin_no = cp_data.get('originProductNo')
                            matched_channel_name = cp_data.get('name', clean_title_shopping)
                            matched_c_no = mall_product_id
                            matched_price = cp_data.get('salePrice')
                    
                    # [상황 B] 500위 밖이라 쇼핑 검색 실패 -> 지능형 단어 매칭 발동!
                    else:
                        search_url = "https://api.commerce.naver.com/external/v1/products/search"
                        payload = {"page": 1, "size": 30}
                        c_res = requests.post(search_url, headers=c_headers, json=payload, timeout=5)
                        
                        if c_res.status_code == 200:
                            contents = c_res.json().get('contents', [])
                            kw_simple = simplify(kw.keyword)
                            first_word = simplify(kw.keyword.split()[0]) if kw.keyword.split() else ""
                            
                            for p in contents:
                                c_prods = p.get('channelProducts', [])
                                c_name = c_prods[0].get('name', '') if c_prods else p.get('name', '')
                                c_name_simple = simplify(c_name)
                                
                                # 키워드가 통째로 있거나, 최소한 첫 번째 단어(예: 파이썬)라도 일치하면 합격!
                                if (kw_simple in c_name_simple) or (first_word and first_word in c_name_simple):
                                    matched_origin_no = p.get('originProductNo')
                                    matched_channel_name = c_name
                                    matched_c_no = c_prods[0].get('channelProductNo') if c_prods else None
                                    matched_price = c_prods[0].get('salePrice') if c_prods else p.get('salePrice')
                                    break
                    
                    # 일치하는 상품을 찾았다면, 상세 정보(Origin) 조립 완료하기
                    if matched_origin_no:
                        op_url = f"https://api.commerce.naver.com/external/v2/products/origin-products/{matched_origin_no}"
                        op_res = requests.get(op_url, headers=c_headers, timeout=5)
                        if op_res.status_code == 200:
                            op_data = op_res.json()
                            
                            # [핵심 해결] 책 제목을 화면의 '상점 책제목' 자리에 딱 맞게 밀어 넣음
                            kw.store_name = matched_channel_name 
                            kw.book_title = "" 
                            
                            if matched_c_no:
                                kw.product_link = f"https://smartstore.naver.com/main/products/{matched_c_no}"
                                
                            if matched_price is not None:
                                kw.price = f"{matched_price:,}원"
                            elif kw.price == "-": 
                                s_price = op_data.get('salePrice')
                                if s_price is not None: kw.price = f"{s_price:,}원"
                                
                            base_fee = op_data.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                            if base_fee is not None:
                                kw.shipping_fee = "무료" if base_fee == 0 else f"{base_fee:,}원"
                                
                            book_info = op_data.get('detailAttribute', {}).get('bookInfo', {})
                            if book_info:
                                kw.isbn = book_info.get('isbn', '-')
                                kw.publisher = book_info.get('publisher', '-')
                        else:
                            kw.store_name = f"{matched_channel_name} (상세 조회 실패)"
                    else:
                        kw.store_name = "매칭 상품 없음 (스토어 확인)"
                        
                except Exception as e:
                    kw.store_name = "데이터 로드 에러"
            else:
                kw.store_name = "커머스 API 키 오류"
                
            db.session.commit()
            time.sleep(0.2)

@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    search_id = os.environ.get("NAVER_CLIENT_ID", "")
    search_pw = os.environ.get("NAVER_CLIENT_SECRET", "")
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # 누르는 즉시 화면 피드백을 주기 위해 전체 초기화
    keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
    for kw in keywords:
        kw.store_rank = "⏳ 대기중..."
        kw.store_name = "업데이트 예정..."
        kw.book_title = ""
        kw.product_link = "-"
        kw.price = "-"
        kw.shipping_fee = "-"
        kw.isbn = "-"
        kw.publisher = "-"
    db.session.commit()
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, search_id, search_pw))
    thread.start()
    return jsonify({'success': True, 'message': '✅ 백그라운드 업데이트가 시작되었습니다.\n5~10초 간격으로 새로고침하여 진행상황을 확인하세요!'})
