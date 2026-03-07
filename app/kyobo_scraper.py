import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

def fetch_kyobo_book_info(isbn):
    """
    ISBN을 사용하여 교보문고에서 도서 정보를 크롤링합니다.
    (이름, 이미지, 출판사, ISBN, 가격, 출판일, 목차, 등록일)
    """
    # 봇 차단을 우회하기 위한 브라우저 헤더 위장
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    # 1. ISBN으로 교보문고 검색 (내부 검색 API 활용 또는 일반 검색)
    search_url = f"https://search.kyobobook.co.kr/search?keyword={isbn}"
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # 실제로는 교보문고 검색 페이지가 JS로 렌더링되므로, 
        # HTML 텍스트 내에서 상품 상세 페이지 URL을 정규식으로 찾습니다.
        product_id_match = re.search(r'S\d{14}', response.text)
        
        if not product_id_match:
            return {'success': False, 'message': '교보문고에서 해당 ISBN의 도서를 찾을 수 없습니다.'}
            
        product_id = product_id_match.group(0)
        
        # 2. 상품 상세 페이지 접근
        detail_url = f"https://product.kyobobook.co.kr/detail/{product_id}"
        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
        detail_resp.raise_for_status()
        
        soup = BeautifulSoup(detail_resp.text, 'html.parser')
        
        # 3. 데이터 추출 (교보문고의 일반적인 메타 태그 및 HTML 구조 기반)
        # 메타 태그에서 기본 정보 추출
        title = soup.find('meta', property='og:title')
        title = title['content'] if title else '제목 없음'
        
        image = soup.find('meta', property='og:image')
        image = image['content'] if image else ''
        
        # 본문에서 상세 정보 추출
        publisher_tag = soup.select_one('.prod_info_text .name')
        publisher = publisher_tag.text.strip() if publisher_tag else '출판사 정보 없음'
        
        price_tag = soup.select_one('.prod_price .val')
        price = price_tag.text.strip() if price_tag else '가격 정보 없음'
        
        pub_date_tag = soup.select_one('.prod_info_text .date')
        pub_date = pub_date_tag.text.strip() if pub_date_tag else '출판일 정보 없음'
        
        # 목차 추출 (보통 클래스명이나 id로 매핑됨)
        toc_tag = soup.select_one('.book_contents_item .info_text')
        toc = toc_tag.text.strip() if toc_tag else '목차 정보가 제공되지 않습니다.'
        
        # 크롤링을 수행한 현재 시간을 '등록일(조회일)'로 사용
        reg_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

        return {
            'success': True,
            'title': title,
            'image': image,
            'publisher': publisher,
            'isbn': isbn,
            'price': price,
            'pub_date': pub_date,
            'toc': toc,
            'reg_date': reg_date,
            'detail_url': detail_url
        }

    except Exception as e:
        return {'success': False, 'message': f'크롤링 중 오류가 발생했습니다: {str(e)}'}
