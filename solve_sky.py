#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import time
import json
import requests
from requests.exceptions import RequestException

ASTROMETRY_API = "http://nova.astrometry.net/api"

# =========================
# Utility
# =========================
def log(msg):
    print(msg, flush=True)

def safe_sleep(sec):
    """exe 環境でも確実に待つ"""
    end = time.time() + sec
    while time.time() < end:
        time.sleep(0.5)

def api_post(endpoint, data=None, files=None):
    url = f"{ASTROMETRY_API}/{endpoint}"
    r = requests.post(url, data=data, files=files, timeout=60)
    r.raise_for_status()
    return r.json()

def api_get(endpoint):
    url = f"{ASTROMETRY_API}/{endpoint}"
    r = requests.get(url, timeout=60)
    r.raise_for_status()
    return r.json()

# =========================
# Main
# =========================

def main():
    # 画像探索（先頭スペース・全角対策）
    log("Searching for image...")
    image_file = None
    for f in os.listdir("."):
        fn = f.strip().lower()
        if "starphoto" in fn and fn.endswith((".jpg", ".jpeg", ".png")):
            image_file = f
            break

    if not image_file:
        log("Image not found.")
        sys.exit(1)

    log(f"Target image: {image_file}")

    api_key = "frminzlefpwosbcj"

    # Step 1: Login
    log("Step 1: Logging in...")
    login = api_post(
        "login",
        data={"request-json": json.dumps({"apikey": api_key})}
    )

    session = login.get("session")
    if not session:
        log("Login failed.")
        sys.exit(1)

    log("Logged in. Session ID acquired.")

    # Step 2: Upload
    log("Step 2: Uploading image...")
    with open(image_file, "rb") as f:
        upload = api_post(
            "upload",
            data={
                "request-json": json.dumps({
                    "session": session,
                    "publicly_visible": "y",
                    "allow_commercial_use": "n",
                    "allow_modifications": "n",

                    # ★ ここが重要（過拘束しない）
                    "scale_units": "arcsecperpix",
                    "scale_lower": 0.1,
                    "scale_upper": 20.0
                })
            },
            files={"file": f}
        )

    sub_id = upload.get("subid")
    if not sub_id:
        log("Upload failed.")
        sys.exit(1)

    log(f"Upload success. Submission ID: {sub_id}")

    # Step 3: Wait for job
    log("Step 3: Waiting for astrometry solve...")
    job_id = None

    for i in range(60):
        sub = api_get(f"submissions/{sub_id}")
        jobs = sub.get("jobs", [])
        if jobs and jobs[0] is not None:
            job_id = jobs[0]
            break
        safe_sleep(5)

    if not job_id:
        log("Job ID not assigned.")
        sys.exit(1)

    # Step 4: Poll job
    for i in range(180):
        try:
            job = api_get(f"jobs/{job_id}")
            status = job.get("status")
        except RequestException as e:
            log(f"Polling warning: {e}")
            safe_sleep(5)
            continue

        log(f"[{i+1}/180] Job {job_id} status: {status}")

        if status == "success":
            log("Astrometry solve SUCCESS.")
            sys.exit(0)

        if status == "failure":
            log("Astrometry solve FAILED.")
            sys.exit(1)

        safe_sleep(10)

    log("Timed out waiting for solve.")
    sys.exit(1)


if __name__ == "__main__":
    main()