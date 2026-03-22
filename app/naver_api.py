import time
import base64
import requests
import bcrypt

def get_naver_token(client_id, client_secret):
    """네이버 커머스 API 인증 토큰 발급"""
    url = "https://api.commerce.naver.com/external/v1/oauth2/token"
    timestamp = str(int(time.time() * 1000))
    
    try:
        password = f"{client_id}_{timestamp}"
        hashed = bcrypt.hashpw(password.encode('utf-8'), client_secret.encode('utf-8'))
        signature = base64.b64encode(hashed).decode('utf-8')
    except Exception as e:
        print("Token Error:", e)
        return None

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': client_id,
        'timestamp': timestamp,
        'client_secret_sign': signature,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    res = requests.post(url, headers=headers, data=data)
    if res.status_code == 200:
        return res.json().get('access_token')
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
