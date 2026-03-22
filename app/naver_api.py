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
        res = requests.post(url, headers=headers, data=data, timeout=10)
        if res.status_code == 200:
            return res.json().get('access_token')
    except:
        pass
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

def delete_product(token, origin_no, channel_no, retries=3):
    """(최신 V2 API) 네이버 요청 폭주 시 자동 재시도(Retry) 방어 로직 탑재"""
    headers = {
        'Authorization': f'Bearer {token}', 
        'Accept': 'application/json;charset=UTF-8'
    }
    
    # 실패 시 최대 3번까지 다시 시도합니다.
    for attempt in range(retries):
        try:
            if channel_no:
                delete_url = f"https://api.commerce.naver.com/external/v2/products/channel-products/{channel_no}"
                res = requests.delete(delete_url, headers=headers, timeout=10)
                
                if res.status_code == 200:
                    return "완전 삭제 완료"
                
                # 네이버가 "요청이 너무 많다"며 거절한 경우 -> 1.5초 쉬고 재시도
                elif res.status_code == 429 or "요청이 많아" in res.text:
                    time.sleep(1.5)
                    continue 
                
                # 다른 사유로 삭제가 거절된 경우 (재시도 없이 바로 사유 반환)
                else:
                    try:
                        error_msg = res.json().get('message', f'HTTP {res.status_code}')
                        return f"삭제 불가 ({error_msg})"
                    except:
                        return f"API 거절 (HTTP {res.status_code})"
                        
            return "식별 번호 누락"
        
        except requests.exceptions.Timeout:
            # 타임아웃 발생 시에도 조금 쉬었다가 재시도
            time.sleep(1)
            continue
        except Exception as e:
            return "시스템 오류 발생"
            
    # 3번을 재시도했는데도 계속 요청 폭주로 튕겨내면 최종 포기
    return "삭제 불가 (API 요청량 초과, 스킵됨)"

def fetch_all_products(token):
    url = "https://api.commerce.naver.com/external/v1/products/search"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    all_products = []
    page = 1
    
    while True:
        payload = {"page": page, "size": 50, "orderType": "NO"}
        try:
            res = requests.post(url, headers=headers, json=payload, timeout=10)
            if res.status_code != 200: break
            contents = res.json().get('contents', [])
            if not contents: break
            all_products.extend(contents)
            if len(contents) < 50: break
            page += 1
            time.sleep(0.2)
        except:
            break
            
    return all_products
