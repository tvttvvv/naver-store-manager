from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.kyobo_scraper import fetch_kyobo_book_info

kyobo_bp = Blueprint('kyobo', __name__)

@kyobo_bp.route('/fetch_book', methods=['GET', 'POST'])
@login_required
def fetch_book():
    if request.method == 'POST':
        isbn = request.form.get('isbn', '').strip()
        
        if not isbn:
            return jsonify({'success': False, 'message': 'ISBN을 입력해주세요.'})
            
        # 교보문고 크롤러 호출
        book_info = fetch_kyobo_book_info(isbn)
        return jsonify(book_info)
        
    return render_template('kyobo/search.html')
