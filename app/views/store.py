import json
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.models import ApiKey, User
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, suspend_products_in_bulk, fetch_all_products

store_bp = Blueprint('store', __name__)

# --- ✨ 핵심: 백그라운드 작업 상태 전역 메모리 저장소 ✨ ---
# 브라우저가 꺼져도 서버 메모리에 작업 상태가 안전하게 저장됩니다.
global_tasks = {}

def init_task(user_id, delete_mode):
    global_tasks[user_id] = {
        'is_running': True,
        'mode': delete_mode,
        'status': 'start',
        'message': '작업을 준비 중입니다...',
        'current': 0,
        'total': 0,
        'target_name': '',
        'result_status': '',
        'success_count': 0,
        'fail_count': 0,
        'logs': []
    }

def update_task(user_id, status=None, message=None, current=None, total=None, target_name=None, result_status=None, s_count=None, f_count=None):
    if user_id not in global_tasks:
        return
    t = global_tasks[user_id]
    
    if status: t['status'] = status
    if message: t['message'] = message
    if current is not None: t['current'] = current
    if total is not None: t['total'] = total
    if target_name: t['target_name'] = target_name
    if result_status: t['result_status'] = result_status
    if s_count is not None: t['success_count'] = s_count
    if f_count is not None: t['fail_count'] = f_count

    # UI에 뿌려줄 로그 기록 (최근 300개만 유지하여 서버 메모리 과부하 방지)
    if target_name and result_status:
        log_type = 'success' if '완료' in result_status or '우회' in result_status else 'danger'
        if '안내' in target_name or '에러' in target_name:
            log_type = 'info' if '안내' in target_name else 'danger'

        t['logs'].append({
            'type': log_type,
            'target': target_name,
            'statusMsg': result_status
        })
        if len(t['logs']) > 300:
            t['logs'].pop(0)

# --- 🚀 백그라운드 독립 실행 엔진 🚀 ---
def background_delete_job(app, store_id, delete_mode, isbn_list, user_id):
    """이 함수는 브라우저와 상관없이 서버 뒷단에서 혼자 묵묵히 돌아갑니다."""
    with app.app_context():
        try:
            user = User.query.get(user_id)
            selected_key = ApiKey.query.filter_by(id=store_id, owner=user).first()
            if not selected_key:
                update_task(user_id, status='error', message='상점 정보가 유효하지 않습니다.')
                return

            update_task(user_id, status='info', message='네이버 API 인증 토큰 발급 중...', target_name='시스템 안내', result_status='토큰 발급 중...')
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                update_task(user_id, status='error', message='API 인증에 실패했습니다. 키를 확인하세요.', target_name='시스템 에러', result_status='인증 실패')
                return

            if delete_mode == 'isbn':
                # [ISBN 특정 삭제 모드]
                update_task(user_id, status='info', message='입력한 ISBN 상품 정보 조회 중...')
                update_task(user_id, status='start', total=len(isbn_list), message='1차: 대상 상품 완전 삭제 시도 중...')
                
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
                            update_task(user_id, status='progress', current=current_count, total=len(isbn_list), target_name=f'ISBN: {isbn}', result_status="조회 불가 (상품 없음)", s_count=success_count, f_count=fail_count)

                    for future in as_completed(future_to_del):
                        isbn, origin_no, channel_no = future_to_del[future]
                        res_status = future.result()
                        
                        if '완료' in res_status:
                            current_count += 1
                            success_count += 1
                            update_task(user_id, status='progress', current=current_count, total=len(isbn_list), target_name=f'ISBN: {isbn}', result_status=res_status, s_count=success_count, f_count=fail_count)
                        else:
                            if channel_no:
                                suspend_targets.append(channel_no)
                                item_details[channel_no] = isbn
                            else:
                                current_count += 1
                                fail_count += 1
                                update_task(user_id, status='progress', current=current_count, total=len(isbn_list), target_name=f'ISBN: {isbn}', result_status=res_status, s_count=success_count, f_count=fail_count)

                if suspend_targets:
                    for i in range(0, len(suspend_targets), 50):
                        batch = suspend_targets[i:i+50]
                        update_task(user_id, status='info', message=f'2차: 삭제 실패 상품 {len(batch)}개 일괄 중지 처리 중...')
                        suspend_res = suspend_products_in_bulk(token, batch)
                        
                        for c_no in batch:
                            isbn = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res or '우회' in suspend_res:
                                success_count += 1
                            else:
                                fail_count += 1
                            
                            res_msg = suspend_res if ('완료' in suspend_res or '우회' in suspend_res) else f'최종 실패 ({suspend_res})'
                            update_task(user_id, status='progress', current=current_count, total=len(isbn_list), target_name=f'ISBN: {isbn}', result_status=res_msg, s_count=success_count, f_count=fail_count)
                
                update_task(user_id, status='done', message='모든 작업이 완료되었습니다!')

            elif delete_mode == 'all':
                # [전체 싹쓸이 무한 스윕 모드]
                update_task(user_id, status='start', total=0, message='🚀 1차: 완전삭제 ➡️ 2차: 묶음중지 콤보 가동!')
                
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                
                processed_ids = set()
                page = 1
                current_count = 0
                success_count, fail_count = 0, 0
                found_any_in_sweep = False  
                
                session = requests.Session()
                
                while True:
                    if not global_tasks[user_id]['is_running']: break # 안전 종료 장치
                    
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try:
                        res = session.post(url, headers=headers, json=payload, timeout=10)
                    except Exception as e:
                        update_task(user_id, status='info', message=f'응답 지연... 재시도 중 ({page}페이지)')
                        time.sleep(2)
                        continue

                    if res.status_code != 200:
                        update_task(user_id, status='error', message=f'API 호출 실패 ({res.status_code})')
                        return
                        
                    contents = res.json().get('contents', [])
                    
                    if not contents:
                        if found_any_in_sweep:
                            update_task(user_id, status='info', message='누락 상품 점검을 위해 1페이지부터 재탐색합니다.')
                            page = 1
                            found_any_in_sweep = False
                            continue
                        else:
                            break 
                            
                    new_items = [p for p in contents if p.get('originProductNo') not in processed_ids]
                    
                    if not new_items:
                        page += 1
                        update_task(user_id, status='info', message=f'이미 처리된 상품 패스 중... (현재 {page}페이지 탐색)')
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
                                update_task(user_id, status='progress', current=current_count, total=0, target_name=f'[{origin_no}] {name[:15]}...', result_status=res_status, s_count=success_count, f_count=fail_count)
                            else:
                                if channel_no:
                                    suspend_targets.append(channel_no)
                                    item_details[channel_no] = (origin_no, name)
                                else:
                                    current_count += 1
                                    fail_count += 1
                                    update_task(user_id, status='progress', current=current_count, total=0, target_name=f'[{origin_no}] {name[:15]}...', result_status=res_status, s_count=success_count, f_count=fail_count)
                                    
                    if suspend_targets:
                        update_task(user_id, status='info', message=f'삭제 불가 상품 {len(suspend_targets)}개 일괄 중지 처리 중...')
                        suspend_res = suspend_products_in_bulk(token, suspend_targets)
                        
                        for c_no in suspend_targets:
                            origin_no, name = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res or '우회' in suspend_res:
                                success_count += 1
                            else:
                                fail_count += 1
                            update_task(user_id, status='progress', current=current_count, total=0, target_name=f'[{origin_no}] {name[:15]}...', result_status=suspend_res, s_count=success_count, f_count=fail_count)
                            
                    page += 1 
                    time.sleep(0.5)
                    
                update_task(user_id, status='done', message='상점 내 모든 상품 완전삭제 및 묶음중지 완료!')

        except Exception as e:
            update_task(user_id, status='error', message=f'서버 내부 오류: {str(e)}')
        finally:
            if user_id in global_tasks:
                global_tasks[user_id]['is_running'] = False


# --- 라우터 엔드포인트 ---

@store_bp.route('/')
@login_required
def index():
    return render_template('store/index.html', store_count=len(current_user.api_keys))

@store_bp.route('/delete_isbn', methods=['GET'])
@login_required
def delete_isbn():
    return render_template('store/delete_isbn.html', api_keys=current_user.api_keys)

@store_bp.route('/api/get_task_status', methods=['GET'])
@login_required
def get_task_status():
    """브라우저가 1초마다 주기적으로 상태를 물어볼 때 답변하는 엔드포인트"""
    user_id = current_user.id
    if user_id in global_tasks:
        return jsonify(global_tasks[user_id])
    return jsonify({'status': 'empty'})

@store_bp.route('/api/start_task', methods=['POST'])
@login_required
def start_task():
    """백그라운드 스레드를 발진시키는 엔드포인트"""
    user_id = current_user.id

    if user_id in global_tasks and global_tasks[user_id]['is_running']:
        return jsonify({'success': False, 'message': '이미 작업이 진행 중입니다. 화면을 갱신합니다.'})

    store_id = request.form.get('selected_store')
    delete_mode = request.form.get('delete_mode', 'isbn')
    isbn_input = request.form.get('isbn_list', '')

    init_task(user_id, delete_mode)

    isbn_list = []
    if delete_mode == 'isbn':
        isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()]

    app = current_app._get_current_object()
    thread = threading.Thread(target=background_delete_job, args=(app, store_id, delete_mode, isbn_list, user_id))
    thread.start() # 일꾼 출발!

    return jsonify({'success': True})

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
