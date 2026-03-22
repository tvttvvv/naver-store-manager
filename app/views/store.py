import json
import time
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context
from flask_login import login_required, current_user
from app.models import ApiKey
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, fetch_all_products

store_bp = Blueprint('store', __name__)

@store_bp.route('/')
@login_required
def index():
    return render_template('store/index.html', store_count=len(current_user.api_keys))

@store_bp.route('/delete_isbn', methods=['GET'])
@login_required
def delete_isbn():
    """화면 렌더링만 담당하고, 실제 삭제는 /api/stream_delete에서 처리합니다."""
    return render_template('store/delete_isbn.html', api_keys=current_user.api_keys)

@store_bp.route('/api/stream_delete', methods=['POST'])
@login_required
def stream_delete():
    """실시간으로 진행 상황을 프론트엔드(브라우저)로 스트리밍 전송합니다."""
    store_id = request.form.get('selected_store')
    delete_mode = request.form.get('delete_mode', 'isbn')
    isbn_input = request.form.get('isbn_list', '')

    def generate():
        try:
            # 1. 상점 정보 및 토큰 확인
            selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
            if not selected_key:
                yield json.dumps({'status': 'error', 'message': '상점 정보가 유효하지 않습니다.'}) + '\n'
                return

            yield json.dumps({'status': 'info', 'message': '네이버 API 인증 토큰 발급 중...'}) + '\n'
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                yield json.dumps({'status': 'error', 'message': 'API 인증에 실패했습니다. 키를 확인하세요.'}) + '\n'
                return

            # 2. 대상 상품 조회
            targets = []
            if delete_mode == 'isbn':
                yield json.dumps({'status': 'info', 'message': '입력한 ISBN 상품 정보 조회 중...'}) + '\n'
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                for isbn in isbn_list:
                    origin_no, channel_no = find_product_by_isbn(token, isbn)
                    targets.append({'display_name': f'ISBN: {isbn}', 'origin_no': origin_no, 'channel_no': channel_no})
            elif delete_mode == 'all':
                yield json.dumps({'status': 'info', 'message': '전체 상품 목록 수집 중 (잠시만 기다려주세요)...'}) + '\n'
                products = fetch_all_products(token)
                for p in products:
                    origin_no = p.get('originProductNo')
                    channel_products = p.get('channelProducts', [{}])
                    channel_no = channel_products[0].get('channelProductNo') if channel_products else None
                    name = channel_products[0].get('name', '이름 없는 상품') if channel_products else '이름 없는 상품'
                    targets.append({'display_name': f'[{origin_no}] {name[:15]}...', 'origin_no': origin_no, 'channel_no': channel_no})

            total = len(targets)
            if total == 0:
                yield json.dumps({'status': 'error', 'message': '삭제할 상품을 찾지 못했습니다.'}) + '\n'
                return

            # 3. 실시간 삭제 작업 및 스트리밍 진행
            yield json.dumps({'status': 'start', 'total': total, 'message': f'총 {total}개 상품 삭제 작업을 시작합니다.'}) + '\n'
            
            success_count, fail_count = 0, 0

            for i, target in enumerate(targets):
                if target['origin_no'] or target['channel_no']:
                    res_status = delete_product(token, target['origin_no'], target['channel_no'])
                    if '완료' in res_status:
                        success_count += 1
                    else:
                        fail_count += 1
                else:
                    res_status = "조회 불가 (상품 없음)"
                    fail_count += 1

                # 삭제 진행 1건마다 브라우저로 데이터 발송
                yield json.dumps({
                    'status': 'progress',
                    'current': i + 1,
                    'total': total,
                    'target_name': target['display_name'],
                    'result_status': res_status
                }) + '\n'
                
                time.sleep(0.1)  # API 과부하 방지를 위한 미세한 대기시간

            # 4. 종료
            yield json.dumps({'status': 'done', 'message': '모든 작업이 완료되었습니다!', 'success_count': success_count, 'fail_count': fail_count}) + '\n'

        except Exception as e:
            yield json.dumps({'status': 'error', 'message': f'시스템 오류 발생: {str(e)}'}) + '\n'

    # stream_with_context를 사용하여 제너레이터의 결과를 실시간으로 전송합니다.
    return Response(stream_with_context(generate()), mimetype='application/json')

# -------- 아래는 기존 코드 유지 --------
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
        seen_names, duplicates = {}, []
        
        for p in products:
            channel_products = p.get('channelProducts', [{}])
            if not channel_products: continue
                
            channel_product = channel_products[0]
            name = channel_product.get('name', '이름 없는 상품')
            prod_id = channel_product.get('channelProductNo', 'ID 없음')
            
            if name in seen_names:
                duplicates.append({'name': name, 'original_id': seen_names[name], 'duplicate_id': prod_id})
            else:
                seen_names[name] = prod_id
                
        return jsonify({'success': True, 'total_checked': len(products), 'duplicate_count': len(duplicates), 'duplicates': duplicates})
        
    return render_template('store/check_duplicates.html', api_keys=current_user.api_keys)
