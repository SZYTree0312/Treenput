#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证生成的引擎：抽查常见拼音的首候选是否正确、繁体是否清除干净。

用法：
    python3 verify_engine.py /usr/share/uim/pinyin-cn-utf8.scm [更多文件...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

ENTRY_RE = re.compile(r'\(\(\((?P<syl>[^()]*)\)\)\s*\((?P<cands>[^()]*)\)')
QUOTED_RE = re.compile(r'"([^"]*)"')

# 期望的首候选。简体拼音输入法最基本的体验就是"输 ni 出 你"。
# 注意：上游XCIN 表里纯声母音节（sh/zh/ch 等）只有注音占位符、没有汉字，
# 这是源表的已知局限，真正的汉字在 sh+韵母 的组合里。故此处不做 sh 抽查。
EXPECT = [
    (("n", "i"), "你"),
    (("h", "a", "o"), "好"),
    (("z", "h", "o", "n", "g"), "中"),
    (("g", "u", "o"), "国"),
    (("s", "h", "i"), "是"),
    (("j", "i"), "机"),
    (("w", "o"), "我"),
    (("t", "a"), "他"),
    (("d", "e"), "的"),
    (("y", "i"), "一"),
]
TRAD_CHARS = "龍龜電腦這個這樣時間國會學說"


def load(path: Path) -> dict[tuple[str, ...], list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    table: dict[tuple[str, ...], list[str]] = {}
    for m in ENTRY_RE.finditer(raw):
        syl = tuple(QUOTED_RE.findall(m.group("syl")))
        cands = QUOTED_RE.findall(m.group("cands"))
        if syl and cands:
            table.setdefault(syl, cands)
    return table


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 2
    rc = 0
    for arg in sys.argv[1:]:
        path = Path(arg)
        if not path.exists():
            print("跳过（不存在）: %s" % path)
            continue
        raw = path.read_text(encoding="utf-8", errors="replace")
        table = load(path)

        print("=== %s ===" % path.name)
        print("  音节 %d 条 / 候选 %d 个 / %d 字节"
              % (len(table), sum(len(v) for v in table.values()), len(raw)))

        trad = sum(raw.count(c) for c in TRAD_CHARS)
        print("  繁体残留: %d %s" % (trad, "OK" if trad == 0 else "<-- 异常"))
        if trad:
            rc = 1

        ok = 0
        print("  抽查首候选:")
        for syl, expect in EXPECT:
            cands = table.get(syl, [])
            got = cands[0] if cands else "(无候选)"
            flag = "OK " if got == expect else "!! "
            if got == expect:
                ok += 1
            else:
                rc = 1
            print("    %s %-8s 期望=%s 实际=%s   前5: %s"
                  % (flag, " ".join(syl), expect, got, " ".join(cands[:5])))
        print("  抽查通过 %d/%d\n" % (ok, len(EXPECT)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())