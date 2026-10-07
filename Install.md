# Install

## 安装

安装由 `install.sh` 全权负责——**不需要手工执行里面的步骤，也不要改它**。
你只需要做一件事：把下面这行命令在设备的 SSH 终端里执行。

### 一条命令

```sh
curl -fsSL https://raw.githubusercontent.com/SZYTree0312/Treenput/main/install.sh | sudo sh
```

命令会打印每一步的进度，结束时打印校验结果。装完**重启 phosh**，
点键盘左上角切到拼音模式，输 `ni hao` 看是否出「你好」。

> 屏幕键盘进程由 phosh 拉起。**不重启 phosh 的话，当前会话里仍然是旧的
> `phosh-osk-stub`（无中文）**。想让安装立刻接管键盘，就在命令末尾加
> `--replace-now`，或直接重启手机。

命令幂等，中途失败**直接重跑同一条命令**即可，不需要回滚。

> **v1.0.5 起引擎是预生成的**，安装时不再需要 Python / opencc / jieba，
> 从仓库里直接装`data/pinyin-cn-utf8.scm`（含79,228 条多音节词条）。

---

## 常见情况

### 取不到 raw.githubusercontent.com

部分网络环境（含国内代理）会拦这个域名。本机实测即持续返回 502，
而 `codeload.github.com` 正常。改用打包下载，功能完全一致：

```sh
curl -fsSL https://codeload.github.com/SZYTree0312/Treenput/tar.gz/refs/heads/main \
  | sudo tar -xz -C /opt && sudo /opt/Treenput-main/install.sh
```

也可以先克隆再运行（脚本会优先使用所在目录的仓库，不重新拉取）：

```sh
git clone https://github.com/SZYTree0312/Treenput
cd Treenput && sudo ./install.sh
```

### 在 SSH 里跑，`gsettings` 那步拿不到会话总线

正常现象，不是失败。SSH 会话没有图形会话总线，脚本检测不到就会把该条命令
打印出来，你在**设备的图形界面终端**里手动跑一次即可：

```sh
gsettings set org.gnome.desktop.input-sources sources "[('xkb','us'),('ibus','uim:cn')]"
```

其余步骤（生成引擎、注册 uim、编译 stevia）都不依赖图形会话，SSH 下能完整装完。

### `--replace-now` 拉不起 stevia（→ 键盘没了怎么办）

stevia 启动失败时脚本会自动把 `phosh-osk-stub` 拉回来，所以正常不会留下
无键盘状态。万一键盘还是没了，用这条救回来（不动任何文件）：

```sh
sudo ./install.sh --restore-osk
```

或者手动：

```sh
systemd-run --user --unit=phosh-osk-stub-restore \
  /usr/bin/phosh-osk-stub --allow-replacement
```

最常见的原因是 **stevia 版本与 phosh 版本不匹配**：stevia 从 v0.56.0 起要求
合成器提供 `ext_data_control_manager_v1`，而 phosh 0.46 的 phoc 只有老的
`zwlr_data_control_manager_v1`。缺这个协议时 stevia 会等 5 秒超时退出。
本项目已把版本锁在 **v0.55.0**（兼容且带中文的最高版本）。
若你用的是更新的 phosh（≥ 0.49），可用 `TREE_STEVIA_VERSION=v0.57.0` 覆盖。

### Firefox 等应用里点输入框不弹屏幕键盘

**已知未解决，不要再去试 XIM 那条路。** 根因是 IM 协议代差：

stevia 只绑定 `zwp_input_method_manager_v2`（物理键盘路由），而 phosh 0.46 提供
`zwp_text_input_manager_v3`（OSK 的 preedit/候选 UI 靠它显形）—— 两个不同的协议。
**Firefox ESR 是原生 Wayland 应用**，直接跟 compositor 谈 v3，绕过了 stevia；
而系统应用和终端走 GTK 的 v3 或 XIM，所以它们正常。

v1.0.5 曾给 Firefox 写过 `MOZ_ENABLE_WAYLAND=0` 的用户级覆盖想让它退回
XWayland 走 XIM，**实测无效**：XWayland 下 Firefox 直接报
`Loading IM context type 'xim' failed`。该改动已撤回，`install.sh` 不再写入。

装过 v1.0.5 的机器上会留下这个文件，删掉即可：

```sh
rm ~/.local/share/applications/firefox-esr.desktop
```

要根治只能让 stevia 支持 text-input v3（上游改动，非本项目范围）。
当前的实用选择是**用 GTK 系浏览器**（Epiphany 等）——GTK 同时走 v3 和
IM module，能正常弹键盘。

### 能切到拼音模式，但一个汉字都不出

uim 的 generic 引擎**默认是 `off`（直接输入）模式**——该模式下按键原样透传、
根本不查表，preedit 和候选列表都是空的。屏幕键盘上看起来已经切到拼音了，
实际一个候选也生成不出来。

generic 引擎是靠 Ctrl-E 把自己切回 `on` 的，而手机屏幕键盘上没有能按出
Ctrl-E 的地方。本项目已让 stevia 在建好 context 后自动切换一次，
`install.sh` 装的 stevia 不需要你手动操作。

若你用的是自行编译的 stevia（没走本项目的脚本），就会卡在这一步。

### 能打出汉字，但打不出词

**这也是 v1.0.5 修的。** v1.0.0 的引擎只有单字候选：输 `nihao` 只能拿到
「你」「好」两个独立字。原因是上游表（以及 uim 自带的 `py.scm` /
`pyunihan.scm`）**全是单音节→单字，没有任何词条**。

v1.0.5 补进79,228 条多音节词条，单字候选全部保留。若你的引擎还是旧的，
重新跑一遍安装命令即可（幂等，会覆盖 `/usr/share/uim/pinyin-cn-utf8.scm`）。

### 其他

更多报错见 **[docs/TroubleShooting.md](docs/TroubleShooting.md)**。

---

## 选项

默认完整安装，且**不替换当前屏幕键盘**。需要调整时在命令末尾追加：

| 选项 | 作用 |
|------|------|
| `--replace-now` | 装完立刻停掉 `phosh-osk-stub` 并拉起 stevia。**拉不起来会自动把系统键盘恢复回来** |
| `--restore-osk` | 只把系统自带键盘（`phosh-osk-stub`）拉起来，不动任何文件。键盘没了就用这条 |
| `--skip-stevia` | 只装拼音引擎，跳过 stevia 源码编译（省几分钟，但屏幕键盘仍无中文）|
| `--status` | 只打印当前安装状态 |
| `--verify-only` | 只跑校验 |
| `--uninstall` | 卸载引擎、清配置、恢复原屏幕键盘 |
| `-h` | 帮助 |

---

## 脚本做了什么

供你确认范围，**不需要你照着做**。

| 步骤 | 内容 |
|------|------|
| 1 | `apt` 装构建依赖（uim / OpenCC / GTK3 / meson…），自动处理 Mobian 的 GTK3 版本冲突 |
| 2 | 安装简体引擎 `/usr/share/uim/pinyin-cn-utf8.scm`。**优先用仓库里的预生成产物**（含 79,228 条多音节词条，单字候选全保留）；仓库里没有才回退到现场生成（需 python3 + opencc）|
| 3 | 注册 uim 引擎：preload 加载模块 `pinyin-cn-utf8`，由引擎文件内的 `generic-register-im` 注册出输入法 `cn`（用户级 + 系统级预载）|
| 4 | 源码编译安装 **stevia** 屏幕键盘（首个带中文的 Phosh OSK）：放宽 dconf 版本断言、把中文引擎指向本项目的 `cn`、建好 context 后自动打开中文输入模式、设置随图形会话自启 |
| 5 | 把 GNOME 输入源设为 `[us, uim:cn]` |
| 6 | 装用户词典工具 `treenput-dict` → `/usr/local/bin`，建好 `~/.config/treenput/` |
| 7 | 校验：繁体残留、单字抽查（输 `ni` 含「你」）、词条抽查（`nihao` 含「你好」）|

全程**不升级内核、不替换发行版、不动系统输入法框架**，不装独立 IM 客户端。
唯一写入系统目录的是 `/usr/share/uim/pinyin-cn-utf8.scm`（本项目自己的引擎文件）。

## 加自己的词 / 调词频

内置 79,228 条词条来自通用语料，不是你的用词习惯。装完可以加自己的：

```sh
treenput-dict add "ni hao" 你好     # 加词
treenput-dict freq 你好 10          # 提频
treenput-dict learn ~/notes.txt     # 从自己的文本学词频
treenput-dict apply                 # 生效：改引擎 + 自动重启屏幕键盘
treenput-dict list                  # 看已加的
```

你加的词在候选里**排最前**，比内置那 79,228 条都靠前。
数据全在 `~/.config/treenput/`，`apply` 前会自动备份引擎。

> `apply` 会重启屏幕键盘进程（`phosh-osk-stevia`）——引擎是进程启动时加载的，
> 不重启就读不到新词。键盘会闪一下，属正常。不想重启加 `--no-restart`。

完整说明见 [README](README.md)。

## 手动安装

需要逐步确认、或无网时，照 **[docs/Manual.md](docs/Manual.md)** 走。