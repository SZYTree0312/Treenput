#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""把仓库里的文本文件统一成 LF。

背景：本项目在 Windows 上开发、在 Linux（Mobian/phosh）上跑。.gitattributes
已声明 `*.sh text eol=lf` 等规则，但 git 的 filter 只在文件被 add 的那一刻
生效 —— 谁在 Windows 上改完直接提交，谁就会把 CRLF 带进仓库。CRLF 的 .sh
在 Linux 下由 sh 执行会直接崩（行尾的 \\r 变成命令名的一部分）。

之前踩过一次：引擎 .scm 在设备上是 CRLF 版（每行多一个 \\r，整个文件大
62883 字节），本地是 LF —— 同一份内容两个 md5，排查时极易误判成"文件损坏"。

所以留这个脚本做兜底：`--check` 挂在任何改动之后跑一遍，确认没有 CRLF 漏网。

用法：
    python3 engine/normalize_eol.py          # 实际改写
    python3 engine/normalize_eol.py --check  # 只报告，不改（有 CRLF 则退出码 1）
"""
from __future__ import annotations

import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXT_EXT = {".sh", ".py", ".scm", ".txt", ".md", ".yml", ".yaml", ".json"}
SKIP_DIRS = {".git", "__pycache__", "_archive", "node_modules"}


def iter_files():
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for fn in files:
            if os.path.splitext(fn)[1].lower() in TEXT_EXT:
                yield os.path.join(base, fn)


def main() -> int:
    check_only = "--check" in sys.argv
    fixed, dirty = [], []
    for path in iter_files():
        with open(path, "rb") as f:
            raw = f.read()
        if b"\r\n" not in raw:
            continue
        rel = os.path.relpath(path, ROOT).replace("\\", "/")
        if check_only:
            dirty.append(rel)
            continue
        with open(path, "wb") as f:
            f.write(raw.replace(b"\r\n", b"\n"))
        fixed.append(rel)

    if check_only:
        if dirty:
            print("CRLF 文件 %d 个，需要归一化：" % len(dirty))
            for r in dirty:
                print("  " + r)
            return 1
        print("全部已是 LF")
        return 0

    for r in fixed:
        print("LF <- " + r)
    print("归一化 %d 个文件" % len(fixed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
