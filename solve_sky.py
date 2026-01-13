import requests
import json
import time
import os
import sys

def run_analysis():
    # ---------------------------------------------------------
    # 設定・定数
    # ---------------------------------------------------------
    API_KEY = "frminzlefpwosbcj"
    BASE_URL = "http://nova.astrometry.net/api"
    
    # ---------------------------------------------------------
    # 画像ファイルの自動探索
    # ---------------------------------------------------------
    print("Searching for image...")
    target_file = None
    
    all_files = os.listdir(".")
    for f in all_files:
        lower_name = f.lower()
        if lower_name.endswith(".py") or lower_name.endswith(".exe") or lower_name.endswith(".spec"):
            continue
        if "starphoto" in lower_name:
            target_file = f
            break
    
    if target_file is None:
        print("ERROR: Could not find any file containing 'starphoto'.")
        sys.exit(1)
        
    print(f"Target Image Found: '{target_file}'")

    # ---------------------------------------------------------
    # 1. Login
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
    # 2. Upload
    # ---------------------------------------------------------
    print("Step 2: Uploading image...")
    try:
        with open(target_file, 'rb') as f:
            args = {
                'allow_commercial_use': 'n',
                'allow_modifications': 'n',
                'publicly_visible': 'y',
                'session': session
            }
            upload_data = {'request-json': json.dumps(args)}
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
    # 3. Wait for processing
    # ---------------------------------------------------------
    print("Step 3: Waiting for processing...")
    job_id = None
    max_retries = 40 # 待ち時間を少し延長
    
    for i in range(max_retries):
        time.sleep(10)
        try:
            resp = requests.get(f"{BASE_URL}/submissions/{sub_id}")
            sub_status = resp.json()
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
                print("Astrometry analysis failed.")
                sys.exit(1)
            print(f"Job processing... Status: {status_str} ({i+1}/{max_retries})")
        except Exception as e:
            print(f"Job Status Exception: {e}")

    if not job_done:
        print("Timed out waiting for job completion.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. Result & Annotated Image Download (安全対策強化版)
    # ---------------------------------------------------------
    print("Step 4: Fetching results & Annotated Image...")
    try:
        # 座標データの取得
        resp = requests.get(f"{BASE_URL}/jobs/{job_id}/calibration")
        cal_data = resp.json()
        
        print("\n" + "="*40)
        print("       ANALYSIS RESULT       ")
        print("="*40)
        print(f"Right Ascension (RA) : {cal_data.get('ra')}")
        print(f"Declination (Dec)    : {cal_data.get('dec')}")
        print("="*40 + "\n")

        # --- 画像ダウンロード処理 ---
        print("Downloading Annotated Image (Safe Mode)...")
        
        # 'annotated_full' はフルサイズ画像の正規エンドポイントです
        # ここからリダイレクトされて実際の画像(JPGなど)に飛びます
        img_url = f"http://nova.astrometry.net/annotated_full/{job_id}"
        
        # allow_redirects=True でリダイレクトを許可
        img_resp = requests.get(img_url, allow_redirects=True)
        
        # 【重要】Content-Typeを確認する
        content_type = img_resp.headers.get("Content-Type", "").lower()
        print(f"DEBUG: Response Content-Type: {content_type}")
        
        if img_resp.status_code == 200 and "image" in content_type:
            # 画像として正しい場合のみ保存
            output_filename = "annotated_result.jpg"
            with open(output_filename, 'wb') as f:
                f.write(img_resp.content)
            print(f"SUCCESS: Saved annotated image to '{output_filename}'")
        else:
            # 画像じゃなかった場合、エラーを表示して中身の一部をログに出す（デバッグ用）
            print("ERROR: The response was NOT an image.")
            print(f"Status Code: {img_resp.status_code}")
            print(f"Content Start: {img_resp.text[:200]}") # 冒頭200文字を表示
            # ここでexitしないと、壊れたファイルをアーティファクトとして上げようとしてしまう
            # ただし、座標データは取れているのでexitせずに進む手もあるが、今回はエラーを明確にする
            
    except Exception as e:
        print(f"Result Fetch Exception: {e}")

if __name__ == '__main__':
    run_analysis()
