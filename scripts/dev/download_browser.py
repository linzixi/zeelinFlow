"""下载官方 Playwright 浏览器分段包；校验范围、ZIP CRC 后安装。

Owner: ACE migration
Last verified: 2026-10-23
Idempotent: yes, reuses verified range parts
Requires: internet; CLI stdout contains progress only
"""

from __future__ import annotations

import os
import time
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[2]
URL = "https://storage.googleapis.com/chrome-for-testing-public/149.0.7827.55/win64/chrome-headless-shell-win64.zip"
SIZE = 119099822
CHUNK = 1024 * 1024
PARTS = ROOT / ".runtime/browser-parts"


def download(index):
    start, end = index * CHUNK, min((index + 1) * CHUNK, SIZE) - 1
    target = PARTS / f"{index:04d}.part"
    if target.exists() and target.stat().st_size == end - start + 1:
        return target
    for attempt in range(5):
        try:
            with httpx.Client(timeout=120, follow_redirects=True) as client:
                result = client.get(URL, headers={"Range": f"bytes={start}-{end}"})
                if (
                    result.status_code != 206
                    or result.headers.get("content-range")
                    != f"bytes {start}-{end}/{SIZE}"
                ):
                    raise ValueError("Official archive range mismatch")
                if len(result.content) != end - start + 1:
                    raise ValueError("Incomplete archive range")
                target.write_bytes(result.content)
                return target
        except (httpx.HTTPError, ValueError):
            if attempt == 4:
                raise
            time.sleep(attempt + 1)


def main():
    PARTS.mkdir(parents=True, exist_ok=True)
    count = (SIZE + CHUNK - 1) // CHUNK
    with ThreadPoolExecutor(max_workers=32) as pool:
        futures = [pool.submit(download, i) for i in range(count)]
        for done, future in enumerate(as_completed(futures), 1):
            future.result()
            if done % 10 == 0 or done == count:
                print(f"Official browser parts: {done}/{count}", flush=True)
    archive = PARTS.parent / "chrome-headless-shell.zip"
    with archive.open("wb") as output:
        for index in range(count):
            output.write((PARTS / f"{index:04d}.part").read_bytes())
    destination = (
        Path(os.environ["LOCALAPPDATA"]) / "ms-playwright/chromium_headless_shell-1228"
    )
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        for member in bundle.namelist():
            if (
                not (destination / member)
                .resolve()
                .is_relative_to(destination.resolve())
            ):
                raise ValueError("Archive path escaped browser directory")
        bundle.extractall(destination)
    (destination / "INSTALLATION_COMPLETE").write_text("", encoding="utf-8")
    print("Official archive CRC passed; browser installed.", flush=True)


if __name__ == "__main__":
    main()
