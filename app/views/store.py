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
                # [ISBN 특정 삭제 모드]
                yield send_json({'status': 'info', 'message': '입력한 ISBN 상품 정보 조회 중...'})
                isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]
                yield send_json({'status': 'start', 'total': len(isbn_list), 'message': '1차: 대상 상품 완전 삭제 시도 중...'})
                
                success_count, fail_count, current_count = 0, 0, 0
                targets_info = []

                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_isbn = {executor.submit(find_product_by_isbn, token, isbn): isbn for isbn in isbn_list}
                    for future in as_completed(future_to_isbn):
                        isbn = future_to_isbn[future]
                        origin_no, channel_no = future.result()
                        targets_info.append((isbn, origin_no, channel_no))
                
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
                            if channel_no:
                                suspend_targets.append(channel_no)
                                item_details[channel_no] = isbn
                            else:
                                current_count += 1
                                fail_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': res_status})

                if suspend_targets:
                    for i in range(0, len(suspend_targets), 50):
                        batch = suspend_targets[i:i+50]
                        yield send_json({'status': 'info', 'message': f'2차: 삭제 실패 상품 {len(batch)}개 일괄 중지 처리 중...'})
                        suspend_res = suspend_products_in_bulk(token, batch)
                        
                        for c_no in batch:
                            isbn = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res or '우회' in suspend_res:
                                success_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': suspend_res})
                            else:
                                fail_count += 1
                                yield send_json({'status': 'progress', 'current': current_count, 'total': len(isbn_list), 'target_name': f'ISBN: {isbn}', 'result_status': f'최종 실패 ({suspend_res})'})
                
                yield send_json({'status': 'done', 'message': '모든 작업이 완료되었습니다!', 'success_count': success_count, 'fail_count': fail_count})

            elif delete_mode == 'all':
                # ✨ [싹쓸이 무한 스윕 모드] 멈춤 현상 완벽 방어 ✨
                yield send_json({'status': 'start', 'total': 0, 'message': '🚀 1차: 완전삭제 ➡️ 2차: 묶음중지 콤보 가동!'})
                
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                
                processed_ids = set()
                page = 1
                current_count = 0
                success_count, fail_count = 0, 0
                found_any_in_sweep = False  # 한 바퀴(스윕) 도는 동안 처리한 상품이 있는지 체크
                
                # 통신 안정성을 위해 Session 사용
                session = requests.Session()
                
                while True:
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try:
                        res = session.post(url, headers=headers, json=payload, timeout=10)
                    except Exception as e:
                        yield send_json({'status': 'info', 'message': f'응답 지연... 재시도 중 ({page}페이지)'})
                        time.sleep(2)
                        continue

                    if res.status_code != 200:
                        yield send_json({'status': 'error', 'message': f'API 호출 실패 ({res.status_code})'})
                        return
                        
                    contents = res.json().get('contents', [])
                    
                    # 더 이상 페이지에 상품이 없으면 (끝까지 도달함)
                    if not contents:
                        if found_any_in_sweep:
                            # 처리한 게 있다면 순서가 밀린 상품이 있을 수 있으니 1페이지부터 다시 한 바퀴 돕니다.
                            yield send_json({'status': 'info', 'message': '누락 상품 점검을 위해 1페이지부터 재탐색합니다.'})
                            page = 1
                            found_any_in_sweep = False
                            continue
                        else:
                            # 한 바퀴를 다 돌았는데 처리한 게 없다면 완벽하게 끝난 것입니다.
                            break 
                            
                    # 이미 처리한 상품 걸러내기
                    new_items = [p for p in contents if p.get('originProductNo') not in processed_ids]
                    
                    if not new_items:
                        # [핵심 방어] 이 페이지엔 지울 게 없지만, 화면이 멈추지 않도록 생존 신고(Heartbeat)를 보냅니다.
                        page += 1
                        yield send_json({'status': 'info', 'message': f'이미 처리된 상품 패스 중... (현재 {page}페이지 탐색)'})
                        time.sleep(0.1)
                        continue
                        
                    found_any_in_sweep = True
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
                            processed_ids.add(origin_no) 
                            
                            try:
                                res_status = future.result()
                            except Exception:
                                res_status = "시스템 오류"
                                
                            if '완료' in res_status:
                                current_count += 1
                                success_count += 1
                                yield send_json({
                                    'status': 'progress', 'current': current_count, 'total': 0,
                                    'target_name': f'[{origin_no}] {name[:15]}...', 'result_status': res_status
                                })
                            else:
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
                                    
                    if suspend_targets:
                        yield send_json({'status': 'info', 'message': f'삭제 불가 상품 {len(suspend_targets)}개 일괄 중지 처리 중...'})
                        suspend_res = suspend_products_in_bulk(token, suspend_targets)
                        
                        for c_no in suspend_targets:
                            origin_no, name = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res or '우회' in suspend_res:
                                success_count += 1
                            else:
                                fail_count += 1
                                
                            yield send_json({
                                'status': 'progress', 'current': current_count, 'total': 0,
                                'target_name': f'[{origin_no}] {name[:15]}...', 'result_status': suspend_res
                            })
                            
                    # 매 페이지 처리 완료 후 앞으로 전진합니다. 1페이지로 돌아가지 않습니다!
                    page += 1 
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
