import os
import time
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword
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

    grade = data.get('grade', '')
    keyword = data.get('keyword', '')
    
    if 'A' in grade and keyword:
        user = User.query.first()
        if not user: return jsonify({'success': False, 'message': 'No user found'})
            
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        
        if not existing:
            new_kw = MonitoredKeyword(
                user_id=user.id,
                keyword=keyword,
                search_volume=data.get('search_volume', 0),
                rank_info="최상단 노출",
                link=data.get('link', '#'),
                shipping_fee='-', 
                store_rank=data.get('store_rank', '-'),
                prev_store_rank='-'
            )
            db.session.add(new_kw)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved'})
        else:
            return jsonify({'success': True, 'message': 'Already exists'})

    return jsonify({'success': False, 'message': 'Not A grade'})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id,
            'keyword': k.keyword,
            'search_volume': k.search_volume,
            'rank': k.rank_info,
            'link': k.link,
            'publisher': k.publisher,
            'supply_rate': k.supply_rate,
            'isbn': k.isbn,
            'price': k.price,
            'shipping_fee': k.shipping_fee,
            'store_name': k.store_name,
            'book_title': k.book_title,
            'product_link': k.product_link,
            'store_rank': k.store_rank,
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


# ✨ [신규 추가] 백그라운드에서 순위를 업데이트하는 실제 일꾼 함수
def async_refresh_ranks(app, user_id, client_id, client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            try:
                headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
                url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100"
                res = requests.get(url, headers=headers, timeout=5)
                
                if res.status_code == 200:
                    items = res.json().get('items', [])
                    rank = "100위 밖" 
                    for idx, item in enumerate(items):
                        if "스터디박스" in item.get('mallName', ''):
                            rank = str(idx + 1)
                            break
                    kw.store_rank = rank
                else:
                    kw.store_rank = "API에러"
            except:
                kw.store_rank = "통신실패"
                
            # ✨ 네이버 차단도 막고, 화면에 하나씩 갱신되는 걸 보여주기 위해 즉시 저장!
            time.sleep(0.1) 
            db.session.commit() 


# ✨ 버튼을 누르면 스레드(일꾼)만 출발시키고 1초만에 응답을 주는 API
@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    
    if not client_id or not client_secret:
        return jsonify({'success': False, 'message': '네이버 API 환경변수(ID/SECRET)가 서버에 설정되어 있지 않습니다.'})
    
    # 플라스크 앱과 사용자 정보를 스레드에 넘겨주기 위해 준비
    app = current_app._get_current_object()
    user_id = current_user.id
    
    # 백그라운드에서 작업 시작! (브라우저는 여기서 기다리지 않음)
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, client_id, client_secret))
    thread.start()
            
    return jsonify({'success': True, 'message': '✅ 백그라운드 순위 갱신이 시작되었습니다!\n(데이터 개수에 따라 1~2분 정도 소요되며, 화면에 실시간으로 반영됩니다.)'})
