#!/bin/sh
# Treenput（树入法）一键安装
#     https://github.com/SZYTree0312/Treenput
#
# 用法：
#     curl -fsSL https://raw.githubusercontent.com/SZYTree0312/Treenput/main/install.sh | sudo sh
#     或： git clone <repo> && cd Treenput && sudo ./install.sh
#
# 装完不重启 phosh，当前会话里仍是旧的 phosh-osk-stub（无中文）。
# 要立刻接管键盘，加 --replace-now。
# 幂等：中途失败可以直接重跑。不动内核、不换发行版、
# 不装独立 IM 客户端（那会抢占屏幕键盘）。
#
# 选项：
#   --skip-stevia   只装拼音引擎，跳过 stevia 屏幕键盘的源码编译
#   --replace-now   装完立即替换当前屏幕键盘（默认只装不换）
#   --verify-only   只跑校验
#   --status        只打印当前状态
#   --restore-osk   只把系统自带屏幕键盘拉起来（键盘没了时用这条救回来）
#   --uninstall     卸载引擎并恢复原屏幕键盘
#   -h, --help      显示帮助
set -eu

REPO_URL="https://github.com/SZYTree0312/Treenput.git"
STEVIA_URL="https://gitlab.gnome.org/World/Phosh/stevia.git"
# 版本必须锁在 v0.55.0。
# stevia 从 v0.56.0 起要求合成器提供 ext_data_control_manager_v1，
# 而 phoc 0.46（Debian 13 / Mobian）只有老的 zwlr_data_control_manager_v1。
# 缺这个 global 时 stevia 会等 5 秒超时后退出，屏幕键盘就没了 ——
# 实测 v0.57.0 在 phosh 0.46 上必定启动失败。v0.55.0 是兼容且带中文的最高版本。
# 有更新合成器（phosh >= 0.49）时可覆盖：TREE_STEVIA_VERSION=v0.57.0
STEVIA_VERSION="${TREE_STEVIA_VERSION:-v0.55.0}"
ENGINE=/usr/share/uim/pinyin-cn-utf8.scm
UIM_TABLE=/usr/share/uim/pinyin-big5.scm
STEVIA_SRC=/opt/stevia-src
REPO_DIR=/opt/treenput
PRELOAD_SCM=/etc/uim/preload_scm
UIM_DEFAULTS=/etc/uim/defaults
TRAD_CHARS='龍龜電腦這個這樣時間國會學說'

usage() {
    # 从「用法：」到选项列表末尾，行号随注释改动需同步
    sed -n '5,21s/^#\{1,\} \{0,1\}//p' "$0"
}

# ---------------------------------------------------------------- 输出

step() { printf '\n==> %s\n' "$*"; }
info() { printf '  %s\n' "$*"; }
warn() { printf '  [警告] %s\n' "$*" >&2; }
die()  { printf '\n[失败] %s\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- 桌面用户

# 本项目要改两样「属于某个桌面用户」的东西：~/.uim-preload 和
# org.gnome.desktop.input-sources。sudo 后 $HOME 是 /root，写进去等于白写；
# gsettings 还需要该用户的会话总线。所以必须先定位真实的登录用户。
DESKTOP_USER=""
PASSWD_FILE=/etc/passwd

detect_desktop_user() {
    if [ ! -f "$PASSWD_FILE" ]; then
        DESKTOP_USER=""
        return 1
    fi
    if [ -n "${TREENPUT_USER:-}" ]; then
        DESKTOP_USER="$TREENPUT_USER"
    elif [ -n "${SUDO_USER:-}" ] && [ "$SUDO_USER" != root ]; then
        DESKTOP_USER="$SUDO_USER"
    else
        _u=""
        if command -v loginctl >/dev/null 2>&1; then
            _u="$(loginctl list-sessions --no-legend 2>/dev/null \
                  | awk '$3 ~ /^(x11|wayland|mir|wayland-remote)$/ {print $3; exit}')"
        fi
        if [ -z "${_u:-}" ]; then
            _u="$(awk -F: '$3 >= 1000 && $3 < 65534 && $6 != "" {print $1; exit}' "$PASSWD_FILE")"
        fi
        if [ -z "${_u:-}" ] || [ "$_u" = root ]; then
            DESKTOP_USER=""
            return 1
        fi
        DESKTOP_USER="$_u"
    fi
    [ -n "$DESKTOP_USER" ]
}

user_home() { awk -F: -v u="$1" '$1 == u {print $6; exit}' "$PASSWD_FILE" 2>/dev/null; }
user_uid()  { awk -F: -v u="$1" '$1 == u {print $3; exit}' "$PASSWD_FILE" 2>/dev/null; }

# 以桌面用户身份跑命令（带干净的 XDG_RUNTIME_DIR，gsettings 要靠它找会话总线）
as_desktop_user() {
    _uid="$(user_uid "$DESKTOP_USER")"
    if command -v runuser >/dev/null 2>&1; then
        runuser -u "$DESKTOP_USER" -- env XDG_RUNTIME_DIR="/run/user/$_uid" \
            XDG_SESSION_TYPE=wayland "$@"
    else
        _home="$(user_home "$DESKTOP_USER")"
        su -s /bin/sh "$DESKTOP_USER" -c \
            "XDG_RUNTIME_DIR=/run/user/$_uid XDG_SESSION_TYPE=wayland $*"
    fi
}

# ---------------------------------------------------------------- apt

# DEBIAN_FRONTEND 只作用于 apt 这一个命令，不 export，避免泄到子进程。
apt_get()  { DEBIAN_FRONTEND=noninteractive apt-get "$@"; }
apt_quiet() { DEBIAN_FRONTEND=noninteractive apt-get -y -qq "$@"; }

BUILD_DEPS="meson ninja-build pkg-config gettext
libgtk-3-dev libhandy-1-dev libjson-glib-dev
libwayland-dev libsystemd-dev libxml2-utils
libhunspell-dev libpresage-dev libuim-dev
libgmobile-dev libgnome-desktop-3-dev libfeedback-dev
libgovarnam-dev
uim uim-pinyin uim-anthy uim-data
opencc libopencc1.1 libopencc-data
fonts-noto-ui-core fonts-noto-cjk"

# Mobian 给 GTK3 打了 -mobian1 版本号，而 Debian 源里的 -dev 只认原版号，
# 于是 libgtk-3-dev 装不上。只降这两个包，影响面最小。
# 降级前把版本号存下来供回滚。
fix_mobian_gtk3() {
    _orig="$(dpkg-query -W -f='${Version}' gir1.2-gtk-3.0 2>/dev/null || true)"
    [ -n "$_orig" ] || return 0
    case "$_orig" in
        *mobian*) ;;
        *) return 0 ;;   # 不是 Mobian 补丁版，用不着动
    esac
    warn "检出 Mobian GTK3 补丁版本 $_orig，显式降级到 3.24.49-3"
    printf 'gir1.2-gtk-3.0 %s\nlibgtk-3-0t64 %s\n' "$_orig" "$_orig" \
        > /root/treenput-gtk3-rollback.txt
    info "回滚记录：/root/treenput-gtk3-rollback.txt"
    # shellcheck disable=SC2086
    apt_quiet install -y --allow-downgrades \
        gir1.2-gtk-3.0=3.24.49-3 libgtk-3-0t64=3.24.49-3 || {
        warn "降级失败；桌面可能受影响，回滚见 /root/treenput-gtk3-rollback.txt"
        return 1
    }
}

install_deps() {
    step "安装依赖"
    apt_get update -qq
    # shellcheck disable=SC2086
    if apt_quiet install -y $BUILD_DEPS 2>/dev/null; then
        info "依赖就绪"
        return 0
    fi
    warn "直接安装失败，尝试修复 Mobian GTK3 版本冲突"
    fix_mobian_gtk3 || true
    # shellcheck disable=SC2086
    apt_quiet install -y $BUILD_DEPS
}

# ---------------------------------------------------------------- 仓库

locate_repo() {
    if [ -f "./engine/build_cn_engine.py" ]; then
        REPO_DIR="$(pwd)"; return 0
    fi
    if [ -n "${TREENPUT_DIR:-}" ] && [ -f "$TREENPUT_DIR/engine/build_cn_engine.py" ]; then
        REPO_DIR="$TREENPUT_DIR"; return 0
    fi
    if [ -f "$0" ]; then
        _guess="$(CDPATH= cd -- "$(dirname -- "$0")" 2>/dev/null && pwd || true)"
        if [ -n "${_guess:-}" ] && [ -f "$_guess/engine/build_cn_engine.py" ]; then
            REPO_DIR="$_guess"; return 0
        fi
    fi
    # tarball 方式解压出来的目录名带版本后缀，形如 /opt/Treenput-main
    for _cand in /opt/Treenput* /usr/local/src/Treenput*; do
        if [ -f "$_cand/engine/build_cn_engine.py" ]; then
            REPO_DIR="$_cand"; return 0
        fi
    done
    if [ -f "$REPO_DIR/engine/build_cn_engine.py" ]; then
        return 0
    fi
    return 1
}

ensure_repo() {
    if locate_repo; then
        info "使用仓库：$REPO_DIR"
        return 0
    fi
    step "获取 Treenput"
    if [ -d "$REPO_DIR/.git" ]; then
        info "更新已有克隆 $REPO_DIR"
        git -C "$REPO_DIR" fetch --depth 1 origin || true
        git -C "$REPO_DIR" reset --hard FETCH_HEAD || true
    elif ! git clone --depth 1 "$REPO_URL" "$REPO_DIR"; then
        # clone 失败最常见的原因是 raw.githubusercontent / github.com 被拦。
        # 给出可直接粘贴的备用通道，而不是让set -e 静默中断。
        die "git clone 失败。若网络受限，改用打包下载：
  curl -fsSL https://codeload.github.com/SZYTree0312/Treenput/tar.gz/refs/heads/main \\
    | sudo tar -xz -C /opt && sudo /opt/Treenput-main/install.sh
  或先手动 clone 到任意目录，再 cd 进去执行 sudo ./install.sh"
    fi
    [ -f "$REPO_DIR/engine/build_cn_engine.py" ] \
        || die "仓库内容异常：$REPO_DIR 下找不到 engine/build_cn_engine.py"
}

# ---------------------------------------------------------------- 引擎

build_engine() {
    step "生成简体拼音引擎"
    ensure_repo
    [ -f "$UIM_TABLE" ] || die "找不到上游拼音表 $UIM_TABLE（uim-data 装上了吗）"
    _freq="$REPO_DIR/data/frequency.txt"
    if [ -f "$_freq" ]; then
        python3 "$REPO_DIR/engine/build_cn_engine.py" \
            --input "$UIM_TABLE" --output "$ENGINE" --freq "$_freq"
    else
        warn "仓库内无 data/frequency.txt，退化为内置基线排序"
        python3 "$REPO_DIR/engine/build_cn_engine.py" \
            --input "$UIM_TABLE" --output "$ENGINE"
    fi
    [ -s "$ENGINE" ] || die "引擎文件生成失败：$ENGINE"
}

# 向文件追加一行，已存在则跳过。文件不存在则创建。
append_once() {
    _file="$1"; _line="$2"
    mkdir -p "$(dirname "$_file")"
    touch "$_file"
    if grep -qF "$_line" "$_file" 2>/dev/null; then
        return 0
    fi
    printf '%s\n' "$_line" >> "$_file"
}

register_uim_preload() {
    step "注册 uim 引擎"
    # 注册逻辑写在生成的引擎文件里（generic-register-im，见 build_cn_engine.py）。
    # uim 通过 preload 加载名为 pinyin-cn-utf8 的模块来触发它，
    # 所以这里只需要把模块名加进 modules 列表。
    #
    # Debian trixie 的 uim 不带任何 /etc 文件，/etc/uim 默认不存在。
    # 早期版本把它包在 [ -d /etc/uim ] 里，导致注册一行都不会写 —— 现在改为
    # 系统级目录按需创建，并始终写用户级。
    mkdir -p /etc/uim 2>/dev/null || true
    if [ -d /etc/uim ]; then
        append_once "$PRELOAD_SCM" '(append!olist "modules" "pinyin-cn-utf8")'
        info "已写入 $PRELOAD_SCM"
    fi
    # 用户级预载。必须是桌面用户的家，不是 /root。
    if [ -n "$DESKTOP_USER" ]; then
        _target="$(user_home "$DESKTOP_USER")/.uim-preload"
        append_once "$_target" '(append!olist "modules" "pinyin-cn-utf8")'
        chown "$DESKTOP_USER" "$_target" 2>/dev/null || true
        info "已写入 $_target （用户 $DESKTOP_USER）"
    else
        warn "定位不到桌面用户，跳过 ~/.uim-preload；引擎仍可用，只是少一条预载"
    fi
}

# ---------------------------------------------------------------- stevia

build_stevia() {
    step "构建 stevia 屏幕键盘（首个带中文的 Phosh OSK）"
    # 已装的版本不对（比如 0.57 在新 phosh 上会起不来）时也要重编，
    # 所以这里检查源码树里的版本，而不只是"命令在不在"。
    if [ -d "$STEVIA_SRC/.git" ]; then
        _cur="$(git -C "$STEVIA_SRC" describe --tags 2>/dev/null || true)"
        if [ "$_cur" = "$STEVIA_VERSION" ] && command -v phosh-osk-stevia >/dev/null 2>&1; then
            info "已装版本 $_cur 与目标一致，跳过编译"
            return 0
        fi
        info "源码树版本 $_cur，目标 $STEVIA_VERSION，重新编译"
    elif command -v phosh-osk-stevia >/dev/null 2>&1; then
        info "phosh-osk-stevia 已安装，跳过编译"
        return 0
    fi
    command -v meson >/dev/null 2>&1 || die "缺 meson，依赖安装有问题"
    mkdir -p "$(dirname "$STEVIA_SRC")"
    if [ ! -d "$STEVIA_SRC/.git" ]; then
        rm -rf "$STEVIA_SRC"
        git clone --depth 1 --branch "$STEVIA_VERSION" "$STEVIA_URL" "$STEVIA_SRC"
    else
        git -C "$STEVIA_SRC" fetch --depth 1 origin tag "$STEVIA_VERSION" || true
        git -C "$STEVIA_SRC" checkout "$STEVIA_VERSION" || true
    fi
    cd "$STEVIA_SRC"
    info "stevia 版本：$(git -C "$STEVIA_SRC" describe --tags 2>/dev/null || echo 未知)"
    # Debian trixie 的 dconf 是 0.40.0，stevia main 要求 >= 0.49。
    # 上游全文只有这一处声明 dconf，放宽不损失能力，已在 arm64 真机验证。
    if grep -q "dependency('dconf', version: '>= 0.49')" meson.build 2>/dev/null; then
        info "放宽 dconf 版本断言（trixie 实测安全）"
        sed -i "s/dependency('dconf', version: '>= 0.49')/dependency('dconf')/" meson.build
    fi
    rm -rf _build
    meson setup -Dgtk_doc=false -Dman=false _build
    ninja -C _build
    ninja -C _build install
    ldconfig
    command -v phosh-osk-stevia >/dev/null || warn "phosh-osk-stevia 不在 PATH"
}

# 拉起系统自带键盘。这是任何时候都能用的安全网 ——
# 屏幕键盘没了手机就等于不能用，所以恢复动作必须独立于本项目的成败。
# 用 systemd-run 而不是直接后台起：SSH 一断，直接起的进程就跟着没了。
restore_osk() {
    step "恢复系统默认屏幕键盘"
    if pgrep -f "phosh-osk-stub" >/dev/null 2>&1; then
        info "phosh-osk-stub 已在运行"
        return 0
    fi
    if [ -z "$DESKTOP_USER" ]; then
        warn "定位不到桌面用户，无法恢复键盘"
        return 1
    fi
    _uid="$(user_uid "$DESKTOP_USER")"
    if command -v systemctl >/dev/null 2>&1; then
        if runuser -u "$DESKTOP_USER" -- env \
            XDG_RUNTIME_DIR="/run/user/$_uid" \
            DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$_uid/bus" \
            WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
            systemctl --user start phosh-osk-stub-restore 2>/dev/null; then
            :
        else
            runuser -u "$DESKTOP_USER" -- env \
                XDG_RUNTIME_DIR="/run/user/$_uid" \
                DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$_uid/bus" \
                WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
                systemd-run --user --unit=phosh-osk-stub-restore \
                /usr/bin/phosh-osk-stub --allow-replacement >/dev/null 2>&1 || {
                warn "systemd-run 拉起失败"
                return 1
            }
        fi
    fi
    sleep 3
    if pgrep -f "phosh-osk-stub" >/dev/null 2>&1; then
        info "phosh-osk-stub 已恢复"
        return 0
    fi
    warn "未能恢复 phosh-osk-stub"
    return 1
}

# stevia 与 osk-stub 抢同一个 Wayland input-method slot，
# 只用官方支持的 --replace 顶替。
#
# 这里的顺序很重要：stevia 会因为协议缺失/版本不匹配而启动失败，
# 而它一旦失败、osk-stub 又已经被杀掉，手机上就没有任何键盘了。
# 所以先杀后起、起不来立刻把 stub 拉回来，不留无键盘的中间态。
replace_osk() {
    step "切换到 stevia 屏幕键盘"
    if pgrep -f phosh-osk-stevia >/dev/null 2>&1; then
        info "stevia 已在运行"
        return 0
    fi
    if ! command -v phosh-osk-stevia >/dev/null 2>&1; then
        warn "phosh-osk-stevia 未安装，键盘维持原样"
        return 0
    fi
    if [ -z "$DESKTOP_USER" ]; then
        warn "定位不到桌面用户，不动键盘（避免留下无键盘状态）"
        return 0
    fi

    _uid="$(user_uid "$DESKTOP_USER")"
    pkill -f phosh-osk-stub 2>/dev/null || true
    info "已停掉 phosh-osk-stub"

    runuser -u "$DESKTOP_USER" -- env \
        XDG_RUNTIME_DIR="/run/user/$_uid" \
        DBUS_SESSION_BUS_ADDRESS="unix:path=/run/user/$_uid/bus" \
        WAYLAND_DISPLAY="${WAYLAND_DISPLAY:-wayland-0}" \
        systemd-run --user --unit=phosh-osk-stevia-replace \
        phosh-osk-stevia --replace >/dev/null 2>&1 || true

    # stevia 缺协议时是 5 秒超时退出，等 8 秒足够判定
    sleep 8
    if pgrep -f phosh-osk-stevia >/dev/null 2>&1; then
        info "stevia 已接管屏幕键盘"
        return 0
    fi

    warn "stevia 启动失败，正在把系统键盘拉回来"
    restore_osk
    return 1
}

# ---------------------------------------------------------------- 输入源

enable_input_source() {
    step "启用中文输入源"
    if [ -z "$DESKTOP_USER" ]; then
        warn "定位不到桌面用户，跳过 gsettings"
        return 0
    fi
    if as_desktop_user gsettings get org.gnome.desktop.input-sources sources >/dev/null 2>&1; then
        as_desktop_user gsettings set org.gnome.desktop.input-sources sources \
            "[('xkb', 'us'), ('ibus', 'uim:cn')]"
        info "已设置 input-sources 为 [us, uim:cn]"
    else
        # SSH 执行时通常拿不到会话总线，这是正常现象，不是失败。
        warn "拿不到桌面会话总线（SSH 下的正常现象），请在手机上手动执行一次："
        warn "  gsettings set org.gnome.desktop.input-sources sources \"[('xkb','us'),('ibus','uim:cn')]\""
    fi
}

# ---------------------------------------------------------------- 校验

verify() {
    _rc=0
    _home="$( [ -n "$DESKTOP_USER" ] && user_home "$DESKTOP_USER" )"
    step "校验"
    if [ -s "$ENGINE" ]; then
        info "引擎文件：$(wc -c <"$ENGINE" | tr -d ' ') 字节  $ENGINE"
        _trad="$(grep -oE "[$TRAD_CHARS]" "$ENGINE" 2>/dev/null | wc -l | tr -d ' ' || printf 0)"
        if [ "$_trad" = "0" ]; then
            info "繁体残留：0"
        else
            warn "繁体残留：$_trad （期望 0）"
            _rc=1
        fi
    else
        warn "引擎文件缺失或为空：$ENGINE"
        _rc=1
    fi

    # 抽查首候选（输 ni 出你这类基本体验），用仓库自带的校验器
    if [ -s "$ENGINE" ] && locate_repo && [ -f "$REPO_DIR/engine/verify_engine.py" ]; then
        python3 "$REPO_DIR/engine/verify_engine.py" "$ENGINE" || _rc=1
    fi

    # 最关键的一项：uim 到底有没有真的注册出名为 cn 的输入法。
    # 引擎文件在、排序对，都不代表 uim:cn 能用了；注册失败时屏幕上依然没有中文，
    # 而前面几项全是绿的。所以必须查 uim 自己的运行时登记表。
    if command -v uim-sh >/dev/null 2>&1; then
        _im="$(printf '%s\n' \
            '(require "im.scm")' \
            '(require "generic.scm")' \
            '(require "pinyin-cn-utf8.scm")' \
            '(let ((cnim (retrieve-im (quote cn))))' \
            '  (print (if cnim' \
            '            (string-append "FOUND:" (symbol->string (im-name cnim))' \
            '                           "/" (im-lang cnim))' \
            '            "MISSING")))' \
            | HOME="${_home:-/root}" timeout 60 uim-sh 2>/dev/null \
            | tr -d '\r' | grep -aoE "FOUND:[A-Za-z_/0-9]+|MISSING" | head -1)"
        if [ "${_im:-}" = "MISSING" ]; then
            warn "uim 里没有注册出 cn 输入法 —— 屏幕键盘不会有中文"
            _rc=1
        elif [ -n "${_im:-}" ]; then
            info "uim 输入法注册：$_im"
        else
            warn "无法确认 cn 是否注册（uim-sh 没返回结果）"
        fi
    else
        warn "无 uim-sh，跳过输入法注册检查"
    fi

    if command -v phosh-osk-stevia >/dev/null 2>&1; then
        info "屏幕键盘：phosh-osk-stevia 已安装"
    else
        info "屏幕键盘：仍是 phosh-osk-stub（无中文）；去掉 --skip-stevia 重跑可装 stevia"
    fi
    return $_rc
}

status() {
    step "当前状态"
    if [ -s "$ENGINE" ]; then
        info "引擎：已安装（$(wc -c <"$ENGINE" | tr -d ' ') 字节）"
    else
        info "引擎：未安装"
    fi
    if command -v phosh-osk-stevia >/dev/null 2>&1; then
        info "stevia：已安装"
    else
        info "stevia：未安装（屏幕键盘无中文）"
    fi
    if pgrep -f phosh-osk-stevia >/dev/null 2>&1; then
        info "stevia 进程：运行中"
    else
        info "stevia 进程：未运行"
    fi
    if pgrep -f phosh-osk-stub >/dev/null 2>&1; then
        info "osk-stub 进程：运行中"
    fi
    if [ -n "$DESKTOP_USER" ]; then
        info "桌面用户：$DESKTOP_USER"
        _src="$(as_desktop_user gsettings get org.gnome.desktop.input-sources sources 2>/dev/null || printf '(读不到)')"
        info "输入源：$_src"
    else
        info "桌面用户：定位不到"
    fi
    return 0
}

uninstall() {
    step "卸载"
    rm -f "$ENGINE"
    info "已删除引擎 $ENGINE"
    for f in "$PRELOAD_SCM" "$UIM_DEFAULTS"; do
        if [ -f "$f" ]; then
            sed -i '/pinyin-cn-utf8/d' "$f" || true
        fi
    done
    if [ -n "$DESKTOP_USER" ]; then
        _f="$(user_home "$DESKTOP_USER")/.uim-preload"
        if [ -f "$_f" ]; then
            sed -i '/pinyin-cn-utf8/d' "$_f" || true
        fi
    fi
    info "已清理预载配置"
    if pgrep -f phosh-osk-stevia >/dev/null 2>&1; then
        pkill -f phosh-osk-stevia || true
        if command -v phosh-osk-stub >/dev/null 2>&1; then
            (setsid phosh-osk-stub --allow-replacement >/dev/null 2>&1 &) || true
            info "已尝试恢复 phosh-osk-stub"
        fi
    fi
    if [ -n "$DESKTOP_USER" ]; then
        as_desktop_user gsettings set org.gnome.desktop.input-sources sources \
            "[('xkb', 'us')]" 2>/dev/null || true
    fi
    info "完成。stevia 是源码安装（ninja install），没有 apt 包名；"
    info "要彻底清掉： cd /opt/stevia-src && sudo ninja -C _build uninstall"
}

# ---------------------------------------------------------------- 主流程

SKIP_STEVIA=0
REPLACE_NOW=0
MODE=install

for arg in "$@"; do
    case "$arg" in
        --skip-stevia) SKIP_STEVIA=1 ;;
        --replace-now) REPLACE_NOW=1 ;;
        --verify-only) MODE=verify ;;
        --status)      MODE=status ;;
        --uninstall)   MODE=uninstall ;;
        --restore-osk) MODE=restore ;;
        -h|--help)     usage; exit 0 ;;
        *) die "未知选项：$arg（-h 看帮助）" ;;
    esac
done

detect_desktop_user || DESKTOP_USER=""

case "$MODE" in
    verify)
        verify
        exit $?
        ;;
    status)
        status
        exit 0
        ;;
    uninstall)
        uninstall
        exit 0
        ;;
    restore)
        # 不动任何系统文件，只把系统自带键盘拉起来。
        # 屏幕键盘没了手机就没法用，所以这条路径不依赖本项目是否装成功。
        restore_osk
        exit $?
        ;;
esac

[ "$(id -u)" = 0 ] || die "需要 root：curl -fsSL <repo>/install.sh | sudo sh"

step "Treenput 树入法 · 一键安装"
if [ -n "$DESKTOP_USER" ]; then
    info "桌面用户：$DESKTOP_USER"
else
    warn "定位不到桌面用户，配置步骤会部分跳过（引擎仍会装好）"
fi

ensure_repo
install_deps
build_engine
register_uim_preload
if [ "$SKIP_STEVIA" = 0 ]; then
    build_stevia
else
    step "跳过 stevia（--skip-stevia）"
fi
enable_input_source
if [ "$REPLACE_NOW" = 1 ]; then
    replace_osk
fi

step "安装结果"
verify || warn "校验有未通过项，见上方提示"

echo
echo "接下来：重启 phosh（或手动执行 phosh-osk-stevia --replace），"
echo "然后点键盘左上角的 mode 按钮切到拼音模式，输 ni hao 看是否出「你好」。"
if [ "$SKIP_STEVIA" = 0 ] && [ "$REPLACE_NOW" = 0 ]; then
    echo "想现在就换掉屏幕键盘： sudo ./install.sh --replace-now"
fi