import json
import time
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, Response, stream_with_context
from flask_login import login_required, current_user
from app.models import ApiKey
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, suspend_products_in_bulk, fetch_all_products

store_bp = Blueprint('store', __name__)

def send_json(data):
    """버퍼링 무력화 패딩 (강제 전송)"""
    return json.dumps(data) + " " * 2048 + "\n"

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

            if delete_mode == 'isbn':
                # ----------------------------------------------------
                # [ISBN 특정 삭제 모드] 하이브리드(삭제->묶음중지) 적용
                # ----------------------------------------------------
                yield send_json({'status': 'info', 'message': '입력한 ISBN 상품 정보 조회 중...'})
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                yield send_json({'status': 'start', 'total': len(isbn_list), 'message': '1차 작업: 대상 상품 완전 삭제 시도 중...'})
                
                success_count, fail_count, current_count = 0, 0, 0
                targets_info = []

                # 1. ISBN을 기반으로 상품 번호 동시 탐색
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_isbn = {executor.submit(find_product_by_isbn, token, isbn): isbn for isbn in isbn_list}
                    for future in as_completed(future_to_isbn):
                        isbn = future_to_isbn[future]
                        origin_no, channel_no = future.result()
                        targets_info.append((isbn, origin_no, channel_no))
                
                # 2. 완전 삭제 우선 시도
                suspend_targets = []
                item_details = {}
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_del = {}
                    for isbn, origin_no, channel_no in targets_info:
                        if origin_no or channel_no:
                            future_to_del[executor.submit(delete_product, token, origin_no, channel_no)] = (isbn, origin_no, channel_no)
                        else:
                            current_count += 1
                            fail_count += 1
                            yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': "조회 불가 (상품 없음)"})

                    for future in as_completed(future_to_del):
                        isbn, origin_no, channel_no = future_to_del[future]
                        res_status = future.result()
                        
                        if '완료' in res_status:
                            current_count += 1
                            success_count += 1
                            yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': res_status})
                        else:
                            # 삭제 실패 시, 2차 작업을 위해 보류 리스트에 담아둡니다.
                            if channel_no:
                                suspend_targets.append(channel_no)
                                item_details[channel_no] = isbn
                            else:
                                current_count += 1
                                fail_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': res_status})

                # 3. 삭제 실패한 상품들 모아서 일괄 판매/전시 중지
                if suspend_targets:
                    # 네이버 정책상 최대 50개씩 쪼개서 묶음 전송
                    for i in range(0, len(suspend_targets), 50):
                        batch = suspend_targets[i:i+50]
                        yield send_json({'status': 'info', 'message': f'2차 작업: 완전 삭제 실패 상품 {len(batch)}개 일괄 중지 처리 중...'})
                        suspend_res = suspend_products_in_bulk(token, batch)
                        
                        for c_no in batch:
                            isbn = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res:
                                success_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': suspend_res})
                            else:
                                fail_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': f'최종 실패 ({suspend_res})'})
                
                yield send_json({'status': 'done', 'message': '모든 작업이 완료되었습니다!', 'success_count': success_count, 'fail_count': fail_count})

            elif delete_mode == 'all':
                # ----------------------------------------------------
                # [전체 싹쓸이 모드] 하이브리드(삭제->묶음중지) 적용
                # ----------------------------------------------------
                yield send_json({'status': 'start', 'total': 0, 'message': '🚀 1차: 완전삭제 ➡️ 2차: 묶음중지 콤보를 가동합니다!'})
                
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                
                processed_ids = set()
                page = 1
                current_count = 0
                success_count, fail_count = 0, 0
                
                while True:
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try:
                        res = requests.post(url, headers=headers, json=payload, timeout=10)
                    except Exception as e:
                        yield send_json({'status': 'info', 'message': '응답 지연... 안전하게 재시도 중입니다.'})
                        time.sleep(2)
                        continue

                    if res.status_code != 200:
                        yield send_json({'status': 'error', 'message': f'API 호출 실패 ({res.status_code})'})
                        return
                        
                    contents = res.json().get('contents', [])
                    if not contents:
                        break # 남은 상품이 0개면 무한루프 종료!
                        
                    new_items = [p for p in contents if p.get('originProductNo') not in processed_ids]
                    if not new_items:
                        page += 1
                        continue
                        
                    # 1단계: 3배속 엔진으로 '완전 삭제' 시도
                    suspend_targets = []
                    item_details = {}
                    
                    with ThreadPoolExecutor(max_workers=3) as executor:
                        future_to_item = {}
                        for p in new_items:
                            origin_no = p.get('originProductNo')
                            channel_products = p.get('channelProducts', [{}])
                            channel_no = channel_products[0].get('channelProductNo') if channel_products else None
                            name = channel_products[0].get('name', '이름 없는 상품') if channel_products else '이름 없는 상품'
                            
                            future = executor.submit(delete_product, token, origin_no, channel_no)
                            future_to_item[future] = (origin_no, channel_no, name)
                            
                        for future in as_completed(future_to_item):
                            origin_no, channel_no, name = future_to_item[future]
                            processed_ids.add(origin_no) # 다시 무한루프 도는 것 방지
                            
                            res_status = future.result()
                            if '완료' in res_status:
                                current_count += 1
                                success_count += 1
                                yield send_json({
                                    'status': 'progress', 'current': current_count, 'total': 0,
                                    'target_name': f'[{origin_no}] {name[:15]}...', 'result_status': res_status
                                })
                            else:
                                # 삭제가 불가능한 상품(판매 이력 등)은 '묶음 중지' 대기열로 넘김
                                if channel_no:
                                    suspend_targets.append(channel_no)
                                    item_details[channel_no] = (origin_no, name)
                                else:
                                    current_count += 1
                                    fail_count += 1
                                    yield send_json({
                                        'status': 'progress', 'current': current_count, 'total': 0,
                                        'target_name': f'[{origin_no}] {name[:15]}...', 'result_status': res_status
                                    })
                                    
                    # 2단계: 대기열에 담긴 '삭제 실패작'들을 한 방에 묶어서 중지 처리
                    if suspend_targets:
                        yield send_json({'status': 'info', 'message': f'완전 삭제 실패 상품 {len(suspend_targets)}개 일괄 중지 처리 중...'})
                        suspend_res = suspend_products_in_bulk(token, suspend_targets)
                        
                        for c_no in suspend_targets:
                            origin_no, name = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res:
                                success_count += 1
                            else:
                                fail_count += 1
                                
                            yield send_json({
                                'status': 'progress', 'current': current_count, 'total': 0,
                                'target_name': f'[{origin_no}] {name[:15]}...', 'result_status': suspend_res
                            })
                            
                    page = 1 # 상품들을 삭제/중지했기 때문에 목록이 갱신되었습니다. 1페이지부터 다시 스캔!
                    time.sleep(0.5)
                    
                yield send_json({'status': 'done', 'message': '상점 내 모든 상품 완전삭제 및 묶음중지 완료!', 'success_count': success_count, 'fail_count': fail_count})

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
