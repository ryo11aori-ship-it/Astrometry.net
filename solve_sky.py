import requests
import json
import time
import os
import sys

# --- 描画・天文学用ライブラリ ---
import matplotlib.pyplot as plt
from astropy.wcs import WCS
from astropy.io import fits
import warnings

# Astropyの警告を抑制
warnings.simplefilter('ignore')

def run_analysis():
    # ---------------------------------------------------------
    # 設定
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
    max_retries = 60
    
    for i in range(max_retries):
        time.sleep(5)
        try:
            resp = requests.get(f"{BASE_URL}/submissions/{sub_id}")
            sub_status = resp.json()
            if sub_status.get('jobs') and len(sub_status['jobs']) > 0:
                job_id = sub_status['jobs'][0]
                if job_id:
                    # ジョブの完了確認
                    resp_job = requests.get(f"{BASE_URL}/jobs/{job_id}")
                    if resp_job.json().get('status') == 'success':
                        print(f"Job finished: {job_id}")
                        break
            print(f"Waiting... ({i+1}/{max_retries})")
        except Exception as e:
            print(f"Polling warning: {e}")
            
    if not job_id:
        print("Timed out.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. Result & Drawing (ここが完全リニューアル)
    # ---------------------------------------------------------
    print("Step 4: Fetching Data & Drawing locally...")
    
    try:
        # A. 座標データ(RA/Dec)の表示
        cal_resp = requests.get(f"{BASE_URL}/jobs/{job_id}/calibration")
        cal_data = cal_resp.json()
        print(f"RA: {cal_data.get('ra')}, Dec: {cal_data.get('dec')}")

        # B. WCSファイル(天球座標の定義ファイル)のダウンロード
        # これさえあれば、画像のどのピクセルが宇宙のどこか、数学的に特定できます
        wcs_url = f"http://nova.astrometry.net/wcs_file/{job_id}"
        print(f"Downloading WCS file from {wcs_url}...")
        
        wcs_resp = requests.get(wcs_url)
        wcs_filename = "wcs.fits"
        with open(wcs_filename, 'wb') as f:
            f.write(wcs_resp.content)
            
        print("WCS file downloaded. Generating annotated image...")

        # --- C. 自前での描画処理 (Matplotlib + Astropy) ---
        # 1. WCSファイルを読み込む
        wcs = WCS(fits.open(wcs_filename)[0].header)
        
        # 2. 元画像を読み込む (Matplotlibで読める形式に)
        img_data = plt.imread(target_file)
        
        # 3. プロット作成
        plt.figure(figsize=(10, 10)) # 画像サイズ
        
        # WCSプロジェクションを使って画像を表示設定
        ax = plt.subplot(projection=wcs)
        
        # 画像を表示 (origin='lower' ではなく 'upper' が通常写真の向きに近いことが多いが調整可)
        # Astrometry.netは左下が原点の場合が多いので一旦デフォルトで
        ax.imshow(img_data)
        
        # 4. グリッド線（赤経・赤緯の線）を引く
        # これが「正確な線」になります
        ax.coords.grid(True, color='white', ls='solid', alpha=0.5)
        ax.coords['ra'].set_axislabel('Right Ascension')
        ax.coords['dec'].set_axislabel('Declination')
        
        # タイトル
        plt.title(f"Analysis Result: Job {job_id}")
        
        # 5. 保存
        output_filename = "annotated_result.jpg"
        plt.savefig(output_filename, dpi=150, bbox_inches='tight')
        
        print(f"SUCCESS: Generated '{output_filename}' locally!")
        
    except Exception as e:
        print(f"Drawing Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    run_analysis()
