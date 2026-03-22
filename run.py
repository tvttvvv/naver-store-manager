import os
import requests
from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

# Gunicorn이 이 'app' 변수를 찾아 실행합니다.
app = create_app()

def print_server_ip():
    """Railway 서버의 현재 외부 IP를 확인하여 로그에 출력합니다."""
    try:
        # 외부 IP 확인 API 호출
        ip = requests.get('https://api.ipify.org', timeout=5).text
        print("\n" + "="*60)
        print(f"🌍 [필독] 현재 Railway 서버의 외부 IP 주소: {ip}")
        print("👉 이 IP 주소를 복사해서 [네이버 커머스 API 센터 -> 애플리케이션 상세 -> API 호출 허용 IP]에 추가해주세요!")
        print("="*60 + "\n")
    except Exception as e:
        print(f"\n[❌] 서버 IP 확인 실패: {e}\n")

# 서버 시작 시 기본 로직 (DB 초기화 및 IP 출력)
with app.app_context():
    admin_user = User.query.filter_by(username='admin').first()
    hashed_password = generate_password_hash('admin1234', method='pbkdf2:sha256')
    
    if not admin_user:
        # 계정이 없으면 새로 생성
        new_admin = User(username='admin', password_hash=hashed_password)
        db.session.add(new_admin)
        print("초기 관리자 계정이 생성되었습니다. (ID: admin / PW: admin1234)")
    else:
        # 이미 계정이 있다면 비밀번호를 강제로 다시 초기화 (로그인 오류 해결용)
        admin_user.password_hash = hashed_password
        print("기존 관리자 계정의 비밀번호가 'admin1234'로 강제 초기화되었습니다.")
        
    db.session.commit()
    
    # 네이버 API 화이트리스트 등록용 IP 출력 실행
    print_server_ip()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
