# Research — 调研记录：为什么传统路线都走不通

写这份文档是为了让后来者不必重走一遍死路。

> 里面的 `apt-cache policy`、`dpkg -L` 等命令是当初验证结论时用的，只读、
> 不改动系统。要安装请用根目录的 `install.sh`（见 [Install.md](../Install.md)）。

---

## 目标环境（实测基线）

| 项 | 值 |
|---|---|
| 设备 | OnePlus 6 (enchilada), sdm845 |
| 系统 | Mobian / Debian 13 (trixie) / arm64 |
| 合成器 | phoc 0.46.0-1 |
| Shell | phosh 0.46.0-3+deb13u1 |
| 屏幕键盘 | `phosh-osk-stub --allow-replacement` |
| 可用内存 | 7.5 GB |
| 网络 | Debian 源（中科大镜像）通；GitHub/Docker Hub 直连超时 |

---

## 路线一：fcitx5 + fcitx5-chinese-addons ❌ 滑铁卢

**结论：不可用。这是本项目存在的主要理由。**

已在真机验证的失败机理：

1. Phosh 0.46 的屏幕键盘是 `phosh-osk-stub`，带 `--allow-replacement`
2. fcitx5 作为 Wayland IM 客户端注册后把 osk-stub 顶掉
3. fcitx5 **只做输入转换，不提供键盘 UI**
4. 结果：屏幕上没有任何键盘，彻底无法输入

**判别特征**：锁屏能输入、桌面不能输入。
（锁屏用自己的键盘，不走 IM 协议。）

**根因反思**：桌面 Linux 的 `GTK_IM_MODULE=fcitx` 那套假设「桌面已有键盘可用」。
而 Phosh 是纯 Wayland 手机环境，**IM 协议本身承担键盘 UI 角色**。
引入「不做 UI 的 IM」等于删掉键盘。

详见 `TroubleShooting.md` 第一节。

---

## 路线二：`uim-pinyin`（Debian 官方包）❌ 空壳

```bash
$ dpkg -L uim-pinyin
/.
/usr
/usr/share
/usr/share/doc
/usr/share/doc/uim-pinyin
```

**只有 doc 目录，没有任何引擎文件。**

实际上 uim 的拼音表在 `uim-data` 里，名为 `pinyin-big5.scm`，
来自 XCIN 项目。名字里的 "big5" 是历史遗留 —— Debian 维护者
已把候选表转成 UTF-8 汉字（不是 Big5 码位），这点很关键。

**本项目就是基于这个表做简繁统一 + 排序。**

---

## 路线三：stevia 内置 uim 中文（上游方案）⚠️ 半成品

2026-03-02 上游宣布：

> We just landed initial support for Chinese (via #pinyin) and Japanese
> (via #anthy / romaji) in Phosh's on screen keyboard #stevia using #uim.
> **As our current maintainers don't speak / write these languages we
> appreciate testing feedback**...

### 现状

- ✅ 键盘框架（stevia）本身可用，纯 C，编译顺利
- ✅ uim 引擎集成可用（`Uim: YES`）
- ✅ `phosh-osk-stevia-uim` 子包依赖 `uim-pinyin`
- ❌ **但 `uim:cn`（简体引擎）在这类系统中不存在**

上游发布说明里给的启用方式：

```bash
gsettings set org.gnome.desktop.input-sources sources \
  "[('xkb','us'), ('ibus','uim:cn')]"
```

但 `uim:cn` 需要一个 `cn` 输入法定义和对应的 `pinyin-cn-utf8` 表，
这两样在任何 Debian/Ubuntu 包里都没有。

**维护者自己承认不读写中文**，这块没有社区保障 —— 这正是我们的切入点。

### 补充考证（2026-10-04，OnePlus 6 / Debian 13 真机）

早期版本以为注册只要写一行 `(named-input-method "cn" "pinyin-cn-utf8")`。
**这是错的**，已证伪：

- `/usr/share/uim/*.scm` 全文、`libuim.so.8` 符号表里都没有 `named-input-method`；
  写进配置只会报 `unbound variable`，注册不出任何输入法。
- Debian 13 的 uim 1:1.9.6 **不带 `uim-proc`**，只有 `uim-sh` 与 `libuim.so.8`。
  stevia 是直接链接 `libuim.so.8`，不走外部进程。
- 正确途径是 `generic-register-im`，样板在系统自带的 `pyload.scm`。
- 还要注意 `register-im` 内部的 gating：`enabled-im-list` 非空时，名字不在列表里的
  IM 会被**静默丢弃**。uim 自己的 `uim-module-manager.scm` 也是先
  `(set! enabled-im-list ())` 再注册。

另外纠正一处背景 inaccurate：**uim 本来就自带简体拼音输入法 `py`**
（pyload.scm 注册的 "New Pinyin (Simplified)"），另有 `pyunihan`、
`pinyin-big5`（繁体）。本项目不是从零造拼音引擎，而是
「自带词频排序的简体表 + 注册成 `cn`」。

---

## 路线四：Waydroid / Android 容器 ❌ 方向错误

常被推荐来「解决 APK 兼容」，但：
- 与「让 deb 显示/输入正常」是两个正交问题
- 救不了 deb 的排版和输入
- 代价：几百 MB Android 镜像 + 内核 binder/ashmem 支持

只有在你**确实缺某个 Android 独占 app** 时才值得。

---

## 路线五：ibus / libpinyin ❌ 包不存在

```bash
$ apt-cache policy ibus-libpinyin ibus-pinyin
# 无候选
```

Mobian 精简掉了 ibus 引擎栈。

---

## 选定方案

**在不换内核、不换发行版、不换 IM 框架的前提下，
构建 stevia + 用 OpenCC 加工出真正的简体拼音引擎。**

### 验证结果（arm64 真机）

```
opencc批量转换: 可用 (去重后 6231 个汉字)
已生成 /usr/share/uim/pinyin-cn-utf8.scm
  音节 1388 条 / 候选 11619 个
```

抽查候选排序：

| 拼音 | 首个候选 | 是否正确 |
|------|---------|---------|
| `ni` | 你 | ✅ |
| `hao` | 好 | ✅ |
| `zhong` | 中 | ✅ |
| `guo` | 国 | ✅ |
| `shi` | 是 | ✅ |

繁体残留检测：`0`

### 关键决策记录

**不升级 Mobian 内核。** 内核升级风险极高（无线网卡、触摸、显示、
电源管理全部依赖厂商内核补丁），且对本项目目标无帮助 ——
中文输入完全在用户态。

**改一处源码版本断言。** stevia 要求 `dconf >= 0.49`，
Debian trixie 只有 0.40.0。这不是能力缺失（stevia 只在
`meson.build` 一处声明 dconf 依赖），是上游针对更新发行版的假设。
放宽后编译、运行、测试全部通过。

**降级 GTK3 两个包。** Mobian 的 `3.24.49-3mobian1` 与 Debian 原版 `-dev`
版本号不匹配导致装不上 `libgtk-3-dev`。显式降级
`gir1.2-gtk-3.0` 和 `libgtk-3-0t64` 两个包后解决，
实测桌面（phoc / phosh / osk-stub）零损伤。

---

## 待办 / 已知缺口

- [ ] **词频库**：`data/frequency.txt` 目前只有基线常用字，
      需要真实词频数据才能让候选顺序达到商用 IME 手感
- [ ] **词组级候选**：目前是单字引擎，接`uim` 的 `dict` 机制可做词组
- [ ] **上传/引码方案**：stevia 自带上传模式，可作为默认
- [ ] **PC 端验证**：本项目只验证了 Mobian；其他发行版需按 `docs/Manual.md` 验证
- [ ] 长期可用性：需要有人长期维护（这是上游放弃的部分）