#!/bin/sh
# 构建 stevia 屏幕键盘（Phosh 的新一代 OSK，首个带中文支持的版本）。
#
# 为什么不用发行版包：Debian 13 / trixie 的 phosh 0.46 只有 phosh-osk-stub，
# 没有中文；stevia 从 0.54.0 起才带 uim 中文支持，但还没进 trixie。
#
# 用法：sudo ./build-stevia.sh [目标目录]
set -eu

SRC="${1:-/opt/stevia-src}"
URL="https://gitlab.gnome.org/World/Phosh/stevia.git"

echo "==> 安装构建依赖"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq \
    git meson ninja-build pkg-config gettext \
    libgtk-3-dev libhandy-1-dev libjson-glib-dev \
    libwayland-dev libsystemd-dev libxml2-utils \
    libhunspell-dev libpresage-dev libuim-dev \
    libgmobile-dev libgnome-desktop-3-dev libfeedback-dev \
    libgovarnam-dev \
    uim uim-pinyin uim-anthy uim-data

echo "==> 获取源码 $SRC"
if [ ! -d "$SRC/.git" ]; then
    mkdir -p "$(dirname "$SRC")"
    git clone --depth 1 "$URL" "$SRC"
fi

cd "$SRC"

# Debian trixie 的 dconf 是 0.40.0，stevia main 要求 >= 0.49。
# 这是上游对更新发行版的假设，不是能力缺失——全文仅meson.build 一处声明 dconf。
# 放宽后已在 arm64 真机验证编译+运行通过。
if grep -q "dependency('dconf', version: '>= 0.49')" meson.build; then
    echo "==> 放宽 dconf 版本断言（trixie 实测安全）"
    sed -i "s/dependency('dconf', version: '>= 0.49')/dependency('dconf')/" meson.build
fi

echo "==> 配置"
rm -rf _build
meson setup -Dgtk_doc=false -Dman=false _build

echo "==> 编译"
ninja -C _build

echo "==> 安装"
ninja -C _build install
ldconfig

echo
echo "完成。已安装："
command -v phosh-osk-stevia || echo "  警告：phosh-osk-stevia 不在 PATH"
echo
echo "启用方式：pkill -f phosh-osk-stub && phosh-osk-stevia --replace"
echo "（--replace 是官方支持的临时替换手段，stevia 与 osk-stub 抢同一个 IM slot）"