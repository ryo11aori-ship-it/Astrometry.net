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

# ---------------------------------------------------------
# 設定・定数
# ---------------------------------------------------------
API_KEY = "frminzlefpwosbcj"
BASE_URL = "http://nova.astrometry.net"
API_URL = "http://nova.astrometry.net/api"
# 星座線データURL
CONSTELLATION_JSON_URL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json"

def get_session(session_client):
    """ログインしてセッションIDを取得し、Cookieにセットする"""
    print("Step 1: Logging in...")
    try:
        resp = session_client.post(f"{API_URL}/login", data={'request-json': json.dumps({"apikey": API_KEY})})
        result = resp.json()
        if result.get('status') != 'success':
            print(f"Login Failed: {result}")
            sys.exit(1)
        session_id = result['session']
        print(f"Logged in. Session ID: {session_id}")
        session_client.cookies.set('session', session_id)
        return session_id
    except Exception as e:
        print(f"Login Exception: {e}")
        sys.exit(1)

def upload_image(session_client, target_file, session_id):
    """画像をアップロードしてSubmission IDを取得する"""
    print("Step 2: Uploading image...")
    try:
        with open(target_file, 'rb') as f:
            args = {
                'allow_commercial_use': 'n',
                'allow_modifications': 'n',
                'publicly_visible': 'y',
                'session': session_id
            }
            upload_data = {'request-json': json.dumps(args)}
            resp = session_client.post(f"{API_URL}/upload", files={'file': f}, data=upload_data)
        
        upload_result = resp.json()
        if upload_result.get('status') != 'success':
            print(f"Upload Failed: {upload_result}")
            sys.exit(1)
        sub_id = upload_result['subid']
        print(f"Upload Success. Submission ID: {sub_id}")
        return sub_id
    except Exception as e:
        print(f"Upload Exception: {e}")
        sys.exit(1)

def wait_for_job(session_client, sub_id):
    """解析完了を待ち、Job IDを取得する"""
    print("Step 3: Waiting for processing...")
    max_retries = 60
    for i in range(max_retries):
        time.sleep(5)
        try:
            resp = session_client.get(f"{API_URL}/submissions/{sub_id}")
            sub_status = resp.json()
            if sub_status.get('jobs') and len(sub_status['jobs']) > 0:
                job_id = sub_status['jobs'][0]
                if job_id:
                    resp_job = session_client.get(f"{API_URL}/jobs/{job_id}")
                    status = resp_job.json().get('status')
                    if status == 'success':
                        print(f"Job finished successfully: {job_id}")
                        return job_id
                    elif status == 'failure':
                        print("Analysis failed.")
                        sys.exit(1)
                    else:
                         print(f"Status: {status} ({i+1}/{max_retries})")
            else:
                 print(f"Waiting for job... ({i+1}/{max_retries})")
        except Exception as e:
            print(f"Polling warning: {e}")
    print("Timed out.")
    sys.exit(1)

def download_file(url, filename, session_client=None):
    """ファイルをダウンロードして保存する"""
    print(f"Downloading {filename} from {url}...")
    try:
        client = session_client if session_client else requests
        resp = client.get(url, allow_redirects=True)
        if resp.status_code == 200:
            with open(filename, 'wb') as f:
                f.write(resp.content)
            print(f"Saved: {filename}")
            return True
        print(f"Failed to download {filename}. Status: {resp.status_code}")
    except Exception as e:
        print(f"Download Error: {e}")
    return False

def draw_on_original_image(target_file, wcs_filename, const_data):
    """元画像の向きのまま、星座線とグリッドを描画する"""
    print("Drawing on original image orientation...")
    
    # 1. データ読み込み
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    # 2. プロット準備 (元画像基準)
    fig, ax = plt.subplots(figsize=(12, 12))
    # 画像の原点を左上に設定して表示（通常の画像座標系）
    ax.imshow(img_data, origin='upper')

    # 3. 天球グリッド線の描画 (薄く細く)
    print(" - Drawing grid lines...")
    grid_color = 'white'
    grid_alpha = 0.2
    grid_lw = 0.5
    
    # RA線 (15度=1時間ごと)
    for ra in range(0, 360, 15):
        decs = np.linspace(-90, 90, 100)
        ras = np.full_like(decs, ra)
        # 天球座標(RA,Dec) -> ピクセル座標(X,Y) 変換
        # 第3引数の0は、ピクセルの原点が(0,0)であることを指定
        pix_coords = wcs.all_world2pix(np.stack([ras, decs], axis=1), 0)
        ax.plot(pix_coords[:, 0], pix_coords[:, 1], color=grid_color, alpha=grid_alpha, lw=grid_lw)

    # Dec線 (10度ごと)
    for dec in range(-80, 81, 10):
        ras = np.linspace(0, 360, 100)
        decs_arr = np.full_like(ras, dec)
        pix_coords = wcs.all_world2pix(np.stack([ras, decs_arr], axis=1), 0)
        ax.plot(pix_coords[:, 0], pix_coords[:, 1], color=grid_color, alpha=grid_alpha, lw=grid_lw)

    # 4. 星座線の描画
    print(" - Drawing constellation lines...")
    line_count = 0
    for feature in const_data['features']:
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_array = np.array(line) # [[RA, Dec], ...]
                # 座標変換
                pix_coords = wcs.all_world2pix(line_array, 0)
                # プロット
                ax.plot(pix_coords[:, 0], pix_coords[:, 1], 
                        color='cyan', linewidth=1.5, alpha=0.8)
                line_count += 1
    print(f"   Drew {line_count} segments.")

    # 5. 表示範囲と体裁を整える
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0) # Y軸を反転させて画像の座標系に合わせる
    ax.axis('off') # 軸や枠線を消す

    # 6. 保存
    output_filename = "result_original_orient.jpg"
    plt.savefig(output_filename, dpi=150, bbox_inches='tight', pad_inches=0)
    print(f"SUCCESS: Generated '{output_filename}'")
    plt.close(fig)

def run_analysis():
    # 画像探索
    print("Searching for image...")
    target_file = next((f for f in os.listdir(".") if "starphoto" in f.lower() and f.lower().endswith(('.png', '.jpg', '.jpeg'))), None)
    if not target_file:
        print("ERROR: 'starphoto' image not found.")
        sys.exit(1)
    print(f"Target Image Found: '{target_file}'")

    # APIクライアント準備
    session_client = requests.Session()
    session_client.headers.update({'User-Agent': 'Mozilla/5.0 (Python script)'})

    # 一連のAPI処理
    session_id = get_session(session_client)
    sub_id = upload_image(session_client, target_file, session_id)
    job_id = wait_for_job(session_client, sub_id)

    print("Step 4: Fetching Data & Drawing...")

    # A. Astrometry.net標準の正規化画像（北が上）をダウンロード（比較用）
    norm_img_url = f"{BASE_URL}/annotated_image/{job_id}"
    download_file(norm_img_url, "result_normalized.jpg", session_client)

    # B. WCSファイルダウンロード（自前描画用）
    wcs_filename = "wcs.fits"
    if not download_file(f"{BASE_URL}/wcs_file/{job_id}", wcs_filename):
        sys.exit(1)

    # C. 星座線データダウンロード
    const_data = requests.get(CONSTELLATION_JSON_URL).json()

    # D. 元画像の向きで描画を実行
    draw_on_original_image(target_file, wcs_filename, const_data)

if __name__ == '__main__':
    run_analysis()
