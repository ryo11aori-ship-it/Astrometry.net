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

# ------------------------------------------------------------------
# 画像生成1: 元画像向き (あなたの写真と同じ向き) - 修正版
# ------------------------------------------------------------------
def draw_original_orientation(target_file, wcs_filename, const_data):
    print("Generating Image 1: Original Orientation (Full view)...")
    
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    # --- 【修正1】画像サイズに合わせてキャンバスを作成し、余白を完全になくす ---
    dpi = 150  # 解像度
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    # Axesをキャンバス全体(0,0から1,1まで)に配置
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off() # 軸を非表示
    
    ax.imshow(img_data, origin='upper')

    # グリッド描画範囲計算
    try:
        corners_pix = np.array([[0, 0], [w, 0], [w, h], [0, h]])
        corners_world = wcs.all_pix2world(corners_pix, 0)
        ra_min, ra_max = np.min(corners_world[:, 0]), np.max(corners_world[:, 0])
        dec_min, dec_max = np.min(corners_world[:, 1]), np.max(corners_world[:, 1])
        if ra_max - ra_min > 180: ra_min, ra_max = 0, 360
        else: ra_min, ra_max = max(0, ra_min - 10), min(360, ra_max + 10)
        dec_min, dec_max = max(-90, dec_min - 10), min(90, dec_max + 10)
    except:
        ra_min, ra_max, dec_min, dec_max = 0, 360, -90, 90

    # 天球グリッド
    grid_args = {'color': 'white', 'alpha': 0.2, 'lw': 0.5}
    start_ra = int(ra_min / 15) * 15
    end_ra = int(ra_max / 15) * 15 + 15
    for ra in range(start_ra, end_ra + 1, 15):
        if ra > 360: continue
        decs = np.linspace(dec_min, dec_max, 100)
        ras = np.full_like(decs, ra)
        try:
            pix = wcs.all_world2pix(np.stack([ras, decs], axis=1), 0, quiet=True)
            mask = ~np.isnan(pix[:, 0]) & (pix[:, 0] > -w) & (pix[:, 0] < 2*w)
            if np.any(mask): ax.plot(pix[mask, 0], pix[mask, 1], **grid_args)
        except: pass

    start_dec = int(dec_min / 10) * 10
    end_dec = int(dec_max / 10) * 10 + 10
    for dec in range(start_dec, end_dec + 1, 10):
        if dec > 90: continue
        ras = np.linspace(ra_min, ra_max, 100)
        decs_arr = np.full_like(ras, dec)
        try:
            pix = wcs.all_world2pix(np.stack([ras, decs_arr], axis=1), 0, quiet=True)
            mask = ~np.isnan(pix[:, 0]) & (pix[:, 0] > -w) & (pix[:, 0] < 2*w)
            if np.any(mask): ax.plot(pix[mask, 0], pix[mask, 1], **grid_args)
        except: pass

    # 星座線
    line_count = 0
    for feature in const_data['features']:
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_arr = np.array(line)
                if (np.max(line_arr[:,1]) < dec_min) or (np.min(line_arr[:,1]) > dec_max): continue
                try:
                    pix = wcs.all_world2pix(line_arr, 0, quiet=True)
                    if np.all(np.isnan(pix)): continue
                    mask = (pix[:, 0] > -w*0.5) & (pix[:, 0] < w*1.5) & (pix[:, 1] > -h*0.5) & (pix[:, 1] < h*1.5)
                    if np.any(mask):
                        ax.plot(pix[:, 0], pix[:, 1], color='cyan', lw=1.5, alpha=0.8)
                        line_count += 1
                except: pass
    
    print(f"   Drew {line_count} segments.")
    
    # 表示範囲を画像サイズに固定
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)

    out_file = "result_original_orient.jpg"
    # pad_inches=0 で余白を完全にゼロにする
    plt.savefig(out_file, dpi=dpi, bbox_inches='tight', pad_inches=0)
    print(f"SUCCESS: Generated '{out_file}'")
    plt.close(fig)

# ------------------------------------------------------------------
# 画像生成2: 天球向き (北が上) - 修正版
# ------------------------------------------------------------------
def draw_normalized_orientation(target_file, wcs_filename, const_data):
    print("Generating Image 2: Normalized Orientation (Full view)...")
    
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    fig = plt.figure(figsize=(12, 12))
    ax = plt.subplot(projection=wcs)
    
    ax.imshow(img_data)
    ax.coords.grid(True, color='white', ls='dotted', alpha=0.3)
    
    for feature in const_data['features']:
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_arr = np.array(line)
                ra = line_arr[:, 0]
                dec = line_arr[:, 1]
                try:
                    ax.plot(ra, dec, transform=ax.get_transform('world'), 
                            color='cyan', lw=1.5, alpha=0.8)
                except: pass

    lon = ax.coords[0]
    lat = ax.coords[1]
    lon.set_ticklabel_visible(False)
    lon.set_axislabel('')
    lat.set_ticklabel_visible(False)
    lat.set_axislabel('')

    # --- 【修正2】元の画像の全ピクセル範囲が含まれるように表示範囲を明示的に設定 ---
    # ピクセルの中心を基準に、端まで含めるよう -0.5 から w-0.5 (h-0.5) までを指定
    # origin='upper' (デフォルト) なので Y軸は反転して指定
    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(h - 0.5, -0.5)

    out_file = "result_normalized.jpg"
    # こちらは少し余白を持たせて全体が見えるようにする
    plt.savefig(out_file, dpi=150, bbox_inches='tight', pad_inches=0.1)
    print(f"SUCCESS: Generated '{out_file}'")
    plt.close(fig)

# ------------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------------
def run_analysis():
    print("Searching for image...")
    target_file = next((f for f in os.listdir(".") if "starphoto" in f.lower() and f.lower().endswith(('.png', '.jpg', '.jpeg'))), None)
    if not target_file:
        print("ERROR: 'starphoto' image not found.")
        sys.exit(1)
    print(f"Target Image Found: '{target_file}'")

    session_client = requests.Session()
    session_client.headers.update({'User-Agent': 'Mozilla/5.0 (Python script)'})

    session_id = get_session(session_client)
    sub_id = upload_image(session_client, target_file, session_id)
    job_id = wait_for_job(session_client, sub_id)

    print("Step 4: Fetching Data & Drawing...")
    
    wcs_filename = "wcs.fits"
    if not download_file(f"{BASE_URL}/wcs_file/{job_id}", wcs_filename):
        sys.exit(1)

    const_data = requests.get(CONSTELLATION_JSON_URL).json()

    # 2種類の画像を自前で生成
    draw_original_orientation(target_file, wcs_filename, const_data)
    draw_normalized_orientation(target_file, wcs_filename, const_data)

if __name__ == '__main__':
    run_analysis()
