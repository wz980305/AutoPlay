#!/bin/sh
# AutoPlay week-1 hardening for a ZTE F50 running OpenWrt (mu300-linux, vendor 5.4 kernel).
# POSIX sh (busybox ash). Idempotent: every lever checks the current state first and logs what it did.
#
#   harden.sh [--dry-run] [--country CC] [--lock-linux] [--fs] [--no-wifi-reload] [--rps MASK] [--a76-max KHZ]
#   harden.sh --revert [--dry-run]
#   harden.sh --status
#
# Each lever names the finding it comes from (H1/H3/H5/H6/H7/H9 = hardware review; PA#n = platform audit;
# WP1/WP5/WP7 = hardening roadmap). See tools/f50/README.md for the reasoning, the risk and whether a reboot is needed.
# Nothing here touches the receiver, the identity directory, the kernel, BlueZ or the bootloader.
#
# What it changes (apply):
#   1. uci network.wan.dl_reboot=0                     PA#5  (no reboot)
#   2. wireless country/channel 149/htmode VHT80       PA#9, H6 (wifi reload = WCN chip power cycle; not during a session)
#   3. mu300-next-boot: print status; attempts 6, or lock with --lock-linux   PA#1, WP1
#   4. regenerate the uhttpd TLS key once               PA#3, WP7 (restarts uhttpd)
#   5. mu300-usb adb off                                PA#15, WP7
#   6. drop mali_kbase / sprd_gpu_cooling / sc27xx-vibra from mu300's extra-modules   H5 (reboot to take effect)
#   7. install /etc/init.d/autoplay-tune + hotplug + sysctl: CPU0 cpuidle, RPS, A76 cap, dmesg -n 1,
#      oom_score_adj, tmpfs for /var/run/autoplay, core dumps off, tcp_notsent_lowat, LEDs off   H1 H3 H9 WP5 WP6
#   8. tune2fs -e remount-ro on the root device (only with --fs)   H7
#   9. uci commit + service reloads
# Revert restores what this script recorded in /etc/autoplay/harden.prev; it cannot bring back the old uhttpd key.
set -u

DRY=0
REVERT=0
STATUS=0
COUNTRY=CN
LOCK_LINUX=0
DO_FS=0
WIFI_RELOAD=1
RPS_MASK=f0
A76_MAX_KHZ=1500000
CPU0_IDLE_MODE=boot      # boot | session | off  (session: only while /var/run/autoplay/session exists)

R=${AUTOPLAY_SYSROOT:-}   # a fake / for tests; empty on the device
ETC=$R/etc/autoplay
PREV=$ETC/harden.prev
STAMP_DIR=$ETC/stamps
TUNE_CONF=$ETC/tune.conf
INIT=$R/etc/init.d/autoplay-tune
HOTPLUG=$R/etc/hotplug.d/net/50-autoplay-rps
SYSCTL=$R/etc/sysctl.d/60-autoplay.conf
MU=$R/opt/mu300/bin
EXTRA_MODULES=$MU/extra-modules
DROP_MODULES="mali_kbase sprd_gpu_cooling sc27xx-vibra"
export PATH="$PATH:/opt/mu300/bin:/opt/mu300/busybox-bin:/usr/sbin:/sbin:/usr/bin:/bin"

usage() {
    sed -n '2,20p' "$0" | sed 's/^# \{0,1\}//'
    exit "${1:-0}"
}

while [ $# -gt 0 ]; do
    case $1 in
        --dry-run) DRY=1 ;;
        --revert) REVERT=1 ;;
        --status) STATUS=1 ;;
        --country) shift; COUNTRY=${1:-}; [ -n "$COUNTRY" ] || usage 2 ;;
        --country=*) COUNTRY=${1#--country=} ;;
        --lock-linux) LOCK_LINUX=1 ;;
        --fs) DO_FS=1 ;;
        --no-wifi-reload) WIFI_RELOAD=0 ;;
        --rps) shift; RPS_MASK=${1:-f0} ;;
        --rps=*) RPS_MASK=${1#--rps=} ;;
        --a76-max) shift; A76_MAX_KHZ=${1:-1500000} ;;
        --a76-max=*) A76_MAX_KHZ=${1#--a76-max=} ;;
        --cpu0-idle) shift; CPU0_IDLE_MODE=${1:-boot} ;;
        --cpu0-idle=*) CPU0_IDLE_MODE=${1#--cpu0-idle=} ;;
        -h|--help) usage 0 ;;
        *) echo "unknown argument: $1" >&2; usage 2 ;;
    esac
    shift
done
case $CPU0_IDLE_MODE in boot|session|off) ;; *) echo "--cpu0-idle must be boot|session|off" >&2; exit 2 ;; esac
case $COUNTRY in [A-Z][A-Z]) ;; *) echo "--country must be a two-letter ISO code (got '$COUNTRY')" >&2; exit 2 ;; esac

# ---------- logging and execution ----------
log() { echo "harden: $*"; logger -t autoplay-harden -- "$*" 2>/dev/null || true; }
lever() { echo; echo "== $1  [$2]"; }
run() {  # run CMD ARGS...: execute, or print under --dry-run
    if [ "$DRY" = 1 ]; then echo "   (dry) $*"; return 0; fi
    echo "   + $*"
    "$@"
}
# write_file PATH <<EOF ... : write a file (dry-run prints the path only)
write_file() {
    _p=$1
    if [ "$DRY" = 1 ]; then echo "   (dry) write $_p"; cat >/dev/null; return 0; fi
    mkdir -p "${_p%/*}"
    cat > "$_p.tmp" && mv -f "$_p.tmp" "$_p"
    echo "   + wrote $_p"
}
have() { command -v "$1" >/dev/null 2>&1; }
stamp_has() { [ -f "$STAMP_DIR/$1" ]; }
stamp_set() { [ "$DRY" = 1 ] || { mkdir -p "$STAMP_DIR"; : > "$STAMP_DIR/$1"; }; }
# prev_save KEY VALUE: remember the value before the first change, for --revert (first write wins)
prev_save() {
    [ "$DRY" = 1 ] && return 0
    mkdir -p "$ETC"
    [ -f "$PREV" ] || : > "$PREV"
    grep -q "^$1=" "$PREV" 2>/dev/null && return 0
    echo "$1=$2" >> "$PREV"
}
prev_get() { sed -n "s/^$1=//p" "$PREV" 2>/dev/null | tail -n1; }
uci_get() { uci -q get "$1" 2>/dev/null || true; }

# ---------- discovery ----------
radio5g() {  # the 5 GHz wifi-device section name; radio0 on the F50
    _r=
    for _d in $(uci -q show wireless 2>/dev/null | sed -n 's/^wireless\.\([^.=]*\)=wifi-device$/\1/p'); do
        _band=$(uci_get "wireless.$_d.band"); _hw=$(uci_get "wireless.$_d.hwmode")
        case "$_band$_hw" in *5g*|*11a*) _r=$_d; break ;; esac
        [ -z "$_r" ] && _r=$_d
    done
    echo "${_r:-radio0}"
}
root_dev() {
    _d=$(awk '$2 == "/" { d = $1 } END { print d }' /proc/mounts 2>/dev/null)
    case $_d in /dev/root|"") _d=$(sed -n 's/.*[ ]root=\([^ ]*\).*/\1/p' /proc/cmdline 2>/dev/null) ;; esac
    echo "$_d"
}
session_hook_exists() {  # a future receiver/supervisor marks a live CarPlay session with this file
    [ -e /var/run/autoplay/session ] || grep -qs "autoplay/session" /opt/autoplay/*.py /opt/dashplay/*.py 2>/dev/null
}

# ---------- status ----------
show_status() {
    echo "AutoPlay hardening status ($(date 2>/dev/null))"
    echo "dl_reboot:            $(uci_get network.wan.dl_reboot) (want 0)"
    _r=$(radio5g)
    echo "wireless.$_r:        country=$(uci_get "wireless.$_r.country") channel=$(uci_get "wireless.$_r.channel") htmode=$(uci_get "wireless.$_r.htmode")"
    have iw && echo "iw reg:               $(iw reg get 2>/dev/null | sed -n 's/^country \([A-Z0-9][A-Z0-9]\):.*/\1/p' | head -n1)"
    if have mu300-next-boot; then mu300-next-boot status 2>/dev/null | sed 's/^/next-boot:            /'; fi
    echo "uhttpd key stamp:     $(stamp_has uhttpd-key && echo regenerated || echo not yet)"
    have mu300-usb && echo "adb:                  $(mu300-usb 2>/dev/null | grep -i adb | head -n1)"
    if [ -f "$EXTRA_MODULES" ]; then
        for m in $DROP_MODULES; do
            grep -q "for m in .*\b$m\b" "$EXTRA_MODULES" && echo "extra-modules:        $m still listed" || echo "extra-modules:        $m dropped"
        done
        for m in $DROP_MODULES; do grep -q "^$m " /proc/modules 2>/dev/null && echo "loaded now:           $m"; done
    fi
    echo "autoplay-tune init:   $([ -x "$INIT" ] && echo installed || echo absent)"
    [ -f "$TUNE_CONF" ] && sed 's/^/tune.conf:            /' "$TUNE_CONF"
    for n in /sys/devices/system/cpu/cpu0/cpuidle/state[1-9]*/disable; do [ -f "$n" ] && echo "cpu0 ${n%/disable}: disable=$(cat "$n")"; done
    [ -f /sys/class/net/wlan0/queues/rx-0/rps_cpus ] && echo "wlan0 rps_cpus:       $(cat /sys/class/net/wlan0/queues/rx-0/rps_cpus)"
    for p in /sys/devices/system/cpu/cpufreq/policy*; do
        [ -d "$p" ] && echo "${p##*/}:              max=$(cat "$p/scaling_max_freq" 2>/dev/null) hw=$(cat "$p/cpuinfo_max_freq" 2>/dev/null) cpus=$(cat "$p/related_cpus" 2>/dev/null)"
    done
    echo "tcp_notsent_lowat:    $(sysctl -n net.ipv4.tcp_notsent_lowat 2>/dev/null)"
    echo "core_pattern:         $(sysctl -n kernel.core_pattern 2>/dev/null)"
    _rd=$(root_dev)
    echo "root device:          $_rd"
    have tune2fs && [ -n "$_rd" ] && tune2fs -l "$_rd" 2>/dev/null | grep -E "Errors behavior|Filesystem state" | sed 's/^/  /'
    grep -qs " /var/run/autoplay " /proc/mounts && echo "/var/run/autoplay:    tmpfs mounted"
}

# ---------- levers ----------
lever_dl_reboot() {
    lever "1. mobile-data watchdog must not reboot the box" "PA#5 / WP1"
    _cur=$(uci_get network.wan.dl_reboot)
    if [ "$_cur" = 0 ]; then echo "   already 0"; return 0; fi
    prev_save network.wan.dl_reboot "${_cur:-__unset__}"
    run uci set network.wan.dl_reboot=0
    COMMIT_NETWORK=1
    log "dl_reboot ${_cur:-unset} -> 0 (takes effect at the watchdog's next decision; no reboot)"
}

lever_wireless() {
    lever "2. 5 GHz hotspot: country $COUNTRY, channel 149, VHT80" "PA#9 / H6 / WP1"
    _r=$(radio5g)
    _c=$(uci_get "wireless.$_r.country"); _ch=$(uci_get "wireless.$_r.channel"); _hm=$(uci_get "wireless.$_r.htmode")
    echo "   radio=$_r now: country=$_c channel=$_ch htmode=$_hm"
    case $COUNTRY in
        TR|IL) echo "   WARNING: channel 149 is not allowed under $COUNTRY regulatory rules; the AP would fall back or go AP-DISABLED. Pick 36-48 by hand." ;;
    esac
    _changed=0
    if [ "$_c" != "$COUNTRY" ]; then prev_save "wireless.$_r.country" "${_c:-__unset__}"; run uci set "wireless.$_r.country=$COUNTRY"; _changed=1; fi
    if [ "$_ch" != 149 ]; then prev_save "wireless.$_r.channel" "${_ch:-__unset__}"; run uci set "wireless.$_r.channel=149"; _changed=1; fi
    if [ "$_hm" != VHT80 ]; then prev_save "wireless.$_r.htmode" "${_hm:-__unset__}"; run uci set "wireless.$_r.htmode=VHT80"; _changed=1; fi
    if [ "$_changed" = 1 ]; then COMMIT_WIRELESS=1; log "wireless.$_r -> country=$COUNTRY channel=149 htmode=VHT80"; else echo "   already set"; fi
    if have iw; then
        _reg=$(iw reg get 2>/dev/null | sed -n 's/^country \([A-Z0-9][A-Z0-9]\):.*/\1/p' | head -n1)
        [ -n "$_reg" ] && [ "$_reg" != "$COUNTRY" ] && echo "   note: kernel regulatory domain is '$_reg' now; it follows the uci country after the Wi-Fi reload or reboot (check: iw reg get)"
    fi
}

lever_next_boot() {
    lever "3. boot-fallback policy (stock Android after N failed boots)" "PA#1 / WP1"
    if ! have mu300-next-boot; then echo "   mu300-next-boot not found: not a mu300-linux image? Nothing done."; return 0; fi
    echo "   current:"
    mu300-next-boot status 2>&1 | sed 's/^/     /'
    _locked=$(mu300-next-boot status 2>/dev/null | sed -n 's/^locked: \(yes\|no\).*/\1/p')
    _att=$(mu300-next-boot attempts 2>/dev/null | tr -dc '0-9')
    if [ "$LOCK_LINUX" = 1 ]; then
        if [ "$_locked" = yes ]; then echo "   already locked"; return 0; fi
        echo "   --lock-linux: Linux stays the default whatever happens; a broken Linux then needs the USB rescue path (mu300-linux wiki: Going-Back-to-Android)."
        prev_save next_boot_locked "${_locked:-no}"
        run mu300-next-boot lock || log "mu300-next-boot lock failed (see output above)"
        log "next-boot: locked Linux"
    else
        if [ "${_att:-5}" -ge 6 ] 2>/dev/null; then echo "   attempts already ${_att} (maximum)"; return 0; fi
        prev_save next_boot_attempts "${_att:-5}"
        run mu300-next-boot attempts 6 || log "mu300-next-boot attempts 6 failed (see output above)"
        log "next-boot: attempts ${_att:-5} -> 6 (lock with --lock-linux once the install is accepted)"
    fi
}

lever_uhttpd_key() {
    lever "4. regenerate the LuCI (uhttpd) TLS key shared by every device of the image" "PA#3 / WP7"
    if stamp_has uhttpd-key; then echo "   already regenerated on this device"; return 0; fi
    if [ ! -f "$R/etc/uhttpd.key" ] && [ ! -f "$R/etc/uhttpd.crt" ]; then echo "   no /etc/uhttpd.key or .crt: nothing to replace (uhttpd makes a fresh pair on start)"; stamp_set uhttpd-key; return 0; fi
    if [ ! -x "$R/etc/init.d/uhttpd" ]; then echo "   uhttpd not installed; skipping"; return 0; fi
    run rm -f "$R/etc/uhttpd.key" "$R/etc/uhttpd.crt"
    run "$R/etc/init.d/uhttpd" restart
    stamp_set uhttpd-key
    log "uhttpd TLS key regenerated (browsers that pinned the old LuCI certificate will warn once)"
}

lever_adb() {
    lever "5. adb over USB off (root shell for anyone with a cable)" "PA#15 / WP7"
    if ! have mu300-usb; then echo "   mu300-usb not found; skipping"; return 0; fi
    _st=$(mu300-usb 2>/dev/null | grep -i adb | head -n1)
    echo "   now: ${_st:-unknown}"
    case $_st in *off*) echo "   already off"; return 0 ;; esac
    prev_save adb on
    run mu300-usb adb off || log "mu300-usb adb off failed"
    log "adb off (persisted by mu300 in /etc/mu300/adb)"
}

lever_extra_modules() {
    lever "6. drop GPU / GPU-cooling / vibrator modules from mu300's extra-modules" "H5"
    if [ ! -f "$EXTRA_MODULES" ]; then echo "   $EXTRA_MODULES not found; skipping"; return 0; fi
    _line=$(grep -n '^for m in .*mali_kbase.*; do$' "$EXTRA_MODULES" | head -n1)
    if [ -z "$_line" ]; then
        _still=0
        for m in $DROP_MODULES; do grep -q "\b$m\b" "$EXTRA_MODULES" && _still=1; done
        if [ "$_still" = 0 ]; then echo "   none of [$DROP_MODULES] listed; already done"; else
            echo "   the module list in $EXTRA_MODULES does not look like the known 'for m in ... mali_kbase; do' line."
            echo "   Edit it by hand: remove $DROP_MODULES from the modprobe loop. Not touching it."
        fi
        return 0
    fi
    _n=${_line%%:*}
    [ -f "$EXTRA_MODULES.autoplay-orig" ] || run cp -p "$EXTRA_MODULES" "$EXTRA_MODULES.autoplay-orig"
    for m in $DROP_MODULES; do
        # POSIX BRE, one quoted expression per module: " NAME" followed by a space or the ";" that ends the list
        run sed -i -e "${_n}s/ $m\([ ;]\)/\1/" "$EXTRA_MODULES"
    done
    if [ "$DRY" = 0 ]; then sed -n "${_n}p" "$EXTRA_MODULES" | sed 's/^/   now: /'; fi
    for m in $DROP_MODULES; do
        if grep -q "^$m " /proc/modules 2>/dev/null; then
            run rmmod "$m" 2>/dev/null || echo "   $m is loaded and busy; it goes away at the next boot"
        fi
    done
    log "extra-modules: dropped $DROP_MODULES (reboot to free the ~45 MiB; a mu300-update restores the file, re-run this script after one)"
}

lever_tune() {
    lever "7. boot-time tuning service: CPU0 idle, RPS, A76 cap, console log level, oom_score_adj, tmpfs, cores, sysctl, LEDs" "H1 / H3 / H9 / WP5 / WP6"
    _mode=$CPU0_IDLE_MODE
    if [ "$_mode" = boot ] && session_hook_exists; then
        _mode=session
        echo "   a session hook exists (/var/run/autoplay/session): CPU0 idle states are disabled only during a session"
    fi
    write_file "$TUNE_CONF" <<EOF
# AutoPlay boot tuning (read by /etc/init.d/autoplay-tune). KEY=VALUE, one per line.
# CPU0_IDLE: boot (disable CPU0 deep idle at boot), session (only while /var/run/autoplay/session exists), off
CPU0_IDLE=$_mode
# RPS mask for wlan0 rx-0: f0 = CPUs 4-7 (A76), 0e = CPUs 1-3 (A55, keeps the big cluster asleep). H3 says test both.
RPS_CPUS=$RPS_MASK
# A76 clusters (policies whose related_cpus are 4..7) are capped at the highest table step <= this many kHz. 0 = leave alone.
A76_MAX_KHZ=$A76_MAX_KHZ
# tmpfs size for /var/run/autoplay (logs, measurement CSV, session flag)
RUN_TMPFS_SIZE=64m
# dmesg console log level (1 = only emergencies on the console)
DMESG_LEVEL=1
# LEDs off while running (mu300-led idle on; the thermal alarm still shows)
LEDS_OFF=1
# root filesystem: remount with commit=30 at boot (ext4 only; fewer journal commits in flight at a power cut). 1 only with --fs.
FS_COMMIT30=$DO_FS
EOF
    write_file "$INIT" <<'EOF'
#!/bin/sh /etc/rc.common
# AutoPlay boot tuning for the ZTE F50 (installed by tools/f50/harden.sh; config in /etc/autoplay/tune.conf).
#   /etc/init.d/autoplay-tune start|restart   apply everything
#   /etc/init.d/autoplay-tune session on|off  CPU0 idle states for the duration of a CarPlay session (CPU0_IDLE=session)
#   /etc/init.d/autoplay-tune oom             (re)apply oom_score_adj to the processes that exist now
START=98
STOP=15
EXTRA_COMMANDS="session oom"
EXTRA_HELP="	session on|off  CPU0 deep idle off/on for a CarPlay session
	oom             re-apply oom_score_adj"
CONF=/etc/autoplay/tune.conf
RUN=/var/run/autoplay
export PATH="$PATH:/opt/mu300/bin:/opt/mu300/busybox-bin:/usr/sbin:/sbin"

cfg() { sed -n "s/^$1=//p" "$CONF" 2>/dev/null | tail -n1; }
say() { logger -t autoplay-tune -- "$*" 2>/dev/null; echo "autoplay-tune: $*"; }

cpu0_idle() {  # cpu0_idle 1|0 : 1 disables CPU0's deep states (state1 and up; state0/WFI stays)
	local any=0 n
	for n in /sys/devices/system/cpu/cpu0/cpuidle/state[1-9]*/disable; do
		[ -f "$n" ] || continue
		any=1
		echo "$1" > "$n" 2>/dev/null
	done
	[ "$any" = 1 ] && say "cpu0 deep idle $([ "$1" = 1 ] && echo off || echo on)"
}
rps() {
	local mask=$(cfg RPS_CPUS) q=/sys/class/net/wlan0/queues/rx-0/rps_cpus
	[ -n "$mask" ] && [ -w "$q" ] || return 0
	echo "$mask" > "$q" 2>/dev/null && say "wlan0 rps_cpus=$mask"
	echo 4096 > /sys/class/net/wlan0/queues/rx-0/rps_flow_cnt 2>/dev/null
	sysctl -q -w net.core.rps_sock_flow_entries=4096 2>/dev/null
}
a76_cap() {
	local khz=$(cfg A76_MAX_KHZ) p cpus hwmax cap name
	[ -n "$khz" ] && [ "$khz" -gt 0 ] 2>/dev/null || return 0
	for p in /sys/devices/system/cpu/cpufreq/policy*; do
		[ -d "$p" ] || continue
		cpus=$(cat "$p/related_cpus" 2>/dev/null)
		hwmax=$(cat "$p/cpuinfo_max_freq" 2>/dev/null)
		# the A76 clusters: related_cpus start at 4 or above (policy4 = CPU4-6, policy7 = CPU7 on the T760)
		case "${cpus%% *}" in 4|5|6|7) ;; *) continue ;; esac
		[ -n "$hwmax" ] && [ "$hwmax" -gt "$khz" ] 2>/dev/null || continue
		cap=$(tr ' ' '\n' < "$p/scaling_available_frequencies" 2>/dev/null | awk -v lim="$khz" '$1 != "" && $1 <= lim && $1 > c { c = $1 } END { print c }')
		[ -n "$cap" ] && [ "$cap" -gt 0 ] 2>/dev/null || cap=$khz
		echo "$cap" > "$p/scaling_max_freq" 2>/dev/null || continue
		name=${p##*/}
		# tell mu300's thermal-guard about the ceiling so a cool-down never lifts the cap above it
		mkdir -p /run/mu300 2>/dev/null
		{ grep -v "^$name=" /run/mu300/cpu-ceiling 2>/dev/null; echo "$name=$cap"; } > /run/mu300/cpu-ceiling.tmp 2>/dev/null && mv -f /run/mu300/cpu-ceiling.tmp /run/mu300/cpu-ceiling
		say "$name ($cpus) scaling_max_freq=$cap (hw $hwmax)"
	done
}
oom_adj() {  # the restartable receiver dies first; the network and Bluetooth plumbing last (H9)
	local pid
	for pid in $(pgrep -x java 2>/dev/null); do echo 500 > "/proc/$pid/oom_score_adj" 2>/dev/null; done
	for name in hostapd netifd bluetoothd dnsmasq odhcpd; do
		for pid in $(pgrep -x "$name" 2>/dev/null); do echo -500 > "/proc/$pid/oom_score_adj" 2>/dev/null; done
	done
}
run_tmpfs() {
	local size=$(cfg RUN_TMPFS_SIZE)
	mkdir -p "$RUN"
	grep -qs " $RUN " /proc/mounts && return 0
	mount -t tmpfs -o "size=${size:-64m},mode=0755,nosuid,nodev,noexec" tmpfs "$RUN" 2>/dev/null && say "tmpfs on $RUN (${size:-64m})"
}
leds() {
	[ "$(cfg LEDS_OFF)" = 1 ] || return 0
	[ -x /opt/mu300/bin/mu300-led ] || return 0
	# after the boot-time LED writes (hotspot, modem) have happened
	( sleep 20; /opt/mu300/bin/mu300-led idle on >/dev/null 2>&1; /opt/mu300/bin/mu300-led sleep >/dev/null 2>&1 ) &
}
fs_commit() {
	[ "$(cfg FS_COMMIT30)" = 1 ] || return 0
	mount -o remount,commit=30 / 2>/dev/null && say "root remounted with commit=30"
}

start() {
	ulimit -c 0
	run_tmpfs
	[ -n "$(cfg DMESG_LEVEL)" ] && dmesg -n "$(cfg DMESG_LEVEL)" 2>/dev/null
	[ -f /etc/sysctl.d/60-autoplay.conf ] && sysctl -q -p /etc/sysctl.d/60-autoplay.conf 2>/dev/null
	case $(cfg CPU0_IDLE) in
		boot) cpu0_idle 1 ;;
		session) [ -e "$RUN/session" ] && cpu0_idle 1 || cpu0_idle 0 ;;
		*) ;;
	esac
	rps
	a76_cap
	oom_adj
	fs_commit
	leds
}
stop() {
	cpu0_idle 0
}
restart() { stop; start; }
session() {
	case ${1:-} in
		on)  mkdir -p "$RUN"; : > "$RUN/session"; [ "$(cfg CPU0_IDLE)" = off ] || cpu0_idle 1; oom_adj ;;
		off) rm -f "$RUN/session"; [ "$(cfg CPU0_IDLE)" = boot ] || cpu0_idle 0 ;;
		*) echo "usage: $0 session on|off" >&2; return 2 ;;
	esac
}
oom() { oom_adj; }
EOF
    write_file "$HOTPLUG" <<'EOF'
#!/bin/sh
# AutoPlay: re-apply RPS whenever wlan0 is (re)created; a wifi down/up recreates the interface and resets rps_cpus.
[ "$INTERFACE" = wlan0 ] && [ "$ACTION" = add ] || exit 0
mask=$(sed -n 's/^RPS_CPUS=//p' /etc/autoplay/tune.conf 2>/dev/null | tail -n1)
[ -n "$mask" ] || exit 0
( sleep 2; echo "$mask" > /sys/class/net/wlan0/queues/rx-0/rps_cpus 2>/dev/null; echo 4096 > /sys/class/net/wlan0/queues/rx-0/rps_flow_cnt 2>/dev/null ) &
exit 0
EOF
    write_file "$SYSCTL" <<'EOF'
# AutoPlay (tools/f50/harden.sh)
# WP6: audio and control messages share the TCP stream with video; keep the unsent queue short so they are not
# stuck behind ~256 KiB of video in the kernel buffer.
net.ipv4.tcp_notsent_lowat = 32768
# H9: a JVM core dump into tmpfs would eat RAM; dump nowhere.
kernel.core_pattern = /dev/null
EOF
    run chmod 755 "$INIT" "$HOTPLUG"
    run "$INIT" enable
    run "$INIT" restart
    log "autoplay-tune installed (CPU0_IDLE=$_mode RPS=$RPS_MASK A76_MAX_KHZ=$A76_MAX_KHZ). oom_score_adj for the JVM is best effort from here; the receiver's launcher should set it on itself (+500)."
}

lever_fs() {
    lever "8. root filesystem: errors=remount-ro instead of errors=continue" "H7"
    if [ -n "$R" ]; then echo "   test sysroot set: skipping (touches the real root device)"; return 0; fi
    _rd=$(root_dev)
    echo "   root device: ${_rd:-unknown}"
    if ! have tune2fs; then echo "   tune2fs not installed (opkg/apk: tune2fs). Skipping."; return 0; fi
    if [ -z "$_rd" ] || [ ! -b "$_rd" ]; then echo "   cannot resolve the root block device; skipping"; return 0; fi
    _eb=$(tune2fs -l "$_rd" 2>/dev/null | sed -n 's/^Errors behavior:[ ]*//p')
    echo "   errors behavior now: ${_eb:-unknown}"
    if [ -z "$_eb" ]; then echo "   cannot read an ext4 superblock on $_rd (not ext4, or no permission); skipping"; return 0; fi
    case $_eb in *[Rr]emount*) echo "   already remount-ro"; return 0 ;; esac
    if [ "$DO_FS" != 1 ]; then
        echo "   not executed: re-run with --fs to apply:  tune2fs -e remount-ro $_rd   (and FS_COMMIT30=1 for the boot remount)"
        return 0
    fi
    prev_save fs_errors "${_eb:-continue}"
    run tune2fs -e remount-ro "$_rd"
    log "tune2fs -e remount-ro $_rd (a card returning I/O errors now turns the root read-only instead of running on)"
}

lever_commit() {
    lever "9. commit and reload" "-"
    [ "${COMMIT_NETWORK:-0}" = 1 ] && run uci commit network
    if [ "${COMMIT_WIRELESS:-0}" = 1 ]; then
        run uci commit wireless
        if [ "$WIFI_RELOAD" = 1 ]; then
            echo "   wifi reload = a full power cycle of the Wi-Fi/BT chip (H8): 3-6 s without Wi-Fi, Bluetooth re-initialised. Never during a CarPlay session."
            run wifi reload
        else
            echo "   --no-wifi-reload: the wireless change applies at the next reboot"
        fi
    fi
    [ "${COMMIT_NETWORK:-0}" = 1 ] || [ "${COMMIT_WIRELESS:-0}" = 1 ] || echo "   nothing to commit"
}

# ---------- revert ----------
revert() {
    echo "AutoPlay hardening: revert (from $PREV)"
    [ -f "$PREV" ] || { echo "no $PREV: nothing recorded, nothing to revert"; }
    _v=$(prev_get network.wan.dl_reboot)
    if [ -n "$_v" ]; then
        if [ "$_v" = __unset__ ]; then run uci -q delete network.wan.dl_reboot; else run uci set "network.wan.dl_reboot=$_v"; fi
        run uci commit network
    fi
    _r=$(radio5g); _w=0
    for k in country channel htmode; do
        _v=$(prev_get "wireless.$_r.$k")
        [ -n "$_v" ] || continue
        _w=1
        if [ "$_v" = __unset__ ]; then run uci -q delete "wireless.$_r.$k"; else run uci set "wireless.$_r.$k=$_v"; fi
    done
    if [ "$_w" = 1 ]; then run uci commit wireless; [ "$WIFI_RELOAD" = 1 ] && run wifi reload; fi
    if have mu300-next-boot; then
        _v=$(prev_get next_boot_locked); [ "$_v" = no ] && run mu300-next-boot unlock
        _v=$(prev_get next_boot_attempts); [ -n "$_v" ] && run mu300-next-boot attempts "$_v"
    fi
    [ "$(prev_get adb)" = on ] && have mu300-usb && run mu300-usb adb on
    if [ -f "$EXTRA_MODULES.autoplay-orig" ]; then run mv -f "$EXTRA_MODULES.autoplay-orig" "$EXTRA_MODULES"; fi
    if [ -x "$INIT" ]; then run "$INIT" stop; run "$INIT" disable; fi
    run rm -f "$INIT" "$HOTPLUG" "$SYSCTL" "$TUNE_CONF"
    if [ -z "$R" ]; then   # live system only (never from a test sysroot)
        have mu300-led && run mu300-led idle off
        run sysctl -q -w net.ipv4.tcp_notsent_lowat=4294967295
        run sysctl -q -w "kernel.core_pattern=/tmp/%e.%t.%p.%s.core"
        _v=$(prev_get fs_errors); _rd=$(root_dev)
        if [ -n "$_v" ] && have tune2fs && [ -b "$_rd" ]; then run tune2fs -e continue "$_rd"; fi
    fi
    echo "not reverted: the regenerated uhttpd key (the old one is gone; that is the point), the RPS/scaling_max_freq values of this boot (back at reboot), the tmpfs mount."
    [ "$DRY" = 1 ] || { rm -f "$PREV"; rm -rf "$STAMP_DIR"; }
    log "revert done"
}

# ---------- main ----------
if [ "$STATUS" = 1 ]; then show_status; exit 0; fi
if [ "$(id -u 2>/dev/null)" != 0 ] && [ "$DRY" = 0 ]; then echo "run as root (or with --dry-run)" >&2; exit 1; fi
if [ "$REVERT" = 1 ]; then revert; exit 0; fi

echo "AutoPlay F50 hardening $( [ "$DRY" = 1 ] && echo '(DRY RUN: nothing is changed)' )"
echo "country=$COUNTRY lock-linux=$LOCK_LINUX fs=$DO_FS wifi-reload=$WIFI_RELOAD rps=$RPS_MASK a76-max=$A76_MAX_KHZ cpu0-idle=$CPU0_IDLE_MODE"
if [ -e /var/run/autoplay/session ] || pgrep -x java >/dev/null 2>&1 && [ "$WIFI_RELOAD" = 1 ]; then
    echo "note: a receiver is running. The Wi-Fi reload in step 9 would end a live CarPlay session; use --no-wifi-reload to defer it."
fi
COMMIT_NETWORK=0; COMMIT_WIRELESS=0
lever_dl_reboot
lever_wireless
lever_next_boot
lever_uhttpd_key
lever_adb
lever_extra_modules
lever_tune
lever_fs
lever_commit
echo
echo "done. Reboot needed for: extra-modules (step 6). Check with: $0 --status"
