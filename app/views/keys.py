import os
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import ApiKey

keys_bp = Blueprint('keys', __name__)

@keys_bp.route('/', methods=['GET', 'POST'])
@login_required
def index():
    # 현재 로그인한 사용자의 API 키 정보를 가져옵니다.
    api_key = ApiKey.query.filter_by(user_id=current_user.id).first()
    
    if request.method == 'POST':
        store_name = request.form.get('store_name', '스터디박스')
        client_id = request.form.get('client_id', '').strip()
        client_secret = request.form.get('client_secret', '').strip()
        
        if not client_id or not client_secret:
            flash('Client ID와 Secret을 모두 입력해주세요.', 'danger')
            return redirect(url_for('keys.index'))
            
        if api_key:
            # 이미 있으면 덮어쓰기 (업데이트)
            api_key.store_name = store_name
            api_key.client_id = client_id
            api_key.client_secret = client_secret
        else:
            # 없으면 새로 생성
            api_key = ApiKey(
                store_name=store_name,
                client_id=client_id,
                client_secret=client_secret,
                user_id=current_user.id
            )
            db.session.add(api_key)
            
        db.session.commit()
        flash('✅ 네이버 커머스 API 키가 성공적으로 저장되었습니다!', 'success')
        return redirect(url_for('keys.index'))
        
    return render_template('keys/index.html', api_key=api_key)
