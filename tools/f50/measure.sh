#!/bin/sh
# AutoPlay measurement logger for the ZTE F50 (WP0 / hardware review "measurement plan").
# Every INTERVAL seconds it appends one CSV line to a tmpfs file, and every FLUSH seconds it appends the new lines to
# a file on the SD card (one commit a minute instead of twelve; H7). POSIX sh for busybox ash; every reading is
# best effort and leaves its column empty when the source is missing.
#
#   measure.sh [--car IP] [--interval S] [--flush S] [--out FILE] [--persist DIR] [--once]
#   defaults: --interval 10 --flush 60 --out /var/run/autoplay/measure.csv --persist /opt/autoplay/state/measure
#   /etc/autoplay/measure.conf (KEY=VALUE: CAR_IP, INTERVAL, FLUSH, OUT, PERSIST) supplies defaults; arguments win.
#
# Columns (the header is written when the CSV is created; variable parts are discovered at start):
#   time, uptime, load1, mem_avail_kb, jvm_pid, jvm_rss_kb, stations,
#   ss_conns, ss_rtt_max_ms, ss_retrans_d, ss_unacked_max   (TCP to --car IP, via ss -tin)
#   wlan0_rx_bytes_d, wlan0_tx_bytes_d                       (/proc/net/dev deltas over the interval)
#   cpuN_busy, cpuN_softirq  (percent of the interval, per CPU; IRQ_TIME_ACCOUNTING makes softirq meaningful)
#   policyN_cur_khz, policyN_max_khz                          (per cpufreq policy)
#   tz_<type>_mc                                               (every /sys/class/thermal/thermal_zone*, milli-degrees)
#   cd<N>_<type>                                               (every cooling device: cur_state)
#   irq<N>_<name>_d, irq<N>_<name>_cpu0_d                      (interrupt deltas for lines matching WCN/PCIe/SIPC/IPA)
set -u
export PATH="$PATH:/opt/mu300/busybox-bin:/usr/sbin:/sbin:/usr/bin:/bin"

CONF=${AUTOPLAY_MEASURE_CONF:-/etc/autoplay/measure.conf}
cfg() { sed -n "s/^$1=//p" "$CONF" 2>/dev/null | tail -n1; }
CAR_IP=$(cfg CAR_IP)
INTERVAL=${INTERVAL:-$(cfg INTERVAL)}; INTERVAL=${INTERVAL:-10}
FLUSH=${FLUSH:-$(cfg FLUSH)}; FLUSH=${FLUSH:-60}
OUT=$(cfg OUT); OUT=${OUT:-/var/run/autoplay/measure.csv}
PERSIST=$(cfg PERSIST); PERSIST=${PERSIST:-/opt/autoplay/state/measure}
ONCE=0
IRQ_MATCH=${IRQ_MATCH:-'[Ww][Cc][Nn]|[Pp][Cc][Ii][Ee]|[Ss][Ii][Pp][Cc]|[Mm]ailbox|[Mm]box|[Ii][Pp][Aa]|sprd_wlan|marlin'}
MAX_TMP_BYTES=${MAX_TMP_BYTES:-8388608}
SYS=${AUTOPLAY_SYSROOT:-}

while [ $# -gt 0 ]; do
    case $1 in
        --car) shift; CAR_IP=${1:-} ;;
        --car=*) CAR_IP=${1#--car=} ;;
        --interval) shift; INTERVAL=${1:-10} ;;
        --interval=*) INTERVAL=${1#--interval=} ;;
        --flush) shift; FLUSH=${1:-60} ;;
        --flush=*) FLUSH=${1#--flush=} ;;
        --out) shift; OUT=${1:-$OUT} ;;
        --out=*) OUT=${1#--out=} ;;
        --persist) shift; PERSIST=${1:-$PERSIST} ;;
        --persist=*) PERSIST=${1#--persist=} ;;
        --once) ONCE=1 ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) echo "measure: unknown argument $1" >&2; exit 2 ;;
    esac
    shift
done

STATE=${OUT%/*}/.measure-state
mkdir -p "${OUT%/*}" "$STATE" 2>/dev/null
have() { command -v "$1" >/dev/null 2>&1; }
rd() { cat "$1" 2>/dev/null; }
san() { printf '%s' "$1" | tr -c 'A-Za-z0-9_\n' '_' ; }

# ---------- discovery (once per start) ----------
NCPU=$(grep -c '^cpu[0-9]' "$SYS/proc/stat" 2>/dev/null); NCPU=${NCPU:-0}
POLICIES=$(for p in "$SYS"/sys/devices/system/cpu/cpufreq/policy*; do [ -d "$p" ] && echo "${p##*/}"; done)
ZONES=$(for z in "$SYS"/sys/class/thermal/thermal_zone*; do [ -r "$z/temp" ] && echo "${z##*/}:$(san "$(rd "$z/type")")"; done)
CDEVS=$(for c in "$SYS"/sys/class/thermal/cooling_device*; do [ -r "$c/cur_state" ] && echo "${c##*/}:$(san "$(rd "$c/type")")"; done)
# interrupt lines of interest: "NUMBER:NAME" where NAME is the last field of the /proc/interrupts line
IRQS=$(grep -E "^ *[0-9]+:" "$SYS/proc/interrupts" 2>/dev/null | grep -E "$IRQ_MATCH" | awk '{ n = $1; sub(":", "", n); print n ":" $NF }' | head -n 12)
IRQ_NCOL=$(head -n1 "$SYS/proc/interrupts" 2>/dev/null | awk '{ print NF }'); IRQ_NCOL=${IRQ_NCOL:-0}

header() {
    printf 'time,uptime,load1,mem_avail_kb,jvm_pid,jvm_rss_kb,stations,ss_conns,ss_rtt_max_ms,ss_retrans_d,ss_unacked_max,wlan0_rx_bytes_d,wlan0_tx_bytes_d'
    i=0; while [ "$i" -lt "$NCPU" ]; do printf ',cpu%s_busy,cpu%s_softirq' "$i" "$i"; i=$((i + 1)); done
    for p in $POLICIES; do printf ',%s_cur_khz,%s_max_khz' "$p" "$p"; done
    for z in $ZONES; do printf ',tz_%s_mc' "${z#*:}"; done
    for c in $CDEVS; do printf ',cd%s_%s' "$(printf '%s' "${c%%:*}" | tr -dc '0-9')" "${c#*:}"; done
    for q in $IRQS; do printf ',irq%s_%s_d,irq%s_%s_cpu0_d' "${q%%:*}" "$(san "${q#*:}")" "${q%%:*}" "$(san "${q#*:}")"; done
    printf '\n'
}

# ---------- per-sample readers ----------
cpu_fields() {  # busy% and softirq% per CPU from two /proc/stat snapshots; empty on the first sample
    [ -s "$STATE/stat.prev" ] || { i=0; while [ "$i" -lt "$NCPU" ]; do printf ',,'; i=$((i + 1)); done; return 0; }
    awk -v n="$NCPU" '
        FNR == NR { if ($1 ~ /^cpu[0-9]/) { for (k = 2; k <= 9; k++) p[$1, k] = $k } ; next }
        $1 ~ /^cpu[0-9]/ {
            tot = 0; ptot = 0
            for (k = 2; k <= 9; k++) { tot += $k; ptot += p[$1, k] }
            d = tot - ptot
            idle = ($5 - p[$1, 5]) + ($6 - p[$1, 6])
            sirq = $8 - p[$1, 8]
            if (d > 0) { busy[$1] = sprintf("%.1f", 100 * (d - idle) / d); si[$1] = sprintf("%.1f", 100 * sirq / d) }
        }
        END { for (i = 0; i < n; i++) printf ",%s,%s", busy["cpu" i], si["cpu" i] }' "$STATE/stat.prev" "$SYS/proc/stat"
}
policy_fields() {
    for p in $POLICIES; do printf ',%s,%s' "$(rd "$SYS/sys/devices/system/cpu/cpufreq/$p/scaling_cur_freq")" "$(rd "$SYS/sys/devices/system/cpu/cpufreq/$p/scaling_max_freq")"; done
}
zone_fields() { for z in $ZONES; do printf ',%s' "$(rd "$SYS/sys/class/thermal/${z%%:*}/temp")"; done; }
cdev_fields() { for c in $CDEVS; do printf ',%s' "$(rd "$SYS/sys/class/thermal/${c%%:*}/cur_state")"; done; }
irq_fields() {  # deltas of total and CPU0 count per selected IRQ; empty on the first sample
    [ -n "$IRQS" ] || return 0
    if [ ! -s "$STATE/irq.prev" ]; then for q in $IRQS; do printf ',,'; done; return 0; fi
    awk -v list="$IRQS" -v ncol="$IRQ_NCOL" '
        BEGIN { n = split(list, a, "\n"); for (i = 1; i <= n; i++) { split(a[i], kv, ":"); want[kv[1]] = i; order[i] = kv[1] } }
        FNR == NR { if ($1 ~ /^[0-9]+:$/) { k = $1; sub(":", "", k); if (k in want) { t = 0; for (c = 2; c <= ncol + 1 && c <= NF; c++) if ($c ~ /^[0-9]+$/) t += $c; pt[k] = t; p0[k] = $2 } } ; next }
        $1 ~ /^[0-9]+:$/ { k = $1; sub(":", "", k); if (k in want) { t = 0; for (c = 2; c <= ncol + 1 && c <= NF; c++) if ($c ~ /^[0-9]+$/) t += $c; ct[k] = t; c0[k] = $2; seen[k] = 1 } }
        END { for (i = 1; i <= n; i++) { k = order[i]; if (seen[k] && (k in pt)) printf ",%d,%d", ct[k] - pt[k], c0[k] - p0[k]; else printf ",," } }' "$STATE/irq.prev" "$SYS/proc/interrupts"
}
netdev_fields() {  # wlan0 rx/tx byte deltas
    # strip the "wlan0:" prefix, then rx_bytes is field 1 and tx_bytes field 9
    cur=$(grep -E '^ *wlan0:' "$SYS/proc/net/dev" 2>/dev/null | sed 's/^ *wlan0: *//' | awk '{ print $1 " " $9 }')
    prev=$(rd "$STATE/netdev.prev")
    if [ -n "$cur" ] && [ -n "$prev" ]; then
        printf ',%s,%s' "$(( ${cur%% *} - ${prev%% *} ))" "$(( ${cur##* } - ${prev##* } ))"
    else
        printf ',,'
    fi
    [ -n "$cur" ] && printf '%s\n' "$cur" > "$STATE/netdev.prev"
}
ss_fields() {  # conns, max rtt, retrans delta, max unacked for TCP to the car
    if [ -z "$CAR_IP" ] || ! have ss; then printf ',,,,'; return 0; fi
    out=$(ss -tin "dst $CAR_IP" 2>/dev/null)
    conns=$(printf '%s\n' "$out" | grep -c '^ESTAB')
    rtt=$(printf '%s\n' "$out" | sed -n 's/.* rtt:\([0-9.]*\)\/.*/\1/p' | sort -n | tail -n1)
    retr=$(printf '%s\n' "$out" | sed -n 's/.* retrans:[0-9]*\/\([0-9]*\).*/\1/p' | awk '{ s += $1 } END { print s + 0 }')
    unack=$(printf '%s\n' "$out" | sed -n 's/.* unacked:\([0-9]*\).*/\1/p' | sort -n | tail -n1)
    prevr=$(rd "$STATE/retrans.prev")
    retr_d=; [ -n "$prevr" ] && retr_d=$((retr - prevr))
    printf '%s\n' "$retr" > "$STATE/retrans.prev"
    printf ',%s,%s,%s,%s' "$conns" "${rtt:-}" "${retr_d:-}" "${unack:-}"
}
jvm_fields() {
    pid=$(pgrep -x java 2>/dev/null | head -n1)
    [ -n "$pid" ] || { printf ',,'; return 0; }
    printf ',%s,%s' "$pid" "$(sed -n 's/^VmRSS:[ ]*\([0-9]*\).*/\1/p' "/proc/$pid/status" 2>/dev/null)"
}
stations() {
    have iw || { printf ''; return 0; }
    iw dev wlan0 station dump 2>/dev/null | grep -c '^Station'
}

sample() {
    t=$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null)
    up=$(cut -d' ' -f1 "$SYS/proc/uptime" 2>/dev/null)
    load=$(cut -d' ' -f1 "$SYS/proc/loadavg" 2>/dev/null)
    mem=$(sed -n 's/^MemAvailable:[ ]*\([0-9]*\).*/\1/p' "$SYS/proc/meminfo" 2>/dev/null)
    {
        printf '%s,%s,%s,%s' "$t" "$up" "$load" "$mem"
        jvm_fields
        printf ',%s' "$(stations)"
        ss_fields
        netdev_fields
        cpu_fields
        policy_fields
        zone_fields
        cdev_fields
        irq_fields
        printf '\n'
    } >> "$OUT"
    cp "$SYS/proc/stat" "$STATE/stat.prev" 2>/dev/null
    cp "$SYS/proc/interrupts" "$STATE/irq.prev" 2>/dev/null
}

BOOT=$(cut -c1-8 "$SYS/proc/sys/kernel/random/boot_id" 2>/dev/null); BOOT=${BOOT:-noboot}
PFILE=$PERSIST/measure-$BOOT.csv
# FLUSHED: how many bytes of $OUT are already in $PFILE. Kept in tmpfs so a respawned logger does not re-append.
FLUSHED=0
if [ -s "$PFILE" ] && [ -s "$STATE/flushed" ]; then FLUSHED=$(rd "$STATE/flushed"); fi
case $FLUSHED in ''|*[!0-9]*) FLUSHED=0 ;; esac
flush() {  # append the lines written since the last flush to the persistent copy
    [ -n "$PERSIST" ] || return 0
    mkdir -p "$PERSIST" 2>/dev/null || return 0
    sz=$(wc -c < "$OUT" 2>/dev/null || echo 0)
    if [ ! -s "$PFILE" ]; then head -n1 "$OUT" > "$PFILE" 2>/dev/null; FLUSHED=$(head -n1 "$OUT" | wc -c); fi
    if [ "$sz" -gt "$FLUSHED" ] 2>/dev/null; then
        tail -c +$((FLUSHED + 1)) "$OUT" >> "$PFILE" 2>/dev/null && FLUSHED=$sz
    fi
    echo "$FLUSHED" > "$STATE/flushed" 2>/dev/null
}
rotate() {  # keep the tmpfs file bounded: flush, then keep header + last 1000 lines (all of them already persisted)
    sz=$(wc -c < "$OUT" 2>/dev/null || echo 0)
    [ "$sz" -gt "$MAX_TMP_BYTES" ] 2>/dev/null || return 0
    flush
    { head -n1 "$OUT"; tail -n 1000 "$OUT"; } > "$OUT.tmp" && mv -f "$OUT.tmp" "$OUT"
    FLUSHED=$(wc -c < "$OUT" 2>/dev/null || echo 0)
    echo "$FLUSHED" > "$STATE/flushed" 2>/dev/null
}

[ -s "$OUT" ] || header > "$OUT"
logger -t autoplay-measure -- "start: interval=${INTERVAL}s flush=${FLUSH}s out=$OUT persist=$PFILE car=${CAR_IP:-none} cpus=$NCPU zones=$(printf '%s\n' "$ZONES" | grep -c .) irqs=$(printf '%s\n' "$IRQS" | grep -c .)" 2>/dev/null
trap 'flush; exit 0' TERM INT
since_flush=0
while :; do
    sample
    rotate
    [ "$ONCE" = 1 ] && { flush; exit 0; }
    since_flush=$((since_flush + INTERVAL))
    if [ "$since_flush" -ge "$FLUSH" ]; then flush; since_flush=0; fi
    sleep "$INTERVAL"
done
