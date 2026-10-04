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

### 能切到拼音模式，但一个汉字都不出

uim 的 generic 引擎**默认是 `off`（直接输入）模式**——该模式下按键原样透传、
根本不查表，preedit 和候选列表都是空的。屏幕键盘上看起来已经切到拼音了，
实际一个候选也生成不出来。

generic 引擎是靠 Ctrl-E 把自己切回 `on` 的，而手机屏幕键盘上没有能按出
Ctrl-E 的地方。本项目已让 stevia 在建好 context 后自动切换一次，
`install.sh` 装的 stevia 不需要你手动操作。

若你用的是自行编译的 stevia（没走本项目的脚本），就会卡在这一步。

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
| 2 | 从 `uim-data` 的 `pinyin-big5.scm` 生成简体引擎 `/usr/share/uim/pinyin-cn-utf8.scm`，按 `data/frequency.txt` 排序 |
| 3 | 注册 uim 引擎：preload 加载模块 `pinyin-cn-utf8`，由引擎文件内的 `generic-register-im` 注册出输入法 `cn`（用户级 + 系统级预载）|
| 4 | 源码编译安装 **stevia** 屏幕键盘（首个带中文的 Phosh OSK）：放宽 dconf 版本断言、把中文引擎指向本项目的 `cn`、建好 context 后自动打开中文输入模式、设置随图形会话自启 |
| 5 | 把 GNOME 输入源设为 `[us, uim:cn]` |
| 6 | 校验：繁体残留、首候选抽查（输 `ni` 出「你」）|

全程**不升级内核、不替换发行版、不动系统输入法框架**，不装独立 IM 客户端。

## 手动安装

需要逐步确认、或无网时，照 **[docs/Manual.md](docs/Manual.md)** 走。