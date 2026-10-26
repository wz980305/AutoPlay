# 构建

三个可构建的部分：接收端（JVM）、投屏页（web）、OpenWrt 包（apk）。盒子上的 Python（`box/`）不需要构建。

> **重要：** 本里程碑的 Kotlin 改动没有在编写环境里编译过（没有 JDK/Gradle 和网络）。`receiver/docs/UNVERIFIED-KOTLIN.md` 列出了哪些文件改过、改了什么、预期怎么验证。第一次 `./gradlew` 之前先读它，编译错误优先按那份清单排查。

## 1. 接收端（`receiver/`）

需要 JDK 21 和网络（Gradle wrapper 会下载 Gradle 和 Maven 依赖；`settings.gradle.kts` 只允许 Maven Central）。

```sh
cd receiver
./gradlew :server:installDist          # 产物：server/build/install/playport/{bin,lib}
./gradlew test                         # protocol + server 的单元测试（PlayPort 原有 96 个，DashPlay 补丁又加了一些）
```

`:server:installDist` 生成的 `lib/` 就是盒子上 `/opt/autoplay/playport/lib/` 的内容；启动类 `com.playport.server.MainKt`，盒子上由 `run-receiver.py` 以 `-Xms64m -Xmx384m` 加 AppCDS 启动（见 `box/scripts/onecloud/run-receiver.py`）。上游 10.23 起的 `playport-slim-runtime` 已去掉 HTTP/3、protobuf、JBoss 编解码器，jar 约 27MB。

离线环境：Gradle 需要一次在线的依赖缓存（`~/.gradle/caches`），之后 `--offline` 可用。编写环境里没有做到这一点，所以 Kotlin 侧只做了读代码级别的核对。

## 2. 投屏页（`receiver/web/`）

两条路：

**在线（上游的正式构建）**

```sh
cd receiver/web
npm ci                                  # typescript、vite
npm run build                           # tsc && vite build → dist/
```

**离线（本仓库的替代）**：`node receiver/web/scripts/build-esbuild.mjs receiver/web`，用 `/opt/npm-tools` 或任何本地 esbuild 把 `src/` 打成 `dist/`。它和 Vite 在标记和 CSS 上同源，但压缩器不同；界面审查的 308 张截图就是用这条路构建后渲染的（`viewer_ui_audit.md` §14 注明了这一差异）。没有 esbuild 时这条路不可用。

产物 `dist/` 要和 `lib/` 一起进程序包；盒子上 JVM 从 `playport/web/dist/` 提供静态文件，`receiver-access.json` 在运行时写到同一目录（硬件审查 H7 建议挪到 tmpfs）。

页面的检查脚本（不需要浏览器）：`npm test`，等于依次 `node check.mjs check-audio.mjs check-car.mjs check-browser.mjs check-flac.mjs`，需要 `node_modules/typescript`（它们用 `ts.transpileModule` 即时编译被测模块）。

`tools/probe/index.html` 不需要构建，是单文件。

## 3. OpenWrt 包（`openwrt/`）

三个包：`dashplay`（程序 + procd 服务 + `/etc/config/dashplay`，各架构通用）、`dashplay-jre`（jlink 裁剪的 Temurin 21 musl JRE，按 aarch64 的各个包架构各一个）、`luci-app-dashplay`（含 zh-cn 翻译）。用官方 SDK 容器构建，需要 Docker：

```sh
sh openwrt/scripts/build-packages.sh out/                       # 从 Makefile 指定的发布页下载程序包并校验哈希
sh openwrt/scripts/build-packages.sh out/ dashplay-bundle.tar   # 或者用自己构建的程序包（未发布的版本）
```

程序包 `dashplay-bundle-<版本>.tar` 由 `box/scripts/onecloud/firmware/build-bundle.sh` 打：`scripts/onecloud` 的 Python、第 1 节的 `lib/`、第 2 节的 `dist/`、dbus-next、acme.sh。`openwrt/dashplay/Makefile` 的 `PKG_SOURCE_URL`/`PKG_HASH` 指向这个 tar。镜像默认是 `openwrt/sdk:x86-64-25.12.5`（`OPENWRT_SDK` 可改）。

F50 是 aarch64_cortex-a76 还是 aarch64_generic，以盒子上 `cat /etc/apk/arch` 为准；`dashplay-jre` 对每个 aarch64 包架构都产出一个包，内容相同。

装到盒子上：

```sh
scp out/*.apk root@100.96.0.1:/tmp/
ssh root@100.96.0.1 'cd /tmp && apk add --allow-untrusted dashplay-jre-*_$(cat /etc/apk/arch).apk dashplay-2*.apk luci-app-dashplay-*.apk luci-i18n-dashplay-zh-cn-*.apk'
```

包没有签名（WP9 的待办），所以要 `--allow-untrusted`。F50 的蓝牙用的是 DashPlay 安装脚本装进 `/opt/dashplay-bluez` 的私有 BlueZ，不是 `apk add bluez-daemon`（系统包会带入不匹配的 6.12 内核模块）；这一步仍由 `box/scripts/f50-install.py` 完成。

## 4. 工具（`tools/`）

不需要构建。验证方式见 `docs/TEST.md`。

## 5. 版本钉住

每个 AutoPlay 版本固定一组：mu300-linux 版本和内核（当前 DashPlay 的安装器固定 v2026.10.15，平台审计 PA#3 建议在自己浸泡测试后升到 ≥ v2026.10.19.3）、OpenWrt 25.12.x、Temurin 21 构建号、PlayPort 基线提交。记录在 `CHANGELOG.md` 的对应版本里。
