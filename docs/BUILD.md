# 构建

三个可构建的部分：接收端（JVM）、投屏页（web）、OpenWrt 包（apk）。盒子上的 Python（`box/`）不需要构建，但要打进程序包。

> **构建状态：** 0.1.1 用 Temurin 21.0.13 与 Gradle 9.5.0 完成过构建和测试，1.0.0 在车上跑通；1.1.0 到 1.3.0 对接收端 Kotlin 的改动在没有 Gradle 网络的环境里写成，还没有编译——`receiver/docs/UNVERIFIED-KOTLIN.md` 是现行清单，`./gradlew build` 是第一步。

## 1. 接收端（`receiver/`）

需要 JDK 21 和网络（Gradle wrapper 会下载 Gradle 和 Maven 依赖；`settings.gradle.kts` 只允许 Maven Central）。

```sh
cd receiver
./gradlew build                        # 先编译两个模块并跑测试（UNVERIFIED-KOTLIN.md 要求的第一步）
./gradlew :server:installDist          # 产物：server/build/install/server/{bin,lib}
```

`:server:installDist` 生成的 `lib/` 就是盒子上 `/opt/autoplay/playport/lib/` 的内容；启动类 `com.playport.server.MainKt`，盒子上由 `run-receiver.py` 以 `-Xms64m -Xmx384m`、`-XX:+ExitOnOutOfMemoryError`、`-XX:ErrorFile=<state>`、AppCDS 启动。kxml2 依赖随有线代码一起去掉了；`protocol/build.gradle.kts` 是改过的文件之一。

离线环境：Gradle 需要一次在线的依赖缓存（`~/.gradle/caches`），之后 `--offline` 可用。

## 2. 投屏页（`receiver/web/`）

详细说明在 `receiver/web/README-build.md`。两条路产出同一种 `dist/` 布局（`dist/index.html`、`dist/assets/boot.js` + 分块、`dist/assets/style.css`、`dist/browser-check.js`）：

**在线（Vite，上游的方式）**

```sh
cd receiver/web
npm ci                                  # 使用提交的锁文件
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
node check.mjs && node check-car.mjs && node check-browser.mjs && node check-runtime.mjs   # 或 npm test
```

`check*.mjs` 以裸模块名导入 `typescript`。没有 `npm install` 时，把预装的拷贝软链进来（`node_modules/` 在 `.gitignore` 里）：

```sh
mkdir -p node_modules && ln -sfn /opt/npm-tools/node_modules/typescript node_modules/typescript
```

页面的常量在 `src/flags.ts`（1.3.0 起只剩 `TESLA`；声音的常量随页面音频一起删除，`docs/AUDIO.md`），改默认值不需要改盒子。`tools/probe/index.html` 不需要构建，是单文件。

## 3. 程序包（`box/`）

OpenWrt 包解开到 `/opt/autoplay` 的内容是 `autoplay-bundle-<版本>.tar`，由 `box/scripts/build-bundle.sh` 从本仓库打出（先完成第 1、2 节）：

```sh
AUTOPLAY_VERSION=1.6.4 sh box/scripts/build-bundle.sh autoplay-bundle.tar      # RECEIVER=<路径> 指定接收端构建目录，默认 ../receiver
```

需要主机上有：接收端的 `installDist` 产物和 `web/dist/`、`javac` 21、pip、curl、unzip。它从经过审核的源码目录枚举顶层 Python 模块（不再依赖 `.git`，新增模块不会遗漏），另下载两份固定哈希的依赖：dbus-next 0.2.3（蓝牙桥）和 acme.sh 3.1.6 连同 DuckDNS、DNSPod 两个 DNS 钩子（证书）；`scan-sensitive.py` 的检查会拒绝打进个人文件。

## 4. OpenWrt 包（`openwrt/`）

三个包：`autoplay`（程序 + `/etc/init.d/autoplay` + `/etc/config/autoplay` + uci-defaults `90-autoplay-tesla` + `hotplug-iface`/`hotplug-ntp`，各架构通用；`CONFLICTS:=dashplay`，postinst 从 `/opt/dashplay/{state,identity}` 和私有 BlueZ 根迁移并复制旧 uci 选项）、`autoplay-jre`（jlink 裁剪的 Temurin 21 musl JRE，aarch64 的各个包架构各一个）、`luci-app-autoplay`（含 zh-cn）。用官方 SDK 容器构建，需要 Docker：

```sh
sh openwrt/scripts/build-packages.sh out/                       # SDK 从 autoplay/Makefile 指定的发布页下载程序包并校验
sh openwrt/scripts/build-packages.sh out/ autoplay-bundle.tar   # 用第 3 节打出的程序包（现在只能走这条）
sh openwrt/scripts/bump-autoplay.sh <版本> autoplay-bundle-<版本>.tar   # 发布后更新 Makefile 的版本与校验值
```

**发布：** 1.3.1 起整条链（接收端、网页、程序包、OpenWrt 包、更新清单、签名、GitHub Release）由 `box/scripts/release.sh` 完成，推送 `v*` 标签时 `.github/workflows/release.yml` 在 GitHub Actions 上跑它（`docs/RELEASE.md`）。`openwrt/autoplay/Makefile` 的 `PKG_SOURCE_URL` 指向 `wz980305/AutoPlay` 的 Release，`PKG_HASH:=skip`（打包时总是用刚构建的本地程序包，`build-packages.sh` 第二个参数）；`update.py` 的更新源是同一个仓库（`AUTOPLAY_UPDATE_OWNER/REPO/FEED_REPO`、`AUTOPLAY_UPDATE_FEED` 可改）。SDK 镜像默认 `openwrt/sdk:x86-64-25.12.5`（`OPENWRT_SDK` 可改）。

装到盒子上：

```sh
scp out/*.apk root@100.96.0.1:/tmp/
ssh root@100.96.0.1 'cd /tmp && apk add --allow-untrusted autoplay-jre-*_$(cat /etc/apk/arch).apk autoplay-[0-9]*.apk luci-app-autoplay-*.apk luci-i18n-autoplay-zh-cn-*.apk'
```

包没有签名（WP9 的待办），所以要 `--allow-untrusted`。F50 的蓝牙用的是 `python3 /opt/autoplay/board_zte_f50.py --setup` 装进 `/opt/autoplay-bluez` 的私有 BlueZ，不是 `apk add bluez-daemon`（系统包会带入不匹配的 6.12 内核模块）。刷机、root 只看 mu300-linux 的文档（ADR-11）；上游 DashPlay 的 B16 装机脚本已于 2026-11-03 从仓库删除。随包的 `update-key.pem` 是项目自己的发布公钥（1.3.1 起；指纹 `2d53ecc5bdb9c382`），之后的版本可以在线升级（`docs/RELEASE.md`）。

## 5. 工具（`tools/`）

不需要构建。验证方式见 `docs/TEST.md`。

## 6. 版本钉住

每个 AutoPlay 版本固定一组：mu300-linux 版本和内核（实车那台是 OpenWrt 25.12 / 5.4 内核的 mu300-linux 镜像；本仓库不固定它的版本，车主按 mu300-linux 的说明升级）、OpenWrt 25.12.x、Temurin 21 构建号、PlayPort 基线提交。记录在 `CHANGELOG.md` 的对应版本里。
