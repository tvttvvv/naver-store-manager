import datetime
from flask import Blueprint, jsonify
from apscheduler.schedulers.background import BackgroundScheduler

studybox_bp = Blueprint('studybox', __name__, url_prefix='/studybox')

# 임시 데이터 DB
books_data = [
    {"id": 1, "keyword": "어른의행복은조용", "naver_count": "7720", "shop_rank": "2", "link": "", "publisher": "", "supply_rate": "", "isbn": "", "price": "", "shipping": "무료", "shop_title": ""},
    {"id": 2, "keyword": "부아에이르는단순한길", "naver_count": "1940", "shop_rank": "1", "link": "", "publisher": "", "supply_rate": "", "isbn": "", "price": "", "shipping": "", "shop_title": ""},
    {"id": 3, "keyword": "대형주추세추종책", "naver_count": "90", "shop_rank": "1", "link": "", "publisher": "", "supply_rate": "", "isbn": "", "price": "", "shipping": "", "shop_title": ""},
    {"id": 4, "keyword": "파이썬기초책추천", "naver_count": "70", "shop_rank": "1", "link": "", "publisher": "", "supply_rate": "", "isbn": "", "price": "", "shipping": "", "shop_title": ""},
    {"id": 5, "keyword": "위버맨쉬", "naver_count": "6980", "shop_rank": "4", "link": "", "publisher": "", "supply_rate": "", "isbn": "", "price": "", "shipping": "", "shop_title": ""}
]

def fetch_naver_data_via_api(keyword):
    """네이버 API 연동 로직 (임시)"""
    return "업데이트됨", "1"

def send_to_book_analyzer_pro(updated_data):
    """Book 분석기 Pro 연동 로직"""
    print(f"[{datetime.datetime.now()}] Book 분석기 Pro 연동 완료")

def nightly_update_job():
    print("=== 밤 9시: 스터디박스 모니터링 자동 업데이트 시작 ===")
    updated_info = []
    for book in books_data:
        new_count, new_rank = fetch_naver_data_via_api(book["keyword"])
        book["naver_count"] = new_count
        book["shop_rank"] = new_rank
        updated_info.append(book)
    send_to_book_analyzer_pro(updated_info)
    print("=== 업데이트 및 연동 완료 ===")

# 스케줄러 설정
scheduler = BackgroundScheduler(timezone="Asia/Seoul")
scheduler.add_job(func=nightly_update_job, trigger="cron", hour=21, minute=0)
scheduler.start()

@studybox_bp.route('/api/data', methods=['GET'])
def get_data():
    """프론트엔드에 데이터를 전달하는 API"""
    return jsonify({"books": books_data})

@studybox_bp.route('/api/manual_update', methods=['POST'])
def manual_update():
    """수동 업데이트 버튼 실행 시 호출"""
    nightly_update_job()
    return jsonify({"status": "success", "message": "모니터링 데이터 업데이트 및 Book 분석기 Pro 연동이 완료되었습니다."})
