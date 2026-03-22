import os
from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword

monitoring_bp = Blueprint('monitoring', __name__)

@monitoring_bp.route('/')
@login_required
def index():
    return render_template('monitoring/index.html')

# ✨ [핵심] 1번 사이트(도서 분석기)가 데이터를 던져줄 통로 (Webhook) ✨
# (외부 서버가 보내는 것이므로 @login_required를 뺍니다)
@monitoring_bp.route('/api/webhook', methods=['POST'])
def receive_webhook():
    data = request.get_json()
    if not data:
        return jsonify({'success': False, 'message': 'No data'})

    grade = data.get('grade', '')
    keyword = data.get('keyword', '')
    
    # A등급(황금) 데이터가 날아왔을 때만 처리
    if 'A' in grade and keyword:
        # 단일 관리자 계정(첫 번째 유저)의 DB에 저장하도록 설정
        user = User.query.first()
        if not user:
            return jsonify({'success': False, 'message': 'No user found'})
            
        # 중복 체크: 이미 보관함에 있는 키워드인지 확인
        existing = MonitoredKeyword.query.filter_by(user_id=user.id, keyword=keyword).first()
        
        if not existing:
            # 중복이 아니면 DB에 영구 저장!
            new_kw = MonitoredKeyword(
                user_id=user.id,
                keyword=keyword,
                search_volume=data.get('search_volume', 0),
                rank_info="최상단 노출",
                link=data.get('link', '#')
            )
            db.session.add(new_kw)
            db.session.commit()
            return jsonify({'success': True, 'message': 'Saved'})
        else:
            return jsonify({'success': True, 'message': 'Already exists'})

    return jsonify({'success': False, 'message': 'Not A grade'})

# --- 프론트엔드에서 데이터를 갱신할 때 쓰는 API ---
@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    """DB에 저장된 황금 키워드 목록을 반환합니다."""
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.desc()).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id,
            'keyword': k.keyword,
            'search_volume': k.search_volume,
            'rank': k.rank_info,
            'link': k.link
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
