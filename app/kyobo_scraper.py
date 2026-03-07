import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

def parse_kyobo_html(html_text, detail_url, isbn_fallback=''):
    """서버에서 HTML을 직접 읽고 분석하여 도서 정보를 추출하는 공통 함수"""
    soup = BeautifulSoup(html_text, 'html.parser')
    
    # 기본 메타 태그 정보
    title_meta = soup.find('meta', property='og:title')
    title = title_meta['content'] if title_meta else '제목 없음'
    
    image_meta = soup.find('meta', property='og:image')
    image = image_meta['content'] if image_meta else ''
    
    # 출판사 및 출판일 추출
    publisher_tag = soup.select_one('.prod_info_text .name, .author .name')
    publisher = publisher_tag.text.strip() if publisher_tag else '출판사 정보 없음'
    
    pub_date_tag = soup.select_one('.prod_info_text .date')
    pub_date = pub_date_tag.text.strip() if pub_date_tag else '출판일 정보 없음'
    
    # 가격 추출
    price_tag = soup.select_one('.prod_price .val')
    price = price_tag.text.strip() if price_tag else '가격 정보 없음'
    
    # ISBN 추출 (HTML의 상세 스펙 테이블에서 조회)
    isbn = isbn_fallback
    spec_rows = soup.select('.tbl_row tbody tr')
    for row in spec_rows:
        th = row.select_one('th')
        if th and ('ISBN' in th.text or '상품코드' in th.text):
            td = row.select_one('td')
            if td:
                isbn = td.text.strip()
                break
                
    # 목차 추출
    toc = '목차 정보가 제공되지 않습니다.'
    toc_tag = soup.select_one('.book_contents_item .info_text')
    if toc_tag:
        toc = toc_tag.text.strip()
    else:
        # 다른 구조의 목차 영역 탐색
        alt_toc = soup.select_one('#scrollSpyToc .info_text')
        if alt_toc:
            toc = alt_toc.text.strip()

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

def fetch_kyobo_by_url(url):
    """사용자가 직접 입력한 교보문고 URL의 HTML을 읽어오는 기능"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    try:
        response = requests.get(url, headers=headers, timeout=10)
        response.raise_for_status()
        return parse_kyobo_html(response.text, url)
    except Exception as e:
        return {'success': False, 'message': f'URL HTML 파싱 중 오류가 발생했습니다: {str(e)}'}

def fetch_kyobo_book_info(isbn):
    """ISBN으로 교보문고를 검색한 뒤 HTML을 읽어오는 기능"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    search_url = f"https://search.kyobobook.co.kr/search?keyword={isbn}"
    
    try:
        response = requests.get(search_url, headers=headers, timeout=10)
        response.raise_for_status()
        
        # 교보문고 검색 결과 페이지의 숨겨진 Next.js 데이터에서 상품 코드 추출
        product_id = None
        match = re.search(r'"saleCmdtid":"(S\d+)"', response.text)
        if match:
            product_id = match.group(1)
        else:
            # 바코드(ISBN) 필드와 일치하는 상품 코드를 다시 한번 정밀 탐색
            match_alt = re.search(f'"barcode":"{isbn}".*?"saleCmdtid":"(S\d+)"', response.text)
            if match_alt:
                product_id = match_alt.group(1)
                
        if not product_id:
            return {'success': False, 'message': '교보문고에서 해당 ISBN의 도서를 찾을 수 없습니다. (URL 직접 입력을 사용해보세요)'}
            
        # 상품 상세 페이지 URL 생성 및 HTML 파싱 함수 호출
        detail_url = f"https://product.kyobobook.co.kr/detail/{product_id}"
        detail_resp = requests.get(detail_url, headers=headers, timeout=10)
        detail_resp.raise_for_status()
        
        return parse_kyobo_html(detail_resp.text, detail_url, isbn_fallback=isbn)

    except Exception as e:
        return {'success': False, 'message': f'크롤링 중 오류가 발생했습니다: {str(e)}'}
