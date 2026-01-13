import requests
import json
import time
import os
import sys

def run_analysis():
    # ---------------------------------------------------------
    # 設定・定数（ご指定のAPIキーを埋め込み済み）
    # ---------------------------------------------------------
    API_KEY = "frminzlefpwosbcj"
    BASE_URL = "http://nova.astrometry.net/api"
    
    # 対象画像の特定 (jpg または png)
    target_file = None
    if os.path.exists("starphoto.jpg"):
        target_file = "starphoto.jpg"
    elif os.path.exists("starphoto.png"):
        target_file = "starphoto.png"
    elif os.path.exists("starphoto.jpeg"):
        target_file = "starphoto.jpeg"
    
    if target_file is None:
        print("ERROR: starphoto.jpg または starphoto.png が見つかりません。")
        sys.exit(1)
        
    print(f"Target Image Found: {target_file}")

    # ---------------------------------------------------------
    # 1. ログイン処理 (Session IDの取得)
    # ---------------------------------------------------------
    print("Step 1: Logging in...")
    try:
        resp = requests.post(f"{BASE_URL}/login", data={'request-json': json.dumps({"apikey": API_KEY})})
        result = resp.json()
        if result.get('status') != 'success':
            print(f"Login Failed: {result}")
            sys.exit(1)
        session = result['session']
        print(f"Logged in. Session: {session}")
    except Exception as e:
        print(f"Login Exception: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 2. 画像のアップロード
    # ---------------------------------------------------------
    print("Step 2: Uploading image...")
    try:
        with open(target_file, 'rb') as f:
            upload_data = {
                'allow_commercial_use': 'n',
                'allow_modifications': 'n',
                'publicly_visible': 'y',
                'session': session
            }
            resp = requests.post(f"{BASE_URL}/upload", files={'file': f}, data=upload_data)
        upload_result = resp.json()
        if upload_result.get('status') != 'success':
            print(f"Upload Failed: {upload_result}")
            sys.exit(1)
        sub_id = upload_result['subid']
        print(f"Upload Success. Submission ID: {sub_id}")
    except Exception as e:
        print(f"Upload Exception: {e}")
        sys.exit(1)

    # ---------------------------------------------------------
    # 3. 解析完了待ち (ポーリング)
    # ---------------------------------------------------------
    print("Step 3: Waiting for processing (this may take time)...")
    job_id = None
    max_retries = 30  # 最大待ち回数
    
    for i in range(max_retries):
        time.sleep(10) # 10秒ごとに確認
        try:
            resp = requests.get(f"{BASE_URL}/submissions/{sub_id}")
            sub_status = resp.json()
            
            # jobが入っているか確認
            if sub_status.get('jobs') and len(sub_status['jobs']) > 0:
                job_id = sub_status['jobs'][0]
                if job_id:
                    print(f"Job assigned: {job_id}")
                    break
            
            print(f"Waiting for job assignment... ({i+1}/{max_retries})")
        except Exception as e:
            print(f"Polling Exception: {e}")
    
    if not job_id:
        print("Timed out waiting for Job ID.")
        sys.exit(1)

    # Jobのステータス確認
    print("Checking job status...")
    job_done = False
    for i in range(max_retries):
        time.sleep(5)
        try:
            resp = requests.get(f"{BASE_URL}/jobs/{job_id}")
            job_status = resp.json()
            status_str = job_status.get('status')
            
            if status_str == 'success':
                job_done = True
                break
            elif status_str == 'failure':
                print("Astrometry analysis failed (could not solve).")
                sys.exit(1)
            
            print(f"Job processing... Status: {status_str} ({i+1}/{max_retries})")
        except Exception as e:
            print(f"Job Status Exception: {e}")

    if not job_done:
        print("Timed out waiting for job completion.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. 結果の取得 (Calibration Data)
    # ---------------------------------------------------------
    print("Step 4: Fetching results...")
    try:
        resp = requests.get(f"{BASE_URL}/jobs/{job_id}/calibration")
        cal_data = resp.json()
        
        print("\n" + "="*40)
        print("       ANALYSIS RESULT       ")
        print("="*40)
        print(f"Right Ascension (RA) : {cal_data.get('ra')}")
        print(f"Declination (Dec)    : {cal_data.get('dec')}")
        print(f"Radius (deg)         : {cal_data.get('radius')}")
        print(f"Pixel Scale          : {cal_data.get('pixscale')} arcsec/pixel")
        print(f"Parity               : {cal_data.get('parity')}")
        print(f"Orientation          : {cal_data.get('orientation')}")
        print("="*40 + "\n")
        
    except Exception as e:
        print(f"Result Fetch Exception: {e}")

if __name__ == '__main__':
    run_analysis()
