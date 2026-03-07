import os
from app import create_app

# Gunicorn이 이 'app' 변수를 찾아 실행합니다.
app = create_app()

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
