# 发布与在线升级

自 1.3.1 起每个版本都是一个 GitHub Release（`github.com/wz980305/AutoPlay/releases/vX.Y.Z`），盒子每天看一次有没有新版本，车主在设置页点一下就升级。本文说发布方怎么做、盒子怎么信任一个发布、第一次怎么接上这条链。盒子端的升级逻辑（备份、回退、断电续作）在 `box/scripts/onecloud/update.py` 的文件头和 `box/docs/STATUS-MODEL.md` 的 update 一节。

## 一、一个发布里有什么

| 文件 | 来自 | 盒子怎么用 |
|---|---|---|
| `autoplay-update.json` | `box/scripts/make-update-manifest.py` | 更新清单：版本、变更说明（CHANGELOG 对应小节）、能否在线升级（`online`）、下面每个文件的名字、大小、SHA-256 |
| `autoplay-update.json.sig` | 发布私钥的 Ed25519 签名 | 盒子只认用它能验证的清单；验证用的公钥随 `autoplay` 包装在 `/opt/autoplay/update-key.pem` |
| `autoplay-<版本>-r1.apk`、`luci-app-autoplay-*.apk`、`luci-i18n-autoplay-zh-cn-*.apk` | `openwrt/scripts/build-packages.sh`（OpenWrt SDK 容器） | 升级装的就是它们 |
| `autoplay-jre-<JRE 版本>_<架构>.apk` × 5 | 同上 | 只在 JRE 版本变了才下载 |
| `SHA256SUMS`、`SHA256SUMS.sig` | `sha256sum *.apk` + 签名 | 升级前先下载**当前版本**的包留作退路，用这份签过名的清单核对 |
| `autoplay-bundle-<版本>.tar`（+ `.sha256`） | `box/scripts/build-bundle.sh` | 程序本体（`/opt/autoplay` 的内容），OpenWrt 包就是从它打出来的；手动打包时用 |

地址：清单固定从 `releases/latest/download/autoplay-update.json` 取，其余从 `releases/download/v<版本>/<文件名>` 取；GitHub 连不上时按 uci `update_mirror`（默认 `https://ghfast.top/`）加前缀重试。签名让任何镜像都不需要被信任。

## 二、密钥

一对 Ed25519 密钥（`openssl genpkey -algorithm ed25519`）：

- **公钥** `box/scripts/onecloud/update-key.pem`，在仓库里，随 `autoplay` 包装到每台盒子。指纹（DER 的 SHA-256 前 16 位）`2d53ecc5bdb9c382`。
- **私钥**不在仓库里，也不应该出现在任何提交、日志或聊天里。它存在 GitHub 仓库的 Actions secret `AUTOPLAY_RELEASE_KEY`（内容是整个 PEM 文件），发布工作流只在打标签时读它；另在密码管理器里保存一份。

丢了私钥：以后的发布盒子不认，只能手动装一次带新公钥的包（见第五节的引导），再把新公钥提交进仓库。泄露了私钥：持有者可以给所有盒子推任何包——换钥的做法同上，并把 secret 换掉。换钥不需要改代码：公钥文件替换、发一个用新私钥签的版本、盒子手动装一次。

## 三、发一个版本

1. 代码、测试、文档就绪；版本号在五处一致（`receiver/build.gradle.kts`、`receiver/server/.../Main.kt` 的兜底串、`receiver/web/package.json`（和 lock）、`openwrt/autoplay/Makefile` 的 `PKG_VERSION`、`openwrt/luci-app-autoplay/Makefile` 的 `autoplay (>=…)`）；`CHANGELOG.md` 有 `## [X.Y.Z]` 小节——它就是盒子设置页上显示的"这一版改了什么"。`box/scripts/release.sh` 的第 1 步检查这些。
2. 推到 `main`。工作流 `.github/workflows/release.yml` 对每次推送跑全部测试并**完整构建**（接收端 Gradle、网页、程序包、五个架构的 JRE 包、清单），但不签名、不发布；产物作为 workflow artifact 保留 14 天，可以下载来手动装。构建失败就在这里看到。
3. 打标签 `vX.Y.Z` 并推送（GitHub Desktop：History → 右键该提交 → Create Tag… → Push origin）。同一个工作流再跑一遍，最后一步 `release.sh --publish` 用 secret 里的私钥签清单和 SHA256SUMS、用仓库里的公钥反验一次（secret 和公钥不配就失败）、`gh release create` 把所有文件挂上去。
4. 看 Actions 页面绿了，Release 页面有 14 个文件。盒子在下一次每日检查（开机 2 分钟后一次，之后每 24 小时）时显示"有新版本"，车主在设置页或 LuCI 点「立即升级」。

在自己电脑上做同样的事（需要 JDK 21、Node、Docker、`gh`）：

```sh
sh box/scripts/release.sh 1.4.1                      # 只构建到 out/release-1.4.1，不发布
AUTOPLAY_RELEASE_KEY_FILE=~/autoplay-release.key sh box/scripts/release.sh 1.4.1 --publish
```

## 四、盒子那边发生什么

每天一次 `update.py check`：取清单、验签、和 `apk info` 里装着的版本比较，结果写到 `state/update-check.json`，设置页和 LuCI 显示。点「立即升级」→ `update.py install`（独立于服务进程）：

1. 先下载**当前版本**的三个包（JRE 版本没变就不下载）并用签过名的 SHA256SUMS 核对——这是退路，没有退路不升级；
2. 下载新版本的包，逐个核对清单里的 SHA-256 和大小；
3. `apk add --simulate` 看计划，计划里出现内核、kmod 或 bluez 就停（F50 跑的是厂商 5.4 内核）；
4. 备份配对、证书、设置到 `/opt/autoplay-update-backup.tar.gz`；
5. 安装；接收程序在约 4 分钟内应答且蓝牙上电才算成功，否则装回原来的版本；
6. 全程写 `state/update-journal.json`，中途断电下次开机接着收尾或回退。

CarPlay 在用时不升级；升级约 1 分钟断开 CarPlay；升级不碰 `/opt/autoplay/{state,identity}`。

## 五、第一次接上这条链（一次性）

升级前要下载"当前已装版本"的包，而且盒子要先带着新公钥——所以**已经装着 1.3.0 或更早版本的盒子要手动装一次 1.3.1 或更新的版本**（1.3.1 是第一个带包、带新公钥的发布；直接装最新的也一样）：

```sh
# 从最新的 Release（v1.3.1 或更新）下载到电脑，再 scp 到盒子 /tmp/autoplay-upgrade/
ssh root@100.96.0.1 'cd /tmp/autoplay-upgrade && apk update && apk add --upgrade --allow-untrusted \
    autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-[0-9]*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk'
```

之后的 1.3.2、1.4.0、1.4.1……都在设置页点一下。`apk` 的包签名（`--allow-untrusted`）仍未做：安全性由清单里的哈希和清单的签名保证，这是 WP9 剩下的一项。

## 六、常见问题

- **Actions 的 build 失败在 Gradle**：1.1.0 到 1.3.0 的 Kotlin 改动在没有编译器的环境里写成（`receiver/docs/UNVERIFIED-KOTLIN.md`），第一次跑工作流最可能在这里报错；按日志修，再推。
- **发布失败在 "does not verify with update-key.pem"**：secret 里的私钥和仓库里的公钥不是一对。
- **盒子说"找不到当前版本 X 的安装包"**：X 不是正式发布过的版本（本地打的包）。按第五节手动装一次正式发布的版本。
- **盒子说"更新清单的签名不对"**：盒子上的公钥和签发布的私钥不配（换过钥、或装的是旧包），或镜像给了别的东西。
- **删 Release**：永远不要删——旧盒子升级时还要下载它的包作退路。
- **发错了**：发一个修正版本号的新发布；`update.py` 只往更高的版本走。
- **标签的运行因为工作流本身的问题失败了**（代码没问题）：在 `main` 上修好工作流，然后 Actions → release → Run workflow，`tag` 填 `vX.Y.Z`。这次运行用 `main` 上的工作流去构建并发布那个已有的标签，版本号不用变（v1.3.1 就是这样发布的：它的标签运行因工作流里一处 `umask 077` 失败）。
