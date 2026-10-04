# TroubleShooting

> 装不上先重跑 `install.sh`（幂等），仍失败再看这里对应条目。
> 安装入口见 [Install.md](../Install.md)。

## 一、fcitx5 抢占屏幕键盘事故（完整复盘）

这是 Mobian 上中文输入最经典的坑，值得完整记录，因为它有很强的误导性。

### 症状

- 装了fcitx5 + fcitx5-chinese-addons 后，**手机上彻底没法打字**
- 诡异之处：**锁屏能输入，桌面不能输入**
- 中文输入需要物理键盘（蓝牙/OTG）才能用

### 根因

三个事实叠加：

1. **Phosh 0.46 的屏幕键盘是 `phosh-osk-stub`**，以 `--allow-replacement` 运行。
2. fcitx5 作为 Wayland input-method 客户端注册后，
   把 osk-stub **顶替**掉了（因为它带 `allow-replacement`）。
3. **fcitx5 只提供输入法引擎，不画屏幕键盘**。

于是：屏幕键盘被顶掉→ 没有键盘 UI 出现 → 完全无法输入。

**「锁屏能输、桌面不能输」就是这个 bug 的判别特征**：
锁屏界面（phosh lockscreen）用自己的键盘，不走 input-method 协议，
所以不受影响。凡是看到这个症状，基本可以直接确诊。

### 为什么常见传统做法在这里全错

桌面 Linux 上的标准做法是：

```bash
# ✗ 在Phosh 上这是反模式
export GTK_IM_MODULE=fcitx
export QT_IM_MODULE=fcitx
export XMODIFIERS=@im=fcitx
# + 把 fcitx5 加进 autostart
```

这套在 X11 桌面上成立，但它假设了「桌面已有 X11 键盘可用，IM 只负责输入转换」。
Phosh 是纯Wayland 手机环境，**IM 协议本身就承担了键盘 UI 的角色**——
引入一个「只做转换不做 UI」的 IM，等于把键盘删了。

### 结论与教训

> **在 Phosh / Wayland 手机环境下，不要引入「不提供键盘 UI 的独立 IM 客户端」。
> 屏幕键盘和输入法引擎必须是一个整体。**

这也是本项目选择「让屏幕键盘自带中文引擎」而不是「装独立 IM」的根本原因。

### 处置

本项目**不使用 fcitx5**，故无需处置。若你之前装过并已卸载，确认：

```bash
which fcitx5 || echo "未安装（正确）"
pgrep -f fcitx5 || echo "无残留进程（正确）"
```

---

## 二、编译 stevia 相关

### `meson setup` 报 dconf 版本不足

```
ERROR: Dependency lookup for dconf ... Invalid version, need '>= 0.49' found '0.40.0'
```

**这是 Debian trixie 的正常情况**，trixie 的 dconf 就是 0.40.0。
stevia main 分支已针对更新的发行版。

```bash
sed -i "s/dependency('dconf', version: '>= 0.49')/dependency('dconf')/" meson.build
```

全文仅一处声明 dconf，放宽后实测无副作用（已在 arm64 真机验证编译+运行）。

### 依赖求解失败：`libgtk-3-dev 依赖 gir1.2-gtk-3.0 (= 3.24.49-3) 但是 ...-mobian1`

Mobian 专有问题，见 `docs/Manual.md` 常见问题 A。
`install.sh` 会自动处理：检测到 `-mobian1` 版本就显式降级那2 个包，
并把原版本号存到 `/root/treenput-gtk3-rollback.txt` 供回滚。

**不要**用 `--allow-change-held-packages` 硬闯，也不要整体`--allow-downgrades`，
先显式降级那 2 个包，把影响面控制到最小。

### uim 测试失败但其实是好的

```
ERROR: assertion failed (display_name == "Japan (anthy)"): ("日本 (anthy)" == "Japan (anthy)")
```

这是**本地化字符串差异**（系统 locale 是中文，测试期望英文），
不是功能失败。用 `LANG=C.UTF-8` 跑即可通过：

```bash
xvfb-run -a env LANG=C.UTF-8 ./_build/tests/test-completer-uim
# ok 1 /pos/completer/uim/object
```

---

## 三、运行时问题

### 屏幕键盘不弹出

```bash
pgrep -a osk-stub        # 原OSK 是否还在
pgrep -a stevia          # stevia 是否已接管
```

两者会抢同一个 IM slot。stevia 启动时会自动替换，还是不行就手动：

```bash
pkill -f phosh-osk-stub
_build/run --replace# 源码树试运行
```

另外确认 GNOME 的「屏幕键盘」开关是开的：

```bash
gsettings get org.gnome.desktop.a11y.applications screen-keyboard-enabled
# 若不是 true：
gsettings set org.gnome.desktop.a11y.applications screen-keyboard-enabled true
```

### 只有英文，没有中文候选

按顺序检查：

```bash
# 1. 输入源里有没有 cn
gsettings get org.gnome.desktop.input-sources sources
# 应包含 ('ibus', 'uim:cn')

# 2. uim 里有没有真的注册出 cn
#    Debian 13 的 uim 没有 uim-proc（只有 uim-sh 与 libuim.so.8），
#    旧文档的 uim-proc -e cn-inputmethod 是失效命令。改用：
uim-sh <<'SCHEME'
(require "im.scm")
(require "generic.scm")
(require "pinyin-cn-utf8.scm")
(print (if (retrieve-im (quote cn)) "FOUND" "MISSING"))
SCHEME

# 3. 预载配置是否写了
cat ~/.uim-preload

# 4. 引擎文件在位
ls -la /usr/share/uim/pinyin-cn-utf8.scm

# 5. 引擎表里真有内容
grep -c '(((' /usr/share/uim/pinyin-cn-utf8.scm
```

### 候选出繁体字

```bash
echo "繁體測試" | opencc -c t2s.json    # 应为 "繁体测试"
```

若这条正常，说明引擎表没重新生成。重新跑 `build_cn_engine.py`。

### 候选顺序很乱（生僻字排在前面）

没提供词频文件。生成时加 `--freq`：

```bash
python3 engine/build_cn_engine.py \
    --input /usr/share/uim/pinyin-big5.scm \
    --output /usr/share/uim/pinyin-cn-utf8.scm \
    --freq data/frequency.txt
```

### 触屏无反应 / 只有鼠标能用

**这是应用后端问题，不是输入法问题。**

现象：桌面 app 只认鼠标，触屏点了没反应。

诊断：

```bash
ls /tmp/.X11-unix/          # 若有 X0/X1 说明 XWayland 在跑
tr '\0' '\n' < /proc/<pid>/environ | grep -E 'DISPLAY|WAYLAND'
```

若 app 跑在 X11/XWayland 后端上，XWayland 把触控当 XInput 事件发，
而 Electron/CEF 的 X11 后端只处理核心指针（鼠标），触控等于没反应。

解法：强制原生 Wayland。

```bash
# Electron / CEF 类
<app> --ozone-platform=wayland
# 并确保环境里没有 DISPLAY
unset DISPLAY
```

GTK4 / Qt 应用在 phoc 下默认就是 Wayland，通常无需处理。

---

## 四、快速诊断清单

| 症状 | 首查 |
|------|------|
| 完全没法打字 | 是否装了独立 IM 抢占屏幕键盘（见第一节） |
| 锁屏能输桌面不能 | **确诊：IM 抢占** |
| 触屏没反应只有鼠标行 | app 是否跑在 XWayland 上 |
| 键盘不弹出 | `pgrep -a stevia` / `screen-keyboard-enabled` |
| 没中文候选 | `gsettings ... input-sources` 是否含 `uim:cn` |
| 候选是繁体 | opencc 是否可用；重新生成引擎 |
| 候选顺序乱 | 是否加了 `--freq` |
| meson dconf 报错 | 见第二节 |
| apt 依赖冲突 | Mobian GTK3 补丁版冲突，`install.sh` 自动降级；手动见 `docs/Manual.md` 常见问题 A |