import time
import bcrypt
import jwt
import requests

def get_naver_token(client_id, client_secret):
    timestamp = str(int((time.time() - 3) * 1000))
    pwd = f"{client_id}_{timestamp}"
    hashed_pwd = bcrypt.hashpw(pwd.encode('utf-8'), client_secret.encode('utf-8'))
    
    client_secret_sign = jwt.encode({"client_id": client_id, "timestamp": timestamp}, client_secret, algorithm="HS256")
    
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': client_id,
        'timestamp': timestamp,
        'client_secret_sign': client_secret_sign,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    response = requests.post('https://api.commerce.naver.com/external/v1/oauth2/token', headers=headers, data=data)
    if response.status_code == 200:
        return response.json().get('access_token')
    return None

def find_product_by_isbn(access_token, isbn):
    headers = {'Authorization': f'Bearer {access_token}'}
    search_url = f'https://api.commerce.naver.com/external/v1/products/search?keyword={isbn}'
    response = requests.get(search_url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        if data.get('content'):
            return data['content'][0].get('channelProducts', [{}])[0].get('channelProductNo')
    return None

def delete_product(access_token, product_id):
    headers = {'Authorization': f'Bearer {access_token}', 'Content-Type': 'application/json'}
    delete_url = 'https://api.commerce.naver.com/external/v1/products'
    data = {"channelProductNos": [product_id], "statusType": "DELETED"}
    
    response = requests.put(delete_url, headers=headers, json=data)
    return response.status_code == 200

def fetch_all_products(access_token):
    """상점의 전체 상품 목록을 가져오는 함수 (중복 체크용)"""
    headers = {'Authorization': f'Bearer {access_token}'}
    # 실제 환경에서는 page/size 파라미터를 이용해 반복문으로 전체 데이터를 가져와야 합니다.
    search_url = 'https://api.commerce.naver.com/external/v1/products/search?pageSize=100'
    response = requests.get(search_url, headers=headers)
    
    if response.status_code == 200:
        data = response.json()
        return data.get('content', [])
    return []
