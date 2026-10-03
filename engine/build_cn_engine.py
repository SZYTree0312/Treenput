#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 uim 的 pinyin-big5 候选表生成简体拼音引擎 cn-utf8。

背景
----
Debian 的 `uim-pinyin` 是空壳 metapackage（只含 /usr/share/doc），没有任何引擎文件。
唯一可用的拼音表是 `uim-data` 里的 `pinyin-big5.scm`（来自 XCIN 项目）。
该表的候选**已经是 UTF-8 汉字**，但混杂大量繁体，且没有任何词频排序
——按原始顺序选字会先蹦出「拋」「菐」这类低频字。

本脚本做三件事（纯用户态，不碰内核、不碰系统包）：
  1. 解析 pinyin-big5.scm 的候选表
  2. 用 OpenCC t2s 把候选统一成简体，并顺带做一简对多繁的合并去重
  3. 按内置词频 + 使用度启发式重排候选，生成 `pinyin-cn-utf8.scm`

用法
----
  python3 build_cn_engine.py \
      --input  /usr/share/uim/pinyin-big5.scm \
      --output /usr/share/uim/pinyin-cn-utf8.scm \
      [--freq data/frequency.txt]

`--input` 可以是任意 uim 拼音表；`--freq` 是可选的词频文件（每行一个词）。
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

# pinyin-big5.scm 里的候选行形如：
#     ((("b" "a" "i")) ("掰" "白" "百" ...))
# 音节用空格分隔的拼音字母，候选是一串双引号包裹的汉字。
ENTRY_RE = re.compile(
    r'\(\(\((?P<syllable>[^()]*)\)\)\s*\((?P<candidates>[^()]*)\)',
    re.S,
)
QUOTED_RE = re.compile(r'"([^"]*)"')

# uim 拼音表里用假名/注音符号表示"仅作占位、不是真汉字"的条目，
# 例如 "ㄚ" "ㄞ" "£"。这些不应该出现在简体中文候选里。
BOGUS_CHARS = re.compile(r'[\u3100-\u312f\u3200-\u32ff]|[£€]')

# 上游表里混入了纯符号音节（"!" "#" "|" "}" 等，见 pinyin-big5.scm 尾部）。
# 这些不是拼音音节，整条丢弃。
NON_PINYIN_SYL = re.compile(r'[^a-z0-9]')

# 单字默认使用度。先给高频常用字一份基线分，未列出的字按 0 起步。
# 这不是完整的词频库，而是"保证常用字不被生僻字挤掉"的最小集合，
# 项目提供 --freq 让使用者喂真实词频覆盖它。
COMMON_BASE = (
    "的一是了我不人在他有这个上们来到时大地为子中你说生国年着就那和要她出也得里后自以会家可下而过"
    "天去能对小多然于心学么之都好看起发当没成只如事把还用第样道想作种开美总从无情己面最女但现前些所同日"
    "手又行意动方期它头经长儿回位分爱老因很给名法间斯知世什两次使身者被高已亲其进此话常与活正感"
    "见明问力理尔点文几定本公特做外孩相西果走将月十实向声车全信重三机工物气每并别真打太新比才便夫"
    "再书部水像眼等体却加电主界门利海受听达表万少直代党务原放马史话百政位非 turning"
)
# 去掉误入的英文并去重
COMMON_BASE = "".join(ch for ch in COMMON_BASE if "\u4e00" <= ch <= "\u9fff")
CHAR_BASE_SCORE = {ch: len(COMMON_BASE) - i for i, ch in enumerate(dict.fromkeys(COMMON_BASE))}


class T2S:
    """批量繁体->简体转换器。

    逐条调用 opencc 会有上千次进程启动开销（实测超时），所以先把所有待转
    字符去重成一批，一次性喂给 opencc，再从结果里查表。
    """

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._ok = False

    def warm(self, chars: set[str]) -> None:
        todo = sorted(c for c in chars if c and BOGUS_CHARS.search(c) is None)
        if not todo:
            self._ok = True
            return
        payload = "".join(todo)
        try:
            out = subprocess.run(
                ["opencc", "-c", "t2s.json"],
                input=payload,
                capture_output=True,
                text=True,
                timeout=60,
            )
        except (OSError, subprocess.SubprocessError):
            return
        if out.returncode != 0:
            return
        converted = out.stdout.strip()
        # opencc 是一一映射，长度应一致；不一致就放弃转换而不是错位
        if len(converted) != len(payload):
            return
        self._map = dict(zip(todo, converted))
        self._ok = True

    def __call__(self, text: str) -> str:
        if not self._ok or not text:
            return text
        return "".join(self._map.get(ch, ch) for ch in text)


def parse_table(path: Path) -> dict[tuple[str, ...], list[str]]:
    """解析 uim 拼音表 -> {音节元组: 候选汉字列表}"""
    raw = path.read_text(encoding="utf-8", errors="replace")
    table: dict[tuple[str, ...], list[str]] = {}
    for match in ENTRY_RE.finditer(raw):
        syllable_raw = match.group("syllable")
        letters = QUOTED_RE.findall(syllable_raw)
        syllable = tuple(l.strip().lower() for l in letters if l.strip())
        if not syllable:
            continue
        # 丢弃纯符号音节（"!" "#" "|" "}" 等非拼音条目）
        if any(NON_PINYIN_SYL.search(s) for s in syllable):
            continue
        candidates = QUOTED_RE.findall(match.group("candidates"))
        # 去重但保持原顺序
        seen: set[str] = set()
        cleaned: list[str] = []
        for c in candidates:
            if not c or c in seen:
                continue
            seen.add(c)
            cleaned.append(c)
        if cleaned:
            table[syllable] = cleaned
    return table


def load_frequency(path: Path | None) -> dict[str, int]:
    """读取词频文件。

    返回 {词: 排名分}。排名分同时编码两件事：
      - 首次出现的次序（越小越优先）—— 使用者直接用排列顺序表达意图；
      - 出现次数（重复行加权）—— 同一词写多次表示它更常用。
    """
    order: dict[str, int] = {}
    if path is None or not path.exists():
        return order
    rank: dict[str, int] = {}
    count: dict[str, int] = defaultdict(int)
    seq = 0
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        word = line.strip()
        if not word or word.startswith("#"):
            continue
        if word not in rank:
            rank[word] = seq
            seq += 1
        count[word] += 1
    # 重复次数作为主要权重（乘大数压过次序），次序做次序权重
    for word, r in rank.items():
        order[word] = count[word] * 10_000 + (10_000 - r)
    return order


def score_candidate(cand: str, freq: dict[str, int]) -> int:
    """候选排序分数，越大越靠前。

    分层策略：
      1. 词频文件里出现过的词/字，按排名分排序（重复次数优先，其次文件内次序）。
      2. 词频文件里没有的单字，回退到内置常用字基线。
      3. 都没有（生僻字），分数为 0，保持上游原始顺序。

    早期版本用「频次 × 基线」加权，导致同频次时反被内置基线翻盘
    （内置基线是随手写的，精度远不如显式词频表），故改为分层。
    """
    hit = freq.get(cand)
    if hit is not None:
        return 1_000_000 + hit
    if len(cand) == 1:
        return CHAR_BASE_SCORE.get(cand, 0)
    return 0


def convert_entry(candidates: list[str], freq: dict[str, int], t2s: T2S) -> list[str]:
    """把一条候选转成简体、去占位符、合并同字、按使用度重排。"""
    simplified: list[str] = []
    seen: set[str] = set()
    for cand in candidates:
        # 纯注音/假名/符号占位直接丢
        if BOGUS_CHARS.search(cand):
            continue
        conv = t2s(cand)
        if not conv or BOGUS_CHARS.search(conv):
            continue
        if conv in seen:
            # 一简对多繁时多个繁体会塌缩成同一个简体，合并即可
            continue
        seen.add(conv)
        simplified.append(conv)

    # 稳定排序：分数高的在前，同分保持上游原始顺序
    indexed = list(enumerate(simplified))
    indexed.sort(key=lambda pair: (-score_candidate(pair[1], freq), pair[0]))
    return [cand for _, cand in indexed]


RULE_TEMPLATE = """;; pinyin-cn-utf8.scm -- 简体拼音引擎（由 build_cn_engine.py 生成，请勿手改）
;;
;; 上游: /usr/share/uim/pinyin-big5.scm (uim-data, XCIN 项目)
;; 处理: 繁体转简体 (OpenCC t2s) + 过滤假名占位 + 按词频重排
;; 条目: __COUNT__ 条音节，__TOTAL__ 个候选
(define pinyin-cn-utf8-rule
  '((BODY)))
"""


def render(
    table: dict[tuple[str, ...], list[str]],
    freq: dict[str, int],
    t2s: T2S,
) -> str:
    blocks: list[str] = []
    total = 0
    for syllable in sorted(table):
        candidates = convert_entry(table[syllable], freq, t2s)
        if not candidates:
            continue
        total += len(candidates)
        syl_text = " ".join('"%s"' % s for s in syllable)
        cand_text = " ".join('"%s"' % c for c in candidates)
        blocks.append("    (((%s)) (%s))" % (syl_text, cand_text))
    body = "\n".join(blocks)
    header = (
        RULE_TEMPLATE.replace("__COUNT__", str(len(blocks)))
        .replace("__TOTAL__", str(total))
        .replace("(BODY)", body)
    )
    # uim 表习惯在最后留一个换行
    return header + "\n"


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 uim 简体拼音引擎")
    ap.add_argument(
        "--input",
        default="/usr/share/uim/pinyin-big5.scm",
        help="上游 uim 拼音表（默认 pinyin-big5.scm）",
    )
    ap.add_argument("--output", required=True, help="输出的 .scm 路径")
    ap.add_argument("--freq", default=None, help="可选词频文件，每行一词")
    args = ap.parse_args()

    src = Path(args.input)
    if not src.exists():
        print("找不到上游拼音表: %s" % src, file=sys.stderr)
        return 1

    table = parse_table(src)
    if not table:
        print("上游表解析出0 条音节，格式可能不匹配: %s" % src, file=sys.stderr)
        return 1
    freq = load_frequency(Path(args.freq) if args.freq else None)

    # 先把所有候选里出现过的汉字收集起来，一次性做繁->简转换
    t2s = T2S()
    all_chars: set[str] = set()
    for cands in table.values():
        for cand in cands:
            all_chars.update(cand)
    t2s.warm(all_chars)
    print("opencc批量转换: %s (去重后 %d 个汉字)" % ("可用" if t2s._ok else "不可用，回退原样", len(t2s._map)))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render(table, freq, t2s), encoding="utf-8")

    print("已生成 %s" % out)
    print("  音节 %d 条 / 候选 %d 个" % (len(table), sum(len(v) for v in table.values())))
    if not freq:
        print("  未提供词频文件，仅用内置常用字基线排序（建议加 --freq 提升手感）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())