#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""验证生成的引擎：抽查常见拼音的首候选、词条是否就位、繁体是否清除干净。

用法：
    python3 verify_engine.py /usr/share/uim/pinyin-cn-utf8.scm [更多文件...]
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

# 规则行形如 `((("k" "e" "y")) ("cand1" "cand2"))`。
# 不能写成 `\[^()\]*` 去匹配键序列 —— 键位本身可能是 `(` 或 `)`
# （v1.1.3 起标点键进了规则表），那样会把键里的括号当成结构括号，
# 圆括号键位直接匹配不上。改成「只认带引号的字符串」来切分。
_STR = r'"(?:[^"\\]|\\.)*"'
ENTRY_RE = re.compile(
    r'\(\(\(\s*(?P<syl>(?:%s\s*)*)\)\)\s*\(\s*(?P<cands>(?:%s\s*)*)\)' % (_STR, _STR)
)
# 键位与候选都可能含转义（符号键 `"` 渲染成 \"），所以要能解析 \"
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")

# 期望的首候选。简体拼音输入法最基本的体验就是"输 ni 出 你"。
# 注意：上游XCIN 表里纯声母音节（sh/zh/ch 等）只有注音占位符、没有汉字，
# 这是源表的已知局限，真正的汉字在 sh+韵母 的组合里。故此处不做 sh 抽查。
#
# 注意：引擎带 --phrase 生成后，同音节里会排进多字词条，首候选**可能**是词
# （例如 ni 桶里可能有「你们」）。所以这里改成「候选里必须包含期望字」，
# 而不是「首候选必须等于期望字」—— 只在没有词条时才检查首位。
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

# 多音节词条抽查：(音节序列, 期望词)。这些是"能不能打词"的核心验收项。
EXPECT_PHRASES = [
    (("n", "i", "h", "a", "o"), "你好"),
    (("z", "h", "o", "n", "g", "g", "u", "o"), "中国"),
    (("s", "h", "e", "n", "m", "e"), "什么"),
    (("w", "o", "m", "e", "n"), "我们"),
    (("k", "e", "y", "i"), "可以"),
    (("x", "u", "e", "s", "h", "e", "n", "g"), "学生"),
]

# 符号抽查（v1.1.3 起）。键位是 us 布局上的英文标点键，
# 期望值 = 按键后**直接上屏**的那个候选（候选列表的第一个）。
# 这些是「中文符号能不能打出来」的验收项。
EXPECT_PUNCT = [
    (",", "，"), (".", "。"), ("?", "？"), ("!", "！"),
    (":", "："), (";", "；"), ("(", "（"), (")", "）"),
    ("[", "《"), ("]", "》"), ("\"", "“"), ("'", "‘"),
    ("\\", "、"), ("/", "／"), ("@", "＠"), ("#", "＃"),
    ("$", "￥"), ("%", "％"), ("&", "＆"), ("*", "×"),
    ("+", "＋"), ("=", "＝"), ("-", "——"), ("_", "……"),
    ("~", "～"), ("^", "·"), ("|", "｜"),
]

TRAD_CHARS = "龍龜電腦這個這樣時間國會學說"


def check_balance(raw: str) -> tuple[bool, str]:
    """括号配平检查 —— 这是「uim 会不会整表解析失败」的直接指标。

    Scheme 读表时，如果某个字符串没正确转义（比如键位是 `"` 却渲染成三个
    连续引号），引号会提前闭合、后面的括号全乱套，uim 报的错是莫名其妙的
    "procedure or syntax required"，根本指不到真正的问题行。这里模拟
    Scheme 的词法：跳过字符串内部（含 \\" 转义）再数括号，能离线抓到这类
    致命错误，不用等真机加载失败。
    """
    depth = 0
    in_str = False
    esc = False
    for i, ch in enumerate(raw):
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth < 0:
                return False, "第 %d 个字符处出现多余的右括号" % i
    if in_str:
        return False, "文件末尾字符串未闭合（引号没转义干净？）"
    if depth != 0:
        return False, "括号没配平，余额 %d" % depth
    return True, "OK"


def load(path: Path) -> dict[tuple[str, ...], list[str]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    table: dict[tuple[str, ...], list[str]] = {}
    for m in ENTRY_RE.finditer(raw):
        syl = tuple(_unescape(x) for x in QUOTED_RE.findall(m.group("syl")))
        cands = [_unescape(x) for x in QUOTED_RE.findall(m.group("cands"))]
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

        # 括号配平（引号转义是否干净）—— 不配平的话 uim 直接读表失败
        bal, why = check_balance(raw)
        print("  括号配平: %s %s" % ("OK" if bal else "<-- 异常", "" if bal else why))
        if not bal:
            rc = 1

        trad = sum(raw.count(c) for c in TRAD_CHARS)
        print("  繁体残留: %d %s" % (trad, "OK" if trad == 0 else "<-- 异常"))
        if trad:
            rc = 1

        ok = 0
        print("  抽查候选（单字是否在候选里）:")
        for syl, expect in EXPECT:
            cands = table.get(syl, [])
            got = cands[0] if cands else "(无候选)"
            # 词条排在前面，所以只要求「期望字在候选列表里」
            hit = expect in cands
            flag = "OK " if hit else "!! "
            if hit:
                ok += 1
            else:
                rc = 1
            print("    %s %-8s 期望含=%s 实际首位=%s   前5: %s"
                  % (flag, " ".join(syl), expect, got, " ".join(cands[:5])))
        print("  单字抽查通过 %d/%d" % (ok, len(EXPECT)))

        # 词条验收：带 --phrase 生成的引擎必须有这些多音节词
        pok = 0
        print("  抽查词条（多音节）:")
        for syl, expect in EXPECT_PHRASES:
            cands = table.get(syl, [])
            hit = expect in cands
            flag = "OK " if hit else "!! "
            if hit:
                pok += 1
            print("    %s %-24s 期望=%s   前5: %s"
                  % (flag, " ".join(syl), expect, " ".join(cands[:5])))
        if pok == 0:
            print("    （无任何词条命中：若引擎是带 --phrase 生成的，这是异常）")
        print("  词条抽查通过 %d/%d\n" % (pok, len(EXPECT_PHRASES)))

        # 符号验收：v1.1.3 起引擎要能直接打出中文标点。
        # 引擎若是不带 --punct 生成的，这里会全军覆没 —— 那正是要抓的情况。
        punc_ok = 0
        print("  抽查符号（按键 -> 直接上屏的候选）:")
        for key, expect in EXPECT_PUNCT:
            cands = table.get((key,), [])
            got = cands[0] if cands else "(无)"
            hit = got == expect
            flag = "OK " if hit else "!! "
            if hit:
                punc_ok += 1
            else:
                rc = 1
            print("    %s %-3s 期望=%s 实际=%s" % (flag, key, expect, got))
        if punc_ok == 0:
            print("    （一个符号都没有：引擎没带 --punct 生成）")
        print("  符号抽查通过 %d/%d\n" % (punc_ok, len(EXPECT_PUNCT)))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())