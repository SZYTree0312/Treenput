# Treenput

**树入法** — 面向 Mobian / Phosh 等移动 Linux 的简体拼音输入方案。

纯用户态实现，不修改内核、不替换系统输入法框架、不升级发行版。
针对「Debian 13 + Mobian + phosh 0.46 这类版本组合下没有可用中文拼音」的问题，
在现有系统内部做精准适配。

> 命名说明：起名不蹭任何第三方产品名（不叫 fcitx-pinyin、sogou、mozc 等），
> 「树入」= 树的输入法，同时是「输入」的谐音双关。

**v1.1.0**（2026-10-08）：**用户词典**——`treenput-dict` 加自己的词、调词频，
`apply` 后自动重启屏幕键盘即刻生效。真机实测：`shurufa` 出「树入法」并压过
内置的「输入法」；引擎里原本没有的音节也能现场新建规则行。

**v1.0.5**（2026-10-05）：补上**多音节词条**（79,228 条），`nihao` 出「你好」。

**v1.0.0**（2026-10-05）：在 OnePlus 6 / Mobian Debian 13 / phosh 0.46 / arm64
真机上跑通——一条命令装完，重启后仍是中文键盘，打拼音出汉字候选。

---

## v1.0.5 解决了什么

### 1. 词条：从「只有单字」到「能打词语」

v1.0.0 能打出汉字，但**打不出词**——输 `nihao` 只能拿到「你」「好」两个独立单字，
后续音节从头开始。这不是配置问题，是**词库本身没有词**：

| 表 | 条目 | 含 2 字及以上候选 |
|---|---|---|
| `pinyin-cn-utf8.scm`（本项目 v1.0.0 产物） | 1369 | **0** |
| `py.scm`（uim 自带） | 454 | **0** |
| `pyunihan.scm`（uim 自带） | 407 | **0** |

三张表全是单音节→单字映射。uim 的 `rk` 引擎**本身支持**多音节键（表里 `hao`
就是逐字母的 `"h" "a" "o"`），只是没人往表里放词。

v1.0.5 生成 **79,228 条多音节词条**（jieba 词频 + pypinyin 注音，按词频截取
top 80,000，覆盖 97.1% 词频质量）。**单字候选全部保留**，词条排在同音节单字之前。

真机验证（stevia 直接驱动 `cn`，逐键喂入`nihao`）：

```
[after 'n'] preedit='嗯'      候选：嗯 唔 那 拿 哪 纳 ...
[after 'i'] preedit='你'      候选：你 妮 泥 尼 倪 ...
[after 'a'] preedit='niha'    候选：你好 +o      <- 输到一半已提示完整词
[after 'o']                  精确命中「你好」
```

### 2. 引擎预生成

> **已知未解决：Firefox 等原生 Wayland 应用不弹屏幕键盘。** 根因是 IM 协议
> 代差（stevia 只绑 input-method v2，OSK 的 preedit/候选靠 text-input v3；
> Firefox 原生 Wayland 直接谈 v3 绕过 stevia）。v1.0.5 曾尝试让 Firefox 退回
> XWayland 走 XIM，**实测无效**（XWayland 下 Firefox 报
> `Loading IM context type 'xim' failed`），该改动已撤回。详见
> `docs/TroubleShooting.md`。

`install.sh` 现在**优先安装仓库里的预生成引擎**（`data/pinyin-cn-utf8.scm`），
用户机器上不需要 Python、不需要 opencc、不需要 jieba/pypinyin，装完即可用。
仓库里没有预生成产物时，才回退到现场生成（需要 python3）。

---

## 实测状态

**2026-10-04 在 OnePlus 6 / Debian 13 trixie / phosh 0.46 / arm64 真机跑完整安装**：

```
==> 生成简体拼音引擎
opencc批量转换: 可用 (去重后 6202 个汉字)
  音节 1369 条 / 候选 11190 个

==> 校验
  繁体残留：0
  抽查通过 10/10
    ni→你    hao→好    zhong→中   guo→国    shi→是
    ji→机    wo→我     ta→他     de→的     yi→一
  uim 输入法注册：FOUND:cn/zh_CN        <- 关键：uim 真的认到了 cn
```

`Install.md` 那条命令从头跑到尾，退出 0。

屏幕键盘侧（2026-10-05 补测）：用 stevia 自己的 completer 直接驱动 `cn`，
**不按任何开关，敲第一个字母就出候选**——

```
Uim completer inited with engine 'cn'      <- 用的确实是本项目的表
mode: off -> mode: on                      <- 自动打开输入模式
[输入 'n']      preedit='嗯'   候选：嗯 唔 那 拿 哪 纳 ...
[输入 'h','a','o'] preedit='好' 候选：好 蒿 嚆 号 毫 豪 ...
```

---

## 这个项目解决什么问题

把 PC Linux 发行版刷成手机系统（postmarketOS / Mobian / Droidian）后，
中文输入是一个反复踩的坑：

| 方案 | 在Phosh/Wayland 下的结果 |
|------|------------------------|
| fcitx5 + fcitx5-chinese-addons | **顶掉屏幕键盘后彻底没法输入**。fcitx5 只提供引擎、不画键盘 UI，而 phosh 的 `phosh-osk-stub` 被顶替后就没有任何键盘了（典型症状：锁屏能输、桌面不能输） |
| 传统 `GTK_IM_MODULE=fcitx` + autostart | 同上，在 Phosh 上是反模式 |
| `uim`（`uim-pinyin`） | **Debian 的 `uim-pinyin` 是空壳 metapackage**，`dpkg -L` 只有 `/usr/share/doc`，没有任何引擎文件 |
| `ibus` / `sogou` / `fcitx4` | Mobian 精简掉了；`ibus` 也没有拼音引擎 |

上游在 2026-03 给 Phosh 的新屏幕键盘 **stevia** 加了 uim 中文支持，
但是由于Mobian的Debian版本原因，不能直接套用。

本项目填上这一环：在不换内核、不换输入法框架的前提下，
用系统已有的 uim + OpenCC 生成一个真正可用的简体拼音引擎。

---

## 原理

```
/usr/share/uim/pinyin-big5.scm        (uim-data，来自 XCIN 项目)
        │
        │  ①解析候选表（音节 → 汉字）
        │  ② OpenCC t2s 批量繁 → 简
        │  ③ 过滤注音/假名占位符
        │  ④ 按词频重排候选
        ▼
/usr/share/uim/pinyin-cn-utf8.scm      (本项目生成)
        │
        ▼
   stevia 屏幕键盘 + uim 引擎 → 触屏拼音输入
```

关键点：上游 `pinyin-big5.scm` 的候选**其实已经是 UTF-8 汉字**（不是 Big5 码位），
Debian 维护者已转换过。所以我们不需要重新造词库，只需做简繁统一和排序。

---

## 快速安装

安装由 `install.sh` 全权负责，把下面这一行在设备的 SSH 终端里执行即可：

```sh
curl -fsSL https://raw.githubusercontent.com/SZYTree0312/Treenput/main/install.sh | sudo sh
```

装完**重启 phosh**（或加 `--replace-now` 立刻接管键盘），点键盘左上角切到拼音模式，
输 `ni hao` 看是否出「你好」。

取不到 raw 域名时的备用通道、选项与常见情况见 **[Install.md](Install.md)**；
手动逐步安装见 **[docs/Manual.md](docs/Manual.md)**。

---

## 适用范围

- Mobian（Debian 13 / trixie，phosh 0.46）✅ **引擎侧已真机实测通过**
- 其他 phosh 发行版（需能装 GTK3 + libhandy-1）
- 理论上适用于任何能用 uim 作为 IM 引擎的 Wayland 合成器环境

**不适用**：Waydroid / Android 容器（那是 APK 生态，不走 Wayland IM 协议）。

## 用户词典：加自己的词 + 长期校准

内置 79,228 条词条来自通用语料（jieba 词频），那是**大众的平均习惯**，不是你的
——你的名字、地名、口头禅、专业术语它一条都没有，而且你天天打的词在通用词频里
未必排得靠前。

`treenput-dict` 就是干这个的。数据全在 `~/.config/treenput/`，不动系统文件。

### 加词

```sh
treenput-dict add "ni hao" 你好     # 拼音 + 词
treenput-dict addw 你好             # 只给词，自动注音（需 pypinyin）
treenput-dict apply                 # 生效：改引擎 + 自动重启屏幕键盘
```

你加的词在候选里**排最前**，比内置那 79,228 条都靠前。

> 引擎是输入法**进程启动时**加载进内存的，光改磁盘上的文件没用 —— 所以
> `apply` 会顺手 `systemctl --user restart phosh-osk-stevia`（只重启屏幕键盘
> 这一个进程，键盘闪一下就回来，不是重启 phosh）。不想让它重启用
> `apply --no-restart`，那样新词下次启动才生效。

### 调频（长期校准）

```sh
treenput-dict freq 你好 10          # 手动提频（刚发现某个词排太后面时用）
treenput-dict learn ~/notes.txt     # 从自己的文本批量学
treenput-dict apply
```

`learn` 是长期校准的主力：把你平时写的文字喂给它，用词习惯会累积进词频。
装了 jieba + pypinyin 时还会自动把文本里的高频新词加进词典（没装也能用，
只校准已有词）。

### 管理与回档

```sh
treenput-dict list                  # 看已加的词
treenput-dict rm 你好               # 删词
treenput-dict status                # 看状态
```

每次 `apply` 前自动备份引擎到
`~/.config/treenput/backups/pinyin-cn-utf8.scm.bak-ud-<时间戳>`，改坏了随时能换回来。

（备份放用户目录而不是引擎旁边，是因为 `/usr/share/uim` 归 root，
普通用户在那里建不了新文件 —— 备份会直接失败。）

### 为什么是增量应用

加一个词**不需要**重跑整表生成。整表生成要解析上游表 + opencc 全量转换，
手机上太慢；`apply` 只改含用户词的那几行，其余 6 万多条规则原样保留，秒级完成。

> **已知限制**：「你实际选了哪个候选」**不会**自动记录。那需要 uim / stevia
> 在 C 侧给回调，而本项目是纯用户态的，拿不到选词事件。所以校准目前靠
> `freq`（手动提频）和 `learn`（批量喂文本）两个入口 —— 想更自动就得动上游 C 代码。

## 已知限制

- **屏幕键盘侧待验证**：stevia 在 phosh 0.46 上启动报
  `Failed to find all Wayland globals`，怀疑与 stevia 0.57/phosh 0.46 版本适配有关。
  本项目负责的 uim 引擎侧**已完整跑通**（输入法注册、候选排序、简繁转换全过）。
- **Firefox 等原生 Wayland 应用不弹屏幕键盘**：IM 协议代差所致，已知未解决；
  退回 XWayland 走 XIM 的尝试已实测证伪。建议改用 GTK 系浏览器。
  详见 `docs/TroubleShooting.md`。
- **词频来自通用语料**：`data/phrase.txt` 用的是 jieba 通用词频，
  不是你自己的用词习惯。个人词条与调频见「用户词典」一节。
- 本方案**不解决**「独立 IM 抢占屏幕键盘」之外的 APP 触屏问题
  （那是 XWayland 后端的事，见 `docs/TroubleShooting.md`）。

---

## 项目结构

```
Treenput/
├── install.sh                一键安装（唯一入口）
├── Install.md               安装说明：一句命令 + 选项 + 常见情况
├── engine/
│   ├── build_cn_engine.py     核心：解析上游表 → 生成简体引擎
│   ├── userdict.py            用户词典 CLI（treenput-dict）：加词 + 词频校准
│   ├── build_phrase_dict.py   词条生成：jieba 词频 + pypinyin 注音
│   └── verify_engine.py       校验器：繁体残留 + 首候选抽查
├── data/
│   ├── phrase.txt             词条表（79,228 条，音节+词+词频）
│   ├── pinyin-cn-utf8.scm     预生成引擎（3.6MB，用户侧免编译）
│   └── frequency.txt          词频表（每行一词）
├── docs/
│   ├── Manual.md              手动安装步骤（兜底，无网/非 Mobian 时用）
│   ├── TroubleShooting.md     排障（含 fcitx5 事故复盘）
│   └── Research.md            调研记录：为什么每条传统路线都走不通
└── LICENSE
```

---

## 致谢

- **uim** — 输入法引擎框架（GPL）
- **XCIN 项目** — `pinyin-big5.scm` 拼音表来源
- **OpenCC** — 简繁转换
- **stevia / phosh** — 屏幕键盘与中文支持的上游实现
- **Debian trixie 社区** — 把 XCIN 表转成 UTF-8 的维护者

## 许可

本项目代码以 MIT 许可。
生成的引擎数据继承自 uim/XCIN，遵循其原始许可。
