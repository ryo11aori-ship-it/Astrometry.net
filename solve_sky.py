import requests
import json
import time
import os
import sys
import glob
import re  # 追加：HTMLからリンクを探すための正規表現ライブラリ

def run_analysis():
    # ---------------------------------------------------------
    # 設定・定数
    # ---------------------------------------------------------
    API_KEY = "frminzlefpwosbcj"
    # API用URL
    API_URL = "http://nova.astrometry.net/api"
    # Webサイト用URL (画像の取得などに使用)
    WEB_URL = "http://nova.astrometry.net"
    
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
        resp = requests.post(f"{API_URL}/login", data={'request-json': json.dumps({"apikey": API_KEY})})
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
            resp = requests.post(f"{API_URL}/upload", files={'file': f}, data=upload_data)
        
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
    max_retries = 40
    
    for i in range(max_retries):
        time.sleep(10)
        try:
            resp = requests.get(f"{API_URL}/submissions/{sub_id}")
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
            resp = requests.get(f"{API_URL}/jobs/{job_id}")
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
    # 4. Result & Annotated Image Download (スクレイピング方式)
    # ---------------------------------------------------------
    print("Step 4: Fetching results & Annotated Image...")
    try:
        # 座標データの取得
        resp = requests.get(f"{API_URL}/jobs/{job_id}/calibration")
        cal_data = resp.json()
        
        print("\n" + "="*40)
        print("       ANALYSIS RESULT       ")
        print("="*40)
        print(f"Right Ascension (RA) : {cal_data.get('ra')}")
        print(f"Declination (Dec)    : {cal_data.get('dec')}")
        print("="*40 + "\n")

        # --- 画像ダウンロード処理 (スクレイピングロジック) ---
        print("Downloading Annotated Image (HTML Parsing Mode)...")
        
        # 画像生成には解析完了後少し時間がかかる場合があるため、リトライループに入れる
        image_saved = False
        img_retries = 10 # 5秒 x 10回 = 最大50秒待つ
        
        for i in range(img_retries):
            try:
                # 1. まず表示ページ(HTML)を取りに行く
                # URL例: http://nova.astrometry.net/annotated_display/12345
                display_url = f"{WEB_URL}/annotated_display/{job_id}"
                print(f"Accessing display page: {display_url} ({i+1}/{img_retries})")
                
                page_resp = requests.get(display_url)
                
                # 2. HTMLの中から <img src="..."> を探す
                # 探すパターン: src="/annotated_image/..." のような記述
                match = re.search(r'src="(/annotated_image/[^"]+)"', page_resp.text)
                
                if match:
                    # 見つかったパス (例: /annotated_image/12345)
                    rel_path = match.group(1)
                    real_img_url = f"{WEB_URL}{rel_path}"
                    print(f"Found real image URL: {real_img_url}")
                    
                    # 3. 本物のURLをダウンロードする
                    img_resp = requests.get(real_img_url, allow_redirects=True)
                    content_type = img_resp.headers.get("Content-Type", "").lower()
                    
                    if img_resp.status_code == 200 and "image" in content_type:
                        output_filename = "annotated_result.jpg"
                        with open(output_filename, 'wb') as f:
                            f.write(img_resp.content)
                        print(f"SUCCESS: Saved annotated image to '{output_filename}'")
                        image_saved = True
                        break # 成功したのでループを抜ける
                    else:
                        print(f"Wait: URL found but content was {content_type}")
                else:
                    print("Wait: Image link not found in HTML yet.")
                
            except Exception as e:
                print(f"Download warning: {e}")
            
            # まだ画像がない、またはHTMLだった場合は少し待って再試行
            time.sleep(5)
            
        if not image_saved:
            print("ERROR: Failed to download image after multiple attempts.")
            # 画像は諦めるが、座標データは取れているのでexit(1)にはしない

    except Exception as e:
        print(f"Result Fetch Exception: {e}")

if __name__ == '__main__':
    run_analysis()
