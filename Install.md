# Install

## 一句命令

把下面这行丢给 Agent（SSH 已连上设备），或在设备终端里执行：

```sh
curl -fsSL https://raw.githubusercontent.com/SZYTree0312/Treenput/main/install.sh | sudo sh
```

装完**重启 phosh**（或手动 `phosh-osk-stevia --replace`），点键盘左上角切到拼音模式，
输 `ni hao` 看是否出「你好」。

> 屏幕键盘进程是被 phosh 拉起的，**装完不重启 phosh 的话当前会话里还是旧的
> `phosh-osk-stub`（无中文）**。想立刻生效就用 `--replace-now`，或直接重启手机。

### 取不到 raw.githubusercontent.com？

部分网络环境（含国内代理）会拦这个域名。改用打包下载，功能完全一样：

```sh
curl -fsSL https://codeload.github.com/SZYTree0312/Treenput/tar.gz/refs/heads/main \
  | sudo tar -xz -C /opt && sudo /opt/Treenput-main/install.sh
```

或者直接 `git clone`：

```sh
git clone https://github.com/SZYTree0312/Treenput && cd Treenput && sudo ./install.sh
```

---

## 脚本会做什么

| 步骤 | 内容 |
|------|------|
| 1 | `apt` 装构建依赖（uim / OpenCC / GTK3 / meson…），自动处理 Mobian 的 GTK3 版本冲突 |
| 2 | 从 `uim-data` 的 `pinyin-big5.scm` 生成简体引擎 `/usr/share/uim/pinyin-cn-utf8.scm`，按 `data/frequency.txt` 排序 |
| 3 | 注册 uim 引擎（系统预载 + `named-input-method cn`，以及桌面用户的 `~/.uim-preload`） |
| 4 | 从源码编译安装 **stevia** 屏幕键盘（首个带中文的 Phosh OSK），自动放宽 dconf 版本断言 |
| 5 | 把 GNOME 输入源设为 `[us, uim:cn]` |
| 6 | 校验：繁体残留、首候选抽查（输 `ni` 出「你」）|

全程**不升级内核、不替换发行版、不动系统输入法框架**。幂等，中途失败可直接重跑。

## 选项

| 选项 | 作用 |
|------|------|
| （无）| 完整安装，默认不替换当前屏幕键盘 |
| `--replace-now` | 装完立刻停掉 `phosh-osk-stub` 并拉起 stevia |
| `--skip-stevia` | 只装拼音引擎，跳过 stevia 源码编译（省几分钟，但屏幕键盘仍无中文）|
| `--status` | 只打印当前安装状态 |
| `--verify-only` | 只跑校验 |
| `--uninstall` | 卸载引擎、清配置、恢复原屏幕键盘 |
| `-h` | 帮助 |

先克隆再跑也行（脚本会优先用本地仓库）：

```sh
git clone https://github.com/SZYTree0312/Treenput
cd Treenput && sudo ./install.sh
```

## 常见情况

**SSH 里跑，`gsettings` 那步拿不到会话总线。** 这是正常现象，不是失败 ——
脚本会打印出让你在设备上手动执行的那条命令，在手机终端里跑一次即可。
其余部分（引擎、uim 注册、stevia 编译）都不依赖图形会话，SSH 下能完整装完。

**`--replace-now` 失败。** stevia 需要 Wayland input-method slot，
极少数情况下 SSH 环境下拉不起来。重启 phosh 后在设备终端跑：

```sh
phosh-osk-stevia --replace
```

**其他报错**看 **[docs/TroubleShooting.md](docs/TroubleShooting.md)**。