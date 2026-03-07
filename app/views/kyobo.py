from flask import Blueprint, render_template, request, jsonify
from flask_login import login_required
from app.kyobo_scraper import fetch_kyobo_book_info, fetch_kyobo_by_url

kyobo_bp = Blueprint('kyobo', __name__)

@kyobo_bp.route('/fetch_book', methods=['GET', 'POST'])
@login_required
def fetch_book():
    if request.method == 'POST':
        search_type = request.form.get('search_type', 'isbn')
        input_value = request.form.get('input_value', '').strip()
        
        if not input_value:
            return jsonify({'success': False, 'message': '값을 입력해주세요.'})
            
        if search_type == 'url':
            # URL을 직접 읽어서 HTML을 파싱하는 방식
            if 'kyobobook.co.kr' not in input_value:
                return jsonify({'success': False, 'message': '올바른 교보문고 URL을 입력해주세요.'})
            book_info = fetch_kyobo_by_url(input_value)
            
        else:
            # 기존 ISBN 검색 방식
            book_info = fetch_kyobo_book_info(input_value)
            
        return jsonify(book_info)
        
    return render_template('kyobo/search.html')
