import os
from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required, current_user
from app import db
from app.models import ApiKey

keys_bp = Blueprint('keys', __name__)

def handle_keys():
    # 사용자가 등록한 '모든' 상점 API 키 목록을 가져옵니다.
    api_keys = ApiKey.query.filter_by(user_id=current_user.id).all()
    
    if request.method == 'POST':
        action = request.form.get('action')
        
        # 새 상점 추가
        if action == 'add':
            store_name = request.form.get('store_name', '').strip()
            client_id = request.form.get('client_id', '').strip()
            client_secret = request.form.get('client_secret', '').strip()
            
            if not store_name or not client_id or not client_secret:
                flash('상점명, Client ID, Secret을 모두 입력해주세요.', 'danger')
                return redirect(request.path)
                
            new_key = ApiKey(
                store_name=store_name,
                client_id=client_id,
                client_secret=client_secret,
                user_id=current_user.id
            )
            db.session.add(new_key)
            db.session.commit()
            flash(f'✅ [{store_name}] 상점의 API 키가 성공적으로 추가되었습니다!', 'success')
            return redirect(request.path)
            
        # 기존 상점 삭제
        elif action == 'delete':
            key_id = request.form.get('key_id')
            key_to_delete = ApiKey.query.filter_by(id=key_id, user_id=current_user.id).first()
            if key_to_delete:
                db.session.delete(key_to_delete)
                db.session.commit()
                flash('🗑️ API 키가 성공적으로 삭제되었습니다.', 'success')
            return redirect(request.path)
        
    return render_template('keys/index.html', api_keys=api_keys)

# base.html이 찾을 수 있는 모든 주소의 문을 열어둡니다.
@keys_bp.route('/', methods=['GET', 'POST'], endpoint='index')
@login_required
def index():
    return handle_keys()

@keys_bp.route('/api_keys', methods=['GET', 'POST'], endpoint='api_keys')
@login_required
def api_keys():
    return handle_keys()

@keys_bp.route('/manage', methods=['GET', 'POST'], endpoint='manage')
@login_required
def manage():
    return handle_keys()

@keys_bp.route('/manage_keys', methods=['GET', 'POST'], endpoint='manage_keys')
@login_required
def manage_keys():
    return handle_keys()
