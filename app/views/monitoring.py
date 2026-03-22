import os
import json
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from app import db
from app.models import User, MonitoredKeyword

monitoring_bp = Blueprint('monitoring', __name__)

global_mon_tasks = {}

def init_mon_task(user_id):
    global_mon_tasks[user_id] = {
        'is_running': True,
        'status': 'start',
        'message': '다른 서버(분석기)와 통신을 준비 중입니다...',
        'current': 0,
        'total': 0,
        'new_a_grade_count': 0, # 화면 갱신 트리거용
        'logs': []
    }

def update_mon_task(user_id, status=None, message=None, current=None, total=None, found_new_a_grade=False, log=None):
    if user_id not in global_mon_tasks: return
    t = global_mon_tasks[user_id]
    
    if status: t['status'] = status
    if message: t['message'] = message
    if current is not None: t['current'] = current
    if total is not None: t['total'] = total
    if found_new_a_grade: t['new_a_grade_count'] += 1
    
    if log:
        t['logs'].append(log)
        if len(t['logs']) > 50: t['logs'].pop(0)

def fetch_from_external_analyzer(keyword):
    """도서 분석기 서버로 원격 요청"""
    analyzer_url = os.environ.get('ANALYZER_API_URL')
    if not analyzer_url: raise ValueError("ANALYZER_API_URL 환경변수가 없습니다.")

    payload = {"keyword": keyword, "fetch_isbn": True}
    res = requests.post(analyzer_url, json=payload, timeout=15)
    
    if res.status_code == 200: return res.json()
    else: raise ConnectionError(f"응답 오류 (HTTP {res.status_code})")

def background_monitoring_job(app, keyword_list, user_id):
    with app.app_context():
        try:
            total_count = len(keyword_list)
            update_mon_task(user_id, status='progress', current=0, total=total_count, message='원격 서버를 통해 황금(A등급) 탐색 시작!')
            current_count = 0
            
            with ThreadPoolExecutor(max_workers=5) as executor:
                future_to_kw = {executor.submit(fetch_from_external_analyzer, kw): kw for kw in keyword_list}
                
                for future in as_completed(future_to_kw):
                    if not global_mon_tasks[user_id]['is_running']: break
                    
                    kw = future_to_kw[future]
                    current_count += 1
                    
                    try:
                        result = future.result()
                        grade = result.get('grade', 'C')
                        
                        if 'A' in grade:
                            # ✨ [핵심] 중복 없는 자동 등록 로직 ✨
                            existing = MonitoredKeyword.query.filter_by(user_id=user_id, keyword=kw).first()
                            
                            if not existing:
                                new_kw = MonitoredKeyword(
                                    user_id=user_id,
                                    keyword=kw,
                                    search_volume=result.get('search_volume', 0),
                                    rank_info=result.get('rank', '최상단 노출'),
                                    link=result.get('link', '#')
                                )
                                db.session.add(new_kw)
                                db.session.commit()
                                log_msg = {'type': 'success', 'target': kw, 'statusMsg': f"A등급! 테이블 자동 등록됨"}
                                update_mon_task(user_id, current=current_count, found_new_a_grade=True, log=log_msg)
                            else:
                                log_msg = {'type': 'warning', 'target': kw, 'statusMsg': "A등급 (이미 표에 존재함)"}
                                update_mon_task(user_id, current=current_count, log=log_msg)
                        else:
                            log_msg = {'type': 'secondary', 'target': kw, 'statusMsg': f"{grade[:1]}등급 패스"}
                            update_mon_task(user_id, current=current_count, log=log_msg)
                            
                    except Exception as e:
                        log_msg = {'type': 'danger', 'target': kw, 'statusMsg': "통신/분석 오류"}
                        update_mon_task(user_id, current=current_count, log=log_msg)
                        
            if not global_mon_tasks[user_id]['is_running']:
                update_mon_task(user_id, status='error', message='사용자에 의해 분석이 강제 중단되었습니다.')
            else:
                update_mon_task(user_id, status='done', message='모든 키워드 스캔이 완벽하게 종료되었습니다!')
                
        except Exception as e:
            update_mon_task(user_id, status='error', message=f'서버 통신 중 오류: {str(e)}')
        finally:
            if user_id in global_mon_tasks: global_mon_tasks[user_id]['is_running'] = False


@monitoring_bp.route('/')
@login_required
def index():
    api_url = os.environ.get('ANALYZER_API_URL', '')
    return render_template('monitoring/index.html', api_url_configured=bool(api_url))

@monitoring_bp.route('/api/start', methods=['POST'])
@login_required
def start_monitoring():
    user_id = current_user.id
    if user_id in global_mon_tasks and global_mon_tasks[user_id]['is_running']:
        return jsonify({'success': False, 'message': '이미 분석이 진행 중입니다.'})
        
    keywords_input = request.form.get('keywords', '')
    keyword_list = [k.strip() for k in keywords_input.replace(',', '\n').split('\n') if k.strip()]
    
    if not keyword_list: return jsonify({'success': False, 'message': '분석할 키워드를 입력해주세요.'})
    if not os.environ.get('ANALYZER_API_URL'): return jsonify({'success': False, 'message': 'ANALYZER_API_URL 환경변수가 없습니다.'})
        
    init_mon_task(user_id)
    app = current_app._get_current_object()
    threading.Thread(target=background_monitoring_job, args=(app, keyword_list, user_id)).start()
    return jsonify({'success': True})

@monitoring_bp.route('/api/status', methods=['GET'])
@login_required
def get_status():
    user_id = current_user.id
    if user_id in global_mon_tasks: return jsonify({'status': 'active', 'data': global_mon_tasks[user_id]})
    return jsonify({'status': 'empty'})

@monitoring_bp.route('/api/stop', methods=['POST'])
@login_required
def stop_monitoring():
    user_id = current_user.id
    if user_id in global_mon_tasks: global_mon_tasks[user_id]['is_running'] = False
    return jsonify({'success': True})

@monitoring_bp.route('/api/saved_keywords', methods=['GET'])
@login_required
def get_saved_keywords():
    """DB에 등록된 목록 반환"""
    keywords = MonitoredKeyword.query.filter_by(user_id=current_user.id).order_by(MonitoredKeyword.id.asc()).all()
    return jsonify({
        'success': True,
        'data': [{
            'id': k.id,
            'keyword': k.keyword,
            'search_volume': k.search_volume,
            'link': k.link
        } for k in keywords]
    })

@monitoring_bp.route('/api/delete_keyword', methods=['POST'])
@login_required
def delete_keyword():
    kw_id = request.form.get('id')
    kw = MonitoredKeyword.query.filter_by(id=kw_id, user_id=current_user.id).first()
    if kw:
        db.session.delete(kw)
        db.session.commit()
    return jsonify({'success': True})
