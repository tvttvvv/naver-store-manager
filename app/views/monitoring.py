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


def async_refresh_ranks(app, user_id):
    with app.app_context():
        keywords = MonitoredKeyword.query.filter_by(user_id=user_id).all()
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        
        for kw in keywords:
            kw.prev_store_rank = kw.store_rank
            rank = "순위 밖"
            try:
                url = f"https://search.shopping.naver.com/search/all?query={urllib.parse.quote(kw.keyword)}"
                res = requests.get(url, headers=headers, timeout=5)
                
                if "스터디박스" in res.text:
                    items = res.text.split('class="product_item__')
                    found = False
                    if len(items) > 1:
                        for idx, item in enumerate(items[1:], start=1):
                            if "스터디박스" in item:
                                rank = str(idx)
                                found = True
                                break
                    if not found:
                        names = re.findall(r'"mallName":"([^"]+)"', res.text)
                        for idx, name in enumerate(names, start=1):
                            if "스터디박스" in name:
                                rank = str(idx)
                                break
            except:
                rank = "스크래핑 실패"
                
            kw.store_rank = rank
            time.sleep(1) # 차단 방지용 1초 휴식
            db.session.commit() 


@monitoring_bp.route('/api/refresh_all_ranks', methods=['POST'])
@login_required
def refresh_all_ranks():
    app = current_app._get_current_object()
    user_id = current_user.id
    
    thread = Thread(target=async_refresh_ranks, args=(app, user_id))
    thread.start()
            
    return jsonify({'success': True, 'message': '✅ 백그라운드 웹 스크래핑이 시작되었습니다!\n(데이터당 1초씩 소요되며, 화면에 실시간으로 반영됩니다.)'})
