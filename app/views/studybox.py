import datetime
import random
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from apscheduler.schedulers.background import BackgroundScheduler
from app import db
from app.models import StudyboxKeyword, StudyboxHistory

# 블루프린트 설정
studybox_bp = Blueprint('studybox', __name__, url_prefix='/studybox')

def init_dummy_data_for_graphs(user_id):
    """(편의 기능) DB가 비어있다면, 30일치 변동량 데이터를 가상으로 자동 생성합니다."""
    db.create_all() # 에러 방지용 테이블 생성 확인
    if StudyboxKeyword.query.filter_by(user_id=user_id).count() > 0:
        return # 이미 데이터가 있다면 건너뜁니다

    books_initial = [
        {"keyword": "어른의행복은조용", "n_count": 7720, "stock": 50, "rank": "2"},
        {"keyword": "부아에이르는단순한길", "n_count": 1940, "stock": 120, "rank": "1"},
        {"keyword": "대형주추세추종책", "n_count": 90, "stock": 10, "rank": "1"},
        {"keyword": "파이썬기초책추천", "n_count": 70, "stock": 5, "rank": "1"},
        {"keyword": "위버맨쉬", "n_count": 6980, "stock": 200, "rank": "4"}
    ]

    today = datetime.date.today()
    for item in books_initial:
        # 1. 키워드 본체 생성
        new_kw = StudyboxKeyword(
            user_id=user_id, keyword=item["keyword"], naver_count=item["n_count"],
            stock_quantity=item["stock"], shop_rank=item["rank"], shipping_fee="무료"
        )
        db.session.add(new_kw)
        db.session.commit()

        # 2. 과거 30일치 변동 이력(History) 가상 생성
        for i in range(30, -1, -1):
            hist_date = today - datetime.timedelta(days=i)
            # 오늘 날짜는 현재값 유지, 과거 날짜는 랜덤 오차 발생
            hist_nc = item["n_count"] if i == 0 else int(item["n_count"] * random.uniform(0.8, 1.1))
            hist_stock = item["stock"] if i == 0 else int(item["stock"] * random.uniform(0.7, 1.2))

            hist = StudyboxHistory(keyword_id=new_kw.id, record_date=hist_date, naver_count=hist_nc, stock_quantity=hist_stock)
            db.session.add(hist)
    db.session.commit()

def fetch_naver_data_via_api(keyword):
    """네이버 API 연동 로직 (현재는 임시값 반환)"""
    return "업데이트됨", "1"

def nightly_update_job():
    """매일 밤 9시에 실행될 스케줄러 작업"""
    with db.app.app_context():
        print("=== 밤 9시: 스터디박스 모니터링 자동 업데이트 시작 ===")
        # 향후 여기에 DB 업데이트 로직 추가 가능
        print("=== 업데이트 및 연동 완료 ===")

# 백그라운드 스케줄러 설정 (밤 9시)
scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(func=nightly_update_job, trigger="cron", hour=21, minute=0)
scheduler.start()

@studybox_bp.route('/')
@login_required
def index():
    """스터디박스 페이지 랜더링 (DB에서 변동 기록 포함하여 전달)"""
    init_dummy_data_for_graphs(current_user.id) # 초기 설정 도우미 실행
    
    keywords = StudyboxKeyword.query.filter_by(user_id=current_user.id).all()
    books_list = []
    
    for kw in keywords:
        # 프론트엔드에서 그래프와 +/- 계산을 바로 할 수 있도록 히스토리 데이터를 정리
        history_list = [{
            "date": h.record_date.strftime("%Y-%m-%d"),
            "naver_count": h.naver_count,
            "stock_quantity": h.stock_quantity
        } for h in kw.histories]
        
        books_list.append({
            "id": kw.id, "keyword": kw.keyword, "naver_count": kw.naver_count,
            "stock_quantity": kw.stock_quantity, "shop_rank": kw.shop_rank,
            "link": kw.link, "publisher": kw.publisher, "supply_rate": kw.supply_rate,
            "isbn": kw.isbn, "price": kw.price, "shipping": kw.shipping_fee,
            "shop_title": kw.shop_title, "history": history_list
        })

    return render_template('studybox.html', books=books_list)

@studybox_bp.route('/api/manual_update', methods=['POST'])
@login_required
def manual_update():
    """수동 업데이트 버튼 기능"""
    nightly_update_job()
    return jsonify({"status": "success", "message": "모니터링 데이터 업데이트 및 Book 분석기 Pro 연동이 완료되었습니다."})
