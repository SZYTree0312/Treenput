#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 uim 的 pinyin-big5 候选表生成简体拼音引擎 cn-utf8。

Treenput（树入法）—— 移动 Linux 简体拼音输入方案
    https://github.com/SZYTree0312/Treenput

背景
----
Debian 的 `uim-pinyin` 是空壳 metapackage（只含 /usr/share/doc），没有任何引擎文件。
唯一可用的拼音表是 `uim-data` 里的 `pinyin-big5.scm`（来自 XCIN 项目）。
该表的候选**已经是 UTF-8 汉字**，但混杂大量繁体，且没有任何词频排序
——按原始顺序选字会先蹦出「拋」「菐」这类低频字。

本脚本做三件事（纯用户态，不碰内核、不碰系统包）：
  1. 解析 pinyin-big5.scm 的候选表
  2. 用 OpenCC t2s 把候选统一成简体，并顺带做一简对多繁的合并去重
  3. 按词频分层排序候选，生成 `pinyin-cn-utf8.scm`

用法
----
  python3 build_cn_engine.py \
      --input  /usr/share/uim/pinyin-big5.scm \
      --output /usr/share/uim/pinyin-cn-utf8.scm \
      [--freq data/frequency.txt] [--phrase data/phrase.txt]

`--input` 可以是任意 uim 拼音表；`--freq` 是可选的词频文件（每行一个词）；
`--phrase` 是 build_phrase_dict.py 产出的词条表（音节 + 词 + 词频）。

为什么需要 --phrase
-------------------
上游表（以及 uim 自带的 py.scm / pyunihan.scm）经审计**全是单音节->单字**，
没有任何多字词条。于是输入 `nihao` 时，`ni` 精确命中后候选里没有「你好」，
用户只能拿到「你」，再输 `h` 就断 —— 表现为「打完一个汉字就锁死、没有联想」。

uim 的 rk 引擎本身支持多音节键（表里 `hao` 就是 ("h" "a" "o")），最长前缀
匹配，只是没人往表里放词。--phrase 就是把这些词填进去。词条会排在同音节
单字候选**前面**，这样「你好」先于「你妮泥尼」出现。
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
#
# 注意：不能写成 `\[^()\]*` 去匹配键序列 —— 键位本身可以是 `(`、`)` 这类
# 标点（v1.1.3 起符号键进表），那样括号会被当成结构括号，圆括号键位直接
# 匹配不上。只认「带引号的字符串」来切分才稳。
_STR = r'"(?:[^"\\]|\\.)*"'
ENTRY_RE = re.compile(
    r'\(\(\(\s*(?P<syllable>(?:%s\s*)*)\)\)\s*'
    r'\(\s*(?P<candidates>(?:%s\s*)*)\)' % (_STR, _STR),
    re.S,
)
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')
ESCAPED_QUOTED_RE = QUOTED_RE


def scm_escape(s: str) -> str:
    """Scheme 字符串转义：反斜杠与双引号。与 userdict.py 的 _escape 一致。

    不转义的话双引号键位会渲染出三个连续引号，非法 Scheme，
    uim 解析直接失败，整张表作废 —— 真机踩过的坑。
    """
    return s.replace("\\", "\\\\").replace('"', '\\"')


def scm_unescape(s: str) -> str:
    return s.replace('\\"', '"').replace("\\\\", "\\")


def _render_entry(syllable: tuple[str, ...], candidates: list[str]) -> str:
    """渲染一条规则行（含转义）。"""
    syl_text = " ".join('"%s"' % scm_escape(s) for s in syllable)
    cand_text = " ".join('"%s"' % scm_escape(c) for c in candidates)
    return "    (((%s)) (%s))" % (syl_text, cand_text)

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
    "再书部水像眼等体却加电主界门利海受听达表万少直代党务原放马史话百政位非"
)
# 去掉误入的英文并去重
COMMON_BASE = "".join(ch for ch in COMMON_BASE if "\u4e00" <= ch <= "\u9fff")
CHAR_BASE_SCORE = {ch: len(COMMON_BASE) - i for i, ch in enumerate(dict.fromkeys(COMMON_BASE))}


class T2S:
    """批量繁体->简体转换器。

    逐条调用 opencc 会有上千次进程启动开销（实测超时），所以先把所有待转
    字符去重成一批，一次性喂给 opencc，再从结果里查表。

    两种后端：
      -命令行 `opencc`（Debian 上由apt 装，最稳）
      - Python 模块 `opencc`（opencc-python-reimplemented，跨平台）
    命令行不存在时自动回退到模块；都没有就保持原样（仍能生成，只是繁体残留）。
    """

    def __init__(self) -> None:
        self._map: dict[str, str] = {}
        self._ok = False
        self._backend = "none"

    def warm(self, chars: set[str]) -> None:
        todo = sorted(c for c in chars if c and BOGUS_CHARS.search(c) is None)
        if not todo:
            self._ok = True
            self._backend = "noop"
            return
        payload = "".join(todo)

        # 优先用模块：跨平台，且省掉进程启动
        try:
            import opencc as _pyopencc  # type: ignore

            conv = _pyopencc.OpenCC("t2s")
            converted = conv.convert(payload)
            self._backend = "python-module"
        except Exception:
            converted = None

        if converted is None:
            try:
                out = subprocess.run(
                    ["opencc", "-c", "t2s.json"],
                    input=payload,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                if out.returncode == 0:
                    converted = out.stdout.strip()
                    self._backend = "cli"
            except (OSError, subprocess.SubprocessError):
                converted = None

        if converted is None:
            return
        # opencc 是一一映射，长度应一致；不一致就放弃转换而不是错位
        if len(converted) != len(payload):
            self._backend = "none"
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
        letters = [scm_unescape(x) for x in ESCAPED_QUOTED_RE.findall(syllable_raw)]
        syllable = tuple(l.strip().lower() for l in letters if l.strip())
        if not syllable:
            continue
        # 丢弃纯符号音节（"!" "#" "|" "}" 等非拼音条目）
        if any(NON_PINYIN_SYL.search(s) for s in syllable):
            continue
        candidates = [scm_unescape(x) for x in ESCAPED_QUOTED_RE.findall(match.group("candidates"))]
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
    """把一条候选转成简体、去占位符、合并同字、按使用度重排。

    词条（多字候选）恒定排在单字之前：它们按词频已经排好序，
    再交给 score_candidate 会被判成 0 分压到末尾，所以这里单独留head。
    """
    simplified: list[str] = []
    seen: set[str] = set()
    head: list[str] = []          # 已确定优先的多字词条
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
        if len(conv) >= 2:
            head.append(conv)
        else:
            simplified.append(conv)

    # 稳定排序：分数高的在前，同分保持上游原始顺序
    indexed = list(enumerate(simplified))
    indexed.sort(key=lambda pair: (-score_candidate(pair[1], freq), pair[0]))
    return head + [cand for _, cand in indexed]


def load_phrases(path: Path | None) -> dict[tuple[str, ...], list[tuple[str, int]]]:
    """读取词条表 -> {键元组: [(词, 词频), ...]按词频降序}。

    词条表格式（每行）：`ni hao<TAB>你好<TAB>59317`
    空行与 # 开头的行忽略。

    键的表示法必须与上游表一致：上游 `pinyin-big5.scm` 的键是**逐字母**的
    （`"a" "i"` = 先按 a 再按 i 两键），所以词条 `ni hao` 必须展成
    `("n","i","h","a","o")`。若图省事写成 `("ni","hao")`，uim 会把它当成
    按「ni」「hao」这种非法键，词条永远匹配不上 —— 这是实测踩过的坑。
    """
    out: dict[tuple[str, ...], list[tuple[str, int]]] = defaultdict(list)
    if path is None or not path.exists():
        return out
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.rstrip('\n')
        if not line or line.startswith('#'):
            continue
        parts = line.split('\t')
        if len(parts) < 2:
            continue
        syllables = [p.strip().lower() for p in parts[0].split() if p.strip()]
        word = parts[1].strip()
        if not syllables or not word:
            continue
        try:
            freq = int(parts[2]) if len(parts) > 2 else 0
        except ValueError:
            freq = 0
        # 展平成逐字母，与上游表同构
        keys: list[str] = []
        for syl in syllables:
            keys.extend(syl)
        out[tuple(keys)].append((word, freq))
    # 词频降序；同频次按词长升序（短词优先，占用更少按键）
    for syl in out:
        out[syl].sort(key=lambda wf: (-wf[1], len(wf[0])))
    return out


def load_punct(path: Path | None) -> dict[tuple[str, ...], list[str]]:
    """读取符号表 -> {键元组: 候选列表}。

    格式（每行）：`键序列<TAB>候选1[<TAB>候选2 ...]`，# 开头注释。
    键是逐字符的，与引擎键同构（`, ` -> (",",)；候选1 是默认上屏的，
    其余进候选窗。

    为什么需要这个文件：上游 pinyin-big5.scm 尾部虽有 41 条符号条目，
    但候选混着全角变体与竖排符号、引号绑在 #'/#\\ 组合键上（拇指键盘
    按不出），所以这里用一份精选表替代，不依赖上游。
    """
    out: dict[tuple[str, ...], list[str]] = {}
    if path is None or not path.exists():
        return out
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.rstrip("\n")
        # 注释行：# 后跟空格或行尾。不能一刀切 startswith("#") ——
        # `#` 本身是个键位（＃），它的行是 "#\t＃"，会被误当注释吞掉。
        if not line or line == "#" or line.startswith("# "):
            continue
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        keys = tuple(parts[0].strip())
        cands = [c.strip() for c in parts[1:] if c.strip()]
        if not keys or not cands:
            continue
        # 去重保持顺序
        seen: set[str] = set()
        dedup: list[str] = []
        for c in cands:
            if c not in seen:
                seen.add(c)
                dedup.append(c)
        out[keys] = dedup
    return out


def merge_punct(
    table: dict[tuple[str, ...], list[str]],
    punct: dict[tuple[str, ...], list[str]],
) -> int:
    """把符号候选并进规则表。

    符号键（", " "." 等）与拼音音节键共享同一张 rk 规则表：rk 是
    front-match 按序列匹配，单键 `(", " )` 是个独立条目，不会和字母
    键冲突（打字时不会按出逗号键）。合并时符号候选**排在该键候选的
    最前面** —— 不过符号键的桶里本来就只有符号，直接 setdefault 落桶。
    """
    added = 0
    for keys, cands in punct.items():
        bucket = table.setdefault(keys, [])
        existing = set(bucket)
        fresh = [c for c in cands if c not in existing]
        if fresh:
            table[keys] = fresh + bucket
            added += len(fresh)
    return added


def merge_phrases(
    table: dict[tuple[str, ...], list[str]],
    phrases: dict[tuple[str, ...], list[tuple[str, int]]],
) -> int:
    """把词条并进规则表。

    键已经是逐字母（见 load_phrases），与单字表键**同构**，所以能直接落进
    同一个桶：

      - `("n","i")` 桶 -> 「你好」「你们」... 排在「你 妮 泥」**前面**
      - `("n","i","h","a","o")` 是**新桶** -> 只有「你好」
        这是 rk 最长前缀匹配起作用的地方：输到 `nih` 时引擎就会提示
        「你好+ao」，输完 `nihao` 精确命中。
    """
    added = 0
    for syllables, words in phrases.items():
        bucket = table.setdefault(syllables, [])
        existing = set(bucket)
        head: list[str] = []
        for word, _freq in words:
            if word in existing:
                continue
            existing.add(word)
            head.append(word)
        if head:
            # 词在前，单字在后
            table[syllables] = head + bucket
            added += len(head)
    return added


RULE_TEMPLATE = """;; pinyin-cn-utf8.scm -- 简体拼音引擎
;;
;; 由 Treenput（树入法）生成，请勿手改。
;;     https://github.com/SZYTree0312/Treenput
;;     重新生成: python3 engine/build_cn_engine.py \\
;;         --input /usr/share/uim/pinyin-big5.scm \\
;;         --output /usr/share/uim/pinyin-cn-utf8.scm \\
;;         --freq data/frequency.txt --phrase data/phrase.txt \\
;;         --punct data/punct.txt
;;
;; 上游表: /usr/share/uim/pinyin-big5.scm (uim-data, XCIN 项目)
;; 处理:   繁体转简体 (OpenCC t2s) + 过滤注音/假名占位 + 词频分层排序
;; 词条:   __PHRASE__ 条多音节词（jieba词频 + pypinyin，见engine/build_phrase_dict.py）
;; 符号:   __PUNCT__ 个中文标点/符号候选（data/punct.txt）
;; 条目:   __COUNT__ 条音节，__TOTAL__ 个候选
(define pinyin-cn-utf8-rule
  '((BODY)))

;; ---- 把规则表注册成 uim 输入法 "cn" ----------------------------------
;; uim 1.9.6（Debian trixie）里注册输入法的官方途径是 generic-register-im，
;; 见系统自带模板 /usr/share/uim/pyload.scm（注册 py / pyunihan / pinyin-big5）。
;;
;; 注意 register-im 内部有 gating：只有当 enabled-im-list 为空、或目标名字
;; 已在 enabled-im-list 里，注册才会真正生效。uim 自己的做法也是先把
;; enabled-im-list 清空（见 uim-module-manager.scm），这里照做。
;; 已经在列表里就跳过，避免重复执行时把列表越堆越长。
(require "im.scm")
(require "generic.scm")

(if (not (memq 'cn enabled-im-list))
    (set! enabled-im-list (cons 'cn enabled-im-list)))

;; init-handler 里再 require 一次自己：uim 的 require 带 *xxx-loaded* 标记，
;; 已加载时是空操作，所以这只是保险 —— uim 若走了 lazy-load，创建 context 时
;; 这个文件可能还没进过解释器，届时 pinyin-cn-utf8-rule 会是未绑定变量。
;; pyload.scm 注册 py / pinyin-big5 时也是这么写的。
;;
;; 关键：创建完必须立刻 (generic-context-set-on! gc #t)。
;; uim 的 generic 引擎默认是 off（直接输入）模式 —— 该模式下按键全部原样
;; 提交、不查表，preedit 与候选列表都是空的，屏幕键盘上表现为「能切到拼音
;; 却没有任何汉字」。generic-proc-off-mode 里正是用这个函数切回 on 的。
;; 手机屏幕键盘没有方便的热键去 toggle，所以初始就置为 on。
(define pinyin-cn-utf8-init-handler
  (lambda (id im arg)
    (require "pinyin-cn-utf8.scm")
    (let ((gc (generic-context-new id im pinyin-cn-utf8-rule #f)))
      (generic-context-set-on! gc #t)
      gc)))

(generic-register-im
 'cn
 "zh_CN"
 "UTF-8"
 (N_ "Treenput (Simplified)")
 (N_ "Treenput simplified pinyin input method")
 pinyin-cn-utf8-init-handler)
"""


def render(
    table: dict[tuple[str, ...], list[str]],
    freq: dict[str, int],
    t2s: T2S,
    n_phrase: int = 0,
    n_punct: int = 0,
) -> tuple[str, int, int]:
    blocks: list[str] = []
    total = 0
    for syllable in sorted(table):
        candidates = convert_entry(table[syllable], freq, t2s)
        if not candidates:
            continue
        total += len(candidates)
        blocks.append(_render_entry(syllable, candidates))
    body = "\n".join(blocks)
    header = (
        RULE_TEMPLATE.replace("__COUNT__", str(len(blocks)))
        .replace("__TOTAL__", str(total))
        .replace("__PHRASE__", str(n_phrase))
        .replace("__PUNCT__", str(n_punct))
        .replace("(BODY)", body)
    )
    # uim 表习惯在最后留一个换行
    return header + "\n", len(blocks), total


def main() -> int:
    ap = argparse.ArgumentParser(description="生成 uim 简体拼音引擎")
    ap.add_argument(
        "--input",
        default="/usr/share/uim/pinyin-big5.scm",
        help="上游 uim 拼音表（默认 pinyin-big5.scm）",
    )
    ap.add_argument("--output", required=True, help="输出的 .scm 路径")
    ap.add_argument("--freq", default=None, help="可选词频文件，每行一词")
    ap.add_argument("--phrase", default=None,
                    help="可选词条文件（build_phrase_dict.py 产物）")
    ap.add_argument("--punct", default=None,
                    help="可选符号表文件（data/punct.txt 格式）")
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

    # 词条必须在 t2s.warm 之前并进表：这样所有汉字（含词条里的）都能被
    # 一次性收集去做繁->简转换。
    n_phrase = 0
    if args.phrase:
        phrases = load_phrases(Path(args.phrase))
        n_phrase = merge_phrases(table, phrases)
        print("词条: %d 条并入规则表（涉及 %d 个音节）"
              % (n_phrase, len(phrases)))
    else:
        print("未提供词条文件：只有单字候选，输入多音节词会中断（见 --phrase）")

    # 符号同样在 t2s.warm 之前并入（符号不含汉字，t2s 会原样透传，
    # 但统一走一个流程省得单独处理）。
    n_punct = 0
    if args.punct:
        punct = load_punct(Path(args.punct))
        n_punct = merge_punct(table, punct)
        print("符号: %d 个候选并入规则表（%d 个键位）"
              % (n_punct, len(punct)))
    else:
        print("未提供符号表：标点只能靠应用自带（见 --punct）")

    # 先把所有候选里出现过的汉字收集起来，一次性做繁->简转换。
    # 注意：符号不能混进去 —— t2s.warm 会把符号也交给 opencc，而
    # opencc 对某些全角符号有「转换后长度变化」的边界情况，且 BOGUS_CHARS
    # 里的 £€ 就会被误过滤。这里只收汉字。
    t2s = T2S()
    all_chars: set[str] = set()
    punct_keys: set[tuple[str, ...]] = set()
    if args.punct:
        punct_keys = set(load_punct(Path(args.punct)).keys())
    for syl, cands in table.items():
        if syl in punct_keys:
            continue  # 符号桶不进 t2s
        for cand in cands:
            all_chars.update(cand)
    t2s.warm(all_chars)
    print("opencc批量转换: %s (去重后 %d 个汉字)"
          % (t2s._backend if t2s._ok else "不可用，回退原样", len(t2s._map)))

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    # 用 render 回传的计数，保证终端输出与文件头注释一致
    # （table 里的候选数是转换前的，转换后一简对多繁会塌缩，两者不等）
    text, n_syllable, n_cand = render(table, freq, t2s, n_phrase, n_punct)
    out.write_text(text, encoding="utf-8")

    print("已生成 %s" % out)
    print("  音节 %d 条 / 候选 %d 个（其中多字词 %d 个，符号 %d 个）"
          % (n_syllable, n_cand, n_phrase, n_punct))
    if not freq:
        print("  未提供词频文件，仅用内置常用字基线排序（建议加 --freq 提升手感）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())