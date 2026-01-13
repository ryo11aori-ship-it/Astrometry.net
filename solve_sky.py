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
CONSTELLATION_JSON_URL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json"

def get_session(session_client):
    """ログインしてセッションIDを取得"""
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
    """画像をアップロード"""
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
    """解析完了待ち"""
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
    """ファイルダウンロード"""
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
    """元画像の向きで、安全に星座線とグリッドを描画する"""
    print("Drawing on original image orientation...")
    
    # 1. データ読み込み
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    # 2. プロット準備
    fig, ax = plt.subplots(figsize=(12, 12))
    ax.imshow(img_data, origin='upper')

    # ---------------------------------------------------------
    # 【修正箇所1】画像の範囲（四隅）の天球座標を計算し、グリッドの範囲を限定する
    # ---------------------------------------------------------
    print(" - Calculating image bounds...")
    try:
        # 四隅のピクセル座標 [[0,0], [w,0], [w,h], [0,h]]
        corners_pix = np.array([[0, 0], [w, 0], [w, h], [0, h]])
        # これを天球座標(RA, Dec)に変換
        # quiet=True を入れることで、万が一歪みがひどくてもエラーで落ちないようにする
        corners_world = wcs.all_pix2world(corners_pix, 0)
        
        ra_min, ra_max = np.min(corners_world[:, 0]), np.max(corners_world[:, 0])
        dec_min, dec_max = np.min(corners_world[:, 1]), np.max(corners_world[:, 1])
        
        # 0度/360度の境界をまたぐ場合の簡易補正（範囲が広くなりすぎるのを防ぐ）
        if ra_max - ra_min > 180:
            ra_min, ra_max = 0, 360
        else:
            # 少し余裕を持たせる
            ra_min = max(0, ra_min - 10)
            ra_max = min(360, ra_max + 10)
            
        dec_min = max(-90, dec_min - 10)
        dec_max = min(90, dec_max + 10)
        
        print(f"   Bounds: RA[{ra_min:.1f}, {ra_max:.1f}], Dec[{dec_min:.1f}, {dec_max:.1f}]")
        
    except Exception as e:
        print(f"   Warning: Could not calculate bounds ({e}). Using full sky (risky but trying).")
        ra_min, ra_max = 0, 360
        dec_min, dec_max = -90, 90

    # 3. 天球グリッド線の描画
    print(" - Drawing grid lines...")
    grid_color = 'white'
    grid_alpha = 0.2
    grid_lw = 0.5
    
    # RA線 (範囲を限定してループ)
    # stepは15度刻み
    start_ra = int(ra_min / 15) * 15
    end_ra = int(ra_max / 15) * 15 + 15
    
    for ra in range(start_ra, end_ra + 1, 15):
        if ra > 360: continue
        # Dec方向の点は細かく
        decs = np.linspace(dec_min, dec_max, 100)
        ras = np.full_like(decs, ra)
        
        # 変換実行 (quiet=Trueでエラー回避)
        try:
            pix_coords = wcs.all_world2pix(np.stack([ras, decs], axis=1), 0, quiet=True)
            # 正常な値（NaNでない、かつ画像の範囲内付近）のみプロット
            mask = ~np.isnan(pix_coords[:, 0]) & (pix_coords[:, 0] > -w) & (pix_coords[:, 0] < 2*w)
            if np.any(mask):
                ax.plot(pix_coords[mask, 0], pix_coords[mask, 1], color=grid_color, alpha=grid_alpha, lw=grid_lw)
        except:
            pass # 計算できない線は無視

    # Dec線
    start_dec = int(dec_min / 10) * 10
    end_dec = int(dec_max / 10) * 10 + 10
    
    for dec in range(start_dec, end_dec + 1, 10):
        if dec > 90: continue
        ras = np.linspace(ra_min, ra_max, 100)
        decs_arr = np.full_like(ras, dec)
        
        try:
            pix_coords = wcs.all_world2pix(np.stack([ras, decs_arr], axis=1), 0, quiet=True)
            mask = ~np.isnan(pix_coords[:, 0]) & (pix_coords[:, 0] > -w) & (pix_coords[:, 0] < 2*w)
            if np.any(mask):
                ax.plot(pix_coords[mask, 0], pix_coords[mask, 1], color=grid_color, alpha=grid_alpha, lw=grid_lw)
        except:
            pass

    # 4. 星座線の描画
    print(" - Drawing constellation lines...")
    line_count = 0
    for feature in const_data['features']:
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_array = np.array(line) # [[RA, Dec], ...]
                
                # 簡易チェック：線の座標が画面範囲外ならスキップ（高速化）
                l_ra_min, l_ra_max = np.min(line_array[:, 0]), np.max(line_array[:, 0])
                l_dec_min, l_dec_max = np.min(line_array[:, 1]), np.max(line_array[:, 1])
                
                # 範囲外判定
                if (l_dec_max < dec_min) or (l_dec_min > dec_max):
                    continue
                # RAは0/360境界があるため単純比較しにくいが、Decチェックだけでもかなり効く
                
                try:
                    # 変換 (quiet=True)
                    pix_coords = wcs.all_world2pix(line_array, 0, quiet=True)
                    
                    # すべてNaNならスキップ
                    if np.all(np.isnan(pix_coords)):
                        continue
                        
                    # 少なくとも一部が画面内(または画面近く)にあるかチェック
                    visible_mask = (pix_coords[:, 0] > -w*0.5) & (pix_coords[:, 0] < w*1.5) & \
                                   (pix_coords[:, 1] > -h*0.5) & (pix_coords[:, 1] < h*1.5)
                    
                    if np.any(visible_mask):
                        ax.plot(pix_coords[:, 0], pix_coords[:, 1], 
                                color='cyan', linewidth=1.5, alpha=0.8)
                        line_count += 1
                except:
                    continue
                    
    print(f"   Drew {line_count} segments.")

    # 5. 表示範囲設定
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)
    ax.axis('off')

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

    session_id = get_session(session_client)
    sub_id = upload_image(session_client, target_file, session_id)
    job_id = wait_for_job(session_client, sub_id)

    print("Step 4: Fetching Data & Drawing...")

    norm_img_url = f"{BASE_URL}/annotated_image/{job_id}"
    download_file(norm_img_url, "result_normalized.jpg", session_client)

    wcs_filename = "wcs.fits"
    if not download_file(f"{BASE_URL}/wcs_file/{job_id}", wcs_filename):
        sys.exit(1)

    const_data = requests.get(CONSTELLATION_JSON_URL).json()
    draw_on_original_image(target_file, wcs_filename, const_data)

if __name__ == '__main__':
    run_analysis()
