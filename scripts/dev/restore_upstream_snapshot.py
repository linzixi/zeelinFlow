"""按官方 Git tree 校验并补齐固定提交的源码快照，不创建或提交 Git 仓库。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: upstream-tree.json、GitHub raw HTTPS
"""

from __future__ import annotations

import hashlib
import json
import os
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGET = ROOT / "deer-flow"
SHA = "66508d7522015ab6582105130da691e2803eba0d"


def blob_hash(data: bytes) -> str:
    return hashlib.sha1(f"blob {len(data)}\0".encode() + data).hexdigest()


def valid(item: dict) -> bool:
    path = TARGET / item["path"]
    if not path.exists():
        return False
    data = os.readlink(path).encode() if path.is_symlink() else path.read_bytes()
    return blob_hash(data) == item["sha"]


def restore(item: dict) -> str:
    relative = Path(item["path"])
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("上游路径越界")
    url = f"https://raw.githubusercontent.com/bytedance/deer-flow/{SHA}/{item['path']}"
    error = None
    for _attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=30) as response:
                data = response.read()
            if blob_hash(data) != item["sha"]:
                raise ValueError("上游 blob 校验失败")
            path = TARGET / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            if item["mode"] == "120000":
                if path.exists() or path.is_symlink():
                    path.unlink()
                path.symlink_to(data.decode())
            else:
                path.write_bytes(data)
            return item["path"]
        except (OSError, ValueError) as exc:
            error = exc
    raise RuntimeError(f"下载失败：{item['path']} ({type(error).__name__})")


def main() -> None:
    tree = json.loads((ROOT / "upstream-tree.json").read_text(encoding="utf-8-sig"))
    if tree.get("truncated") or tree["sha"] != SHA:
        raise ValueError("上游树不完整或版本不一致")
    files = [item for item in tree["tree"] if item["type"] == "blob"]
    missing = [item for item in files if not valid(item)]
    print(f"校验 {len(files)} 文件，需补齐 {len(missing)}", flush=True)
    failed = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        pending = [pool.submit(restore, item) for item in missing]
        for index, future in enumerate(as_completed(pending), 1):
            try:
                future.result()
            except RuntimeError as exc:
                failed.append(str(exc))
            if index % 100 == 0 or index == len(pending):
                print(f"已处理 {index}/{len(pending)}，失败 {len(failed)}", flush=True)
    if failed:
        print("\n".join(failed))
        raise SystemExit(1)
    unmatched = [item["path"] for item in files if not valid(item)]
    if unmatched:
        raise RuntimeError(f"最终校验失败：{unmatched[:10]}")
    manifest = {
        "url": "https://github.com/bytedance/deer-flow",
        "commit": SHA,
        "branch": "main",
        "version": "2.2.0-dev",
        "files": len(files),
        "verified_at": datetime.now(UTC).isoformat(),
        "verification": "Every file matches GitHub Git blob SHA-1 at fixed commit",
    }
    (ROOT / "UPSTREAM.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    print("完整上游快照逐文件校验通过", flush=True)


if __name__ == "__main__":
    main()
