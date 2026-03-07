import requests
from bs4 import BeautifulSoup
import re
from datetime import datetime

def get_real_browser_headers():
    """실제 크롬 브라우저처럼 보이도록 헤더를 완벽하게 위장합니다."""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Sec-Ch-Ua': '"Chromium";v="122", "Not(A:Brand";v="24", "Google Chrome";v="122"',
        'Sec-Ch-Ua-Mobile': '?0',
        'Sec-Ch-Ua-Platform': '"Windows"',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1',
        'Upgrade-Insecure-Requests': '1'
    }

def parse_kyobo_html(html_text, detail_url, isbn_fallback=''):
    """서버에서 HTML을 직접 읽고 분석하여 도서 정보를 추출하는 공통 함수"""
    soup = BeautifulSoup(html_text, 'html.parser')
    
    # 1. 기본 정보 추출 (메타 태그 최우선 활용)
    title_meta = soup.find('meta', property='og:title')
    title = title_meta['content'] if title_meta else '제목 없음'
    # " - 교보문고" 텍스트가 붙어있다면 제거
    title = title.replace(' - 교보문고', '').strip()
    
    image_meta = soup.find('meta', property='og:image')
    image = image_meta['content'] if image_meta else ''
    
    # 2. 상세 정보 추출 (다양한 CSS 선택자 대비)
    publisher = '출판사 정보 없음'
    pub_tag = soup.select_one('a.btn_sub_link') or soup.select_one('.prod_info_text .name') or soup.select_one('.author .name')
    if pub_tag:
        publisher = pub_tag.text.strip()
        
    pub_date = '출판일 정보 없음'
    date_tag = soup.select_one('.prod_info_text .date')
    if date_tag:
        pub_date = date_tag.text.strip()
        
    price = '가격 정보 없음'
    price_tag = soup.select_one('.prod_price .val') or soup.select_one('.price .val')
    if price_tag:
        price = price_tag.text.strip() + "원"
        
    # 3. ISBN 추출 (상세 스펙 테이블 탐색)
    isbn = isbn_fallback
    spec_rows = soup.select('.tbl_row tbody tr')
    for row in spec_rows:
        th = row.select_one('th')
        if th and ('ISBN' in th.text or '상품코드' in th.text):
            td = row.select_one('td')
            if td:
                isbn = td.text.strip()
                break
                
    # 4. 목차 추출 (교보문고의 여러 목차 클래스명 대비)
    toc = '목차 정보가 제공되지 않습니다.'
    toc_tags = soup.select('.book_contents_item .info_text, #scrollSpyToc .info_text, .prod_info_detail .info_text')
    for tag in toc_tags:
        if tag.text.strip():
            toc = tag.text.strip()
            break

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
    try:
        response = requests.get(url, headers=get_real_browser_headers(), timeout=15)
        
        if response.status_code == 403:
            return {'success': False, 'message': '서버 IP가 교보문고 방화벽에 의해 차단되었습니다 (HTTP 403). 국내 서버 이전이 필요합니다.'}
            
        response.raise_for_status()
        return parse_kyobo_html(response.text, url)
        
    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'교보문고 서버 접근 중 오류가 발생했습니다: {str(e)}'}

def fetch_kyobo_book_info(isbn):
    """ISBN으로 교보문고를 검색한 뒤 HTML을 읽어오는 기능"""
    search_url = f"https://search.kyobobook.co.kr/search?keyword={isbn}"
    
    try:
        # 1. 검색 페이지 요청
        response = requests.get(search_url, headers=get_real_browser_headers(), timeout=15)
        
        if response.status_code == 403:
            return {'success': False, 'message': '서버 IP가 교보문고 방화벽에 의해 차단되었습니다 (HTTP 403). 국내 서버 이전이 필요합니다.'}
            
        response.raise_for_status()
        
        # 2. 정규식을 이용해 모든 형태의 교보문고 상품 코드(S + 숫자 13자리 내외) 추출
        product_id = None
        
        # 교보문고 내부 JSON 데이터에서 상품 코드 찾기
        match = re.search(r'"saleCmdtid":"(S\d+)"', response.text)
        if match:
            product_id = match.group(1)
        else:
            # HTML 텍스트 전체에서 바코드와 가장 가까이 있는 상품 코드 찾기
            match_alt = re.search(f'({isbn}).*?(S\d{{10,15}})', response.text, re.DOTALL)
            if match_alt:
                product_id = match_alt.group(2)
            else:
                # 무식하게 S로 시작하는 상품코드 형태 다 잡아내기
                all_s_codes = re.findall(r'S\d{13,14}', response.text)
                if all_s_codes:
                    product_id = all_s_codes[0]
                
        if not product_id:
            return {
                'success': False, 
                'message': '교보문고에서 해당 ISBN을 검색했지만 매칭되는 상품 코드를 찾지 못했습니다. https://context.reverso.net/translation/korean-english/%EC%A7%81%EC%A0%91+%EC%9E%85%EB%A0%A5%ED%95%A0 방식을 사용해 주세요.'
            }
            
        # 3. 상품 상세 페이지 접근 및 크롤링
        detail_url = f"https://product.kyobobook.co.kr/detail/{product_id}"
        detail_resp = requests.get(detail_url, headers=get_real_browser_headers(), timeout=15)
        detail_resp.raise_for_status()
        
        return parse_kyobo_html(detail_resp.text, detail_url, isbn_fallback=isbn)

    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'통신 오류가 발생했습니다. (IP 차단 또는 타임아웃): {str(e)}'}
