import os
import time
from threading import Thread
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword
import requests
import urllib.parse
import re
import random

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


def async_refresh_ranks(app, user_id, client_id, client_secret):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            rank = "순위 밖"
            
            fake_ip = f"211.{random.randint(10, 250)}.{random.randint(10, 250)}.{random.randint(10, 250)}"
            headers = {
                "User-Agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1",
                "X-Forwarded-For": fake_ip,
                "Accept-Language": "ko-KR,ko;q=0.9"
            }
            
            # 1. 모바일 스크래핑
            found = False
            try:
                url = f"https://msearch.shopping.naver.com/search/all?query={urllib.parse.quote(kw.keyword)}"
                res = requests.get(url, headers=headers, timeout=5)
                if "captcha" not in res.text.lower() and "비정상적인" not in res.text:
                    if "스터디박스" in res.text:
                        names = re.findall(r'"mallName":"([^"]+)"', res.text)
                        for idx, name in enumerate(names, start=1):
                            if "스터디박스" in name:
                                rank = str(idx)
                                found = True
                                break
            except: pass

            # 2. 실패시 API 폴백
            if not found:
                try:
                    if client_id and client_secret:
                        api_headers = {"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}
                        for start_idx in [1, 101]:
                            api_url = f"https://openapi.naver.com/v1/search/shop.json?query={urllib.parse.quote(kw.keyword)}&display=100&start={start_idx}"
                            api_res = requests.get(api_url, headers=api_headers, timeout=5)
                            if api_res.status_code == 200:
                                for idx, item in enumerate(api_res.json().get('items', [])):
                                    if "스터디박스" in item.get('mallName', ''):
                                        rank = str(start_idx + idx)
                                        found = True
                                        break
                            if found: break
                            time.sleep(0.1)
                except: rank = "탐색 실패"
                
            kw.store_rank = rank
            time.sleep(1)
            db.session.commit() 


@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    client_id = os.environ.get("NAVER_CLIENT_ID", "")
    client_secret = os.environ.get("NAVER_CLIENT_SECRET", "")
    
    app = current_app._get_current_object()
    user_id = current_user.id
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id, client_id, client_secret))
    thread.start()
            
    return jsonify({'success': True, 'message': '✅ 백그라운드 우회 탐색(스크래핑+API)이 시작되었습니다!\n(데이터당 1~2초씩 소요되며 화면에 실시간 반영됩니다.)'})
