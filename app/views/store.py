import json
import time
import re
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, current_app
from flask_login import login_required, current_user
from app.models import ApiKey, User
from app.naver_api import get_naver_token, find_product_by_isbn, delete_product, suspend_products_in_bulk, fetch_all_products

store_bp = Blueprint('store', __name__)

# ==============================================================================
# 1. 일괄 삭제 관리용 엔진
# ==============================================================================
global_tasks = {}

def init_task(user_id, store_id, store_name, delete_mode):
    if user_id not in global_tasks: global_tasks[user_id] = {}
    global_tasks[user_id][store_id] = {
        'is_running': True, 'store_name': store_name, 'mode': delete_mode,
        'status': 'start', 'message': '작업을 준비 중입니다...',
        'current': 0, 'total': 0, 'target_name': '', 'result_status': '',
        'success_count': 0, 'fail_count': 0, 'logs': []
    }

def update_task(user_id, store_id, status=None, message=None, current=None, total=None, target_name=None, result_status=None, s_count=None, f_count=None):
    if user_id not in global_tasks or store_id not in global_tasks[user_id]: return
    t = global_tasks[user_id][store_id]
    if status: t['status'] = status
    if message: t['message'] = message
    if current is not None: t['current'] = current
    if total is not None: t['total'] = total
    if target_name: t['target_name'] = target_name
    if result_status: t['result_status'] = result_status
    if s_count is not None: t['success_count'] = s_count
    if f_count is not None: t['fail_count'] = f_count

    if target_name and result_status:
        log_type = 'success' if '완료' in result_status or '우회' in result_status else 'danger'
        if '안내' in target_name or '에러' in target_name: log_type = 'info' if '안내' in target_name else 'danger'
        t['logs'].append({'type': log_type, 'target': target_name, 'statusMsg': result_status})
        if len(t['logs']) > 50: t['logs'].pop(0)

def background_delete_job(app, store_id, delete_mode, isbn_list, user_id):
    with app.app_context():
        try:
            user = User.query.get(user_id)
            selected_key = ApiKey.query.filter_by(id=store_id, owner=user).first()
            if not selected_key:
                update_task(user_id, store_id, status='error', message='상점 정보가 유효하지 않습니다.')
                return

            update_task(user_id, store_id, status='info', message='네이버 API 인증 토큰 발급 중...', target_name='시스템 안내', result_status='토큰 발급 중...')
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                update_task(user_id, store_id, status='error', message='API 인증 실패', target_name='시스템 에러', result_status='인증 실패')
                return

            if delete_mode == 'isbn':
                update_task(user_id, store_id, status='start', total=len(isbn_list), message='대상 상품 완전 삭제 시도 중...')
                success_count, fail_count, current_count = 0, 0, 0
                targets_info, suspend_targets, item_details = [], [], {}

                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_isbn = {executor.submit(find_product_by_isbn, token, isbn): isbn for isbn in isbn_list}
                    for future in as_completed(future_to_isbn):
                        if not global_tasks[user_id][store_id]['is_running']: break
                        isbn = future_to_isbn[future]
                        origin_no, channel_no = future.result()
                        targets_info.append((isbn, origin_no, channel_no))
                
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_del = {}
                    for isbn, origin_no, channel_no in targets_info:
                        if origin_no or channel_no:
                            future_to_del[executor.submit(delete_product, token, origin_no, channel_no)] = (isbn, origin_no, channel_no)
                        else:
                            current_count += 1
                            fail_count += 1
                            update_task(user_id, store_id, status='progress', current=current_count, target_name=f'ISBN: {isbn}', result_status="조회 불가", s_count=success_count, f_count=fail_count)

                    for future in as_completed(future_to_del):
                        if not global_tasks[user_id][store_id]['is_running']: break
                        isbn, origin_no, channel_no = future_to_del[future]
                        res_status = future.result()
                        current_count += 1
                        
                        if '완료' in res_status: success_count += 1
                        else:
                            if channel_no:
                                suspend_targets.append(channel_no)
                                item_details[channel_no] = isbn
                            else: fail_count += 1
                        update_task(user_id, store_id, status='progress', current=current_count, target_name=f'ISBN: {isbn}', result_status=res_status, s_count=success_count, f_count=fail_count)

                if suspend_targets and global_tasks[user_id][store_id]['is_running']:
                    for i in range(0, len(suspend_targets), 500):
                        if not global_tasks[user_id][store_id]['is_running']: break
                        batch = suspend_targets[i:i+500]
                        update_task(user_id, store_id, status='info', message=f'실패 상품 {len(batch)}개 묶음 중지 처리 중...')
                        suspend_res = suspend_products_in_bulk(token, batch)
                        
                        for c_no in batch:
                            isbn = item_details[c_no]
                            current_count += 1
                            if '완료' in suspend_res or '우회' in suspend_res: success_count += 1
                            else: fail_count += 1
                            res_msg = suspend_res if ('완료' in suspend_res or '우회' in suspend_res) else f'최종 실패 ({suspend_res})'
                            update_task(user_id, store_id, status='progress', current=current_count, target_name=f'ISBN: {isbn}', result_status=res_msg, s_count=success_count, f_count=fail_count)
                
                if not global_tasks[user_id][store_id]['is_running']: update_task(user_id, store_id, status='error', message='긴급 정지됨.')
                else: update_task(user_id, store_id, status='done', message='작업 완료!')

            elif delete_mode == 'all':
                update_task(user_id, store_id, status='start', total=0, message='1차: 완전삭제 ➡️ 2차: 중지 하이브리드 가동!')
                url = "https://api.commerce.naver.com/external/v1/products/search"
                headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
                processed_ids = set()
                page = 1
                current_count, success_count, fail_count = 0, 0, 0
                found_any_in_sweep = False  
                session = requests.Session()
                
                while True:
                    if not global_tasks[user_id][store_id]['is_running']: break
                    
                    payload = {"page": page, "size": 50, "orderType": "NO"}
                    try: res = session.post(url, headers=headers, json=payload, timeout=10)
                    except Exception:
                        update_task(user_id, store_id, status='info', message=f'응답 지연... 재시도 중 ({page}페이지)')
                        time.sleep(2)
                        continue

                    if res.status_code != 200:
                        update_task(user_id, store_id, status='error', message=f'API 호출 실패 ({res.status_code})')
                        return
                        
                    contents = res.json().get('contents', [])
                    if not contents:
                        if found_any_in_sweep:
                            page = 1
                            found_any_in_sweep = False
                            continue
                        else: break 
                            
                    new_items = [p for p in contents if p.get('originProductNo') not in processed_ids]
                    if not new_items:
                        page += 1
                        update_task(user_id, store_id, status='info', message=f'잔여 데이터 스캔 및 최종 점검 중... ({page}페이지)')
                        time.sleep(0.1)
                        continue
                        
                    found_any_in_sweep = True
                    suspend_targets, item_details = [], {}
                    
                    with ThreadPoolExecutor(max_workers=3) as executor:
                        future_to_item = {}
                        for p in new_items:
                            origin_no = p.get('originProductNo')
                            channel_no = p.get('channelProductNo')
                            name = str(p.get('name', '이름 없음'))
                            future = executor.submit(delete_product, token, origin_no, channel_no)
                            future_to_item[future] = (origin_no, channel_no, name)
                            
                        for future in as_completed(future_to_item):
                            if not global_tasks[user_id][store_id]['is_running']: break
                            origin_no, channel_no, name = future_to_item[future]
                            processed_ids.add(origin_no) 
                            
                            try: res_status = future.result()
                            except: res_status = "시스템 오류"
                                
                            if '완료' in res_status:
                                current_count += 1
                                success_count += 1
                                update_task(user_id, store_id, status='progress', current=current_count, target_name=f'[{origin_no}] {name[:15]}...', result_status=res_status, s_count=success_count, f_count=fail_count)
                            else:
                                if channel_no:
                                    suspend_targets.append(channel_no)
                                    item_details[channel_no] = (origin_no, name)
                                else:
                                    current_count += 1
                                    fail_count += 1
                                    update_task(user_id, store_id, status='progress', current=current_count, target_name=f'[{origin_no}] {name[:15]}...', result_status=res_status, s_count=success_count, f_count=fail_count)
                                    
                    if suspend_targets and global_tasks[user_id][store_id]['is_running']:
                        for i in range(0, len(suspend_targets), 500):
                            if not global_tasks[user_id][store_id]['is_running']: break
                            batch = suspend_targets[i:i+500]
                            suspend_res = suspend_products_in_bulk(token, batch)
                            
                            for c_no in batch:
                                origin_no, name = item_details[c_no]
                                current_count += 1
                                if '완료' in suspend_res or '우회' in suspend_res: success_count += 1
                                else: fail_count += 1
                                update_task(user_id, store_id, status='progress', current=current_count, target_name=f'[{origin_no}] {name[:15]}...', result_status=suspend_res, s_count=success_count, f_count=fail_count)
                            
                    page += 1 
                    time.sleep(0.5)
                    
                if not global_tasks[user_id][store_id]['is_running']: update_task(user_id, store_id, status='error', message='긴급 정지됨.')
                else: update_task(user_id, store_id, status='done', message='상점 내 모든 상품 하이브리드 작업 완료!')

        except Exception as e:
            update_task(user_id, store_id, status='error', message=f'서버 내부 오류: {str(e)}')
        finally:
            if user_id in global_tasks and store_id in global_tasks[user_id]:
                global_tasks[user_id][store_id]['is_running'] = False


# ==============================================================================
# 2. 상품 중복 체크용 멀티 엔진 (✨ 판매중 & 정밀 ISBN 검사 탑재 완료 ✨)
# ==============================================================================
global_dup_tasks = {}

def init_dup_task(user_id, store_id, store_name):
    if user_id not in global_dup_tasks: global_dup_tasks[user_id] = {}
    global_dup_tasks[user_id][store_id] = {
        'is_running': True, 'store_name': store_name,
        'status': 'start', 'message': '상점 정보 확인 중...',
        'current': 0, 'total': 0, 'duplicates': []
    }

def update_dup_task(user_id, store_id, status=None, message=None, current=None, total=None, duplicates=None):
    if user_id not in global_dup_tasks or store_id not in global_dup_tasks[user_id]: return
    t = global_dup_tasks[user_id][store_id]
    if status: t['status'] = status
    if message: t['message'] = message
    if current is not None: t['current'] = current
    if total is not None: t['total'] = total
    if duplicates is not None: t['duplicates'] = duplicates

def background_duplicate_check_job(app, store_id, user_id):
    with app.app_context():
        try:
            user = User.query.get(user_id)
            selected_key = ApiKey.query.filter_by(id=store_id, owner=user).first()
            if not selected_key:
                update_dup_task(user_id, store_id, status='error', message='상점 정보가 유효하지 않습니다.')
                return

            update_dup_task(user_id, store_id, status='info', message='네이버 API 인증 중...')
            token = get_naver_token(selected_key.client_id, selected_key.client_secret)
            if not token:
                update_dup_task(user_id, store_id, status='error', message='API 인증에 실패했습니다.')
                return

            update_dup_task(user_id, store_id, status='start', message='초고속 판매중(SALE) 상품 스캔 가동...')
            url = "https://api.commerce.naver.com/external/v1/products/search"
            headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
            
            all_products = []
            total_fetched = 0
            page = 1
            session = requests.Session()
            
            while True:
                if not global_dup_tasks[user_id][store_id]['is_running']: break
                
                payload = {"page": page, "size": 50, "orderType": "NO"}
                try: res = session.post(url, headers=headers, json=payload, timeout=10)
                except Exception:
                    update_dup_task(user_id, store_id, status='info', message=f'응답 지연... 재시도 중 ({page}페이지)')
                    time.sleep(2)
                    continue

                if res.status_code != 200:
                    update_dup_task(user_id, store_id, status='error', message=f'API 통신 실패 ({res.status_code})')
                    return
                    
                contents = res.json().get('contents', [])
                if not contents: break
                
                total_fetched += len(contents)
                
                for p in contents:
                    # ✨ 1. 스마트스토어 채널의 실제 상품 상태를 확인합니다.
                    channel_products = p.get('channelProducts', [{}])
                    c_prod = channel_products[0] if channel_products else {}
                    
                    channel_status = str(c_prod.get('statusType', '')).upper()
                    
                    # ✨ 2. 채널 상태가 비어 있다면 원상품의 상태를 가져옵니다.
                    if not channel_status:
                        channel_status = str(p.get('statusType', '')).upper()
                    
                    # ✨ 3. 오직 '판매중(SALE)' 상태인 상품만 중복 검사 대상에 추가합니다.
                    if channel_status == 'SALE':
                        all_products.append(p)
                    
                update_dup_task(user_id, store_id, status='progress', current=len(all_products), message=f'초고속 스캔 중... (스토어 전체: {total_fetched}개 탐색 / 판매중 대상: {len(all_products)}개 획득)')
                
                if len(contents) < 50: break
                page += 1
                time.sleep(0.2)

            if not global_dup_tasks[user_id][store_id]['is_running']:
                update_dup_task(user_id, store_id, status='error', message='사용자에 의해 검사가 강제 종료되었습니다.')
                return

            update_dup_task(user_id, store_id, status='info', message=f'스캔 완료! {len(all_products)}개 판매중 상품의 중복 정밀 분석 중...')
            
            seen_isbns = {}
            seen_names = {}
            duplicates = []
            
            for p in all_products:
                channel_products = p.get('channelProducts', [{}])
                c_prod = channel_products[0] if channel_products else {}
                
                name = str(c_prod.get('name') or p.get('name') or '이름 없는 상품')
                prod_id = str(c_prod.get('channelProductNo') or p.get('channelProductNo') or 'ID 없음')
                
                raw_isbn = str(c_prod.get('sellerManagementCode') or p.get('sellerManagementCode') or '').strip()
                
                dummy_isbns = ['isbn없음', '없음', 'none', 'null', '단품', '0', '-', '']
                is_valid_isbn = bool(raw_isbn and raw_isbn.replace(" ", "").lower() not in dummy_isbns)
                
                is_duplicate = False
                original_id = None
                
                # ✨ 핵심 수정: ISBN이 있으면 무조건 ISBN으로만 판단! (이름이 같아도 다른 책이면 넘어감)
                if is_valid_isbn:
                    if raw_isbn in seen_isbns:
                        is_duplicate = True
                        original_id = seen_isbns[raw_isbn]
                    else:
                        seen_isbns[raw_isbn] = prod_id
                
                # ✨ ISBN이 없는 상품에 한해서만 이름 검사 진행
                else:
                    clean_name = re.sub(r'[\s\-_\(\)\[\]]', '', name).lower().replace('복사본', '').replace('copy', '')
                    if clean_name in seen_names:
                        is_duplicate = True
                        original_id = seen_names[clean_name]
                    else:
                        seen_names[clean_name] = prod_id
                        
                if is_duplicate:
                    duplicates.append({
                        'name': name,
                        'isbn': raw_isbn if is_valid_isbn else 'ISBN없음',
                        'original_id': original_id,
                        'duplicate_id': prod_id
                    })
                    
            update_dup_task(user_id, store_id, status='done', current=len(all_products), total=len(all_products), duplicates=duplicates, message='중복 검사 완료!')

        except Exception as e:
            update_dup_task(user_id, store_id, status='error', message=f'서버 내부 오류: {str(e)}')
        finally:
            if user_id in global_dup_tasks and store_id in global_dup_tasks[user_id]:
                global_dup_tasks[user_id][store_id]['is_running'] = False


# ==============================================================================
# 3. 라우터 엔드포인트
# ==============================================================================
@store_bp.route('/')
@login_required
def index(): return render_template('store/index.html', store_count=len(current_user.api_keys))

@store_bp.route('/delete_isbn', methods=['GET'])
@login_required
def delete_isbn(): return render_template('store/delete_isbn.html', api_keys=current_user.api_keys)

@store_bp.route('/api/get_task_status', methods=['GET'])
@login_required
def get_task_status():
    user_id = current_user.id
    if user_id in global_tasks and global_tasks[user_id]: return jsonify({'status': 'active', 'tasks': global_tasks[user_id]})
    return jsonify({'status': 'empty'})

@store_bp.route('/api/start_task', methods=['POST'])
@login_required
def start_task():
    store_ids = request.form.getlist('selected_stores')
    if not store_ids: return jsonify({'success': False, 'message': '상점을 하나 이상 선택해주세요.'})
    user_id = current_user.id
    delete_mode = request.form.get('delete_mode', 'isbn')
    isbn_input = request.form.get('isbn_list', '')
    isbn_list = [isbn.strip() for isbn in isbn_input.replace(',', '\n').split('\n') if isbn.strip()] if delete_mode == 'isbn' else []
    app = current_app._get_current_object()
    for sid_str in store_ids:
        store_id = int(sid_str)
        key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        if not key: continue
        if user_id in global_tasks and store_id in global_tasks[user_id] and global_tasks[user_id][store_id]['is_running']: continue
        init_task(user_id, store_id, key.store_name, delete_mode)
        threading.Thread(target=background_delete_job, args=(app, store_id, delete_mode, isbn_list, user_id)).start()
    return jsonify({'success': True})

@store_bp.route('/api/stop_task', methods=['POST'])
@login_required
def stop_task():
    store_id = request.form.get('store_id') 
    user_id = current_user.id
    if user_id in global_tasks:
        if store_id == 'all':
            for sid in global_tasks[user_id]: global_tasks[user_id][sid]['is_running'] = False
        else:
            sid = int(store_id)
            if sid in global_tasks[user_id]: global_tasks[user_id][sid]['is_running'] = False
    return jsonify({'success': True})

@store_bp.route('/check_duplicates', methods=['GET'])
@login_required
def check_duplicates(): 
    return render_template('store/check_duplicates.html', api_keys=current_user.api_keys)

@store_bp.route('/api/start_dup_task', methods=['POST'])
@login_required
def start_dup_task():
    store_ids = request.form.getlist('selected_stores')
    if not store_ids: return jsonify({'success': False, 'message': '상점을 하나 이상 선택해주세요.'})
    user_id = current_user.id
    app = current_app._get_current_object()
    for sid_str in store_ids:
        store_id = int(sid_str)
        key = ApiKey.query.filter_by(id=store_id, owner=current_user).first()
        if not key: continue
        if user_id in global_dup_tasks and store_id in global_dup_tasks[user_id] and global_dup_tasks[user_id][store_id]['is_running']: continue
        init_dup_task(user_id, store_id, key.store_name)
        threading.Thread(target=background_duplicate_check_job, args=(app, store_id, user_id)).start()
    return jsonify({'success': True})

@store_bp.route('/api/get_dup_task_status', methods=['GET'])
@login_required
def get_dup_task_status():
    user_id = current_user.id
    if user_id in global_dup_tasks and global_dup_tasks[user_id]:
        return jsonify({'status': 'active', 'tasks': global_dup_tasks[user_id]})
    return jsonify({'status': 'empty'})

@store_bp.route('/api/stop_dup_task', methods=['POST'])
@login_required
def stop_dup_task():
    store_id = request.form.get('store_id') 
    user_id = current_user.id
    if user_id in global_dup_tasks:
        if store_id == 'all':
            for sid in global_dup_tasks[user_id]: global_dup_tasks[user_id][sid]['is_running'] = False
        else:
            sid = int(store_id)
            if sid in global_dup_tasks[user_id]: global_dup_tasks[user_id][sid]['is_running'] = False
    return jsonify({'success': True})

@store_bp.route('/api/suspend_duplicates', methods=['POST'])
@login_required
def suspend_duplicates():
    store_id = request.form.get('store_id')
    dup_ids_str = request.form.get('duplicate_ids', '')
    
    if not store_id or not dup_ids_str:
        return jsonify({'success': False, 'message': '필수 파라미터가 누락되었습니다.'})
        
    dup_ids = [cid.strip() for cid in dup_ids_str.split(',') if cid.strip()]
    if not dup_ids:
        return jsonify({'success': False, 'message': '중지할 유효한 상품 ID가 없습니다.'})
        
    user = User.query.get(current_user.id)
    key = ApiKey.query.filter_by(id=int(store_id), owner=user).first()
    if not key:
        return jsonify({'success': False, 'message': '상점 인증 키를 찾을 수 없습니다.'})
        
    token = get_naver_token(key.client_id, key.client_secret)
    if not token:
        return jsonify({'success': False, 'message': '네이버 API 인증에 실패했습니다. 키를 다시 확인해주세요.'})
        
    success_count = 0
    for i in range(0, len(dup_ids), 500):
        batch = dup_ids[i:i+500]
        res = suspend_products_in_bulk(token, batch)
        if '완료' in res or '불가' not in res: 
            success_count += len(batch)
            
    if success_count > 0:
        return jsonify({'success': True, 'message': f'총 {success_count}개의 중복 상품이 성공적으로 판매/전시 중지되었습니다!\n\n(※ 네이버 스마트스토어 센터에 반영되기까지 약 1~2분 소요될 수 있습니다)'})
    else:
        return jsonify({'success': False, 'message': '상품 중지 처리에 실패했습니다. (API 거절)'})
