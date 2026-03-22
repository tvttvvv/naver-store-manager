import requests
from bs4 import BeautifulSoup
import time
import hmac
import hashlib
import base64
import urllib.parse
import os
import re

def get_ad_header(access_key, secret_key, customer_id, method, uri):
    timestamp = str(int(time.time() * 1000))
    message = f"{timestamp}.{method}.{uri}"
    signature_hash = hmac.new(secret_key.encode('utf-8'), message.encode('utf-8'), hashlib.sha256).digest()
    signature = base64.b64encode(signature_hash).decode()
    
    return {
        "Content-Type": "application/json; charset=UTF-8",
        "X-Timestamp": timestamp,
        "X-API-KEY": access_key,
        "X-Customer": str(customer_id),
        "X-Signature": signature
    }

def analyze_keyword(keyword):
    """키워드를 분석하여 A등급(황금) 여부와 검색량, 판매처 수를 반환합니다."""
    # 환경변수에서 키 가져오기 (.env 파일에 세팅 필요)
    AD_ACCESS_KEY = os.environ.get("ACCESS_KEY", "")
    AD_SECRET_KEY = os.environ.get("SECRET_KEY", "")
    AD_CUSTOMER_ID = os.environ.get("CUSTOMER_ID", "")

    search_volume = 0
    if AD_ACCESS_KEY and AD_SECRET_KEY and AD_CUSTOMER_ID:
        try:
            uri = '/keywordstool'
            clean_keyword = keyword.replace(" ", "")
            params = {'hintKeywords': clean_keyword, 'showDetail': '1'}
            headers = get_ad_header(AD_ACCESS_KEY, AD_SECRET_KEY, AD_CUSTOMER_ID, 'GET', uri)
            res = requests.get(f"https://api.naver.com{uri}", params=params, headers=headers, timeout=5)
            
            if res.status_code == 200:
                data_list = res.json().get('keywordList', [])
                for item in data_list:
                    api_kw = item.get('relKeyword', '').replace(" ", "")
                    if api_kw.lower() == clean_keyword.lower():
                        pc = item.get('monthlyPcQcCnt', 0)
                        mo = item.get('monthlyMobileQcCnt', 0)
                        if isinstance(pc, str): pc = 0
                        if isinstance(mo, str): mo = 0
                        search_volume = pc + mo
                        break
        except Exception as e:
            pass # 광고 API 에러 무시

    pc_link = f"https://search.naver.com/search.naver?where=nexearch&query={urllib.parse.quote(keyword)}"
    grade = ""
    reason = ""
    seller_count = 0
    rank_info = "-"

    try:
        req_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
            "Accept-Language": "ko-KR,ko;q=0.9",
            "Referer": "https://www.naver.com/"
        }
        html_res = requests.get(pc_link, headers=req_headers, timeout=5)
        soup = BeautifulSoup(html_res.text, "html.parser")
        
        main_pack = soup.find(id="main_pack")
        
        if not main_pack:
            grade = "C"
            reason = "검색결과 없음"
        else:
            main_text = main_pack.get_text(separator=" ", strip=True)
            match = re.search(r'(판매처|판매자|판매몰|쇼핑몰)\s*([\d,]+)', main_text)
            
            if match:
                seller_word = match.group(1)
                seller_count = int(match.group(2).replace(',', ''))
                grade = "B"
                reason = f"대표카드 묶임 ({seller_count}개 판매처)"
            else:
                is_book_card_exist = False
                # 도서 카드가 메인팩에 단독 노출되는지 확인
                if main_pack.find(class_=re.compile(r'cs_book|sp_book')):
                    is_book_card_exist = True
                else:
                    for bx in main_pack.find_all("div", class_="api_subject_bx"):
                        title_tag = bx.find(class_=re.compile(r'api_title|title'))
                        if title_tag:
                            title_text = title_tag.get_text(strip=True).replace(" ", "")
                            if "도서" in title_text or "책정보" in title_text:
                                is_book_card_exist = True
                                break
                
                if is_book_card_exist:
                    grade = "A" # ✨ 황금 키워드!
                    reason = "단독 노출 (경쟁 적음)"
                    rank_info = "최상단 노출"
                else:
                    grade = "C"
                    reason = "도서 영역 없음"

    except Exception as e:
        grade = "Error"
        reason = "스크래핑 실패"

    return {
        "keyword": keyword,
        "search_volume": search_volume,
        "seller_count": seller_count if seller_count > 0 else "-",
        "grade": grade,
        "reason": reason,
        "rank": rank_info,
        "link": pc_link
    }
