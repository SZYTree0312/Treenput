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

### stevia 用哪个引擎是硬编码的（2026-10-04 考证）

读 stevia 0.55.0 的 `src/completers/pos-completer-uim.c`：

```c
static PosUimInputMethod ims[] = {
  { .id = "cn", .name = "Pinyin", .uim = "py",         },
  { .id = "jp", .name = "Anthy",  .uim = "anthy-utf8"  },
};
```

**`cn` 被硬编码到 uim 自带的 `py`，不是我们注册的输入法。**
所以只把 `uim:cn` 写进 input-sources 是不够的 —— stevia 内部的
「Pinyin」条目走的是 `py`，本项目生成的词频排序表默认用不上。

要让 stevia 用我们的表，把这一处改成 `.uim = "cn"` 重新编译即可。
两个引擎都是 `generic-context-new` + 同格式的 rule 表
（`((("n" "i")) ("你" "泥" ...))`），实测格式完全兼容，替换风险低。
`install.sh` 已内置这一步，可用 `TREE_STEVIA_USE_UPSTREAM_PY=1` 关掉。

判别方法：装完看键盘上的模式名。走 `py` 与走 `cn` 的候选顺序不同
（我们的表按 `data/frequency.txt` 排）。

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
---

## 六、为什么 v1.0.0 打不出词（2026-10-05 定位）

### 排查过程

v1.0.0 能打出汉字，但输 `nihao` 只能得到「你」「好」两个独立单字。

最初怀疑是 uim custom 配置没生效 —— `generic.scm` 里
`generic-use-candidate-window?` / `generic-show-candidate-implicitly?`
这两个变量控制候选窗口，且在 `/usr/share/uim` 下**没有定义**，
看起来像「默认关掉了」。于是往 `~/.uim.d/customs/custom-generic.scm`
和 `~/.uim` 里追加定义，**行为完全没变**。

### 两个错误假设

1. **custom 文件名**：以为primary group 是 `generic`，写成 `custom-generic.scm`。
   实际 `generic-custom.scm` 里用的是 `define-custom ... '(other-ims candwin)`，
   `(car groups)` 才是 primary group，所以 uim 找的是 `custom-other-ims.scm`。
2. **默认值**：以为这两个变量默认是 `#f`（关）。实际 `define-custom` 的第二参数
   就是默认值 —— `generic-use-candidate-window? #t`、
   `generic-show-candidate-implicitly? #t`，**默认本来就是开**。

所以无论文件名写对与否，行为都不该变。这条线索是死胡同。

### 真正的根因

把设备上三张拼音表全拉下来审计，发现**全是单音节→单字，零词条**：

| 表 | 条目| 含 2 字及以上候选 |
|---|---|---|
| `pinyin-cn-utf8.scm` | 1369 | **0** |
| `py.scm` | 454 | **0** |
| `pyunihan.scm` | 407 | **0** |

所以 `ni` 精确命中后候选里根本没有「你好」，再输 `h` 就断了
（`h` 和 `in` 单独都不在表里，表里只有 `hao`、`yin`）。

### 引擎结构本来就支持词条

`rk.scm` 的匹配语义（已读源码确认）：

- `rk-push-key!` 走 **front-match**，`immediate-commit` 为 `#f`
- `rk-cands-with-minimal-partial` 返回精确匹配 + **最长前缀**的部分匹配
- 表里的键是**逐字母**的：`"h" "a" "o"` 表示按 h、a、o 三键

所以 uim 的generic 引擎**天然支持多音节词**，`("n" "i" "h" "a" "o")` ->
`("你好")` 是合法规则。只是上游 XCIN 表从来没往里放过词。

离线模拟 rk 语义验证（`rk-lib-find-seq` + `rk-lib-find-partial-seqs`
的行为复现），加词条后：

```
 nihao   -> 你好
 nih     -> 你好+ao      <- 输到一半就提示
 niha    -> 你好+o
```

### 实现要点

词条数据用 **jieba**（34.9 万纯汉字词条，带词频）+ **pypinyin**
（汉字→无声调拼音，正好补多音字），按词频取 top 80,000（覆盖 97.1% 词频质量）。

> **踩过的坑（重要）**：规则表键必须与上游表同构，即**逐字母**。
> 词条 `ni hao` 要展成 `("n","i","h","a","o")`；写成 `("ni","hao")`
> 会被当成按两次非法键，症状是「脚本报告加了 N 条，候选里一个词都没有」。

另一处坑：`convert_entry` 原本对所有候选跑 `score_candidate`，
而多字词在词频表里查不到 → 得分 0 → 被排到单字后面。改成
**多字候选恒定排在单字之前**（词条本身已按词频排好序）。

---

## 七、为什么原生 Wayland 应用（Firefox）不弹屏幕键盘

### IM 协议代差

| 协议 | 作用 | 谁提供 / 谁用 |
|---|---|---|
| `zwp_input_method_manager_v2` | 物理键盘路由（谁按的键发给谁） | stevia v0.55.0 绑定 |
| `zwp_text_input_manager_v3` | 文本输入（preedit / 候选窗口 UI） | phoc 0.46 提供，GTK 应用用 |

stevia v0.55.0 只绑了 input-method v2，**没有** text-input v3。
而 OSK 的候选窗口靠 text-input v3 的 `preedit_string` / `cursor_rect`
事件定位到输入框上方。

Firefox ESR 153 是原生 Wayland 应用，直接跟 compositor 谈 text-input v3，
于是绕过 stevia → 键盘不弹。系统应用和终端走 GTK 的 v3 或 XIM，
GTK 会同时用 v3 和 IM module（`im-wayland.so` / `im-xim.so` 都在），
所以不受影响。

### 对策

让 Firefox 退回 XWayland 走 XIM（`uim-xim` 本来就在跑）。
只写 `~/.local/share/applications/` 的用户级 desktop 覆盖，不动系统文件。

根治要等 stevia 支持 text-input v3 —— 那是 C 图形栈的活，
对一个输入法项目来说改动面过大，且无法回退。
