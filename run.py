import os
from app import create_app

# Gunicorn이 찾을 수 있도록 app 객체를 전역으로 생성합니다.
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
