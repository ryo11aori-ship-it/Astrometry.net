import requests
import json
import time
import os
import sys

# --- 描画・天文学用ライブラリ ---
import matplotlib.pyplot as plt
from astropy.wcs import WCS
from astropy.io import fits
import numpy as np
import warnings

# 警告抑制
warnings.simplefilter('ignore')

def run_analysis():
    # ---------------------------------------------------------
    # 設定
    # ---------------------------------------------------------
    API_KEY = "frminzlefpwosbcj"
    BASE_URL = "http://nova.astrometry.net/api"
    
    # 星座線データのURL (d3-celestialのオープンデータを使用)
    CONSTELLATION_JSON_URL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json"
    
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
    # 4. Drawing Perfect Constellation Lines
    # ---------------------------------------------------------
    print("Step 4: Fetching Data & Drawing Constellations...")
    
    try:
        # A. WCSファイル(座標定義)のダウンロード
        wcs_url = f"http://nova.astrometry.net/wcs_file/{job_id}"
        print(f"Downloading WCS file from {wcs_url}...")
        wcs_resp = requests.get(wcs_url)
        wcs_filename = "wcs.fits"
        with open(wcs_filename, 'wb') as f:
            f.write(wcs_resp.content)

        # B. 星座線データ(GeoJSON)のダウンロード
        print("Downloading Constellation Lines Data...")
        const_resp = requests.get(CONSTELLATION_JSON_URL)
        if const_resp.status_code != 200:
            print("ERROR: Failed to download constellation data.")
            sys.exit(1)
        const_data = const_resp.json()
        print("Constellation data loaded.")

        # --- C. 描画処理 ---
        print("Drawing lines...")
        # WCS読み込み
        wcs = WCS(fits.open(wcs_filename)[0].header)
        
        # 画像読み込み
        img_data = plt.imread(target_file)
        
        # プロット準備 (枠線などを消して画像だけにする)
        fig = plt.figure(figsize=(12, 12))
        ax = plt.subplot(projection=wcs)
        
        # 元画像を表示
        ax.imshow(img_data)
        
        # グリッド線も薄く残しておく（お好みでコメントアウト可）
        ax.coords.grid(True, color='white', ls='dotted', alpha=0.3)
        
        # 星座線の描画ループ
        # GeoJSON形式: features -> geometry -> coordinates (MultiLineString)
        line_count = 0
        
        for feature in const_data['features']:
            geometry = feature['geometry']
            const_id = feature['id'] # 星座ID (例: Ori, UMa)
            
            if geometry['type'] == 'MultiLineString':
                lines = geometry['coordinates']
                
                for line in lines:
                    # line は [[RA, Dec], [RA, Dec], ...] のリスト
                    # JSONデータは [RA(度), Dec(度)] の形式
                    line_array = np.array(line)
                    ra = line_array[:, 0]
                    dec = line_array[:, 1]
                    
                    # 線をプロット
                    # transform=ax.get_transform('world') を使うと
                    # RA/Dec の値をそのまま渡して、WCSに従って描画してくれる
                    ax.plot(ra, dec, transform=ax.get_transform('world'), 
                            color='cyan', linewidth=1.5, alpha=0.8)
                    line_count += 1
        
        print(f"Drew {line_count} constellation segments.")

        # タイトルや軸ラベルを消して「写真」っぽくする
        ax.set_xlabel('')
        ax.set_ylabel('')
        ax.tick_params(labelbottom=False, labelleft=False)
        
        # 保存
        output_filename = "annotated_result.jpg"
        plt.savefig(output_filename, dpi=150, bbox_inches='tight', pad_inches=0.05)
        
        print(f"SUCCESS: Generated '{output_filename}' with CONSTELLATION LINES!")
        
    except Exception as e:
        print(f"Drawing Error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == '__main__':
    run_analysis()
