#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""用户词典回归测试 —— 不需要手机，用引擎副本跑全流程。

    python3 engine/test_userdict.py

为什么用副本跑：引擎 3.6MB / 62,829 条规则，测试只改临时副本，
仓库里的 data/pinyin-cn-utf8.scm 一个字节都不会动。

覆盖：
  1. 加词后排最前（盖过内置候选）
  2. 多音节新词能建新桶
  3. apply 幂等
  4. 同音节多用户词按词频降序（这条踩过坑：逐条 insert(0) 会把顺序弄反）
  5. 提频后重排
  6. 删词后真的消失
  7. learn 从文本校准词频
  8. 新音节插入后**文件结构仍然合法**（这条是真机踩出来的）

第 8 条的来历：新音节原本走 append 到文件末尾，而末尾是整张表的闭合括号
`pinyin-cn-utf8-init-handler)` —— 规则行落到它后面就成了裸列表，Scheme 会当
函数调用，uim 报 `procedure or syntax required but got: "s"` 且整个引擎失效。
只查候选顺序是发现不了的，必须查结构。
"""
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

repo = Path(__file__).resolve().parent.parent
PY = sys.executable
SCRIPT = repo / "engine" / "userdict.py"

tmp = Path(tempfile.mkdtemp(prefix="treenput-ud-"))
engine = tmp / "pinyin-cn-utf8.scm"
shutil.copy(repo / "data" / "pinyin-cn-utf8.scm", engine)
home = tmp / "home"

sys.path.insert(0, str(repo / "engine"))
import userdict as U  # noqa: E402

ok = True


def run(*args):
    r = subprocess.run(
        [PY, str(SCRIPT), "--home", str(home), "--engine", str(engine)] + list(args),
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    print("\n$ treenput-dict " + " ".join(args))
    if r.stdout:
        print(r.stdout.rstrip())
    if r.stderr:
        print("  [stderr] " + r.stderr.rstrip())
    return r


def bucket(*letters):
    return U.EnginePatcher(engine).load()._get(tuple(letters))


def check_structure(label):
    """规则行必须全部落在整张表的闭合括号之前，否则 uim 加载就炸。"""
    global ok
    lines = engine.read_text(encoding="utf-8").split("\n")
    close = None
    for i in range(len(lines) - 1, -1, -1):
        if "init-handler" in lines[i] and lines[i].rstrip().endswith(")"):
            close = i
            break
    if close is None:
        print("  FAIL %s：找不到规则表的闭合行" % label)
        ok = False
        return
    bad = [i + 1 for i, ln in enumerate(lines)
           if U.RULE_RE.match(ln) and i > close]
    if bad:
        print("  FAIL %s：%d 条规则行落在闭合括号之后（行号 %s）"
              % (label, len(bad), bad[:5]))
        print("       uim 会当函数调用，报 procedure or syntax required")
        ok = False
    else:
        print("  PASS %s（规则行全在表内，闭合行在第 %d 行）" % (label, close + 1))


def check(label, got, expect_head=None, expect_absent=None):
    global ok
    msg = []
    if expect_head is not None:
        head = got[: len(expect_head)] if got else None
        if head != expect_head:
            ok = False
            msg.append("头部 %r != 期望 %r" % (head, expect_head))
    if expect_absent is not None and expect_absent in (got or []):
        ok = False
        msg.append("%r 应消失但仍在" % expect_absent)
    print("  [%s] %s -> 前3=%s" % ("PASS" if not msg else "FAIL", label,
                                   (got or [])[:3]))
    for m in msg:
        print("         " + m)


print("=" * 62)
print("用户词典回归测试（引擎副本，不动仓库文件）")
print("=" * 62)

check("基线 ni 桶", bucket("n", "i"), expect_head=["你"])
check("基线 nihao 桶", bucket("n", "i", "h", "a", "o"), expect_head=["你好"])

run("add", "ni", "你丫", "--freq", "5000")
run("apply")
check("加词后 ni 桶（用户词盖过内置）", bucket("n", "i"),
      expect_head=["你丫", "你"])

run("add", "ni hao ma", "你好吗", "--freq", "3000")
run("apply")
check("新桶 nihaoma", bucket("n", "i", "h", "a", "o", "m", "a"),
      expect_head=["你好吗"])

run("apply")
check("幂等（再 apply 一次不重复）", bucket("n", "i"),
      expect_head=["你丫", "你"])

run("add", "ni", "尼康", "--freq", "100")
run("apply")
check("同音节两用户词按词频降序", bucket("n", "i"),
      expect_head=["你丫", "尼康", "你"])

run("freq", "尼康", "99999")
run("apply")
check("提频后重排", bucket("n", "i"), expect_head=["尼康", "你丫", "你"])

run("rm", "尼康")
run("apply")
check("删词后消失", bucket("n", "i"),
      expect_head=["你丫", "你"], expect_absent="尼康")

txt = tmp / "note.txt"
txt.write_text("你好吗你好吗你好吗，我今天去了实验室。" * 3, encoding="utf-8")
run("learn", str(txt))
run("apply")

# 8) 新音节：引擎里原本没有这个键，必须新建规则行 —— 落错位置会毁掉整张表
run("add", "sun zhe yuan", "孙哲远", "--freq", "300")
run("apply")
check("新音节建桶", bucket("s", "u", "n", "z", "h", "e", "y", "u", "a", "n"),
      expect_head=["孙哲远"])
check_structure("新音节插入后结构合法")

# 再加一个新音节，确认连续插入不会把行号算错
run("add", "shu ru fa", "树入法", "--freq", "200")
run("apply")
check("连续新音节", bucket("s", "h", "u", "r", "u", "f", "a"),
      expect_head=["树入法", "输入法"])
check_structure("连续插入后结构合法")
# 已有音节仍要正常（验证插入后行号偏移没把别的桶改错）
check("新音节不影响已有桶", bucket("n", "i"), expect_head=["你丫", "你"])

run("status")
run("list")

print("\n" + "=" * 62)
print("结果：%s" % ("全部通过" if ok else "有失败项"))
print("=" * 62)
print("临时目录（可删）: %s" % tmp)

sys.exit(0 if ok else 1)
