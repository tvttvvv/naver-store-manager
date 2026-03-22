from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from app.models import ApiKey
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, fetch_all_products

store_bp = Blueprint('store', __name__)

@store_bp.route('/')
@login_required
def index():
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
                # ISBN으로 상품 번호 추출
                origin_no, channel_no = find_product_by_isbn(token, isbn)
                
                if origin_no or channel_no:
                    # 삭제 로직 실행 (완전 삭제 또는 판매중지 우회)
                    status = delete_product(token, origin_no, channel_no)
                else:
                    status = "조회 불가 (상품 없음)"
                    
                results.append({'isbn': isbn, 'status': status})
            
    return render_template('store/delete_isbn.html', api_keys=current_user.api_keys, results=results)

@store_bp.route('/check_duplicates', methods=['GET', 'POST'])
@login_required
def check_duplicates():
    if request.method == 'POST':
        store_id = request.form.get('selected_store')
        selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        
        if not selected_key:
            return jsonify({'success': False, 'message': '유효하지 않은 상점입니다.'})
            
        token = get_naver_token(selected_key.client_id, selected_key.client_secret)
        if not token:
            return jsonify({'success': False, 'message': 'API 인증에 실패했습니다. API 키를 확인해주세요.'})
        
        products = fetch_all_products(token)
        
        seen_names = {}
        duplicates = []
        
        for p in products:
            channel_products = p.get('channelProducts', [{}])
            if not channel_products:
                continue
                
            channel_product = channel_products[0]
            name = channel_product.get('name', '이름 없는 상품')
            prod_id = channel_product.get('channelProductNo', 'ID 없음')
            
            if name in seen_names:
                duplicates.append({
                    'name': name,
                    'original_id': seen_names[name],
                    'duplicate_id': prod_id
                })
            else:
                seen_names[name] = prod_id
                
        return jsonify({
            'success': True, 
            'total_checked': len(products),
            'duplicate_count': len(duplicates),
            'duplicates': duplicates
        })
        
    return render_template('store/check_duplicates.html', api_keys=current_user.api_keys)
