# Treenput

**树入法** — 面向 Mobian / Phosh 等移动 Linux 的简体拼音输入方案。

纯用户态实现，不修改内核、不替换系统输入法框架、不升级发行版。
针对「Debian 13 + Mobian + phosh 0.46 这类版本组合下没有可用中文拼音」的问题，
在现有系统内部做精准适配。

> 命名说明：起名不蹭任何第三方产品名（不叫 fcitx-pinyin、sogou、mozc 等），
> 「树入」= 树的输入法，同时是「输入」的谐音双关。

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

**屏幕键盘侧尚未打通**：stevia 0.57.0 在这台机器上启动报
`Failed to find all Wayland globals, giving up`。已排查：phoc 确实提供了
`zwp_input_method_manager_v2`、`zwlr_layer_shell_v1`、`phosh_private` 等协议，
缺的不是协议 global —— 怀疑是 stevia 0.57 与 phosh 0.46 的版本兼容性，
属于屏幕键盘自身问题，与本项目生成的 uim 引擎无关。见「已知限制」。

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

## 已知限制

- **屏幕键盘侧待验证**：stevia 在 phosh 0.46 上启动报
  `Failed to find all Wayland globals`，怀疑与 stevia 0.57/phosh 0.46 版本适配有关。
  本项目负责的 uim 引擎侧**已完整跑通**（输入法注册、候选排序、简繁转换全过）。
- **引擎是单字的**：目前不含词组级输入，`uim` 的 dict 机制可以做，未实现。
- **词频表是种子集**：`data/frequency.txt` 覆盖高频字，够用但不如真实语料。
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
│   └── verify_engine.py       校验器：繁体残留 + 首候选抽查
├── data/
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
