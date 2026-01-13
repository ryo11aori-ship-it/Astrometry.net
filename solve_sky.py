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
    BASE_URL = "http://nova.astrometry.net"
    API_URL = "http://nova.astrometry.net/api"
    
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
    # 1. Login (Session保持)
    # ---------------------------------------------------------
    print("Step 1: Logging in...")
    session_client = requests.Session()
    # ブラウザらしく見せるためのヘッダー
    session_client.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    })
    
    try:
        resp = session_client.post(f"{API_URL}/login", data={'request-json': json.dumps({"apikey": API_KEY})})
        result = resp.json()
        if result.get('status') != 'success':
            print(f"Login Failed: {result}")
            sys.exit(1)
        session_id = result['session']
        print(f"Logged in. Session ID: {session_id}")
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
            resp = session_client.get(f"{API_URL}/submissions/{sub_id}")
            sub_status = resp.json()
            if sub_status.get('jobs') and len(sub_status['jobs']) > 0:
                current_job = sub_status['jobs'][0]
                if current_job:
                    # ジョブステータス確認
                    job_resp = session_client.get(f"{API_URL}/jobs/{current_job}")
                    job_status = job_resp.json()
                    status_str = job_status.get('status')
                    
                    if status_str == 'success':
                        job_id = current_job
                        print(f"Job finished successfully: {job_id}")
                        break
                    elif status_str == 'failure':
                        print("Astrometry analysis failed.")
                        sys.exit(1)
                    else:
                         print(f"Job processing... Status: {status_str} ({i+1}/{max_retries})")
            else:
                 print(f"Waiting for job assignment... ({i+1}/{max_retries})")
        except Exception as e:
            # 接続エラーなどが起きてもリトライを続ける
            print(f"Polling Warning: {e}")
            time.sleep(5)
            
    if not job_id:
        print("Timed out waiting for Job completion.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. Result & Annotated Image Download (Files API 探索)
    # ---------------------------------------------------------
    print("Step 4: Searching for result files...")
    
    # RA/Dec 表示
    try:
        cal_resp = session_client.get(f"{API_URL}/jobs/{job_id}/calibration")
        cal_data = cal_resp.json()
        print(f"RA: {cal_data.get('ra')}, Dec: {cal_data.get('dec')}")
    except:
        pass

    # --- 本番: Files APIを使って画像の正体を探す ---
    # ここでHTMLではなく、JSONでファイル一覧を取得します
    print("Accessing Job Files List...")
    download_success = False
    output_filename = "annotated_result.jpg"
    
    # 試行回数
    search_retries = 10
    
    for i in range(search_retries):
        try:
            # ジョブに関連する全ファイルを取得するURL
            # 例: http://nova.astrometry.net/api/jobs/123456/info/ (filesを含む場合がある)
            # または http://nova.astrometry.net/api/jobs/123456 (filesキーがあるか確認)
            
            # まずは jobs/{id} 自体を確認
            job_info_url = f"{API_URL}/jobs/{job_id}"
            info_resp = session_client.get(job_info_url)
            info_data = info_resp.json()
            
            # デバッグ: どんな情報が返ってきているか一部表示
            print(f"Job Info Keys: {list(info_data.keys())}")
            
            # もしここに直接 'annotated_image' などのキーがあればラッキー
            # 無い場合が多いので、推測されるファイル名やエンドポイントを試す
            
            # アプローチA: ブラウザ用URLのソースをHTMLとしてDLして、その中から画像リンクを探す
            # Files APIが公開されていない場合、これが最後の手段
            print(f"Scraping HTML for image source... ({i+1}/{search_retries})")
            
            # annotated_full は一番解像度が高い
            html_url = f"{BASE_URL}/annotated_full/{job_id}"
            html_resp = session_client.get(html_url)
            html_text = html_resp.text
            
            # HTMLの中から <img src="..."> を探す強力なロジック
            # astrometry.net の画像パスは大体 /image/ や /user_images/ を含む
            import re
            # パターン: src=".../image/..." または src=".../user_images/..."
            # 拡張子が jpg/png のものを優先
            candidates = re.findall(r'src=["\']([^"\']+\.(?:jpg|png|jpeg))["\']', html_text)
            
            # 見つからなければ、より広い条件で探す
            if not candidates:
                 candidates = re.findall(r'src=["\'](/image/[^"\']+)["\']', html_text)
            
            if candidates:
                print(f"Found candidate images in HTML: {candidates}")
                
                # 最初に見つかった有力候補をダウンロード
                target_path = candidates[0]
                
                # 相対パスなら絶対パスにする
                if target_path.startswith("/"):
                    real_img_url = f"{BASE_URL}{target_path}"
                elif target_path.startswith("http"):
                    real_img_url = target_path
                else:
                    real_img_url = f"{BASE_URL}/{target_path}"
                
                print(f"Downloading real image from: {real_img_url}")
                
                img_resp = session_client.get(real_img_url)
                ct = img_resp.headers.get("Content-Type", "").lower()
                
                if img_resp.status_code == 200 and "image" in ct:
                    with open(output_filename, 'wb') as f:
                        f.write(img_resp.content)
                    print(f"SUCCESS: Annotated image saved to {output_filename}")
                    download_success = True
                    break
                else:
                    print(f"Wait: Link found but returned {ct}")
            else:
                print("Wait: No image link found in HTML yet (Server still rendering?)")
        
        except Exception as e:
            print(f"Search Error: {e}")
        
        time.sleep(5)

    if not download_success:
        print("ERROR: Failed to extract image from HTML.")
        # 失敗してもアーティファクト(exe)は残すため、ここでは正常終了扱いにする
        # ただしログにはエラーを残す
        sys.exit(1)

if __name__ == '__main__':
    run_analysis()
