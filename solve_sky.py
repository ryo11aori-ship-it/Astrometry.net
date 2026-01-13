#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
solve_sky.py -- Astrometry.net 連携スクリプト（改良版）
- 明示的な timeout を付与
- requests.Session に Retry を設定
- ポーリング間隔を調整
- 例外時の詳細ログを追加
- ダウンロードを stream で処理
"""

import os
import sys
import json
import time
import requests
import http.client
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- 描画・天文学用ライブラリ ---
import matplotlib.pyplot as plt
from astropy.wcs import WCS
from astropy.io import fits
import numpy as np
import warnings

# 警告抑制（必要に応じて解除）
warnings.simplefilter('ignore')

# ---------------------------------------------------------
# 設定・定数（必要なら環境変数で上書き）
# ---------------------------------------------------------
API_KEY = os.environ.get('ASTrometry_API_KEY') or "frminzlefpwosbcj"  # ここは環境変数で渡すこと推奨
BASE_URL = "https://nova.astrometry.net"    # 可能なら HTTPS を使う
API_URL = f"{BASE_URL}/api"
CONSTELLATION_JSON_URL = "https://raw.githubusercontent.com/ofrohn/d3-celestial/master/data/constellations.lines.json"

# タイムアウト（connect timeout, read timeout）
TIMEOUT_CONNECT = 5.0
TIMEOUT_READ = 60.0
DEFAULT_TIMEOUT = (TIMEOUT_CONNECT, TIMEOUT_READ)

# リトライ設定
RETRY_TOTAL = 5
RETRY_BACKOFF = 1.0

# ポーリング設定
POLL_INTERVAL = 10        # 秒（元は5 -> 10）
MAX_POLL_ATTEMPTS = 120   # 合計待ち時間 = POLL_INTERVAL * MAX_POLL_ATTEMPTS

# 出力ファイル
OUT_WCS = "wcs.fits"
OUT_ORIG = "result_original_orient.jpg"
OUT_NORM = "result_normalized.jpg"


# ---------------------------
# ヘルパ — Session with retries
# ---------------------------
def make_session_with_retries(total_retries=RETRY_TOTAL, backoff_factor=RETRY_BACKOFF):
    s = requests.Session()
    s.headers.update({'User-Agent': 'Mozilla/5.0 (Python script)'})

    retry = Retry(
        total=total_retries,
        read=total_retries,
        connect=total_retries,
        backoff_factor=backoff_factor,
        status_forcelist=[429, 502, 503, 504],
        allowed_methods=frozenset(["HEAD", "GET", "POST", "PUT", "DELETE", "OPTIONS"])
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)
    return s


# ---------------------------
# API 呼び出し群（timeout と詳細ログ）
# ---------------------------
def get_session(session_client):
    """ログインしてセッションIDを取得"""
    print("Step 1: Logging in...")
    try:
        resp = session_client.post(
            f"{API_URL}/login",
            data={'request-json': json.dumps({"apikey": API_KEY})},
            timeout=DEFAULT_TIMEOUT
        )
        print(f"  Login HTTP {resp.status_code}")
        text = resp.text
        try:
            result = resp.json()
        except Exception:
            print("  Login response is not JSON. Body (truncated):")
            print(text[:2000])
            raise

        if result.get('status') != 'success':
            print(f"  Login Failed: {result}")
            sys.exit(1)

        session_id = result['session']
        session_client.cookies.set('session', session_id)
        print(f"  Logged in. Session ID: {session_id}")
        return session_id

    except requests.exceptions.RequestException as e:
        print("Login RequestException:", repr(e))
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
            # files をストリームで渡す
            resp = session_client.post(
                f"{API_URL}/upload",
                files={'file': f},
                data=upload_data,
                timeout=DEFAULT_TIMEOUT
            )

        print(f"  Upload HTTP {resp.status_code}")
        text = resp.text
        try:
            upload_result = resp.json()
        except Exception:
            print("  Upload response not JSON (truncated):")
            print(text[:2000])
            raise

        if upload_result.get('status') != 'success':
            print(f"  Upload Failed: {upload_result}")
            sys.exit(1)

        sub_id = upload_result['subid']
        print(f"  Upload Success. Submission ID: {sub_id}")
        return sub_id

    except requests.exceptions.RequestException as e:
        print("Upload RequestException:", repr(e))
        sys.exit(1)
    except FileNotFoundError:
        print(f"Upload Exception: target file '{target_file}' not found.")
        sys.exit(1)


def wait_for_job(session_client, sub_id):
    """解析完了待ち（堅牢なポーリング）"""
    print("Step 3: Waiting for processing...")
    for attempt in range(1, MAX_POLL_ATTEMPTS + 1):
        try:
            time.sleep(POLL_INTERVAL)
            # submissions
            resp = session_client.get(f"{API_URL}/submissions/{sub_id}", timeout=DEFAULT_TIMEOUT)
            print(f"[{attempt}] submissions HTTP {resp.status_code}")
            try:
                sub_status = resp.json()
            except Exception:
                print("  submissions response not JSON (truncated):")
                print(resp.text[:2000])
                continue

            jobs = sub_status.get('jobs')
            if jobs and len(jobs) > 0:
                job_id = jobs[0]
                if job_id:
                    resp_job = session_client.get(f"{API_URL}/jobs/{job_id}", timeout=DEFAULT_TIMEOUT)
                    print(f"  job {job_id} HTTP {resp_job.status_code}")
                    try:
                        job_json = resp_job.json()
                    except Exception:
                        print("  jobs response not JSON (truncated):")
                        print(resp_job.text[:2000])
                        continue

                    status = job_json.get('status')
                    if status == 'success':
                        print(f"Job finished successfully: {job_id}")
                        return job_id
                    elif status == 'failure':
                        print("Analysis failed.")
                        sys.exit(1)
                    else:
                        print(f"Status: {status} (attempt {attempt}/{MAX_POLL_ATTEMPTS})")
                        continue
            else:
                print(f"Waiting for job... (attempt {attempt}/{MAX_POLL_ATTEMPTS})")

        except (requests.exceptions.RequestException, http.client.RemoteDisconnected) as e:
            # 詳細ログを出して次のループで再試行
            print(f"Polling warning (attempt {attempt}): {repr(e)}")
            # リトライつきセッションがあるので continue すれば自動で再試行されることが多い
            continue

    print("Timed out waiting for job.")
    sys.exit(1)


def download_file(url, filename, session_client=None):
    """ファイルダウンロード（stream）"""
    client = session_client if session_client else requests
    print(f"Downloading {filename} from {url} ...")
    try:
        with client.get(url, allow_redirects=True, timeout=DEFAULT_TIMEOUT, stream=True) as resp:
            print(f"  download HTTP {resp.status_code}")
            if resp.status_code == 200:
                with open(filename, 'wb') as f:
                    for chunk in resp.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
                print(f"  Saved: {filename}")
                return True
            else:
                print(f"  Failed to download {filename}. Status: {resp.status_code}")
                # レスポンス本文を一部表示して原因手がかりを残す
                try:
                    print("  Response text (truncated):")
                    print(resp.text[:2000])
                except Exception:
                    pass
                return False
    except requests.exceptions.RequestException as e:
        print("  Download Error:", repr(e))
        return False


# ------------------------------------------------------------------
# 画像生成1: 元画像向き (あなたの写真と同じ向き)
# ------------------------------------------------------------------
def draw_original_orientation(target_file, wcs_filename, const_data):
    print("Generating Image 1: Original Orientation (Full view)...")
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    try:
        wcs = WCS(fits.open(wcs_filename)[0].header)
    except Exception as e:
        print("  Failed to read WCS file:", repr(e))
        raise

    dpi = 150
    fig = plt.figure(figsize=(w / dpi, h / dpi), dpi=dpi)
    ax = fig.add_axes([0, 0, 1, 1])
    ax.set_axis_off()
    ax.imshow(img_data, origin='upper')

    # グリッド描画範囲計算
    try:
        corners_pix = np.array([[0, 0], [w, 0], [w, h], [0, h]])
        corners_world = wcs.all_pix2world(corners_pix, 0)
        ra_min, ra_max = np.min(corners_world[:, 0]), np.max(corners_world[:, 0])
        dec_min, dec_max = np.min(corners_world[:, 1]), np.max(corners_world[:, 1])
        if ra_max - ra_min > 180:
            ra_min, ra_max = 0, 360
        else:
            ra_min, ra_max = max(0, ra_min - 10), min(360, ra_max + 10)
        dec_min, dec_max = max(-90, dec_min - 10), min(90, dec_max + 10)
    except Exception:
        ra_min, ra_max, dec_min, dec_max = 0, 360, -90, 90

    grid_args = {'color': 'white', 'alpha': 0.2, 'lw': 0.5}
    start_ra = int(ra_min / 15) * 15
    end_ra = int(ra_max / 15) * 15 + 15
    for ra in range(start_ra, end_ra + 1, 15):
        if ra > 360:
            continue
        decs = np.linspace(dec_min, dec_max, 100)
        ras = np.full_like(decs, ra)
        try:
            pix = wcs.all_world2pix(np.stack([ras, decs], axis=1), 0)
            mask = ~np.isnan(pix[:, 0]) & (pix[:, 0] > -w) & (pix[:, 0] < 2 * w)
            if np.any(mask):
                ax.plot(pix[mask, 0], pix[mask, 1], **grid_args)
        except Exception:
            pass

    start_dec = int(dec_min / 10) * 10
    end_dec = int(dec_max / 10) * 10 + 10
    for dec in range(start_dec, end_dec + 1, 10):
        if dec > 90:
            continue
        ras = np.linspace(ra_min, ra_max, 100)
        decs_arr = np.full_like(ras, dec)
        try:
            pix = wcs.all_world2pix(np.stack([ras, decs_arr], axis=1), 0)
            mask = ~np.isnan(pix[:, 0]) & (pix[:, 0] > -w) & (pix[:, 0] < 2 * w)
            if np.any(mask):
                ax.plot(pix[mask, 0], pix[mask, 1], **grid_args)
        except Exception:
            pass

    # 星座線
    line_count = 0
    for feature in const_data.get('features', []):
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_arr = np.array(line)
                if (np.max(line_arr[:, 1]) < dec_min) or (np.min(line_arr[:, 1]) > dec_max):
                    continue
                try:
                    pix = wcs.all_world2pix(line_arr, 0)
                    if np.all(np.isnan(pix)):
                        continue
                    mask = (pix[:, 0] > -w * 0.5) & (pix[:, 0] < w * 1.5) & (pix[:, 1] > -h * 0.5) & (pix[:, 1] < h * 1.5)
                    if np.any(mask):
                        ax.plot(pix[:, 0], pix[:, 1], color='cyan', lw=1.5, alpha=0.8)
                        line_count += 1
                except Exception:
                    pass

    print(f"   Drew {line_count} segments.")
    ax.set_xlim(0, w)
    ax.set_ylim(h, 0)

    plt.savefig(OUT_ORIG, dpi=dpi, bbox_inches='tight', pad_inches=0)
    print(f"SUCCESS: Generated '{OUT_ORIG}'")
    plt.close(fig)


# ------------------------------------------------------------------
# 画像生成2: 天球向き (北が上)
# ------------------------------------------------------------------
def draw_normalized_orientation(target_file, wcs_filename, const_data):
    print("Generating Image 2: Normalized Orientation (Full view)...")
    img_data = plt.imread(target_file)
    h, w = img_data.shape[:2]
    try:
        wcs = WCS(fits.open(wcs_filename)[0].header)
    except Exception as e:
        print("  Failed to read WCS file:", repr(e))
        raise

    fig = plt.figure(figsize=(12, 12))
    ax = plt.subplot(projection=wcs)
    ax.imshow(img_data, origin='upper')
    ax.coords.grid(True, color='white', ls='dotted', alpha=0.3)

    for feature in const_data.get('features', []):
        if feature['geometry']['type'] == 'MultiLineString':
            for line in feature['geometry']['coordinates']:
                line_arr = np.array(line)
                ra = line_arr[:, 0]
                dec = line_arr[:, 1]
                try:
                    ax.plot(ra, dec, transform=ax.get_transform('world'),
                            color='cyan', lw=1.5, alpha=0.8)
                except Exception:
                    pass

    lon = ax.coords[0]
    lat = ax.coords[1]
    lon.set_ticklabel_visible(False)
    lon.set_axislabel('')
    lat.set_ticklabel_visible(False)
    lat.set_axislabel('')

    ax.set_xlim(-0.5, w - 0.5)
    ax.set_ylim(h - 0.5, -0.5)

    plt.savefig(OUT_NORM, dpi=150, bbox_inches='tight', pad_inches=0.1)
    print(f"SUCCESS: Generated '{OUT_NORM}'")
    plt.close(fig)


# ------------------------------------------------------------------
# メイン処理
# ------------------------------------------------------------------
def run_analysis():
    print("Searching for image...")
    target_file = next((f for f in os.listdir(".") if "starphoto" in f.lower() and f.lower().endswith(('.png', '.jpg', '.jpeg', '.JPG'))), None)
    if not target_file:
        print("ERROR: 'starphoto' image not found.")
        sys.exit(1)
    print(f"Target Image Found: '{target_file}'")

    # セッション作成（Retry を含む）
    session_client = make_session_with_retries()

    # ログイン → upload → wait_for_job
    session_id = get_session(session_client)
    sub_id = upload_image(session_client, target_file, session_id)
    job_id = wait_for_job(session_client, sub_id)

    print("Step 4: Fetching Data & Drawing...")

    # WCS ファイルをダウンロード
    wcs_url = f"{BASE_URL}/wcs_file/{job_id}"
    if not download_file(wcs_url, OUT_WCS, session_client=session_client):
        sys.exit(1)

    # 星座データを取得（セッション経由で取得）
    try:
        print("Fetching constellation data...")
        resp = session_client.get(CONSTELLATION_JSON_URL, timeout=DEFAULT_TIMEOUT)
        print(f"  CONST HTTP {resp.status_code}")
        const_data = resp.json() if resp.status_code == 200 else {}
    except requests.exceptions.RequestException as e:
        print("Failed to fetch constellation JSON:", repr(e))
        const_data = {}

    # 画像生成
    try:
        draw_original_orientation(target_file, OUT_WCS, const_data)
    except Exception as e:
        print("Error during draw_original_orientation:", repr(e))

    try:
        draw_normalized_orientation(target_file, OUT_WCS, const_data)
    except Exception as e:
        print("Error during draw_normalized_orientation:", repr(e))


if __name__ == '__main__':
    run_analysis()