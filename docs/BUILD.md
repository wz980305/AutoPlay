# 构建

三个可构建的部分：接收端（JVM）、投屏页（web）、OpenWrt 包（apk）。盒子上的 Python（`box/`）不需要构建，但要打进程序包。

> **重要：** 本里程碑的 Kotlin 改动没有编译过（编写环境没有 Gradle 和网络）。`receiver/docs/UNVERIFIED-KOTLIN.md` 逐文件列出改了什么、编译风险在哪、先看什么；第一次 `./gradlew build` 之前先读它，编译错误优先按那份清单排查。网页端已验证：`tsc` 无错、esbuild 能构建、四个 `check*.mjs` 通过。

## 1. 接收端（`receiver/`）

需要 JDK 21 和网络（Gradle wrapper 会下载 Gradle 和 Maven 依赖；`settings.gradle.kts` 只允许 Maven Central）。

```sh
cd receiver
./gradlew build                        # 先编译两个模块并跑测试（UNVERIFIED-KOTLIN.md 要求的第一步）
./gradlew :server:installDist          # 产物：server/build/install/playport/{bin,lib}
```

`:server:installDist` 生成的 `lib/` 就是盒子上 `/opt/autoplay/playport/lib/` 的内容；启动类 `com.playport.server.MainKt`，盒子上由 `run-receiver.py` 以 `-Xms64m -Xmx384m`、`-XX:+ExitOnOutOfMemoryError`、`-XX:ErrorFile=<state>`、AppCDS 启动。kxml2 依赖随有线代码一起去掉了；`protocol/build.gradle.kts` 是改过的文件之一。

离线环境：Gradle 需要一次在线的依赖缓存（`~/.gradle/caches`），之后 `--offline` 可用。

## 2. 投屏页（`receiver/web/`）

详细说明在 `receiver/web/README-build.md`。两条路产出同一种 `dist/` 布局（`dist/index.html`、`dist/assets/boot.js` + 分块、`dist/assets/style.css`、`dist/browser-check.js`）：

**在线（Vite，上游的方式）**

```sh
cd receiver/web
npm install                             # typescript + vite
npm run build                           # tsc && vite build → dist/（压缩、带哈希文件名）
```

**离线（esbuild，本仓库新增）**

```sh
cd receiver/web
node scripts/build-esbuild.mjs          # → dist/；esbuild 从 $ESBUILD、./node_modules/esbuild 或 /opt/npm-tools/node_modules/esbuild 找
# 或从仓库根：node receiver/web/scripts/build-esbuild.mjs receiver/web
```

esbuild 的产物不压缩、入口固定为 `assets/boot.js`；标记和 CSS 与源码一致，所以离线构建可以直接拿去车上测。

**类型检查和自检**

```sh
cd receiver/web
tsc --noEmit -p tsconfig.offline.json   # 只查 src/（tsconfig.json 还覆盖 vite.config.ts，需要 node_modules/vite）
node check.mjs && node check-audio.mjs && node check-car.mjs && node check-browser.mjs
```

`check*.mjs` 以裸模块名导入 `typescript`。没有 `npm install` 时，把预装的拷贝软链进来（`node_modules/` 在 `.gitignore` 里）：

```sh
mkdir -p node_modules && ln -sfn /opt/npm-tools/node_modules/typescript node_modules/typescript
```

页面的常量在 `src/flags.ts`（`CAR_MUSIC`、`TESLA`、`MUSIC_ELEMENT`、`PROMPT_BOOST`），改默认值不需要改盒子。`tools/probe/index.html` 不需要构建，是单文件。

## 3. 程序包（`box/`）

OpenWrt 包解开到 `/opt/autoplay` 的内容是 `autoplay-bundle-<版本>.tar`，由 `box/scripts/build-bundle.sh` 从本仓库打出（先完成第 1、2 节）：

```sh
sh box/scripts/build-bundle.sh autoplay-bundle.tar      # RECEIVER=<路径> 指定接收端构建目录，默认 ../receiver
```

需要主机上有：接收端的 `installDist` 产物和 `web/dist/`、`javac` 21、pip、curl、unzip。它只打包 git 已提交的文件，另下载两份固定哈希的依赖：dbus-next 0.2.3（蓝牙桥）和 acme.sh 3.1.6（DuckDNS 证书）；`scan-sensitive.py` 的检查会拒绝打进个人文件。

## 4. OpenWrt 包（`openwrt/`）

三个包：`autoplay`（程序 + `/etc/init.d/autoplay` + `/etc/config/autoplay` + uci-defaults `90-autoplay-tesla` + `hotplug-iface`/`hotplug-ntp`，各架构通用；`CONFLICTS:=dashplay`，postinst 从 `/opt/dashplay/{state,identity}` 和私有 BlueZ 根迁移并复制旧 uci 选项）、`autoplay-jre`（jlink 裁剪的 Temurin 21 musl JRE，aarch64 的各个包架构各一个）、`luci-app-autoplay`（含 zh-cn）。用官方 SDK 容器构建，需要 Docker：

```sh
sh openwrt/scripts/build-packages.sh out/                       # SDK 从 autoplay/Makefile 指定的发布页下载程序包并校验
sh openwrt/scripts/build-packages.sh out/ autoplay-bundle.tar   # 用第 3 节打出的程序包（现在只能走这条）
sh openwrt/scripts/bump-autoplay.sh <版本> autoplay-bundle-<版本>.tar   # 发布后更新 Makefile 的版本与校验值
```

**现状：** `openwrt/autoplay/Makefile` 的 `PKG_SOURCE_URL` 指向尚未存在的发布页，`PKG_HASH:=skip`；`update.py` 的更新源和清单 URL 是 `openwrt-autoplay` 占位符（`AUTOPLAY_UPDATE_OWNER/REPO/FEED_REPO`、`AUTOPLAY_FEED`）。发布第一个版本前要填上。镜像默认 `openwrt/sdk:x86-64-25.12.5`（`OPENWRT_SDK` 可改）。

装到盒子上：

```sh
scp out/*.apk root@100.96.0.1:/tmp/
ssh root@100.96.0.1 'cd /tmp && apk add --allow-untrusted autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-2*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk'
```

包没有签名（WP9 的待办），所以要 `--allow-untrusted`。F50 的蓝牙用的是装机脚本 `box/scripts/f50-install.py` 的 `autoplay` 阶段装进 `/opt/autoplay-bluez` 的私有 BlueZ，不是 `apk add bluez-daemon`（系统包会带入不匹配的 6.12 内核模块）。装机脚本的 `check`/`flash` 阶段需要 `box/tools/` 里固定版本的 `spd_dump`/`lz4`，这些二进制没有导入本仓库，要从 DashPlay 的检出里拿；`box/skills/autoplay-install/SKILL.md` 也还没按本仓库重写。

## 5. 工具（`tools/`）

不需要构建。验证方式见 `docs/TEST.md`。

## 6. 版本钉住

每个 AutoPlay 版本固定一组：mu300-linux 版本和内核（当前装机脚本固定 v2026.10.15，平台审计 PA#3 建议在自己浸泡测试后升到 ≥ v2026.10.19.3）、OpenWrt 25.12.x、Temurin 21 构建号、PlayPort 基线提交。记录在 `CHANGELOG.md` 的对应版本里。
