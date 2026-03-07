import requests
from bs4 import BeautifulSoup
import re
import json
from datetime import datetime

def get_stealth_headers():
    """웹 서버가 봇(Bot)으로 인식하지 못하도록 실제 브라우저 헤더를 완벽히 모방합니다."""
    return {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7',
        'Accept-Language': 'ko-KR,ko;q=0.9,en-US;q=0.8,en;q=0.7',
        'Cache-Control': 'max-age=0',
        'Connection': 'keep-alive',
        'Upgrade-Insecure-Requests': '1',
        'Sec-Fetch-Dest': 'document',
        'Sec-Fetch-Mode': 'navigate',
        'Sec-Fetch-Site': 'none',
        'Sec-Fetch-User': '?1'
    }

def extract_from_json(html_text, detail_url, isbn_fallback=''):
    """교보문고 Next.js 페이지에 숨겨진 __NEXT_DATA__ JSON 상태 값을 직접 파싱하는 강력한 로직"""
    soup = BeautifulSoup(html_text, 'html.parser')
    
    # 1. 초기값 설정 (실패 시 반환할 기본 텍스트)
    title = '제목 없음'
    image = ''
    publisher = '출판사 정보 없음'
    isbn = isbn_fallback
    price = '가격 정보 없음'
    pub_date = '출판일 정보 없음'
    toc = '목차 정보가 제공되지 않습니다.'
    reg_date = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    try:
        # 2. 가장 확실한 Open Graph 메타 태그 우선 수집 (SEO용이므로 비교적 정확함)
        title_meta = soup.find('meta', property='og:title')
        if title_meta:
            title = title_meta['content'].replace(' - 교보문고', '').strip()
            
        image_meta = soup.find('meta', property='og:image')
        if image_meta:
            image = image_meta['content']
            
        # 3. Next.js의 전체 초기 상태 데이터 (JSON) 확보
        next_data_script = soup.find('script', id='__NEXT_DATA__')
        
        if next_data_script and next_data_script.string:
            # JSON 문자열 전체에서 정규식(Regex)을 사용하여 필요한 키(Key) 값의 밸류를 추출
            json_str = next_data_script.string
            
            # 출판사 찾기 ("pbcmNm":"출판사이름")
            pub_match = re.search(r'"pbcmNm":"([^"]+)"', json_str)
            if pub_match:
                publisher = pub_match.group(1)
                
            # 가격 찾기 ("prc":15000 또는 "spprc":13500)
            price_match = re.search(r'"spprc":(\d+)', json_str)
            if price_match:
                price = format(int(price_match.group(1)), ',') + "원"
                
            # 출판일 찾기 ("rlseDate":"20231025" 등)
            date_match = re.search(r'"rlseDate":"(\d{4})(\d{2})(\d{2})"', json_str)
            if date_match:
                pub_date = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}"
                
            # 목차 찾기 ("toc":"목차내용...")
            toc_match = re.search(r'"toc":"(.*?)"(?:,|})', json_str)
            if toc_match:
                # JSON 이스케이프 문자(\n, \r, \t 등)를 실제 텍스트로 복원
                raw_toc = toc_match.group(1)
                toc = raw_toc.encode('utf-8').decode('unicode_escape').replace('\r', '').strip()
                if not toc:
                    toc = '목차가 비어있습니다.'
                    
            # 상품 상세 코드에서 ISBN 다시 한 번 검증
            isbn_match = re.search(r'"cmdtCode":"(\d{13})"', json_str)
            if isbn_match:
                isbn = isbn_match.group(1)
                
        else:
            # __NEXT_DATA__가 없을 경우를 대비한 최후의 HTML 기반 Fallback
            pub_tag = soup.select_one('.prod_info_text .name')
            if pub_tag: publisher = pub_tag.text.strip()
            date_tag = soup.select_one('.prod_info_text .date')
            if date_tag: pub_date = date_tag.text.strip()
            price_tag = soup.select_one('.prod_price .val')
            if price_tag: price = price_tag.text.strip() + "원"
            toc_tag = soup.select_one('.book_contents_item .info_text')
            if toc_tag: toc = toc_tag.text.strip()

    except Exception as e:
        print(f"JSON 파싱 오류 발생: {e}")

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
    """사용자가 입력한 URL의 페이지 전체 HTML을 다운받아 JSON 파싱 함수로 넘깁니다."""
    try:
        response = requests.get(url, headers=get_stealth_headers(), timeout=15)
        
        # 교보문고 방화벽 차단 확인 (가장 중요한 예외 처리)
        if response.status_code == 403:
            return {'success': False, 'message': '교보문고 보안 시스템이 Railway(해외 IP)의 접속을 강제 차단했습니다 (403). 이 기능은 반드시 국내 서버 또는 내 PC에서 실행해야 합니다.'}
            
        response.raise_for_status()
        return extract_from_json(response.text, url)
        
    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'교보문고 서버 통신 오류 (IP 차단 의심): {str(e)}'}

def fetch_kyobo_book_info(isbn):
    """ISBN으로 교보문고를 검색하여 상품 ID를 찾아낸 뒤, 해당 상세페이지로 이동해 데이터를 긁어옵니다."""
    search_url = f"https://search.kyobobook.co.kr/search?keyword={isbn}"
    
    try:
        # 1. 검색 페이지 요청
        response = requests.get(search_url, headers=get_stealth_headers(), timeout=15)
        
        if response.status_code == 403:
            return {'success': False, 'message': '교보문고 보안 시스템이 Railway(해외 IP)의 접속을 강제 차단했습니다 (403). 이 기능은 반드시 국내 서버 또는 내 PC에서 실행해야 합니다.'}
            
        response.raise_for_status()
        
        # 2. 검색 페이지의 숨겨진 데이터에서 교보문고 자체 상품 코드(S숫자) 찾기
        product_id = None
        match = re.search(r'"saleCmdtid":"(S\d+)"', response.text)
        if match:
            product_id = match.group(1)
        else:
            # ISBN(바코드) 주변에 있는 상품 코드를 강제로 탐색하는 정규식
            match_alt = re.search(f'({isbn}).*?(S\d{{10,15}})', response.text, re.DOTALL)
            if match_alt:
                product_id = match_alt.group(2)
                
        if not product_id:
            return {'success': False, 'message': '교보문고 검색에서 해당 ISBN과 매칭되는 도서를 찾지 못했습니다. https://context.reverso.net/translation/korean-english/%EC%A7%81%EC%A0%91+%EC%9E%85%EB%A0%A5%ED%95%A0 탭을 이용해 주세요.'}
            
        # 3. 상품 상세 페이지 URL 생성 후 파싱 로직 호출
        detail_url = f"https://product.kyobobook.co.kr/detail/{product_id}"
        detail_resp = requests.get(detail_url, headers=get_stealth_headers(), timeout=15)
        detail_resp.raise_for_status()
        
        return extract_from_json(detail_resp.text, detail_url, isbn_fallback=isbn)

    except requests.exceptions.RequestException as e:
        return {'success': False, 'message': f'서버 연결 지연 또는 차단 발생: {str(e)}'}
