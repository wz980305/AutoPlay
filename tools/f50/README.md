# tools/f50：F50（OpenWrt / mu300-linux）上的加固与测量脚本

三件东西，都是 POSIX sh（盒子上的 busybox ash）或纯标准库 Python：

| 文件 | 作用 | 验证方式 |
|---|---|---|
| `harden.sh` | 第 1 周的配置类加固，一次性执行、可重复执行、可回退 | `sh -n`；在假根目录里跑过 apply / 重复 apply / revert |
| `measure.sh` + `measure.init` + `test_measure_shell.py` | procd 服务：每 10 秒记一行 CSV 到 tmpfs，每 60 秒追加到 SD 卡 | `sh -n`；本机 `--once` 和守护模式各跑过，列数对齐、重启不重复；`python3 -m unittest tools/f50/test_measure_shell.py` |
| `measure-report.py` + `test_measure_report.py` | 把 CSV 变成文字摘要（最高温、降频分钟、CPU0 忙碌分位数……） | `python3 -m unittest tools/f50/test_measure_report.py` |

编号来源：**H1–H11** = 《AutoPlay 硬件视角审查与精简方案》第三节；**PA#n** = 平台审计 `platform_audit.md` 的第 n 条发现；**WPn** = 《AutoPlay 日常使用加固路线图》的工作包。所有数值都是那几份文档里的推算值，没有在 F50 上实测过——这正是 `measure.sh` 存在的理由。

## harden.sh

```sh
# 先看会做什么
sh tools/f50/harden.sh --dry-run
# 应用（国内默认 CN；在车里别带 wifi reload，等下次重启）
sh tools/f50/harden.sh --country CN --no-wifi-reload
# 验收通过、不想再退回安卓之后
sh tools/f50/harden.sh --lock-linux
# 文件系统那一项要显式同意
sh tools/f50/harden.sh --fs
# 看现状 / 回退
sh tools/f50/harden.sh --status
sh tools/f50/harden.sh --revert
```

参数：`--country CC`（默认 CN）、`--lock-linux`、`--fs`、`--no-wifi-reload`、`--rps MASK`（默认 `f0`）、`--a76-max KHZ`（默认 1500000）、`--cpu0-idle boot|session|off`（默认 boot）、`--dry-run`、`--revert`、`--status`。改动前的值记在 `/etc/autoplay/harden.prev`，`--revert` 据此恢复；一次性动作的戳记在 `/etc/autoplay/stamps/`。

脚本不碰接收端、身份目录、内核、BlueZ 和引导程序；刷机、root、回安卓的操作只看 mu300-linux 自己的文档（wiki：Installation、Going-Back-to-Android）。

### 各杠杆

| # | 改什么 | 来源 | 为什么 | 风险 | 重启？ |
|---|---|---|---|---|---|
| 1 | `uci set network.wan.dl_reboot=0` | PA#5 / WP1 | mu300 的移动数据看门狗在下行断流时会**重启整机**（默认开，最多连续 3 次）。CarPlay 走本地，不依赖外网，一次调制解调器故障不该结束整趟会话、还消耗一次启动尝试 | 下行真的卡死时不再自动重启，只剩 `mobile-data` 的重拨；车机上网可能要等下一次点火 | 否，看门狗下一次决策时生效 |
| 2 | `wireless.radio0.country=<CC>`、`channel=149`、`htmode=VHT80` | PA#9 / H6 / WP1 | mu300 安装脚本写死 `COUNTRY=TR`，TR 下 149 信道不合法，AP 会退到 36 或 AP-DISABLED；Tesla 在国内能看到 149、看不到 36。H6：5G n41 上行的二次谐波压在 36–48 信道上，149 干净；车里用蓝牙音频时绝不能退到 2.4 GHz | `wifi reload` 等于整颗 Wi-Fi/BT 芯片断电重来（H8）：3–6 秒没 Wi-Fi，蓝牙重新初始化，**会掐断正在进行的 CarPlay**。车上用 `--no-wifi-reload`。TR/IL 国家码下脚本会警告 149 不可用 | 不带 `--no-wifi-reload` 时立即 reload；否则下次重启 |
| 3 | `mu300-next-boot`：打印 `status`；默认 `attempts 6`；`--lock-linux` 时 `lock` | PA#1 / WP1 | 连续 N 次（默认 5）启动没在开机约 1 分钟内被确认成功，F50 就退回原厂安卓；打火压降、短途熄火都算失败。先把尝试次数提到上限 6，验收通过后再锁定 | 锁定后 Linux 坏了也不会自动回安卓，只能走 USB 救援（mu300 wiki）；"锁定槽位在看门狗复位后的行为"上游没写 | 否 |
| 4 | `rm /etc/uhttpd.key /etc/uhttpd.crt; /etc/init.d/uhttpd restart`（只做一次，戳记 `uhttpd-key`） | PA#3 / WP7 | DashPlay 固定安装的 mu300 v2026.10.15 镜像里，LuCI 的 HTTPS 私钥所有设备共用一把 | 曾经信任旧证书的浏览器会再警告一次；旧密钥无法恢复（这正是目的） | 否 |
| 5 | `mu300-usb adb off` | PA#15 / WP7 | 较新的 mu300 镜像默认在 USB 上开放 root 权限的 adb，任何插上数据线的主机都能拿到 root shell；接在车机数据口上供电时尤其危险 | 失去 adb 这条维护通道，改用 SSH；mu300 会把设置持久化到 `/etc/mu300/adb` | 否 |
| 6 | 从 `/opt/mu300/bin/extra-modules` 的 modprobe 循环里删掉 `mali_kbase`、`sprd_gpu_cooling`、`sc27xx-vibra`（备份为 `extra-modules.autoplay-orig`；已加载的尝试 `rmmod`） | H5 | 无头盒子加载 GPU 驱动毫无用处，却占约 45 MiB 内存、拖慢启动；GPU 冷却设备和振动马达同理 | 这是对 mu300 自己脚本的文本修改：`mu300-update` 会把文件还原，升级后要重跑本脚本。脚本只在认出 `for m in … mali_kbase; do` 这一行时才动手，否则打印手工指引 | **是**（本次启动已加载的模块要等重启才释放） |
| 7 | 安装 `/etc/init.d/autoplay-tune`（START=98）、`/etc/hotplug.d/net/50-autoplay-rps`、`/etc/sysctl.d/60-autoplay.conf`、`/etc/autoplay/tune.conf` | H1 / H3 / H9 / WP5 / WP6 | 见下表 | 见下表 | 否（`enable` + `restart` 立即生效） |
| 8 | `tune2fs -e remount-ro <根设备>`（只在 `--fs` 时执行；同时让第 7 项在开机时 `mount -o remount,commit=30 /`） | H7 | 根文件系统在消费级 microSD 上，挂载时没指定 `errors=`，默认 `continue`：卡返回 I/O 错误时系统继续在损坏的文件系统上跑。`remount-ro` 把静默损坏变成可见的只读状态；`commit=30` 让断电时在飞行中的日志提交更少 | 卡出错时盒子会变成只读、CarPlay 配对等写入失败——这是想要的行为，但要有状态提示（WP8）。脚本先打印设备名和当前值，`--fs` 才执行 | 否（`tune2fs -e` 在挂载状态下即可改超级块） |
| 9 | `uci commit network`、`uci commit wireless`、`wifi reload` | — | 把第 1、2 项落盘 | 见第 2 项 | — |

### autoplay-tune 做的事（第 7 项展开）

配置文件 `/etc/autoplay/tune.conf`，`KEY=VALUE`：

| 键 | 默认 | 做什么 | 来源 | 风险 |
|---|---|---|---|---|
| `CPU0_IDLE` | `boot`（存在会话钩子时自动改成 `session`） | `echo 1 > /sys/devices/system/cpu/cpu0/cpuidle/state[1-9]*/disable`，关掉 CPU0 的深度睡眠（保留 state0/WFI）。`session` 模式只在 `/var/run/autoplay/session` 存在时关闭，由 `/etc/init.d/autoplay-tune session on|off` 切换，留给以后的守护进程钩子 | WP5 / H3 / mu300 FINDINGS §200：同一块主板上实测 Wi-Fi 收包等待从平均 34ms 降到 0.6ms | 空闲时多耗 50–150mW（H3 的估算），停在太阳下的车里相当于再高 1–3K。所以 H3 建议只在会话期间开；现在没有钩子，先按 `boot` 做 A/B 对比 |
| `RPS_CPUS` | `f0` | `echo f0 > /sys/class/net/wlan0/queues/rx-0/rps_cpus`，再加 `rps_flow_cnt=4096`、`net.core.rps_sock_flow_entries=4096`；hotplug 脚本在 wlan0 重建时重新写入 | H3：Wi-Fi/BT/调制解调器/USB 的中断全压在 CPU0（A55），没有 RPS/XPS、没有 GRO | 每包 2–5µs 的 IPI 和大核唤醒（耗电）；`0e`（CPU1–3）能让大核继续睡，两种都要测 |
| `A76_MAX_KHZ` | `1500000` | 把 related_cpus 从 4 起的 cpufreq 策略（policy4 = CPU4–6，policy7 = CPU7）的 `scaling_max_freq` 设成频率表里 ≤1.5GHz 的最高档，并写入 `/run/mu300/cpu-ceiling`，这样 mu300 的 `thermal-guard` 降温后不会把上限抬回去 | H1：热预算 3W ≈ 投屏功耗；限频能削掉开机和 JIT 峰值的 1–2W | 每帧工作在大核上慢 1.3–1.5 倍，对这个负载无关紧要；之后 `mu300-cpu profile …` 会覆盖它。只是 `scaling_max_freq`，不碰电压和热触发点 |
| `DMESG_LEVEL` | `1` | `dmesg -n 1`，控制台只打紧急信息 | H3 / PA#3：旧底座的 Wi-Fi 驱动刷屏在 CPU0 上占 1–3% | 控制台看不到内核警告；`logread` 不受影响 |
| （固定） | — | `oom_score_adj`：java +500，hostapd/netifd/bluetoothd/dnsmasq/odhcpd −500；`/etc/init.d/autoplay-tune oom` 可随时重做 | H9：OOM 时应该先死可重启的接收端，而不是网络和蓝牙的底层 | 开机时 JVM 还没起，这里只是尽力而为；**正确的位置是接收端启动器给自己写 `/proc/self/oom_score_adj`** |
| `RUN_TMPFS_SIZE` | `64m` | 把 `/var/run/autoplay` 单独挂成 64MB 的 tmpfs（`nosuid,nodev,noexec`） | H9：无上限的 tmpfs 日志杀不掉，会和 JVM 抢内存 | 日志超过 64MB 就写不进去；measure.sh 自己做了滚动 |
| （固定） | — | `ulimit -c 0` 加 `kernel.core_pattern=/dev/null` | H9：`core_pattern` 指向 `/tmp`，JVM 崩溃会往内存里倒核心转储 | 没有核心转储可分析；JVM 的 `hs_err` 文件不受影响 |
| （固定） | — | `net.ipv4.tcp_notsent_lowat=32768` | WP6：导航、Siri 和视频挤在同一条 TCP 流里，前面可能压着约 300ms 的视频外加 256KiB 内核缓冲 | 对大吞吐无影响；只是让应用层更早感知背压 |
| `LEDS_OFF` | `1` | 开机 20 秒后 `mu300-led idle on` + `mu300-led sleep`：全部熄灭，热告警仍会闪 | H1 / 功耗表：LED 30–60mW | 看不到状态灯；按键可唤醒 |
| `FS_COMMIT30` | `0`（`--fs` 时 1） | `mount -o remount,commit=30 /` | H7 | 断电最多丢 30 秒的日志；状态文件本来就靠 rename 写 |

### 没有做、要在别处做的

- **JVM 参数**（`-XX:+ExitOnOutOfMemoryError`、G1/Serial 的选择、`CICompilerCount`、JCA ChaCha20）：属于接收端启动器（WP2、H4），不在配置脚本里。
- **配对文件原子写、蓝牙后台重试、健康检查**：代码改动（WP2、WP3）。
- **无 SIM 时关闭调制解调器射频**（`mobile-data suspend off`）：和证书续期冲突（特斯拉专属补充 §六），等那条路定下来再做。
- **`mu300-cpu lowlatency on`**：和第 7 项的 `CPU0_IDLE` 是同一件事的两个开关；为了只有一个所有者，脚本用自己的，不写 mu300 的 `cpu.conf`。
- **升级 mu300 底座到 ≥ v2026.10.19.3**（PA#3、WP4）：产品决策，不是脚本。

## measure.sh / measure.init

对应路线图 WP0"盒子侧指标"和硬件审查第六节"记录方式：一个 procd 服务把 CSV 写到 tmpfs，每 60 秒刷一次盘"。

```sh
cp tools/f50/measure.sh   /usr/sbin/autoplay-measure;      chmod 755 /usr/sbin/autoplay-measure
cp tools/f50/measure.init /etc/init.d/autoplay-measure;    chmod 755 /etc/init.d/autoplay-measure
mkdir -p /etc/autoplay; printf 'CAR_IP=100.96.0.20\nINTERVAL=10\nFLUSH=60\n' > /etc/autoplay/measure.conf
/etc/init.d/autoplay-measure enable; /etc/init.d/autoplay-measure start
```

- 每 `INTERVAL`（10 秒）追加一行到 `/var/run/autoplay/measure.csv`（tmpfs；超过 8MB 时保留表头加最近 1000 行）。
- 每 `FLUSH`（60 秒）把新增的行**追加**到 `/opt/autoplay/state/measure/measure-<boot_id 前 8 位>.csv`——一分钟一次提交，而不是每 5 秒一次（H7）。已刷到盘的字节数记在 tmpfs 里，服务被 procd 重启后不会重复追加；收到 TERM 时先刷盘再退出。
- 列：ISO 时间、uptime、1 分钟负载、`MemAvailable`、JVM pid 和 RSS、`iw dev wlan0 station dump` 的站点数、`ss -tin dst <车机 IP>` 的连接数/最大 rtt/重传增量/最大 unacked、wlan0 收发字节增量、每个 CPU 的忙碌% 和软中断%（内核开了 `IRQ_TIME_ACCOUNTING`，软中断列可信）、每个 cpufreq 策略的当前和上限频率、**每个** `thermal_zone` 的温度（列名带 `type`，所以 `soc-thmzone`、`board`、`pa`、`nr` 分开记，H10 的要求）、每个冷却设备的 `cur_state`、`/proc/interrupts` 里名字匹配 WCN/PCIe/SIPC/mailbox/IPA 的中断的总增量和 CPU0 增量。
- 缺什么就留空：没有 `ss`、没有 `iw`、没有 wlan0、没有 JVM 都不会让脚本退出。
- `--once` 只采一行（用来看列对不对）；`CAR_IP` 不填就跳过 `ss` 那四列。

## measure-report.py

```sh
python3 tools/f50/measure-report.py /opt/autoplay/state/measure/measure-*.csv [--hot 85] [--warm 80]
python3 -m unittest tools/f50/test_measure_report.py
```

输出：采样数和时间跨度、最热温区、SoC 温区 ≥80°C 和 ≥85°C 的分钟数（80°C 是投屏页计划的降分辨率门限，85°C 是 IPA 的控制点，H1）、"任一 cpufreq 冷却设备 `cur_state` > 0"的降频分钟数、各策略平均/最低频率和 `scaling_max` 低于本次最高值的分钟数、CPU0 忙碌和软中断的 p50/p90/p99/max、JVM RSS、`MemAvailable` 最小值、wlan0 吞吐、到车机的 rtt/重传/unacked、各中断的每秒速率和 CPU0 份额。缺列就跳过，不编数。`testdata/sample-measure.csv` 是单元测试用的合成数据，可以直接拿来试。

## 上车的 A/B 顺序（WP0 第 1 周）

每次只改一个变量，同一条路线跑 20–30 分钟，用 `measure-report.py` 比较 CPU0 软中断%、SoC 最高温、降频分钟数，再用 `tools/car/touch-latency.md` 的相机法比较触摸延迟：

1. 基线（什么都不改，只装 measure）。
2. `harden.sh --cpu0-idle off`（其余杠杆）→ 再 `--cpu0-idle boot`：看 CPU0 深度睡眠对延迟和温度的影响。
3. `--rps f0` 对 `--rps 0e`。
4. `--a76-max 1500000` 对 `--a76-max 0`（不限频）：看开机那一分钟的峰值温度。


## 0.1.1 测量修正

采样间隔和刷盘间隔必须为正整数；每个输出文件使用自己的 `<输出文件>.state/`，避免同目录多次测量相互污染。滚动只保留一个表头，重启读取已保存偏移时去除空白，网卡计数器归零后该次吞吐留空。`test_measure_shell.py` 用合成 `/proc` 覆盖这些行为；尚无 F50 实测数据。持久文件目前仍需人工归档或定期清理，磁盘写失败时的滚动策略还应继续加固。

> 2026-11-03：1.0.0 已在车上跑通，但 `measure.sh` 和 `harden.sh` 的 A/B 顺序还没有在那台 F50 上执行过，本文的数值仍是推算；第一组实测数据见 `docs/ROADMAP.md`"车上要测的"。
