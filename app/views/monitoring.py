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
import bcrypt
import base64
import json

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

# ✨ [신규 기능] 회원님이 스크린샷으로 보여주신 '네이버 도서 탭' 전용 순위 탐색기!
def get_naver_book_shopping_rank(keyword, target_mall):
    url = f"https://search.shopping.naver.com/book/search?query={urllib.parse.quote(keyword)}"
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
    try:
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            html = res.text
            
            # 방법 1: 도서 탭에 숨겨진 내부 데이터를 꺼내서 정확하게 순위 세기
            match = re.search(r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>', html, re.DOTALL)
            if match:
                try:
                    data = json.loads(match.group(1))
                    book_list = data.get('props', {}).get('pageProps', {}).get('initialState', {}).get('book', {}).get('list', [])
                    if book_list:
                        rank = 1
                        for item in book_list:
                            prod = item.get('item', item)
                            mall = prod.get('mallName', '')
                            if target_mall in mall:
                                return str(rank)
                            rank += 1
                except Exception as e:
                    print(f"[DEBUG] JSON Parse Error: {e}", flush=True)

            # 방법 2 (강력한 보험): HTML 글자 그대로에서 판매처 이름(mall_name) 긁어오기
            mall_tags = re.findall(r'class="[^"]*mall_name[^"]*">([^<]+)<', html)
            if mall_tags:
                for idx, mall in enumerate(mall_tags):
                    if target_mall in mall:
                        return str(idx + 1)
                        
            # 방법 3 (최후의 보루): 소스코드에서 쌍따옴표 묶인 상점명 순서대로 스캔
            names = re.findall(r'"mallName":"([^"]+)"', html)
            if names:
                valid_names = [n for n in names if '네이버' not in n] # 네이버페이 같은 쓰레기값 필터링
                for idx, mall in enumerate(valid_names):
                    if target_mall in mall:
                        return str(idx + 1)
    except Exception as e:
        print(f"[DEBUG] Book Shopping Scrape Error: {e}", flush=True)
    return None

def async_refresh_by_isbn(app, user_id, search_client_id, search_client_secret, target_ids):
    with app.app_context():
        print(f"\n========== [DEBUG START] ISBN UPDATE (User: {user_id}) ==========", flush=True)
        try:
            api_key = ApiKey.query.filter_by(user_id=user_id).first()
            commerce_token = get_commerce_token(api_key.client_id, api_key.client_secret) if api_key else None
            target_mall_name = api_key.store_name if api_key else "스터디박스"
            c_headers = {"Authorization": f"Bearer {commerce_token}", "Content-Type": "application/json"} if commerce_token else {}
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

                print(f"\n[DEBUG] Processing ID: {k_id} | Keyword: '{keyword_text}' | Target ISBN: '{target_isbn}'", flush=True)

                if not target_isbn:
                    kw = db.session.get(MonitoredKeyword, k_id)
                    if kw:
                        kw.store_rank = "500위 밖"
                        kw.book_title = "⚠️ ISBN 미입력"
                        db.session.commit()
                    continue

                updates = {}

                # [1] 네이버 도서 검색 API로 진짜 제목 찾기 (맞춤법 교정)
                real_book_title = ""
                if api_headers and search_client_id:
                    try:
                        book_url = f"https://openapi.naver.com/v1/search/book.json?query={target_isbn}"
                        book_res = requests.get(book_url, headers=api_headers, timeout=5)
                        if book_res.status_code == 200 and book_res.json().get('items'):
                            raw_title = book_res.json()['items'][0].get('title', '')
                            title_clean = re.sub(r'<[^>]*>', '', raw_title)
                            real_book_title = re.sub(r'\(.*?\)', '', title_clean).strip()
                    except Exception as e: pass

                if not real_book_title:
                    real_book_title = get_real_title_via_proxy(target_isbn)

                # ✨ [2] 회원님이 요청하신 '도서 탭 검색결과' 화면 기반의 순위 스캔!
                print(f"[DEBUG] Searching rank in Naver Book Tab...", flush=True)
                new_rank = "500위 밖"
                book_tab_rank = get_naver_book_shopping_rank(keyword_text, target_mall_name)
                
                if book_tab_rank:
                    new_rank = book_tab_rank
                    print(f"[DEBUG] ✅ Found Rank in Book Tab: {new_rank}", flush=True)
                else:
                    # 도서 탭에서 못 찾았다면, 기존의 일반 쇼핑 API로 1번만 더 백업 스캔
                    print(f"[DEBUG] Not found in Book Tab, falling back to Open API", flush=True)
                    if api_headers and search_client_id:
                        try:
                            found_rank = False
                            for start_idx in [1, 101]:
                                api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(keyword_text)}&display=100&start={start_idx}"
                                api_res = requests.get(api_url, headers=api_headers, timeout=5)
                                if api_res.status_code == 200:
                                    for idx, item in enumerate(api_res.json().get('items', [])):
                                        if target_mall_name in item.get('mallName', ''):
                                            new_rank = str(start_idx + idx)
                                            found_rank = True
                                            break
                                if found_rank: break
                        except Exception as e: pass

                # ✨ [3] 커머스 API 내부 스캔 (가격, 링크 등 상세 정보 가져오기)
                matched_data = None
                matched_mall_pid = None
                
                if commerce_token:
                    # ISBN 코드 기반 정밀 탐색
                    candidate_products = []
                    try:
                        payload = {"page": 1, "size": 20, "searchKeywordType": "SELLER_MANAGEMENT_CODE", "sellerManagementCode": target_isbn}
                        c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                        if c_res.status_code == 200:
                            contents = c_res.json().get('contents', [])
                            if contents:
                                fp = contents[0]
                                o_no = fp.get('originProductNo')
                                op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/{o_no}", headers=c_headers, timeout=5)
                                if op_res.status_code == 200:
                                    full_data = op_res.json()
                                    matched_data = (full_data.get('originProduct', full_data), full_data.get('originProduct', full_data))
                    except Exception as e: pass

                    # 실패시 이름 기반 탐색
                    if not matched_data:
                        search_terms = []
                        if keyword_text: search_terms.append(keyword_text)
                        if real_book_title:
                            words = real_book_title.split()
                            search_terms.append(f"{words[0]} {words[1]}" if len(words) >= 2 else real_book_title)
                        
                        for term in search_terms:
                            if matched_data: break
                            try:
                                payload = {"page": 1, "size": 20, "searchKeywordType": "NAME", "searchKeyword": term}
                                c_res = requests.post("https://api.commerce.naver.com/external/v1/products/search", headers=c_headers, json=payload, timeout=5)
                                if c_res.status_code == 200:
                                    contents = c_res.json().get('contents', [])
                                    for p in contents:
                                        o_no = p.get('originProductNo')
                                        try:
                                            op_res = requests.get(f"https://api.commerce.naver.com/external/v2/products/{p.get('channelProducts', [{}])[0].get('channelProductNo') or o_no}", headers=c_headers, timeout=5)
                                            if op_res.status_code == 200:
                                                full_data = op_res.json()
                                                origin_data = full_data.get('originProduct', full_data)
                                                
                                                p_name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', str(origin_data.get('name', '')))
                                                k_name_clean = re.sub(r'[^a-zA-Z0-9가-힣]', '', keyword_text)
                                                if k_name_clean and k_name_clean in p_name_clean:
                                                    matched_data = (p, origin_data)
                                                    break
                                        except Exception as e: pass
                            except Exception as e: pass

                    # 가져온 데이터 최종 포장
                    if matched_data:
                        fp, fop = matched_data
                        c_no = fp.get('channelProductNo')
                        if not c_no and matched_mall_pid: c_no = matched_mall_pid
                        
                        updates['store_name'] = str(fop.get('name') or fp.get('name', '-'))
                        updates['product_link'] = f"https://smartstore.naver.com/main/products/{c_no}" if c_no else "-"
                        
                        sale_price = fop.get('salePrice')
                        if sale_price is not None: updates['price'] = f"{sale_price:,}원"
                        
                        fee = fop.get('deliveryInfo', {}).get('deliveryFee', {}).get('baseFee')
                        if fee is not None: updates['shipping_fee'] = "무료" if fee == 0 else f"{fee:,}원"
                        
                        book_info = fop.get('detailAttribute', {}).get('bookInfo', {})
                        if book_info and book_info.get('publisher'): 
                            updates['publisher'] = str(book_info.get('publisher'))
                        
                        updates['book_title'] = "" 
                    else:
                        updates['book_title'] = "⚠️ 상점에 상품 발견 실패"
                else:
                    updates['book_title'] = "⚠️ 커머스 토큰 에러"

                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = new_rank
                    for key, val in updates.items():
                        if key == 'publisher' and kw.publisher and kw.publisher != '-': continue
                        setattr(kw, key, val)
                    db.session.commit()

            except Exception as e:
                traceback.print_exc()
                kw = db.session.get(MonitoredKeyword, k_id)
                if kw:
                    kw.store_rank = "에러"
                    kw.book_title = f"⚠️ 서버 시스템 에러"
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
    return jsonify({'success': True, 'message': f'✅ ISBN 및 상세 정보 매칭을 시작합니다.'})
