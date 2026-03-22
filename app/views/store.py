import json
import time
import requests
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
    return render_template('store/delete_isbn.html', api_keys=current_user.api_keys)

@store_bp.route('/api/stream_delete', methods=['POST'])
@login_required
def stream_delete():
    store_id = request.form.get('selected_store')
    delete_mode = request.form.get('delete_mode', 'isbn')
    isbn_input = request.form.get('isbn_list', '')

    def generate():
        # [핵심 1] Gunicorn/Nginx 버퍼링 무력화 패딩 (강제로 스트리밍 통로를 엽니다)
        yield " " * 1024 + "\n"
        
        try:
            selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
            if not selected_key:
                yield json.dumps({'status': 'error', 'message': '상점 정보가 유효하지 않습니다.'}) + '\n'
                return

            yield json.dumps({'status': 'info', 'message': '네이버 API 인증 토큰 발급 중...'}) + '\n'
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                yield json.dumps({'status': 'error', 'message': 'API 인증에 실패했습니다. 키를 확인하세요.'}) + '\n'
                return

            targets = []
            if delete_mode == 'isbn':
                yield json.dumps({'status': 'info', 'message': '입력한 ISBN 상품 정보 조회 중...'}) + '\n'
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                for isbn in isbn_list:
                    origin_no, channel_no = find_product_by_isbn(token, isbn)
                    targets.append({'display_name': f'ISBN: {isbn}', 'origin_no': origin_no, 'channel_no': channel_no})
                    
            elif delete_mode == 'all':
                yield json.dumps({'status': 'info', 'message': '전체 상품 목록 수집 시작...'}) + '\n'
                
                # [핵심 2] 상품을 모으는 동안에도 화면에 50개 단위로 진행상황을 쏴줍니다! (멈춤 방지)
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                page = 1
                
                while True:
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try:
                        res = requests.post(url, headers=headers, json=payload, timeout=15)
                    except Exception as e:
                        yield json.dumps({'status': 'error', 'message': f'상품 목록 요청 시간초과: {str(e)}'}) + '\n'
                        return

                    if res.status_code != 200:
                        yield json.dumps({'status': 'error', 'message': f'목록 수집 실패: API 응답코드 {res.status_code}'}) + '\n'
                        return
                        
                    contents = res.json().get('contents', [])
                    if not contents:
                        break
                        
                    for p in contents:
                        origin_no = p.get('originProductNo')
                        channel_products = p.get('channelProducts', [{}])
                        channel_no = channel_products[0].get('channelProductNo') if channel_products else None
                        name = channel_products[0].get('name', '이름 없는 상품') if channel_products else '이름 없는 상품'
                        targets.append({'display_name': f'[{origin_no}] {name[:15]}...', 'origin_no': origin_no, 'channel_no': channel_no})
                        
                    # 50개 모일 때마다 화면으로 데이터 전송! -> 사용자 화면 안 멈춤
                    yield json.dumps({'status': 'info', 'message': f'상품 목록 수집 중... (현재 {len(targets)}개 찾음)'}) + '\n'
                    
                    if len(contents) < 50:
                        break
                        
                    page += 1
                    time.sleep(0.3)

            total = len(targets)
            if total == 0:
                yield json.dumps({'status': 'error', 'message': '삭제할 상품을 찾지 못했습니다.'}) + '\n'
                return

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

                yield json.dumps({
                    'status': 'progress',
                    'current': i + 1,
                    'total': total,
                    'target_name': target['display_name'],
                    'result_status': res_status
                }) + '\n'
                
                time.sleep(0.1)

            yield json.dumps({'status': 'done', 'message': '모든 작업이 완료되었습니다!', 'success_count': success_count, 'fail_count': fail_count}) + '\n'

        except Exception as e:
            yield json.dumps({'status': 'error', 'message': f'시스템 오류 발생: {str(e)}'}) + '\n'

    # [핵심 3] Railway 서버 설정 무시하고 데이터를 강제 송출하도록 헤더 조작
    response = Response(stream_with_context(generate()), mimetype='application/json')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response

# -------- 아래는 기존 중복 체크 로직 그대로 유지 --------
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
