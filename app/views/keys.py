from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import ApiKey
from app import db

keys_bp = Blueprint('keys', __name__)

@keys_bp.route('/manage_keys', methods=['GET', 'POST'])
@login_required
def manage_keys():
    if request.method == 'POST':
        store_name = request.form.get('store_name')
        client_id = request.form.get('client_id')
        client_secret = request.form.get('client_secret')
        
        new_key = ApiKey(store_name=store_name, client_id=client_id, client_secret=client_secret, owner=current_user)
        db.session.add(new_key)
        db.session.commit()
        flash(f'{store_name} 상점 API 키가 등록되었습니다.', 'success')
        return redirect(url_for('keys.manage_keys'))
        
    return render_template('keys/manage_keys.html', api_keys=current_user.api_keys)

@keys_bp.route('/delete_key/<int:key_id>')
@login_required
def delete_key(key_id):
    key_to_delete = ApiKey.query.get_or_404(key_id)
    if key_to_delete.owner == current_user:
        db.session.delete(key_to_delete)
        db.session.commit()
        flash('API 키가 삭제되었습니다.', 'info')
    return redirect(url_for('keys.manage_keys'))
