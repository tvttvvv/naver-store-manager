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
        delete_mode = request.form.get('delete_mode', 'isbn') # 'isbn' 또는 'all'
        
        selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        if not selected_key:
            flash('유효하지 않은 상점입니다.', 'danger')
            return redirect(url_for('store.delete_isbn'))
            
        token = get_naver_token(selected_key.client_id, selected_key.client_secret)
        
        if not token:
            flash('API 인증 실패. Client ID와 Secret을 확인하세요.', 'danger')
        else:
            if delete_mode == 'isbn':
                # ---------------------------------------------
                # 모드 1: 특정 상품 삭제 (ISBN 기준)
                # ---------------------------------------------
                isbn_input = request.form.get('isbn_list', '')
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                
                for isbn in isbn_list:
                    origin_no, channel_no = find_product_by_isbn(token, isbn)
                    if origin_no or channel_no:
                        status = delete_product(token, origin_no, channel_no)
                    else:
                        status = "조회 불가 (상품 없음)"
                    results.append({'target': f'ISBN: {isbn}', 'status': status})
                    
            elif delete_mode == 'all':
                # ---------------------------------------------
                # 모드 2: 상점 내 전체 상품 일괄 삭제
                # ---------------------------------------------
                products = fetch_all_products(token)
                
                if not products:
                    results.append({'target': '전체 상품', 'status': '등록된 상품이 없습니다.'})
                else:
                    for p in products:
                        origin_no = p.get('originProductNo')
                        channel_products = p.get('channelProducts', [{}])
                        
                        # 상품명과 채널번호 추출 (UI 표시용)
                        if channel_products:
                            channel_no = channel_products[0].get('channelProductNo')
                            name = channel_products[0].get('name', '이름 없는 상품')
                        else:
                            channel_no = None
                            name = '이름 없는 상품'
                            
                        if origin_no or channel_no:
                            status = delete_product(token, origin_no, channel_no)
                        else:
                            status = "식별 번호 누락"
                            
                        results.append({'target': f'[{origin_no}] {name[:15]}...', 'status': status})
            
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
