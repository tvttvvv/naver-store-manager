import os
from app import create_app, db
from app.models import User
from werkzeug.security import generate_password_hash

# Gunicorn이 이 'app' 변수를 찾아 실행합니다.
app = create_app()

# 서버 시작 시 기본 관리자 계정 상태 확인 및 비밀번호 강제 초기화
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

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
