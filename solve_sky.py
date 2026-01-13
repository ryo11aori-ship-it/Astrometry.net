import requests
import json
import time
import os
import sys
import warnings

# --- matplotlib ヘッドレス対応 ---
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

# --- 天文学ライブラリ ---
from astropy.wcs import WCS
from astropy.io import fits
import numpy as np

warnings.simplefilter('ignore')

# =========================================================
# 設定
# =========================================================
API_KEY = "frminzlefpwosbcj"

BASE_URL = "https://nova.astrometry.net"
API_URL  = "https://nova.astrometry.net/api"

CONSTELLATION_JSON_URL = (
    "https://raw.githubusercontent.com/ofrohn/"
    "d3-celestial/master/data/constellations.lines.json"
)

# =========================================================
# API 処理
# =========================================================
def get_session(session_client):
    print("Step 1: Logging in...")
    resp = session_client.post(
        f"{API_URL}/login",
        data={'request-json': json.dumps({"apikey": API_KEY})},
        timeout=30
    )
    result = resp.json()
    if result.get('status') != 'success':
        print("Login failed:", result)
        sys.exit(1)

    session_id = result['session']
    session_client.cookies.set('session', session_id)
    print("Logged in. Session ID acquired.")
    return session_id


def upload_image(session_client, target_file, session_id):
    print("Step 2: Uploading image...")

    # ★ 計算量削減用パラメータ
    args = {
        "session": session_id,
        "allow_commercial_use": "n",
        "allow_modifications": "n",
        "publicly_visible": "y",

        # --- 重要 ---
        # プレートスケール制限（例：スマホ / 一眼想定）
        "scale_units": "arcsecperpix",
        "scale_lower": 0.5,
        "scale_upper": 5.0,

        # 探索半径（全天探索を防ぐ）
        "radius": 30
    }

    with open(target_file, 'rb') as f:
        resp = session_client.post(
            f"{API_URL}/upload",
            files={'file': f},
            data={'request-json': json.dumps(args)},
            timeout=60
        )

    result = resp.json()
    if result.get('status') != 'success':
        print("Upload failed:", result)
        sys.exit(1)

    sub_id = result['subid']
    print(f"Upload success. Submission ID: {sub_id}")
    return sub_id


def wait_for_job(session_client, sub_id):
    print("Step 3: Waiting for astrometry solve...")

    max_retries = 180     # 10秒 × 180 = 30分
    sleep_sec  = 10

    for i in range(max_retries):
        time.sleep(sleep_sec)

        try:
            sub_resp = session_client.get(
                f"{API_URL}/submissions/{sub_id}",
                timeout=30
            )
            sub_data = sub_resp.json()
            jobs = [j for j in sub_data.get("jobs", []) if j is not None]

            if not jobs:
                print(f"[{i+1}/{max_retries}] Queue waiting...")
                continue

            job_id = jobs[0]
            job_resp = session_client.get(
                f"{API_URL}/jobs/{job_id}",
                timeout=30
            )
            status = job_resp.json().get("status")

            print(f"[{i+1}/{max_retries}] Job {job_id} status: {status}")

            if status == "success":
                return job_id
            if status == "failure":
                print("Astrometry solve failed.")
                sys.exit(1)

        except Exception as e:
            print("Polling warning:", e)

    print("Timed out waiting for astrometry solve.")
    sys.exit(1)


def download_file(url, filename, session_client):
    print(f"Downloading {filename}...")
    resp = session_client.get(url, allow_redirects=True, timeout=60)
    if resp.status_code != 200:
        print("Download failed:", resp.status_code)
        return False
    with open(filename, "wb") as f:
        f.write(resp.content)
    return True

# =========================================================
# 描画処理（あなたの既存ロジックを維持）
# =========================================================
def draw_original_orientation(target_file, wcs_filename, const_data):
    print("Generating image: original orientation...")

    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    dpi = 150
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.imshow(img_data, origin="upper")

    for feature in const_data["features"]:
        if feature["geometry"]["type"] != "MultiLineString":
            continue
        for line in feature["geometry"]["coordinates"]:
            arr = np.array(line)
            try:
                pix = wcs.all_world2pix(arr, 0, quiet=True)
                ax.plot(pix[:, 0], pix[:, 1],
                        color="cyan", lw=1.2, alpha=0.8)
            except:
                pass

    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)

    plt.savefig("result_original_orient.jpg",
                dpi=dpi, bbox_inches="tight", pad_inches=0)
    plt.close(fig)


def draw_normalized_orientation(target_file, wcs_filename, const_data):
    print("Generating image: normalized orientation...")

    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    wcs = WCS(fits.open(wcs_filename)[0].header)

    fig = plt.figure(figsize=(12, 12))
    ax = plt.subplot(projection=wcs)
    ax.imshow(img_data)
    ax.coords.grid(True, color="white", alpha=0.3)

    for feature in const_data["features"]:
        if feature["geometry"]["type"] != "MultiLineString":
            continue
        for line in feature["geometry"]["coordinates"]:
            arr = np.array(line)
            ax.plot(arr[:, 0], arr[:, 1],
                    transform=ax.get_transform("world"),
                    color="cyan", lw=1.2, alpha=0.8)

    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(h - 0.5, -0.5)

    plt.savefig("result_normalized.jpg",
                dpi=150, bbox_inches="tight", pad_inches=0.1)
    plt.close(fig)

# =========================================================
# メイン
# =========================================================
def run_analysis():
    print("Searching for image...")
    target_file = next(
        f for f in os.listdir(".")
        if "starphoto" in f.lower()
        and f.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    print("Target image:", target_file)

    session_client = requests.Session()
    session_client.headers.update({"User-Agent": "AstrometryClient"})

    session_id = get_session(session_client)
    sub_id = upload_image(session_client, target_file, session_id)
    job_id = wait_for_job(session_client, sub_id)

    wcs_file = "wcs.fits"
    if not download_file(f"{BASE_URL}/wcs_file/{job_id}",
                          wcs_file, session_client):
        sys.exit(1)

    const_data = requests.get(CONSTELLATION_JSON_URL).json()

    draw_original_orientation(target_file, wcs_file, const_data)
    draw_normalized_orientation(target_file, wcs_file, const_data)

    print("All done.")


if __name__ == "__main__":
    run_analysis()