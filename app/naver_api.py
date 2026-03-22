import time
import base64
import requests
import bcrypt

def get_naver_token(client_id, client_secret):
    url = "https://api.commerce.naver.com/external/v1/oauth2/token"
    timestamp = str(int(time.time() * 1000))
    clean_client_id = client_id.strip()
    clean_client_secret = client_secret.strip()
    
    try:
        password = f"{clean_client_id}_{timestamp}"
        hashed = bcrypt.hashpw(password.encode('utf-8'), clean_client_secret.encode('utf-8'))
        signature = base64.b64encode(hashed).decode('utf-8')
    except Exception as e:
        print(f"Token Error: {e}")
        return None

    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    data = {
        'client_id': clean_client_id,
        'timestamp': timestamp,
        'client_secret_sign': signature,
        'grant_type': 'client_credentials',
        'type': 'SELF'
    }
    
    try:
        # 타임아웃 10초 적용
        res = requests.post(url, headers=headers, data=data, timeout=10)
        if res.status_code == 200:
            return res.json().get('access_token')
    except Exception as e:
        print(f"Token Request Error: {e}")
    return None

def find_product_by_isbn(token, isbn):
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    payload = {"page": 1, "size": 50, "sellerManagementCode": isbn}
    try:
        res = requests.post(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200 and res.json().get('contents'):
            p = res.json()['contents'][0]
            return p.get('originProductNo'), p.get('channelProducts', [{}])[0].get('channelProductNo')
    except:
        pass

    payload_name = {"page": 1, "size": 50, "productName": isbn}
    try:
        res_name = requests.post(url, headers=headers, json=payload_name, timeout=10)
        if res_name.status_code == 200 and res_name.json().get('contents'):
            p = res_name.json()['contents'][0]
            return p.get('originProductNo'), p.get('channelProducts', [{}])[0].get('channelProductNo')
    except:
        pass
            
    return None, None

def delete_product(token, origin_no, channel_no):
    """상품 삭제 시도, 실패 시 판매/전시 중지 (타임아웃 및 예외처리 완벽 적용)"""
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    try:
        if origin_no:
            delete_url = f"https://api.commerce.naver.com/external/v1/products/{origin_no}"
            # 타임아웃 10초 적용 (가장 중요!)
            del_res = requests.delete(delete_url, headers=headers, timeout=10)
            if del_res.status_code == 200:
                return "완전 삭제 완료"

        if channel_no:
            status_url = "https://api.commerce.naver.com/external/v2/products/channel-products/status"
            payload = {
                "channelProducts": [
                    {"channelProductNo": channel_no, "saleStateType": "SUSPEND", "displayStateType": "SUSPEND"}
                ]
            }
            # 타임아웃 10초 적용
            status_res = requests.put(status_url, headers=headers, json=payload, timeout=10)
            if status_res.status_code == 200:
                return "판매/전시 중지 완료 (삭제 불가 상품)"
                
        return "삭제/중지 실패 (API 상태 이상)"
    except requests.exceptions.Timeout:
        return "네이버 서버 응답 시간 초과 (건너뜀)"
    except Exception as e:
        return "처리 중 시스템 오류 발생"

def fetch_all_products(token):
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    all_products = []
    page = 1
    
    while True:
        payload = {"page": page, "size": 50, "orderType": "NO"}
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code != 200:
                break
                
            contents = res.json().get('contents', [])
            if not contents:
                break
                
            all_products.extend(contents)
            if len(contents) < 50:
                break
                
            page += 1
            time.sleep(0.2)
        except:
            break
            
    return all_products
