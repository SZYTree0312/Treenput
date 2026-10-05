#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""生成 Treenput 的词条拼音表 data/phrase.txt。

为什么要单独一步
----------------
uim 自带的三张拼音表（pinyin-big5.scm / py.scm / pyunihan.scm）经审计，
**没有任何多字词条**：全是单音节 -> 单字映射。所以 `nihao` 在 `ni` 处
精确命中后，候选里根本没有「你好」，再输 `h` 就断了。这是「打完一个汉字
就锁死、没有联想」的真正根因，不是配置问题。

uim 的 rk 引擎本身**支持**多音节键（表里 `hao` 就是 ("h" "a" "o")），
只是没人往表里放词。本脚本负责把外部词库转成 uim 规则表能吃的形态。

数据来源
--------
  jieba    —— 词条 + 词频（MIT）
  pypinyin —— 汉字 -> 无声调拼音，正好补上多音字（MIT）

产物
----
  data/phrase.txt   每行 ` syllables<TAB>词<TAB>词频`（按词频降序）
  只保留「每个字的音节都能在单字表里拼出来」的词，否则用户根本打不出来。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

# 纯汉字（不含标点、字母、数字）
HANZI_ONLY = re.compile(r'[\u4e00-\u9fff]+')


def find_dict_file() -> Path:
    import jieba
    return Path(jieba.__file__).parent / 'dict.txt'


def load_jieba(min_len: int, max_len: int, limit: int | None) -> list[tuple[str, int]]:
    """读 jieba 词频表，返回 [(词, 词频)] 按词频降序。"""
    path = find_dict_file()
    if not path.exists():
        print("找不到 jieba dict.txt: %s" % path, file=sys.stderr)
        return []
    rows: list[tuple[str, int]] = []
    pat = re.compile(r'[\u4e00-\u9fff]{%d,%d}' % (min_len, max_len))
    with path.open(encoding='utf-8') as fh:
        for line in fh:
            parts = line.split()
            if len(parts) < 2:
                continue
            word, freq = parts[0], parts[1]
            if not pat.fullmatch(word):
                continue
            try:
                rows.append((word, int(freq)))
            except ValueError:
                continue
    rows.sort(key=lambda x: (-x[1], x[0]))
    if limit:
        rows = rows[:limit]
    return rows


def word_to_syllables(word: str) -> list[str] | None:
    """汉字词 -> 无声调音节列表；任一字无音节则返回 None。"""
    from pypinyin import Style, lazy_pinyin
    parts = lazy_pinyin(word, style=Style.NORMAL, errors=lambda x: None)
    if not parts or any(p is None or not p.isascii() or not p.isalpha() for p in parts):
        return None
    return [p.lower() for p in parts]


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 Treenput 词条拼音表")
    ap.add_argument('--out', required=True, help='输出 phrase.txt 路径')
    ap.add_argument('--min-len', type=int, default=2, help='最短词长（字）')
    ap.add_argument('--max-len', type=int, default=4, help='最长词长（字）')
    ap.add_argument('--limit', type=int, default=80000, help='取词频最高的 N 条')
    ap.add_argument('--syllables', default=None,
                    help='可选：单字表音节集合文件，用于过滤打不出来的词')
    args = ap.parse_args()

    rows = load_jieba(args.min_len, args.max_len, args.limit)
    if not rows:
        print('jieba 词频表为空或不可读', file=sys.stderr)
        return 1
    print('候选词（%d-%d 字，取前 %d）: %d 条'
          % (args.min_len, args.max_len, args.limit, len(rows)))

    # 上游单字表的**完整音节**集合。
    #
    # 重要：XCIN 表按完整音节索引（hao / zhi / shi），**不含** zh/ch/sh/h/l/q/x
    # 这类裸单字母音节。所以校验必须按「整音节」查，不能把 zh+ang 拆成查。
    # 直接后果：pypinyin 里 lü/nü 会被写成 lv/nv，uim 表里没有，必须丢掉。
    syl_ok: set[str] | None = None
    if args.syllables and Path(args.syllables).exists():
        raw = Path(args.syllables).read_text(encoding='utf-8', errors='replace')
        syl_ok = set()
        for m in re.finditer(r'\(\(\(([^()]*)\)\)\s*\(([^()]*)\)', raw, re.S):
            keys = [x.strip().lower() for x in re.findall(r'"([^"]*)"', m.group(1))]
            if not keys or any(k.isdigit() for k in keys):
                continue
            syl_ok.add(''.join(keys))
        print('单字表完整音节数: %d（用于过滤）' % len(syl_ok))

    out_lines: list[str] = []
    dropped_nopy = 0
    dropped_syl = 0
    for word, freq in rows:
        parts = word_to_syllables(word)
        if not parts:
            dropped_nopy += 1
            continue
        if syl_ok is not None:
            # 整词里任一音节不在单字表里就丢掉（典型：lü -> lv，uim表里没有）
            if not all(p in syl_ok for p in parts):
                dropped_syl += 1
                continue
        out_lines.append('%s\t%s\t%d' % (' '.join(parts), word, freq))

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text('\n'.join(out_lines) + '\n', encoding='utf-8', newline='\n')
    print('已生成 %s' % out)
    print('  词条 %d 条' % len(out_lines))
    print('  丢弃: 无拼音 %d / 音节拼不出 %d' % (dropped_nopy, dropped_syl))
    print('  文件大小: %.1f KB' % (out.stat().st_size / 1024))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())