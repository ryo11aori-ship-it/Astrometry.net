import requests
import json
import time
import os
import sys
import glob

def run_analysis():
    # ---------------------------------------------------------
    # 設定・定数（APIキー埋め込み済み）
    # ---------------------------------------------------------
    API_KEY = "frminzlefpwosbcj"
    BASE_URL = "http://nova.astrometry.net/api"
    
    # ---------------------------------------------------------
    # 画像ファイルの自動探索 (ここを強力にしました)
    # starphoto で始まるファイルなら、.jpg.jpg でも .jpeg でも何でも拾います
    # ---------------------------------------------------------
    target_file = None
    
    # 'starphoto' で始まるすべてのファイルを探すリスト
    candidates = glob.glob("starphoto*")
    
    # 自分自身(pyファイル)やディレクトリを除外して画像っぽいものを探す
    for f in candidates:
        if f.endswith(".py"):
            continue
        if os.path.isdir(f):
            continue
        target_file = f
        break
    
    if target_file is None:
        # 万が一見つからない場合、カレントディレクトリのファイル一覧を表示して終了
        print("ERROR: 'starphoto' で始まる画像ファイルが見つかりません。")
        print("現在あるファイル一覧:", os.listdir("."))
        sys.exit(1)
        
    print(f"Target Image Found: {target_file}")

    # ---------------------------------------------------------
    # 1. ログイン処理
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
    # 3. 解析完了待ち
    # ---------------------------------------------------------
    print("Step 3: Waiting for processing...")
    job_id = None
    max_retries = 30
    
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
    # 4. 結果の取得
    # ---------------------------------------------------------
    print("Step 4: Fetching results...")
    try:
        resp = requests.get(f"{BASE_URL}/jobs/{job_id}/calibration")
        cal_data = resp.json()
        print("\n" + "="*40)
        print("       ANALYSIS RESULT       ")
        print("="*40)
        print(f"Target File          : {target_file}")
        print(f"Right Ascension (RA) : {cal_data.get('ra')}")
        print(f"Declination (Dec)    : {cal_data.get('dec')}")
        print(f"Radius (deg)         : {cal_data.get('radius')}")
        print("="*40 + "\n")
    except Exception as e:
        print(f"Result Fetch Exception: {e}")

if __name__ == '__main__':
    run_analysis()
