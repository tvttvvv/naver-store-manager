import time
import base64
import requests
import bcrypt

def get_naver_token(client_id, client_secret):
    """네이버 커머스 API 인증 토큰 발급"""
    url = "https://api.commerce.naver.com/external/v1/oauth2/token"
    timestamp = str(int(time.time() * 1000))
    
    # 1. 입력된 키값의 앞뒤 공백(띄어쓰기, 줄바꿈) 자동 제거 (휴먼 에러 방지)
    clean_client_id = client_id.strip()
    clean_client_secret = client_secret.strip()
    
    try:
        # 네이버 커머스 공식 암호화 규격 적용
        password = f"{clean_client_id}_{timestamp}"
        hashed = bcrypt.hashpw(password.encode('utf-8'), clean_client_secret.encode('utf-8'))
        signature = base64.b64encode(hashed).decode('utf-8')
    except Exception as e:
        print(f"\n[❌ API 토큰 오류] 서명 생성 실패 (Secret 키 형식이 잘못되었습니다): {e}\n")
        return None

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': clean_client_id,
        'timestamp': timestamp,
        'client_secret_sign': signature,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    res = requests.post(url, headers=headers, data=data)
    
    # 2. 결과 처리 및 로그 상세 출력
    if res.status_code == 200:
        print("\n[✅ API 인증 성공] 네이버 토큰 발급 완료\n")
        return res.json().get('access_token')
    else:
        print(f"\n[❌ API 인증 실패] 네이버가 토큰 발급을 거부했습니다.")
        print(f"- HTTP 상태 코드: {res.status_code}")
        print(f"- 네이버 상세 에러 메시지: {res.text}\n")
        return None

def find_product_by_isbn(token, isbn):
    """판매자 관리코드 또는 상품명에 ISBN이 포함된 상품의 원본번호와 채널번호 반환"""
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    # 1차 시도: 판매자 관리코드(sellerManagementCode) 기준 검색
    payload = {"page": 1, "size": 50, "sellerManagementCode": isbn}
    res = requests.post(url, headers=headers, json=payload)
    
    if res.status_code == 200:
        contents = res.json().get('contents', [])
        if contents:
            p = contents[0]
            origin_no = p.get('originProductNo')
            channel_no = p.get('channelProducts', [{}])[0].get('channelProductNo')
            return origin_no, channel_no

    # 2차 시도: 상품명(productName) 기준 검색 (1차 실패 시)
    payload_name = {"page": 1, "size": 50, "productName": isbn}
    res_name = requests.post(url, headers=headers, json=payload_name)
    if res_name.status_code == 200:
        contents = res_name.json().get('contents', [])
        if contents:
            p = contents[0]
            origin_no = p.get('originProductNo')
            channel_no = p.get('channelProducts', [{}])[0].get('channelProductNo')
            return origin_no, channel_no
            
    return None, None

def delete_product(token, origin_no, channel_no):
    """상품 삭제 시도, 판매이력 등의 이유로 실패 시 상태 변경으로 우회 처리"""
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    
    # 1. 완전 삭제 시도 (DELETE)
    if origin_no:
        delete_url = f"https://api.commerce.naver.com/external/v1/products/{origin_no}"
        del_res = requests.delete(delete_url, headers=headers)
        if del_res.status_code == 200:
            return "완전 삭제 완료"

    # 2. 삭제 실패 시, 판매/전시 중지 처리 (PUT)
    if channel_no:
        status_url = "https://api.commerce.naver.com/external/v2/products/channel-products/status"
        payload = {
            "channelProducts": [
                {
                    "channelProductNo": channel_no,
                    "saleStateType": "SUSPEND",
                    "displayStateType": "SUSPEND"
                }
            ]
        }
        status_res = requests.put(status_url, headers=headers, json=payload)
        if status_res.status_code == 200:
            return "판매/전시 중지 처리 완료 (삭제 불가 상품)"
            
    return "삭제 및 중지 처리 실패 (API 오류)"

def fetch_all_products(token):
    """중복 체크를 위한 전체 상품 수집"""
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json'
    }
    all_products = []
    page = 1
    
    while True:
        payload = {"page": page, "size": 50, "orderType": "NO"}
        res = requests.post(url, headers=headers, json=payload)
        if res.status_code != 200:
            break
            
        contents = res.json().get('contents', [])
        if not contents:
            break
            
        all_products.extend(contents)
        if len(contents) < 50:
            break
            
        page += 1
        time.sleep(0.3) # API 호출 속도 조절
        
    return all_products
