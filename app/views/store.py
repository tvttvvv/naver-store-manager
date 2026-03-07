from flask import Blueprint, render_template, request, redirect, url_for, flash
from flask_login import login_required, current_user
from app.models import ApiKey
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product

store_bp = Blueprint('store', __name__)

@store_bp.route('/')
@login_required
def index():
    # 추후 통계나 요약 정보를 보여줄 수 있는 메인 대시보드
    return render_template('store/index.html', store_count=len(current_user.api_keys))

@store_bp.route('/delete_isbn', methods=['GET', 'POST'])
@login_required
def delete_isbn():
    results = []
    if request.method == 'POST':
        store_id = request.form.get('selected_store')
        isbn_input = request.form.get('isbn_list', '')
        
        selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        if not selected_key:
            flash('유효하지 않은 상점입니다.', 'danger')
            return redirect(url_for('store.delete_isbn'))
            
        isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
        token = get_naver_token(selected_key.client_id, selected_key.client_secret)
        
        if not token:
            flash('API 인증 실패. Client ID와 Secret을 확인하세요.', 'danger')
        else:
            for isbn in isbn_list:
                product_id = find_product_by_isbn(token, isbn)
                if product_id:
                    success = delete_product(token, product_id)
                    status = "삭제 완료" if success else "삭제 실패"
                else:
                    status = "상품 조회 불가"
                results.append({'isbn': isbn, 'status': status})
            
    return render_template('store/delete_isbn.html', api_keys=current_user.api_keys, results=results)
