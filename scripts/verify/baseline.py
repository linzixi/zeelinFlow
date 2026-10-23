"""核验旧仓库基线、上游文件和新代码规模；标准输出只含校验结果。

Owner: ACE migration
Last verified: 2026-10-22
Idempotent: yes
Requires: git, migration/source baseline hashes, upstream-tree.json
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def legacy() -> dict:
    result = {}
    for name, command in [
        ("status", ["status", "--porcelain=v1"]),
        ("diff", ["diff", "--binary"]),
    ]:
        content = subprocess.check_output(
            ["git", "-C", str(ROOT.parent / "ACE"), *command],
            env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
        )
        expected = (ROOT / f"migration/source/legacy-{name}.sha256").read_text("utf-8")
        result[name + "_unchanged"] = (
            hashlib.sha256(content).hexdigest() == expected.strip()
        )
    result["head"] = (
        subprocess.check_output(
            ["git", "-C", str(ROOT.parent / "ACE"), "rev-parse", "HEAD"]
        )
        .decode()
        .strip()
    )
    return result


def upstream() -> dict:
    tree = json.loads((ROOT / "upstream-tree.json").read_text("utf-8"))["tree"]
    changed, missing, count = [], [], 0
    for entry in tree:
        if entry["type"] != "blob":
            continue
        count += 1
        path = ROOT / "deer-flow" / entry["path"]
        if not path.exists():
            missing.append(entry["path"])
            continue
        content = path.read_bytes()
        digest = hashlib.sha1(f"blob {len(content)}\0".encode() + content).hexdigest()
        if digest != entry["sha"]:
            changed.append(entry["path"])
    return {"files": count, "modified": changed, "missing": missing}


def sizes() -> list[str]:
    violations = []
    for folder in (ROOT / "extensions/ace/ace_ext", ROOT / "scripts"):
        for path in folder.rglob("*.py"):
            if "vendor" in path.parts:
                continue
            text = path.read_text("utf-8")
            relative = str(path.relative_to(ROOT))
            if len(text.splitlines()) > 600:
                violations.append(relative)
            for node in ast.walk(ast.parse(text)):
                if (
                    isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.end_lineno - node.lineno + 1 > 80
                ):
                    violations.append(f"{relative}:{node.name}")
    for path in (ROOT / "extensions/ace/ui/src").rglob("*.tsx"):
        if len(path.read_text("utf-8").splitlines()) > 300:
            violations.append(str(path.relative_to(ROOT)))
    return violations


def main() -> None:
    report = {"legacy": legacy(), "upstream": upstream(), "size_violations": sizes()}
    destination = ROOT / "output/verification/baseline.json"
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False))
    assert report["legacy"]["status_unchanged"] and report["legacy"]["diff_unchanged"]
    assert report["legacy"]["head"] == "26993007caa7869bf10ddf0b29ec94f814145213"
    assert not report["size_violations"] and not report["upstream"]["missing"]
    manifest = json.loads((ROOT / "migration/upstream-changes.json").read_text("utf-8"))
    assert set(report["upstream"]["modified"]) <= set(manifest)
    for name, entry in manifest.items():
        assert (
            hashlib.sha256((ROOT / "deer-flow" / name).read_bytes()).hexdigest()
            == entry["sha256"]
        ), name


if __name__ == "__main__":
    main()
