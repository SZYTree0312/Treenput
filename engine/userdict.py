#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Treenput 用户词典 —— 自创词条管理 + 词频长期校准。

为什么需要它
------------
内置词条（79,228 条）来自 jieba 通用语料，那是「大众的平均习惯」，不是你的。
你的名字、地名、口头禅、专业术语它一条都没有；而且你天天打的词，在通用词频里
未必排得靠前。

本模块提供两件事：

  1. **自创词条**：你自己加的词永久保存，且在候选里**排最前**
     （比内置的 79,228 条都靠前）。
  2. **词频校准**：给词加权，越常用越靠前。
     - `freq` 手动提频（刚打完一个词发现它排太后面时用）
     - `learn` 从你自己的文本批量学习（长期校准的主力入口）

存储（全部在用户家目录，不动系统文件）
--------------------------------------
  ~/.config/treenput/userdict.txt   用户词条：`拼音<TAB>词条<TAB>词频`
  ~/.config/treenput/.applied       已应用到引擎的词（增量同步用）

设计约束（踩过的坑，别改）
--------------------------
  - 词条键必须**逐字母**：`ni hao` → `("n" "i" "h" "a" "o")`。
    写成 `("ni" "hao")` uim 会当成按了两次非法键，词永远匹配不上
    —— 症状是「脚本说加成功了，候选里一个词都没有」。
  - 应用是**增量**的：直接改已装的 `.scm`，不重跑整表生成。
    完整重生成要解析上游表 + opencc 全量转换，在手机上太慢；
    增量只动用户词那几行，秒级完成。
  - 每次应用前**备份**引擎，随时能回档。

用法
----
  treenput-dict add "ni hao" 你好          # 加词（拼音 + 词）
  treenput-dict addw 你好                  # 只给词，自动注音（需 pypinyin）
  treenput-dict freq 你好 10               # 提频：权重 +10
  treenput-dict learn ~/notes.txt          # 从自己的文本学词频
  treenput-dict list                       # 看已加的词
  treenput-dict rm 你好                    # 删词
  treenput-dict apply                      # 应用到引擎（自动备份）
  treenput-dict status                     # 看状态

加词或提频后要跑一次 `apply` 才生效。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# ---------------------------------------------------------------- 路径

DEFAULT_HOME = Path.home() / ".config" / "treenput"
USERDICT_NAME = "userdict.txt"
APPLIED_NAME = ".applied"
DEFAULT_ENGINE = Path("/usr/share/uim/pinyin-cn-utf8.scm")

# 引擎规则行形如：
#     ((("n" "i" "h" "a" "o")) ("你好"))
# 注意候选里的汉字不会有引号，但为稳妥仍允许转义。
RULE_RE = re.compile(
    r'^(?P<indent>\s*)\(\(\((?P<key>[^()]*)\)\)\s*\((?P<cands>[^()]*)\)\)\s*$'
)
QUOTED_RE = re.compile(r'"((?:[^"\\]|\\.)*)"')

# uim 表里合法的单键：单字母或数字。拼音只可能出现 a-z。
VALID_KEY_RE = re.compile(r'^[a-z]$')


def _unescape(s: str) -> str:
    return s.replace('\\"', '"').replace('\\\\', '\\')


def _escape(s: str) -> str:
    return s.replace('\\', '\\\\').replace('"', '\\"')


# ---------------------------------------------------------------- 数据模型


@dataclass
class Entry:
    """一条用户词条。"""

    pinyin: list[str]          # 音节列表，如 ["ni", "hao"]
    word: str                  # 词条，如 "你好"
    freq: int = 100            # 权重，越大越靠前
    hits: int = 0              # 实际被校准/命中的次数（仅统计用）

    @property
    def key(self) -> tuple[str, ...]:
        """uim 规则键：逐字母元组。

        这是全模块最关键的一行。`ni hao` 必须展成
        `("n","i","h","a","o")`，不能是 `("ni","hao")`。
        """
        letters: list[str] = []
        for syl in self.pinyin:
            letters.extend(syl)
        return tuple(letters)

    @property
    def syllables(self) -> str:
        return " ".join(self.pinyin)

    def to_line(self) -> str:
        return "%s\t%s\t%d" % (self.syllables, self.word, self.freq)

    @classmethod
    def from_line(cls, line: str) -> "Entry | None":
        line = line.rstrip("\n").rstrip("\r")
        if not line or line.startswith("#"):
            return None
        parts = line.split("\t")
        if len(parts) < 2:
            return None
        syllables = [p.strip().lower() for p in parts[0].split() if p.strip()]
        word = parts[1].strip()
        if not syllables or not word:
            return None
        try:
            freq = int(parts[2]) if len(parts) > 2 and parts[2].strip() else 100
        except ValueError:
            freq = 100
        # 音节必须全是可接受的拼音字母，否则这条键 uim 永远匹配不上
        if not all(s.isalpha() and s.isascii() for s in syllables):
            return None
        return cls(pinyin=syllables, word=word, freq=freq)


@dataclass
class UserDict:
    """用户词典：增删改查 + 持久化。"""

    path: Path
    entries: list[Entry] = field(default_factory=list)

    def load(self) -> "UserDict":
        self.entries = []
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8",
                                            errors="replace").splitlines():
                e = Entry.from_line(line)
                if e is not None:
                    self.entries.append(e)
        return self

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # 词频降序保存，人打开文件时最常用的一目了然
        ordered = sorted(self.entries, key=lambda e: (-e.freq, e.word))
        text = "\n".join(e.to_line() for e in ordered)
        if text:
            text += "\n"
        self.path.write_text(text, encoding="utf-8")

    def find(self, word: str) -> Entry | None:
        for e in self.entries:
            if e.word == word:
                return e
        return None

    def add(self, syllables: list[str], word: str, freq: int = 100) -> bool:
        """加词。已存在则更新拼音并**提频**（相当于再次确认我想让它靠前）。"""
        if not word:
            return False
        existing = self.find(word)
        if existing is not None:
            existing.pinyin = syllables
            existing.freq = max(existing.freq, freq)
            return False
        self.entries.append(Entry(pinyin=syllables, word=word, freq=freq))
        return True

    def remove(self, word: str) -> bool:
        before = len(self.entries)
        self.entries = [e for e in self.entries if e.word != word]
        return len(self.entries) < before

    def bump(self, word: str, delta: int) -> Entry | None:
        """提频/降频，返回被调整的条目。"""
        e = self.find(word)
        if e is None:
            return None
        e.freq = max(1, e.freq + delta)
        if delta > 0:
            e.hits += delta
        return e


# ---------------------------------------------------------------- 引擎补丁


class EnginePatcher:
    """把用户词增量应用进已装的 .scm 引擎。

    只动「含用户词的规则行」，其余字节原样保留 —— 这样 3.6MB 的表
    不会因为加一个词就被整体重写（也避免把上游数据改坏）。
    """

    def __init__(self, scm_path: Path) -> None:
        self.path = scm_path
        self.lines: list[str] = []
        self.rules: dict[tuple[str, ...], int] = {}   # key -> 行号

    def load(self) -> "EnginePatcher":
        raw = self.path.read_text(encoding="utf-8", errors="replace")
        self.lines = raw.split("\n")
        for i, line in enumerate(self.lines):
            m = RULE_RE.match(line)
            if not m:
                continue
            letters = [_unescape(x).lower() for x in QUOTED_RE.findall(m.group("key"))]
            letters = [x for x in letters if x]
            if not letters or not all(VALID_KEY_RE.match(x) for x in letters):
                continue
            self.rules[tuple(letters)] = i
        return self

    def _candidates_of(self, line_no: int) -> list[str]:
        m = RULE_RE.match(self.lines[line_no])
        assert m is not None
        return [_unescape(x) for x in QUOTED_RE.findall(m.group("cands"))]

    def _render(self, key: tuple[str, ...], cands: list[str], indent: str = "    ") -> str:
        syl = " ".join('"%s"' % _escape(s) for s in key)
        cand = " ".join('"%s"' % _escape(c) for c in cands)
        return "%s(((%s)) (%s))" % (indent, syl, cand)

    def _get(self, key: tuple[str, ...]) -> list[str]:
        i = self.rules.get(key)
        if i is None:
            return []
        return self._candidates_of(i)

    def _set(self, key: tuple[str, ...], cands: list[str]) -> None:
        i = self.rules.get(key)
        if i is None:
            # 新音节：插到规则表**内部**，即最后一条规则行的后面。
            #
            # 不能图省事 append 到文件末尾：末尾是整张表的闭合括号
            # （`pinyin-cn-utf8-init-handler)`），插到它之后这行就成了裸列表，
            # Scheme 会把它当函数调用 —— uim 直接报
            #   "procedure or syntax required but got: \"s\""
            # 并且整个引擎失效（真机实测踩到）。rk 按最长前缀匹配，不依赖行序，
            # 所以放在表内最后一条是安全的。
            anchor = (max(self.rules.values()) + 1) if self.rules else 0
            self.lines.insert(anchor, self._render(key, cands))
            # 插入点之后的行号整体后移，否则后续 _get/_set 会改错行
            for k, v in list(self.rules.items()):
                if v >= anchor:
                    self.rules[k] = v + 1
            self.rules[key] = anchor
        else:
            m = RULE_RE.match(self.lines[i])
            indent = m.group("indent") if m else "    "
            self.lines[i] = self._render(key, cands, indent)

    def apply(self, entries: list[Entry], removed: set[str]) -> int:
        """同步用户词到引擎，返回实际变动的规则行数。

        - `removed` 里的词：从所有桶里抹掉（用户删词后要真的消失）
        - `entries`：按词频降序插到各桶**最前**
        """
        changed = 0
        # 1) 先处理删除：所有桶里都找一遍
        if removed:
            for key, line_no in list(self.rules.items()):
                cands = self._candidates_of(line_no)
                kept = [c for c in cands if c not in removed]
                if len(kept) != len(cands):
                    m = RULE_RE.match(self.lines[line_no])
                    indent = m.group("indent") if m else "    "
                    self.lines[line_no] = self._render(key, kept, indent)
                    changed += 1

        # 2) 按音节分组后**一次性**前置。
        #
        # 不能逐条 insert(0)：那样后处理的词会被顶到更前面，结果是
        # 「最后插入的最低频词排最前」—— 词频排序整个反过来。
        # 必须按词频降序整组 prepend。
        ordered = sorted(entries, key=lambda e: (-e.freq, len(e.word)))
        groups: dict[tuple[str, ...], list[str]] = {}
        for e in ordered:
            groups.setdefault(e.key, []).append(e.word)

        for key, words in groups.items():
            cands = self._get(key)
            # 先摘掉旧位置再整组前置 —— 保证幂等（反复 apply 结果一致）
            users = set(words)
            cands = [c for c in cands if c not in users]
            self._set(key, words + cands)
            changed += 1
        return changed

    def save(self, backup: bool = True, backup_dir: Path | None = None) -> Path | None:
        """写回引擎。

        backup_dir 默认是引擎同目录，但那里通常是 root 的（/usr/share/uim），
        普通用户建不了新文件 —— 备份会 PermissionError，而引擎本身反而能写。
        所以调用方把备份指到用户自己的目录下。
        """
        bak = None
        if backup and self.path.exists():
            if backup_dir is not None:
                backup_dir.mkdir(parents=True, exist_ok=True)
                name = self.path.name + ".bak-ud-%s" % time.strftime("%Y%m%d-%H%M%S")
                bak = backup_dir / name
            else:
                bak = self.path.with_suffix(
                    self.path.suffix + ".bak-ud-%s" % time.strftime("%Y%m%d-%H%M%S")
                )
            bak.write_text(self.path.read_text(encoding="utf-8", errors="replace"),
                           encoding="utf-8")
        self.path.write_text("\n".join(self.lines), encoding="utf-8")
        return bak


# ---------------------------------------------------------------- 校准


def learn_from_text(ud: UserDict, text_path: Path, weight: int = 5) -> tuple[int, int]:
    """从用户自己的文本学习词频 —— 长期校准的主力入口。

    做法：拿用户词典里已有的词去文本里数出现次数，按比例加权。
    这样不需要分词器也能工作（手机上未必装了 jieba），且只校准你已有的词
    —— 你的用词习惯体现在「哪些词更常出现」，而不是凭空造词。

    可选增强：若装了 jieba + pypinyin，会把文本里的高频新词**自动加进词典**。
    """
    if not text_path.exists():
        raise FileNotFoundError(str(text_path))
    text = text_path.read_text(encoding="utf-8", errors="replace")

    touched = 0
    for e in ud.entries:
        n = text.count(e.word)
        if n > 0:
            e.freq += n * weight
            e.hits += n
            touched += 1

    # 可选：自动发现新词（无依赖时静默跳过）
    added = 0
    try:
        import jieba  # type: ignore
        from pypinyin import lazy_pinyin  # type: ignore

        counts: dict[str, int] = {}
        for tok in jieba.cut(text):
            tok = tok.strip()
            if len(tok) < 2 or not tok:
                continue
            if not all("\u4e00" <= ch <= "\u9fff" for ch in tok):
                continue
            counts[tok] = counts.get(tok, 0) + 1
        for word, n in counts.items():
            if n < 3:              # 只收出现 3 次以上的，避免噪音
                continue
            if ud.find(word) is not None:
                continue
            try:
                syl = lazy_pinyin(word)
            except Exception:
                continue
            if not syl or not all(s.isalpha() and s.isascii() for s in syl):
                continue
            ud.entries.append(Entry(pinyin=syl, word=word, freq=n * weight))
            added += 1
    except Exception:
        pass

    return touched, added


def auto_pinyin(word: str) -> list[str] | None:
    """自动注音（需要 pypinyin）。装了就能用 `addw`。"""
    try:
        from pypinyin import lazy_pinyin  # type: ignore
    except Exception:
        return None
    try:
        syl = lazy_pinyin(word)
    except Exception:
        return None
    if not syl or not all(s.isalpha() and s.isascii() for s in syl):
        return None
    return syl


# ---------------------------------------------------------------- CLI


def _ud(args) -> UserDict:
    home = Path(args.home) if getattr(args, "home", None) else DEFAULT_HOME
    return UserDict(home / USERDICT_NAME).load()


def _engine_path(args) -> Path:
    if getattr(args, "engine", None):
        return Path(args.engine)
    return DEFAULT_ENGINE


def cmd_add(args) -> int:
    ud = _ud(args)
    syl = [s.strip().lower() for s in args.pinyin.split() if s.strip()]
    if not syl:
        print("拼音不能为空", file=sys.stderr)
        return 1
    if not all(s.isalpha() and s.isascii() for s in syl):
        print("音节只能是英文字母：%r" % args.pinyin, file=sys.stderr)
        return 1
    is_new = ud.add(syl, args.word, args.freq)
    ud.save()
    print("%s「%s」 %s (词频 %d)" % (
        "新增" if is_new else "更新", args.word,
        " ".join(syl), ud.find(args.word).freq))
    print("跑 treenput-dict apply 生效")
    return 0


def cmd_addw(args) -> int:
    syl = auto_pinyin(args.word)
    if syl is None:
        print("自动注音需要 pypinyin（pip install pypinyin）。", file=sys.stderr)
        print("或者直接给拼音：treenput-dict add \"ni hao\" 你好", file=sys.stderr)
        return 1
    args.pinyin = " ".join(syl)
    print("注音：%s" % args.pinyin)
    return cmd_add(args)


def cmd_list(args) -> int:
    ud = _ud(args)
    if not ud.entries:
        print("词典为空。加一个：treenput-dict add \"ni hao\" 你好")
        return 0
    print("%-20s %-24s %s" % ("词条", "拼音", "词频"))
    print("-" * 56)
    for e in sorted(ud.entries, key=lambda x: -x.freq):
        print("%-20s %-24s %d" % (e.word, e.syllables, e.freq))
    print("\n共 %d 条，存于 %s" % (len(ud.entries), ud.path))
    return 0


def cmd_rm(args) -> int:
    ud = _ud(args)
    if not ud.remove(args.word):
        print("词典里没有「%s」" % args.word, file=sys.stderr)
        return 1
    ud.save()
    print("已删除「%s」，跑 treenput-dict apply 生效" % args.word)
    return 0


def cmd_freq(args) -> int:
    ud = _ud(args)
    e = ud.bump(args.word, args.delta)
    if e is None:
        print("词典里没有「%s」。先加：treenput-dict add \"pinyin\" %s"
              % (args.word, args.word), file=sys.stderr)
        return 1
    ud.save()
    print("「%s」词频 %d（%s%d）" % (
        e.word, e.freq, "+" if args.delta > 0 else "", args.delta))
    print("跑 treenput-dict apply 生效")
    return 0


def cmd_learn(args) -> int:
    ud = _ud(args)
    if not ud.entries:
        print("词典为空，没法学。先加几个词，或先跑一次安装让内置词条就位。",
              file=sys.stderr)
        return 1
    try:
        touched, added = learn_from_text(ud, Path(args.file), args.weight)
    except FileNotFoundError:
        print("找不到文件：%s" % args.file, file=sys.stderr)
        return 1
    ud.save()
    print("从 %s 学习完成" % args.file)
    print("  校准已有词 %d 条，自动新增 %d 条" % (touched, added))
    print("跑 treenput-dict apply 生效")
    return 0


def _current_user() -> str:
    try:
        import pwd
        return pwd.getpwuid(os.getuid()).pw_name
    except Exception:
        return os.environ.get("USER") or os.environ.get("LOGNAME") or "$(whoami)"


def _writable(p: Path) -> bool:
    """root 一律算可写；否则看文件本身（不存在就看父目录）的写权限。"""
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        return True
    target = p if p.exists() else p.parent
    return os.access(target, os.W_OK)


OSK_UNIT = "phosh-osk-stevia.service"


def _reload_input_method() -> bool:
    """让正在跑的屏幕键盘重新读一遍引擎。

    引擎是进程**启动时**加载进内存的，改完磁盘上的 .scm，已经在跑的 stevia
    还抱着旧表 —— 不重启的话用户会以为词没加上。这里只重启 OSK 这一个 user
    unit（不是重启 phosh），代价是键盘闪一下，比让人手敲命令强。

    失败**不算 apply 失败**：词已经写进引擎了，只是得等下次启动。
    """
    import shutil
    import subprocess
    if not shutil.which("systemctl"):
        return False
    try:
        r = subprocess.run(
            ["systemctl", "--user", "restart", OSK_UNIT],
            capture_output=True, text=True, timeout=30,
        )
        return r.returncode == 0
    except Exception:
        # 没有 systemd user session（比如 SSH 里没登录会话）等情况，静默降级
        return False


def _print_engine_perm_help(engine: Path, home: Path, args) -> None:
    """引擎是 root 装的，本命令却跑在用户终端里 —— 说清怎么修，别甩 traceback。"""
    user = _current_user()
    print("[失败] 引擎文件不可写：%s" % engine, file=sys.stderr)
    print("  引擎由安装脚本以 root 写入，当前用户 %s 没有写权限。" % user,
          file=sys.stderr)
    print("")
    print("  修一次即可（之后 apply 都不用 sudo）：", file=sys.stderr)
    print("    sudo chown %s %s" % (user, engine), file=sys.stderr)
    print("")
    print("  或每次用 sudo 跑 —— 必须带 --home，否则 sudo 下 HOME=/root",
          file=sys.stderr)
    print("  会找错词典，把你的词写进 root 的目录：", file=sys.stderr)
    print("    sudo treenput-dict --home %s apply" % home, file=sys.stderr)


def cmd_apply(args) -> int:
    home = Path(args.home) if getattr(args, "home", None) else DEFAULT_HOME
    home.mkdir(parents=True, exist_ok=True)
    ud = UserDict(home / USERDICT_NAME).load()
    applied_file = home / APPLIED_NAME
    prev = set()
    if applied_file.exists():
        prev = {ln.strip() for ln in
                applied_file.read_text(encoding="utf-8",
                                       errors="replace").splitlines() if ln.strip()}

    engine = _engine_path(args)
    if not engine.exists():
        print("找不到引擎文件：%s" % engine, file=sys.stderr)
        print("先跑安装，或用 --engine 指定路径", file=sys.stderr)
        return 1

    # 引擎是 root 装的，而本命令是用户在自己终端里跑的 —— 权限不对就直接崩成
    # 一屏 traceback，太难读。这里先拦下来，给出能照抄的修法。
    if not _writable(engine):
        _print_engine_perm_help(engine, home, args)
        return 1

    cur = {e.word for e in ud.entries}
    removed = prev - cur

    patcher = EnginePatcher(engine).load()
    n = patcher.apply(ud.entries, removed)
    try:
        # 备份落在用户目录：引擎所在目录（/usr/share/uim）建不了新文件
        bak = patcher.save(backup=not args.no_backup,
                           backup_dir=None if args.no_backup else home / "backups")
    except PermissionError as exc:
        print("[失败] 写引擎被拒绝：%s" % exc, file=sys.stderr)
        _print_engine_perm_help(engine, home, args)
        return 1

    applied_file.write_text("\n".join(sorted(cur)) + ("\n" if cur else ""),
                            encoding="utf-8")

    print("已应用到 %s" % engine)
    print("  用户词 %d 条，变动规则行 %d，删除 %d 条" % (len(ud.entries), n, len(removed)))
    if bak:
        print("  备份：%s" % bak)
    # 引擎是进程启动时加载的，改文件不会让正在跑的输入法重新读一遍。
    # 所以这里直接替用户重启 OSK —— 手动敲命令太容易忘，忘了就以为没生效。
    if getattr(args, "no_restart", False):
        print("  已跳过重启（--no-restart），新词下次输入法启动时生效")
    elif _reload_input_method():
        print("  已重启屏幕键盘（%s），新词立即生效" % OSK_UNIT)
    else:
        print("  [警告] 没能自动重启屏幕键盘，新词下次启动才生效。手动执行：")
        print("    systemctl --user restart %s" % OSK_UNIT)
    return 0


def cmd_status(args) -> int:
    home = Path(args.home) if getattr(args, "home", None) else DEFAULT_HOME
    ud = UserDict(home / USERDICT_NAME).load()
    engine = _engine_path(args)
    print("词典目录：%s" % home)
    print("用户词条：%d 条" % len(ud.entries))
    print("引擎文件：%s%s" % (engine, "" if engine.exists() else "  (不存在)"))
    applied_file = home / APPLIED_NAME
    if applied_file.exists():
        n = len([x for x in applied_file.read_text(encoding="utf-8",
                                                   errors="replace").splitlines()
                 if x.strip()])
        print("已应用：%d 条" % n)
        if n != len(ud.entries):
            print("  ^ 与词典不一致，跑 treenput-dict apply 同步")
    else:
        print("已应用：0 条（还没 apply 过）")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="treenput-dict",
        description="Treenput 用户词典：自创词条 + 词频长期校准",
    )
    p.add_argument("--home", default=None,
                   help="词典目录（默认 ~/.config/treenput）")
    p.add_argument("--engine", default=None,
                   help="引擎 .scm 路径（默认 %s）" % DEFAULT_ENGINE)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("add", help="加词：拼音 + 词条")
    s.add_argument("pinyin", help='音节，空格分隔，如 "ni hao"')
    s.add_argument("word", help="词条，如 你好")
    s.add_argument("--freq", type=int, default=100, help="初始词频（默认 100）")
    s.set_defaults(func=cmd_add)

    s = sub.add_parser("addw", help="加词：只给词条，自动注音（需 pypinyin）")
    s.add_argument("word")
    s.add_argument("--freq", type=int, default=100)
    s.set_defaults(func=cmd_addw)

    s = sub.add_parser("list", help="列出用户词条")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("rm", help="删除词条")
    s.add_argument("word")
    s.set_defaults(func=cmd_rm)

    s = sub.add_parser("freq", help="提频/降频（长期校准）")
    s.add_argument("word")
    s.add_argument("delta", type=int, nargs="?", default=10,
                   help="增量，默认 +10；负数降频")
    s.set_defaults(func=cmd_freq)

    s = sub.add_parser("learn", help="从文本学习词频（长期校准）")
    s.add_argument("file")
    s.add_argument("--weight", type=int, default=5, help="每次出现的权重")
    s.set_defaults(func=cmd_learn)

    s = sub.add_parser("apply", help="应用到引擎（自动备份 + 自动重启输入法）")
    s.add_argument("--no-backup", action="store_true", help="不备份引擎")
    s.add_argument("--no-restart", action="store_true",
                   help="不自动重启屏幕键盘（新词下次启动才生效）")
    s.set_defaults(func=cmd_apply)

    s = sub.add_parser("status", help="查看状态")
    s.set_defaults(func=cmd_status)
    return p


def main() -> int:
    args = build_parser().parse_args()
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
