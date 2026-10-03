#!/bin/sh
# 安装本项目生成的简体拼音引擎，并完成 uim /屏幕键盘侧的配置。
#
# 幂等：可重复执行。
# 不动内核、不换发行版、不装独立 IM 客户端（那会抢占屏幕键盘，见 docs/TroubleShooting.md）。
set -eu

ENGINE=/usr/share/uim/pinyin-cn-utf8.scm
UIM_TABLE=/usr/share/uim/pinyin-big5.scm
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"
FREQ="$REPO_DIR/data/frequency.txt"

if [ "$(id -u)" != 0 ]; then
    echo "需要 root：sudo $0" >&2
    exit 1
fi

echo "==> 检查前置"
command -v python3 >/dev/null || { echo "缺python3" >&2; exit 1; }
if [ ! -f "$UIM_TABLE" ]; then
    echo "找不到上游拼音表 $UIM_TABLE" >&2
    echo "请先安装：sudo apt-get install -y uim-data" >&2
    exit 1
fi
if ! command -v opencc >/dev/null; then
    echo "未找到 opencc，正在安装..."
    apt-get install -y -qq opencc libopencc1.1 libopencc-data
fi

echo "==> 生成简体引擎"
if [ -f "$FREQ" ]; then
    python3 "$REPO_DIR/engine/build_cn_engine.py" \
        --input "$UIM_TABLE" --output "$ENGINE" --freq "$FREQ"
else
    python3 "$REPO_DIR/engine/build_cn_engine.py" \
        --input "$UIM_TABLE" --output "$ENGINE"
fi

echo "==> 注册 uim 预载"
PRELOAD=/etc/uim/preload_scm
if [ -d /etc/uim ]; then
    # uim-preload 通常在 ~/.uim-preload；系统级放 /etc/uim/preload_scm
    grep -q 'pinyin-cn-utf8' "$PRELOAD" 2>/dev/null || \
        printf '(append!olist "modules" "pinyin-cn-utf8")\n' >> "$PRELOAD"
    echo "  已写入 $PRELOAD"
fi

USER_PRELOAD="$HOME/.uim-preload"
grep -q 'pinyin-cn-utf8' "$USER_PRELOAD" 2>/dev/null || \
    printf '(append!olist "modules" "pinyin-cn-utf8")\n' >> "$USER_PRELOAD"
echo "  已写入 $USER_PRELOAD"

echo "==> 验证"
if [ ! -s "$ENGINE" ]; then
    echo "引擎文件生成失败" >&2
    exit 1
fi
TRAD=$(grep -oE '[龍龜電腦這個]' "$ENGINE" | wc -l || true)
echo "  引擎文件: $(wc -c <"$ENGINE") 字节"
echo "  繁体残留: $TRAD （期望 0）"
echo "  ni 的首候选: $(grep -m1 '((("n" "i")))' "$ENGINE" | sed 's/.*((\"n\" \"i\")) (//;s/).*//' | cut -d' ' -f1)"

echo
echo "完成。剩余步骤见 Install.md 第 4-5 步："
echo "  1. 构建/安装 stevia 屏幕键盘（scripts/build-stevia.sh）"
echo "  2. gsettings set org.gnome.desktop.input-sources sources \"[('xkb','us'),('ibus','uim:cn')]\""