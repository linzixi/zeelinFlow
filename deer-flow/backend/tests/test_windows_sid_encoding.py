"""Windows whoami 的用户名编码不应影响 ASCII SID 解析。"""

import subprocess
import sys

import pytest

from deerflow.integrations import lark_cli


@pytest.mark.parametrize("encoding,name", [("gbk", "林子夕"), ("utf-8", "林子夕"), ("cp1252", "André")])
def test_sid_probe_handles_native_non_utf8_output(monkeypatch, encoding, name):
    sid = "S-1-5-21-123-456-789-1001"
    output = f'"desktop\\{name}","{sid}"\r\n'.encode(encoding)
    real_run = subprocess.run

    def run(args, **kwargs):
        assert args == ["whoami", "/user", "/fo", "csv", "/nh"]
        # 原样模拟系统命令字节输出；不替换生产代码的解码/CSV解析。
        kwargs.setdefault("encoding", "utf-8")
        return real_run([sys.executable, "-c", f"import os; os.write(1, {output!r})"], **kwargs)

    monkeypatch.setattr(lark_cli.subprocess, "run", run)
    assert lark_cli._resolve_current_user_sid() == sid
