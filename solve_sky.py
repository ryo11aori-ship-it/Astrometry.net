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
    # 1. Login (Sessionの作成)
    # ---------------------------------------------------------
    print("Step 1: Logging in...")
    # RequestsのSessionオブジェクトを使う（Cookie保持のため）
    session_client = requests.Session()
    
    try:
        # ログイン
        resp = session_client.post(f"{API_URL}/login", data={'request-json': json.dumps({"apikey": API_KEY})})
        result = resp.json()
        if result.get('status') != 'success':
            print(f"Login Failed: {result}")
            sys.exit(1)
            
        session_id = result['session']
        print(f"Logged in. Session ID: {session_id}")
        
        # 【重要】以後の通信のためにCookieにセットしておく
        session_client.cookies.set('session', session_id)
        
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
            # Sessionクライアント経由で送信
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
    max_retries = 60 # 画像生成待ちも含めて少し長めに
    
    for i in range(max_retries):
        time.sleep(5)
        try:
            resp = session_client.get(f"{API_URL}/submissions/{sub_id}")
            sub_status = resp.json()
            if sub_status.get('jobs') and len(sub_status['jobs']) > 0:
                # 最初のジョブIDを取得
                current_job = sub_status['jobs'][0]
                if current_job:
                    # ジョブの完了ステータスを確認
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
            print(f"Polling Exception: {e}")
            
    if not job_id:
        print("Timed out waiting for Job completion.")
        sys.exit(1)

    # ---------------------------------------------------------
    # 4. Result & Annotated Image Download (AI推奨: Files経由)
    # ---------------------------------------------------------
    print("Step 4: Fetching results & Annotated Image...")
    try:
        # A. 座標データの取得
        cal_resp = session_client.get(f"{API_URL}/jobs/{job_id}/calibration")
        cal_data = cal_resp.json()
        
        print("\n" + "="*40)
        print("       ANALYSIS RESULT       ")
        print("="*40)
        print(f"Right Ascension (RA) : {cal_data.get('ra')}")
        print(f"Declination (Dec)    : {cal_data.get('dec')}")
        print("="*40 + "\n")

        # B. 星座線入り画像の取得
        # AI分析に基づく「files一覧から annotated を探す」アプローチ
        print("Searching for annotated image in job files...")
        
        output_filename = "annotated_result.jpg"
        download_success = False
        
        # 画像生成にはタイムラグがあるため、ここでもリトライループする
        img_retries = 10
        
        for i in range(img_retries):
            try:
                # --- 方法1: Files API (AI推奨) ---
                # まず、ジョブに関連するファイル一覧を取得する
                # (ドキュメントにはないが、内部APIとして存在する可能性があるため試す)
                # もしこれが404なら、方法2へ進む
                
                # 方法1 & 2 共通: 最終的にダウンロードするURL
                target_img_url = None

                # filesエンドポイントを試す（AI分析のアプローチ）
                # 注意: 存在しない場合のエラーハンドリングが必要
                files_url = f"{API_URL}/jobs/{job_id}/files" # あるいは /api/jobs/.../files
                # AstrometryのAPI仕様上、予測しづらいため、
                # ここでは「Web標準のAnnotated URL」をSession Cookie付きで叩く方法を
                # 最も確実な「方法2」としてメイン実装します。
                # 理由: /files エンドポイントはバージョンによって挙動が不明確なため。
                
                # --- 方法2: Session Cookieを使ったWeb URL直接取得 ---
                # 解説: ブラウザでログインしていると annotated_image URL は画像を返すが、
                # 素のrequestsだとHTMLを返す。
                # 今回は session_client (Cookieあり) を使っているため、これで落ちてくるはず。
                
                # ターゲットURL: http://nova.astrometry.net/annotated_image/{job_id}
                # (display ではなく image, api ではなく web root)
                target_img_url = f"{BASE_URL}/annotated_image/{job_id}"
                
                print(f"Attempting download from: {target_img_url} ({i+1}/{img_retries})")
                
                img_resp = session_client.get(target_img_url, allow_redirects=True)
                content_type = img_resp.headers.get("Content-Type", "").lower()
                
                if img_resp.status_code == 200 and "image" in content_type:
                    with open(output_filename, 'wb') as f:
                        f.write(img_resp.content)
                    print(f"SUCCESS: Saved annotated image to '{output_filename}'")
                    print(f"Content-Type: {content_type}")
                    download_success = True
                    break
                else:
                    print(f"Wait: Server returned {img_resp.status_code} ({content_type}).")
                    # まだ生成中の場合はHTMLが返ることがある
            
            except Exception as e:
                print(f"Download Attempt Error: {e}")
            
            time.sleep(5)

        if not download_success:
            print("ERROR: Failed to download annotated image after multiple attempts.")
            print("Note: The RA/Dec coordinates were retrieved successfully.")
            # 座標は取れているので、ここでexit(1)してActionsを赤くするかはお任せですが、
            # 今回は「画像必須」のオーダーなのでエラー終了させます。
            sys.exit(1)

    except Exception as e:
        print(f"Result Fetch Exception: {e}")

if __name__ == '__main__':
    run_analysis()
