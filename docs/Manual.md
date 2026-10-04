# Manual — 手动安装步骤

> 默认用根目录的 `install.sh` 一条命令装（见 [Install.md](../Install.md)）。
> 这份文档只给这些情况用：无网、需要逐步确认、或要装到非 Mobian 发行版。
>
> 原样保留了实测走通的全过程，包含每一步的判别标准。

适用：**Mobian / Debian 13 (trixie) / phosh 0.46 / arm64**
其他 phosh 发行版参照执行，差异见文末「其他发行版」。

全程**不升级内核、不替换发行版、不动系统输入法框架**，只装用户态包。

---

## 0. 前置检查

```bash
# 确认系统与合成器
cat /etc/os-release | head -2
phoc --version || dpkg -l phoc | tail -1

# 确认屏幕键盘现状（Phosh 0.46 是 phosh-osk-stub，没有中文）
pgrep -a osk-stub

# 确认 uim 与 opencc 可用
apt-cache policy uim uim-pinyin opencc | grep -E "^[a-z]|候选"
```

预期：`uim 1:1.9.6-1`、`opencc 1.1.9` 有候选即可。

---

## 1. 安装构建依赖

```bash
sudo apt-get update
sudo apt-get install -y \
    meson ninja-build pkg-config gettext \
    libgtk-3-dev libhandy-1-dev libjson-glib-dev \
    libwayland-dev libsystemd-dev libxml2-utils \
    libhunspell-dev libpresage-dev libuim-dev \
    libgmobile-dev libgnome-desktop-3-dev libfeedback-dev \
    libgovarnam-dev \
    uim uim-pinyin uim-anthy uim-data \
    opencc libopencc1.1 libopencc-data \
    fonts-noto-ui-core fonts-noto-cjk
```

> **⚠️ Mobian 用户注意**：`libgtk-3-dev` 可能装不上，报
> `libgtk-3-dev 依赖 gir1.2-gtk-3.0 (= 3.24.49-3) 但是 3.24.49-3mobian1 正要被安装`。
> 这是因为 Mobian 给 GTK3 打了 `-mobian1` 补丁版，而 Debian 源里只有原版 `-dev`。
> 解法见文末「常见问题 A」。

---

## 2. 生成简体拼音引擎

```bash
git clone https://github.com/SZYTree0312/Treenput
cd Treenput

python3 engine/build_cn_engine.py \
    --input  /usr/share/uim/pinyin-big5.scm \
    --output /usr/share/uim/pinyin-cn-utf8.scm \
    --freq   data/frequency.txt          # 可选，强烈建议
```

预期输出：

```
opencc批量转换: 可用 (去重后 6231 个汉字)
已生成 /usr/share/uim/pinyin-cn-utf8.scm
  音节 1388 条 / 候选 11619 个
```

`--freq` 省略时脚本仍能工作，但只靠内置常用字基线排序，
真实词频能显著改善候选顺序（见 `data/frequency.txt` 说明）。

---

## 3. 让 uim 引擎认识新表

uim 通过 `~/.uim-preload` 预载自定义模块。写入：

```
;; ~/.uim-preload
(append!olist "modules" "pinyin-cn-utf8")
```

这会加载 `/usr/share/uim/pinyin-cn-utf8.scm`。**注册代码就在那个文件里**——
`build_cn_engine.py` 生成规则表时会一并写出注册块，见下方「注册机制」。

### 注册机制（2026-10-04 在 OnePlus 6 / Debian 13 上考证）

早期版本把注册写成 `(named-input-method "cn" "pinyin-cn-utf8")`，
**这个东西在 uim 里根本不存在**。查证结论：

- 整个 `/usr/share/uim/*.scm` 里没有 `named-input-method` 的定义，
  `libuim.so.8` 里也搜不到对应符号 —— 写进配置只会让 uim 报
  `unbound variable`，而**不会注册出任何输入法**。
- **Debian 13 的 uim 也没有 `uim-proc`**（只有 `uim-sh` 和 `libuim.so.8`），
  所以旧文档的验证命令 `uim-proc -e cn-inputmethod` 是失效命令。

真正的注册途径是 **`generic-register-im`**，系统自带的
`/usr/share/uim/pyload.scm` 就是样板（它注册了 `py` / `pyunihan` / `pinyin-big5`）：

```scheme
(require "im.scm")
(require "generic.scm")

;; register-im 内部有 gating：只有 enabled-im-list 为空、或目标名已在列表里，
;; 注册才会真正生效。uim 自己的做法是注册前先清空（见 uim-module-manager.scm）。
(if (not (memq 'cn enabled-im-list))
    (set! enabled-im-list (cons 'cn enabled-im-list)))

(define pinyin-cn-utf8-init-handler
  (lambda (id im arg)
    (generic-context-new id im pinyin-cn-utf8-rule #f)))

(generic-register-im
 'cn "zh_CN" "UTF-8"
 (N_ "Treenput (Simplified)")
 (N_ "Treenput simplified pinyin input method")
 pinyin-cn-utf8-init-handler)
```

顺带一提：uim **本来就自带简体拼音输入法 `py`**（pyload.scm 注册的
"New Pinyin (Simplified)"），另有 `pyunihan`、`pinyin-big5`（繁体）。
本项目是自带词频排序的简体表并注册为 `cn`，不是从零造拼音引擎。

### 验证注册是否生效

不要信"文件写了"，要问 uim 自己的运行时登记表：

```bash
uim-sh <<'SCHEME'
(require "im.scm")
(require "generic.scm")
(require "pinyin-cn-utf8.scm")
(print (if (retrieve-im 'cn) "FOUND" "MISSING"))
SCHEME
```

返回 `FOUND` 才算真的注册上了。这也是 `install.sh` 最后的校验项之一。

---

## 4. 构建并启用 stevia 屏幕键盘

Phosh 0.46 自带的是 `phosh-osk-stub`，**没有中文**。
stevia 0.54.0 起才带uim 中文支持，需从源码构建。

```bash
sudo apt-get install -y git
git clone --depth 1 https://gitlab.gnome.org/World/Phosh/stevia.git
cd stevia

# Debian trixie 的 dconf 是 0.40，stevia main 要求 >= 0.49。
# 放宽这一行版本断言（全文仅此一处使用 dconf）。
sed -i "s/dependency('dconf', version: '>= 0.49')/dependency('dconf')/" meson.build

meson setup -Dgtk_doc=false -Dman=false _build
ninja -C _build
sudo ninja -C _build install
```

### 切换到 stevia

```bash
sudo systemctl stop phosh-osk-stub   # 或 pkill -f phosh-osk-stub
```

stevia 的 systemd 用户单元会自动接管，也可手动替换现有 OSK 进程：

```bash
pkill -f phosh-osk-stub
_build/run --replace            # 从源码树试运行
# 确认可用后再用系统安装的：
phosh-osk-stevia --replace
```

> **不要用 `--replace` 之外的顶替方式**：stevia 与 osk-stub 抢同一个
> Wayland input-method slot，`--replace` 是官方支持的临时替换手段。

---

## 5. 启用中文拼音

设置输入源（GNOME 标准机制）：

```bash
gsettings set org.gnome.desktop.input-sources sources \
  "[('xkb', 'us'), ('ibus', 'uim:cn')]"
```

在键盘左上角（stevia 的 mode 按钮）切换 `直接入力` → 拼音模式，
然后输入拼音即可出现简体候选。

**注意**：不要设置 `GTK_IM_MODULE=fcitx` 之类的环境变量，
那会重新引入 fcitx5 抢占屏幕键盘的问题（见 `TroubleShooting.md`）。

---

## 6. 验证

```bash
# 1. 引擎在位
ls -la /usr/share/uim/pinyin-cn-utf8.scm

# 2. 候选为简体（应全部是简体字）
grep -oE "[龍龜電腦這個]" /usr/share/uim/pinyin-cn-utf8.scm | wc -l   # 期望 0

# 3. 常见拼音排序正确
grep "n\" \"i" /usr/share/uim/pinyin-cn-utf8.scm   # 第一个应是 "你"
grep "h\" \"a\" \"o" /usr/share/uim/pinyin-cn-utf8.scm  # 第一个应是 "好"

# 4. 屏幕键盘进程在跑
pgrep -a stevia
```

最后在手机屏幕上点一个文本框，切换到拼音，打`ni hao` 看是否出「你好」。

---

## 常见问题

### A. `libgtk-3-dev` 装不上（Mobian 专有）

> `install.sh` 会自动检测并处理这个冲突（降级 GTK3 两个包并留下回滚记录）。
> 手动安装时才需要照下面做。

**症状**
```
E: libgtk-3-dev : 依赖: gir1.2-gtk-3.0 (= 3.24.49-3) 但是 3.24.49-3mobian1 正要被安装
```

**原因**：Mobian 重打包了 GTK3（`3.24.49-3mobian1`），但其私有源
`repo.mobian.org` 不提供 `-dev` 包，Debian 源里的 `-dev` 只认原版版本号。

**解法**：显式降级两个包（实测只动这 2 个，不影响桌面）：

```bash
sudo apt-get install -y --allow-downgrades \
    gir1.2-gtk-3.0=3.24.49-3 \
    libgtk-3-0t64=3.24.49-3
```

降级前建议存档以便回滚：

```bash
dpkg -l gir1.2-gtk-3.0 libgtk-3-0t64 | grep ^ii | sudo tee /root/gtk3-rollback.txt
```

**回滚**（若桌面异常）：
```bash
sudo apt-get install -y --allow-downgrades \
    gir1.2-gtk-3.0=3.24.49-3mobian1 \
    libgtk-3-0t64=3.24.49-3mobian1
```

### B. meson 报 dconf 版本不足

见第 4 步的 `sed`。这是唯一需要改源码的地方，
因为 Debian trixie 的 dconf 停在 0.40.0，而 stevia 要求 ≥ 0.49。

放宽后实测不影响功能——stevia 只在 `meson.build` 一处声明 dconf 依赖。

### C. 触屏完全无反应

大概率是应用跑在 XWayland 上。XWayland 把触控当 XInput 事件，
Electron 等应用的 X11 后端不处理，只吃鼠标。

Electron 应用加 `--ozone-platform=wayland` 并 `unset DISPLAY`。

### D. 候选出繁体

说明走了 OpenCC 但上游表含生僻字映射差异。检查：

```bash
echo "测试繁體" | opencc -c t2s.json    # 应输出 "测试繁体"
```

---

## 其他发行版

| 发行版 | 差异 |
|--------|------|
| Debian 13 / Ubuntu 24.04+ | 本指南可直接用 |
| Debian 12 | dconf 0.40，同样需放宽；libhandy-1 需 ≥ 1.1.90 |
| Arch / Manjaro（Phosh） | 包名不同：`base-devel meson ninja gtk3 libhandy uim opencc`；无版本冲突 |
| postmarketOS | 需先装 GTK3 + libhandy；phosh 版本较老时同样走源码构建 |
| 有 `dconf ≥ 0.49` 的发行版 | 第 4 步的 `sed` 可省略 |

**通用要求**：
- 合成器支持 `zwp_input_method_v2`（phoc 0.46 已支持）
- 能装 GTK3 + libhandy-1（stevia 依赖）
- `uim` 与 `opencc` 可用

---

## 卸载

```bash
# 引擎与配置（install.sh --uninstall 会自动做这些）
sudo rm -f /usr/share/uim/pinyin-cn-utf8.scm
sudo sed -i '/pinyin-cn-utf8/d' ~/.uim-preload
gsettings set org.gnome.desktop.input-sources sources "[('xkb','us')]"

# 恢复原屏幕键盘
pkill -f phosh-osk-stevia && phosh-osk-stub --allow-replacement &

# stevia 是源码 ninja install 的，没有 apt 包名。
# 要彻底清掉（会删掉 phosh-osk-stevia 及相关数据）：
cd /opt/stevia-src && sudo ninja -C _build uninstall
```