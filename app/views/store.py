import json
import time
import requests
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context
from flask_login import login_required, current_user
from app.models import ApiKey
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, fetch_all_products

store_bp = Blueprint('store', __name__)

# [핵심] 버퍼링 무력화 패딩 생성 함수
def send_json(data):
    """데이터 뒤에 공백 1024바이트를 붙여 프록시가 데이터를 움켜쥐지 못하게 강제 방출시킵니다."""
    return json.dumps(data) + " " * 1024 + "\n"

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
        # 시작 전 파이프라인 강제 개방용 공백 발송
        yield " " * 2048 + "\n"
        
        try:
            selected_key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
            if not selected_key:
                yield send_json({'status': 'error', 'message': '상점 정보가 유효하지 않습니다.'})
                return

            yield send_json({'status': 'info', 'message': '네이버 API 인증 토큰 발급 중...'})
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                yield send_json({'status': 'error', 'message': 'API 인증에 실패했습니다. 키를 확인하세요.'})
                return

            targets = []
            if delete_mode == 'isbn':
                yield send_json({'status': 'info', 'message': '입력한 ISBN 상품 정보 조회 중...'})
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                for isbn in isbn_list:
                    origin_no, channel_no = find_product_by_isbn(token, isbn)
                    targets.append({'display_name': f'ISBN: {isbn}', 'origin_no': origin_no, 'channel_no': channel_no})
                    
            elif delete_mode == 'all':
                yield send_json({'status': 'info', 'message': '전체 상품 목록 수집 시작...'})
                
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                page = 1
                
                while True:
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try:
                        res = requests.post(url, headers=headers, json=payload, timeout=15)
                    except Exception as e:
                        yield send_json({'status': 'error', 'message': f'목록 수집 시간초과 (다시 시도해주세요)'})
                        return

                    if res.status_code != 200:
                        yield send_json({'status': 'error', 'message': f'목록 수집 실패: API 응답코드 {res.status_code}'})
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
                        
                    yield send_json({'status': 'info', 'message': f'상품 목록 수집 중... (현재 {len(targets)}개 찾음)'})
                    
                    if len(contents) < 50:
                        break
                        
                    page += 1
                    time.sleep(0.3)

            total = len(targets)
            if total == 0:
                yield send_json({'status': 'error', 'message': '삭제할 상품을 찾지 못했습니다.'})
                return

            # [핵심] 수집이 끝나고 본격적인 삭제 시작을 화면에 즉시 알림!
            yield send_json({'status': 'start', 'total': total, 'message': f'총 {total}개 상품 삭제 처리를 시작합니다.'})
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

                yield send_json({
                    'status': 'progress',
                    'current': i + 1,
                    'total': total,
                    'target_name': target['display_name'],
                    'result_status': res_status
                })
                
                # 네이버 API 차단 방지를 위한 안정적인 휴식 시간 확보
                time.sleep(0.3)

            yield send_json({'status': 'done', 'message': '모든 작업이 안전하게 완료되었습니다!', 'success_count': success_count, 'fail_count': fail_count})

        except Exception as e:
            yield send_json({'status': 'error', 'message': f'서버 내부 오류: {str(e)}'})

    response = Response(stream_with_context(generate()), mimetype='application/json')
    response.headers['X-Accel-Buffering'] = 'no'
    response.headers['Cache-Control'] = 'no-cache'
    return response

# -------- 기존 중복 체크 로직 유지 --------
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
