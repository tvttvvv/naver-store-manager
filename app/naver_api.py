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

def delete_product(token, origin_no, channel_no, retries=5): # ✨ 재시도 횟수를 5회로 넉넉하게 늘렸습니다.
    """채널 상품과 원상품을 모두 완전 삭제합니다."""
    headers = {'Authorization': f'Bearer {token}', 'Accept': 'application/json;charset=UTF-8'}
    
    original_channel_no = channel_no 
    
    for attempt in range(retries):
        try:
            # 1. 채널 상품 삭제 (스토어 노출 중단)
            if channel_no:
                channel_delete_url = f"https://api.commerce.naver.com/external/v2/products/channel-products/{channel_no}"
                res_channel = requests.delete(channel_delete_url, headers=headers, timeout=10)
                
                # ✨ JSON을 먼저 디코딩하여 한글 에러 메시지를 확실하게 잡습니다.
                try: c_msg = res_channel.json().get('message', '')
                except: c_msg = res_channel.text
                
                if res_channel.status_code == 429 or "요청이 많아" in c_msg:
                    time.sleep(2) # 대기 시간을 늘려 안정성 확보
                    continue 
                elif res_channel.status_code in [200, 204, 404]:
                    channel_no = None
            
            # 2. 원상품 삭제 (판매자 센터 DB에서 완전 삭제)
            if origin_no:
                origin_delete_url = f"https://api.commerce.naver.com/external/v1/products/origin-products/{origin_no}"
                res_origin = requests.delete(origin_delete_url, headers=headers, timeout=10)
                
                # ✨ 동일하게 JSON 선 디코딩 적용
                try: o_msg = res_origin.json().get('message', '')
                except: o_msg = res_origin.text
                
                if res_origin.status_code in [200, 204]:
                    return "완전 삭제 완료"
                elif res_origin.status_code == 429 or "요청이 많아" in o_msg:
                    time.sleep(2)
                    continue
                else:
                    return f"원상품 삭제 불가 ({o_msg if o_msg else f'HTTP {res_origin.status_code}'})"

            # 여기까지 왔다면 채널 상품은 지웠지만 원상품이 없는 특이 케이스입니다.
            if not origin_no and original_channel_no and not channel_no:
                return "채널 상품만 삭제됨 (원상품 번호 없음)"
                
            if not origin_no and not original_channel_no:
                return "식별 번호 누락"
                
            return "채널 상품만 삭제됨 (원상품 번호 없음)"

        except requests.exceptions.Timeout:
            time.sleep(1)
            continue
        except Exception:
            return "시스템 오류 발생"
            
    return "API 요청량 초과 (재시도 5회 초과)"

def suspend_products_in_bulk(token, channel_no_list):
    """(2차 작업용) 삭제 실패한 상품들만 모아서 한 방에 중지 처리"""
    if not channel_no_list:
        return "항목 없음"
        
    url = "https://api.commerce.naver.com/external/v2/products/channel-products/status"
    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
    
    payload = {"channelProducts": []}
    for c_no in channel_no_list:
        payload["channelProducts"].append({
            "channelProductNo": c_no,
            "saleStateType": "SUSPEND",
            "displayStateType": "SUSPEND"
        })
        
    try:
        res = requests.put(url, headers=headers, json=payload, timeout=10)
        if res.status_code == 200:
            return "완전 삭제 불가 (판매/전시 중지로 우회 완료)"
        else:
            return f"중지 처리 실패 (HTTP {res.status_code})"
    except Exception as e:
        return "묶음 처리 통신 오류"

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
