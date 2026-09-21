#!/bin/sh
# ============================================================================
# kp-selftest.sh —— 设备状态与环境自检 · 设备端采集器（v1.0.0）
#
# 用法：sh kp-selftest.sh
#   采集全部板块，结果以 TSV 打到 stdout。PC 侧 scripts/device-selftest.py
#   负责解析，并按阈值渲染 [ OK ] / [WARN] / [FAIL] / [ SKIP ] 四态。
#
# 输出协议（制表符分隔）：
#   V<TAB>kp-selftest<TAB><版本>        版本握手（第 1 行，恒定）
#   S<TAB><板块号><TAB><板块名>          板块开始（1..5）
#   K<TAB><键><TAB><值>                 键值（TAB/换行已折叠；空值写 (空)）
#   L<TAB><组名><TAB><字段1>|<字段2>|…   列表行
#   E<TAB><键><TAB><错误摘要>            采集失败（与「本来就是空」显式区分）
#   N<TAB><说明>                        中性备注
#   Z<TAB>END                           结束哨兵
#
# ⚠️ 哨兵的意义：dropbear 在长输出时会 reset 连接。没有 Z 就无法诚实区分
#    「跑完了但没数据」与「跑到一半被截断」。PC 侧解析不到 Z 一律判环境错误。
#
# 硬约束（违反即破坏 risk=read 的承诺）：
#   · 全程只读：不写文件、不改 uci、不启停服务、不发 AT、不 reload 防火墙
#   · 不在 /tmp 落任何中间文件（连临时文件都不放）
#   · 任何单条失败都不能中断整体（失败也要有 E 输出）
#
# busybox / ash 兼容铁律（本机 BusyBox v1.33.2 + dropbear）：
#   · 无 local / 数组 / [[ ]] / {a,b,c} 展开 / trap ... ERR / $LINENO / dirname
#   · 无 jq / timeout / nft / stat / od / base64 / openssl / xxd / tput / lsblk / sqlite3
#   · 判活只用 pidof —— pgrep -c 在本固件恒返回 0，会把活着的服务全报成 NOT RUNNING
#   · 内存只读 /proc/meminfo —— free -m 不认 -m，照样吐 kB，按 MB 读会差 1000 倍
#   · 不用 grep -o（本固件行为有差异）→ 一律 sed -n 's/…/p' 或 awk
#   · 方括号表达式里绝不写 \t（未定义行为）→ 用 printf '\t'
#   · 中文只经 printf，且不做右对齐（${#s} 按字节算，中文占 2 列）
#   · df 一律带 -P（避免长设备名折行）
#   · 超时自管：curl -m N · ubus -t N · docker 前置 pidof 守卫 · dmesg/logread 走 tail
# ============================================================================

set -u

KP_VERSION="1.0.0"

# ============================== 输出原语 ==============================
sec()  { printf 'S\t%s\t%s\n' "$1" "$2"; }
lst()  { printf 'L\t%s\t%s\n' "$1" "$2"; }
err()  { printf 'E\t%s\t%s\n' "$1" "$2"; }
note() { printf 'N\t%s\n' "$1"; }

# kv：值清洗 —— TAB/换行折成空格 → 截 200 字节 → 空值显式标 (空)
kv() {
    _kv_v=$(printf '%s' "$2" | tr '\t\n' '  ' | cut -c1-200)
    [ -n "$_kv_v" ] || _kv_v="(空)"
    printf 'K\t%s\t%s\n' "$1" "$_kv_v"
}

# ============================== 通用探针 ==============================
alive()   { if [ -n "$(pidof "$1" 2>/dev/null)" ]; then echo yes; else echo no; fi; }
svc_en()  { if [ -x "/etc/init.d/$1" ] && /etc/init.d/"$1" enabled 2>/dev/null; then echo yes; else echo no; fi; }
present() { if [ -e "$1" ]; then echo yes; else echo no; fi; }
fbytes()  { wc -c <"$1" 2>/dev/null | tr -d ' '; }
num0()    { printf '%s' "$1" | tr -cd '0-9'; }

# 从 JSON 文本取「不含空格的标量字段」（不用 grep -o）
#   先删掉所有空格/TAB，把 , { } 换成换行，再按 "key":value 取第一个
jval() {
    printf '%s' "$1" | tr -d ' \t' | sed 's/[,{}]/\n/g' \
      | sed -n 's/^"'"$2"'":"\{0,1\}\([^",]*\)"\{0,1\}$/\1/p' | head -n1
}

# 只保留末 4 位 —— IMSI/ICCID/IMEI 脱敏（公开仓红线）
mask4() {
    _m4_s="$1"
    if [ -z "$_m4_s" ]; then echo "(无)"; return; fi
    _m4_t=$(printf '%s' "$_m4_s" | sed -n 's/.*\(....\)$/\1/p')
    [ -n "$_m4_t" ] || _m4_t="****"
    echo "****$_m4_t"
}

# 机型归一化（复刻上游 require_nradio_menu_environment 的口径）
norm_model() {
    case "$1" in
        HC-WT9500|*C2000Ultra*)  echo "NRadio_C2000Ultra" ;;
        *C2000?Max*)             echo "NRadio_C2000MAX" ;;
        *C8-688*)                echo "NRadio_C8-688" ;;
        *C5800*)                 echo "NRadio_C5800" ;;
        "")                      echo "unknown" ;;
        *)                       echo "$1" ;;
    esac
}

# 按文件名兜底定位（本机路径在固件版本间有差异）
find1() {
    _f1_p=$(find "$1" -name "$2" -type f 2>/dev/null | head -n 1)
    printf '%s' "$_f1_p"
}

# 日志异常扫描：输出 L 明细 + K 命中计数（dmesg/logread 都走 tail 控体积）
logscan() {
    _ls_out=$("$1" 2>/dev/null | grep -iE 'out of memory|oom.kill|killed process|f2fs.*(error|fail|corrupt)|mmc.*(error|timeout|crc)|i/o error|segfault|oops|kernel bug|call trace' | tail -n "$3")
    if [ -n "$_ls_out" ]; then
        printf '%s\n' "$_ls_out" | while IFS= read -r _ls_row; do
            [ -n "$_ls_row" ] && lst "$2" "$_ls_row"
        done
    fi
    printf 'K\t%s\t%s\n' "$2" "$(printf '%s\n' "$_ls_out" | grep -c .)"
}

# ============================== S1 · 系统资源与环境 ==============================
s1() {
    sec 1 "系统资源与环境"

    _model=$(cat /tmp/sysinfo/model 2>/dev/null)
    kv model_raw "$_model"
    kv model_norm "$(norm_model "$_model")"
    kv board_name "$(cat /tmp/sysinfo/board_name 2>/dev/null)"
    kv kernel "$(uname -r 2>/dev/null)"
    kv openwrt_release "$(sed -n "s/^DISTRIB_RELEASE='\(.*\)'/\1/p" /etc/openwrt_release 2>/dev/null)"

    # 版本判据的真源是 ubus system board 的 release.revision，不是 DISTRIB_RELEASE
    _board=$(ubus -t 10 call system board 2>/dev/null)
    if [ -n "$_board" ]; then
        kv board_release_rev "$(jval "$_board" revision)"
        kv board_release_ver "$(jval "$_board" version)"
        kv board_kernel "$(jval "$_board" kernel)"
    else
        err board "ubus call system board 无输出（ubus 未起？）"
    fi

    kv uptime_s "$(num0 "$(awk '{print int($1)}' /proc/uptime 2>/dev/null)")"
    kv loadavg "$(cat /proc/loadavg 2>/dev/null)"
    kv cpu_count "$(num0 "$(grep -c ^processor /proc/cpuinfo 2>/dev/null)")"

    # 内存 / swap：只读 /proc/meminfo（单位恒为 kB）
    _mi=$(awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} /^SwapTotal:/{s=$2} /^SwapFree:/{f=$2} END{printf "%d %d %d %d", t, a, s, f}' /proc/meminfo 2>/dev/null)
    kv mem_total_kb "$(printf '%s' "$_mi" | awk '{print $1+0}')"
    kv mem_avail_kb "$(printf '%s' "$_mi" | awk '{print $2+0}')"
    kv swap_total_kb "$(printf '%s' "$_mi" | awk '{print $3+0}')"
    kv swap_free_kb  "$(printf '%s' "$_mi" | awk '{print $4+0}')"

    # 单进程 swap 占用 Top5（本机无 swap 时自然为空）
    for _p in /proc/[0-9]*; do
        [ -r "$_p/status" ] || continue
        _vs=$(sed -n 's/^VmSwap: *\([0-9]*\).*/\1/p' "$_p/status" 2>/dev/null)
        [ -n "$_vs" ] || continue
        [ "$_vs" -gt 0 ] 2>/dev/null || continue
        printf '%s|%s|%s\n' "${_p##*/}" "$(cat "$_p/comm" 2>/dev/null)" "$_vs"
    done | sort -t'|' -k3 -rn | head -n 5 | while IFS= read -r _row; do
        [ -n "$_row" ] && lst SWAP_TOP "$_row"
    done

    # 温度（/sys/class/thermal/thermal_zone*/temp，单位 mdegC）
    _tz=0
    for _z in /sys/class/thermal/thermal_zone*; do
        [ -r "$_z/temp" ] || continue
        _tz=1
        lst TEMP "${_z##*/}|$(cat "$_z/type" 2>/dev/null)|$(cat "$_z/temp" 2>/dev/null)"
    done
    [ "$_tz" = 1 ] || note "无 /sys/class/thermal/thermal_zone*/temp（温度不可采）"

    kv conntrack_count "$(num0 "$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null)")"
    kv conntrack_max "$(num0 "$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null)")"

    # 存储：overlay 载体 + 三个挂载点 + TF 卡在场判据（与上游门禁同款）
    kv overlay_dev "$(awk '$2=="/overlay"{print $1}' /proc/mounts 2>/dev/null)"
    kv df_overlay "$(df -P /overlay 2>/dev/null | tail -n 1)"
    kv df_data "$(df -P /mnt/storage/data 2>/dev/null | tail -n 1)"
    kv df_tmp "$(df -P /tmp 2>/dev/null | tail -n 1)"
    kv mmc_present "$(awk '$1 ~ /^\/dev\/mmcblk/ && $2 ~ /^\/tmp\/storage/ {print $1" -> "$2; exit}' /proc/mounts 2>/dev/null)"
    kv mmc_size_gb "$(num0 "$(awk '{printf "%d", $1/2097152}' /sys/block/mmcblk0/size 2>/dev/null)")"

    logscan dmesg DMESG_HITS 8
    logscan logread LOGREAD_HITS 5

    kv resolv "$(tr '\n' ' ' < /etc/resolv.conf 2>/dev/null)"
}

# ============================== S2 · 容器梳理 ==============================
s2() {
    sec 2 "容器梳理"

    _dpid=$(pidof dockerd 2>/dev/null)
    kv dockerd_pid "$_dpid"
    kv dockerd_enabled "$(svc_en dockerd)"
    kv dockerd_init "$(present /etc/init.d/dockerd)"
    kv docker_bin "$(present /usr/bin/docker)"
    kv dockerd_cfg "$(present /etc/config/dockerd)"
    kv dockerd_data_root "$(sed -n "s/.*option data_root '\(.*\)'.*/\1/p" /etc/config/dockerd 2>/dev/null)"
    kv dockerd_mirrors_n "$(num0 "$(grep -c registry_mirrors /etc/config/dockerd 2>/dev/null)")"
    kv daemon_json "$(present /tmp/dockerd/daemon.json)"

    kv panel_pid "$(pidof 1panel 2>/dev/null)"
    kv panel_port_listen "$(num0 "$(netstat -lnt 2>/dev/null | grep -c ':10090')")"
    kv panel_root "$(present /mnt/storage/data/1panel)"
    if [ -f /mnt/storage/data/1panel/db/1Panel.db ]; then
        kv panel_db_bytes "$(fbytes /mnt/storage/data/1panel/db/1Panel.db)"
    else
        kv panel_db_bytes "MISSING"
    fi

    if [ -z "$_dpid" ]; then
        note "dockerd 未运行 → 容器与镜像清单跳过（若本机未装 Docker，属预期）"
    else
        kv docker_version "$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
        _dinfo=$(docker info 2>/dev/null)
        if [ -n "$_dinfo" ]; then
            kv docker_storage_driver "$(printf '%s\n' "$_dinfo" | sed -n 's/^ *Storage Driver: *//p' | head -n 1)"
            kv docker_backing_fs "$(printf '%s\n' "$_dinfo" | sed -n 's/^ *Backing Filesystem: *//p' | head -n 1)"
            kv docker_root_dir "$(printf '%s\n' "$_dinfo" | sed -n 's/^ *Docker Root Dir: *//p' | head -n 1)"
            kv registry_mirrors "$(printf '%s\n' "$_dinfo" | sed -n '/Registry Mirrors/,/^$/p' | sed 's/^ *//' | grep -v '^$' | tr '\n' ' ')"
        else
            err docker_info "docker info 无输出（dockerd 半死？）"
        fi

        # 🚫 禁用 {{json .}}（Docker 20.10 卡死）与 {{.Size}}（vfs 下 200s 不返回）
        #    Networks 必须带上：本机内核无 veth，非 host 网络的容器必然起不来
        docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}|{{.Networks}}' 2>/dev/null | while IFS= read -r _row; do
            [ -n "$_row" ] && lst CONTAINER "$_row"
        done
        docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null | while IFS= read -r _row; do
            [ -n "$_row" ] && lst IMAGE "$_row"
        done
    fi

    note "面板库只读：1Panel 的 app_installs 表里 name 才是应用 key（app_id 是数字，别当标签）"
}

# ============================== S3 · 网络与信号（含 5G/CPE） ==============================
s3() {
    sec 3 "网络与信号"

    _wan=$(ubus -t 10 call network.interface.wan status 2>/dev/null)
    if [ -n "$_wan" ]; then
        kv wan_up "$(jval "$_wan" up)"
        kv wan_proto "$(jval "$_wan" proto)"
        kv wan_ipv4 "$(jval "$_wan" address)"
    else
        err wan "ubus network.interface.wan status 无输出"
    fi
    _lan=$(ubus -t 10 call network.interface.lan status 2>/dev/null)
    [ -n "$_lan" ] && kv lan_ipv4 "$(jval "$_lan" address)"

    # 逐个接口取状态 —— 本机真正的出口**不一定**是 network.interface.wan。
    # 真机实测：该接口 up=false，但默认路由走 eth3、HTTP 三次全 200、境外 204、5G 已驻网，
    # 上网完全正常。写死接口名会把「能上网」判成「上不了网」→ 必须列出所有接口让 PC 侧综合判。
    _ifaces=$(sed -n "s/^config interface '\(.*\)'/\1/p" /etc/config/network 2>/dev/null)
    for _if in $_ifaces; do
        _st=$(ubus -t 8 call network.interface."$_if" status 2>/dev/null)
        [ -n "$_st" ] || continue
        lst NETIF "$_if|$(jval "$_st" up)|$(jval "$_st" proto)|$(jval "$_st" address)"
    done

    kv defroute4 "$(ip -4 route show default 2>/dev/null | tr '\n' ' ')"
    kv defroute6 "$(ip -6 route show default 2>/dev/null | tr '\n' ' ')"
    kv ip_rule_n "$(num0 "$(ip -4 rule 2>/dev/null | wc -l)")"
    kv clash_pid "$(pidof clash 2>/dev/null)"
    kv openclash_core "$(present /etc/openclash/core/clash_meta)"

    netstat -lnt 2>/dev/null | grep -E ':(7890|7891|7892|7893|7874|9090) ' | awk '{print $4"|"$NF}' | while IFS= read -r _row; do
        [ -n "$_row" ] && lst PROXY_PORT "$_row"
    done
    netstat -lnt 2>/dev/null | grep -E ':(53|5354|7874) ' | awk '{print "tcp|"$4"|"$NF}' | while IFS= read -r _row; do
        [ -n "$_row" ] && lst DNS_LISTEN "$_row"
    done
    netstat -lnup 2>/dev/null | grep -E ':(53|5354|7874) ' | awk '{print "udp|"$4"|"$NF}' | while IFS= read -r _row; do
        [ -n "$_row" ] && lst DNS_LISTEN "$_row"
    done

    kv iwinfo_summary "$(iwinfo 2>/dev/null | head -n 6 | tr '\n' ' ')"

    # 真 HTTP（禁用 ping/TCP 判活：fake-ip + TUN 会本地接管，ping 0% 丢包是假象）
    _i=1
    while [ "$_i" -le 3 ]; do
        kv "http_baidu_$_i" "$(num0 "$(curl -s -o /dev/null -m 8 -w '%{http_code}' http://www.baidu.com 2>/dev/null)")"
        _i=$((_i + 1))
    done
    kv http_gstatic "$(num0 "$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://www.gstatic.com/generate_204 2>/dev/null)")"

    # ---- 5G / CPE（本机走有线 WAN 时通常无数据 → PC 侧按 SKIP）----
    _cpe=""
    _chan=""
    for _c in cpe cpe1; do
        _ct=$(ubus -t 15 call infocd cpestatus '{"name":"'"$_c"'","sync":1}' 2>/dev/null)
        if [ -n "$_ct" ]; then _cpe="$_ct"; _chan="$_c"; break; fi
    done
    kv cpe_channel "$_chan"
    if [ -z "$_cpe" ]; then
        note "CPE/5G 无数据（未插卡 / 未拨号 / 走纯有线出口时均属正常），PC 侧按 SKIP 处理（不是 FAIL）"
    else
        _isp=$(jval "$_cpe" isp_company)
        [ -n "$_isp" ] || _isp=$(jval "$_cpe" isp)
        kv cpe_isp "$_isp"
        kv cpe_mode "$(jval "$_cpe" mode)"
        kv cpe_rsrp "$(jval "$_cpe" rsrp)"
        kv cpe_sinr "$(jval "$_cpe" sinr)"
        kv cpe_rsrq "$(jval "$_cpe" rsrq)"
        _band=$(jval "$_cpe" band)
        [ -n "$_band" ] || _band=$(jval "$_cpe" currentband)
        kv cpe_band "$_band"
        kv cpe_pci "$(jval "$_cpe" pci)"
        kv cpe_earfcn "$(jval "$_cpe" earfcn)"
        kv cpe_cell "$(jval "$_cpe" cell)"
        _tac=$(jval "$_cpe" tac)
        [ -n "$_tac" ] || _tac=$(jval "$_cpe" lac)
        kv cpe_tac "$_tac"
        kv cpe_model "$(jval "$_cpe" model)"
        kv cpe_revision "$(jval "$_cpe" revision)"
        kv cpe_model_temp "$(jval "$_cpe" model_temp)"
        # 身份字段一律只出末 4 位（公开仓红线）
        kv cpe_imsi_tail  "$(mask4 "$(jval "$_cpe" imsi)")"
        kv cpe_iccid_tail "$(mask4 "$(jval "$_cpe" iccid)")"
        kv cpe_imei_tail  "$(mask4 "$(jval "$_cpe" imei)")"
    fi
    _rt=$(ubus -t 10 call infocd runtime 2>/dev/null)
    if [ -n "$_rt" ]; then
        kv dev_temp "$(jval "$_rt" device_temp)"
        kv wifi_temp "$(jval "$_rt" wifi_temp)"
        kv cpu_percent "$(jval "$_rt" cpu_percent)"
        kv mem_percent "$(jval "$_rt" mem_percent)"
    fi
    kv cpe_uart_n "$(num0 "$(ls /dev/ttyUSB* 2>/dev/null | wc -l)")"
    kv cpe_sim_cur "$(uci -q get cpesel.sim.cur 2>/dev/null)"
    kv sim_name_map_n "$(num0 "$(grep -c . /etc/nradio-sim-name.map 2>/dev/null)")"
    note "未发任何 AT 指令（发 AT 会打扰 5G 模块）；如需 AT 探测请人工执行"
}

# ============================== S4 · 服务与补丁状态 ==============================
s4() {
    sec 4 "服务与补丁状态"

    # ⚠️ cron 的服务名是 `cron`、进程名才是 `crond`（本机没有 /etc/init.d/crond）。
    #    直接 svc_en crond 会得到 no → 把健康机器误报成「未 enable」，真机实测踩过。
    for _svc in dropbear uhttpd dnsmasq cron odhcpd rpcd; do
        _proc=$_svc
        [ "$_svc" = "cron" ] && _proc="crond"
        lst SVC_CORE "$_svc|$(alive "$_proc")|$(svc_en "$_svc")"
    done

    for _f in /etc/init.d/*; do
        [ -x "$_f" ] || continue
        if "$_f" enabled 2>/dev/null; then lst SVC_ENABLED "${_f##*/}"; fi
    done

    # 应用商店补丁 marker（三个主 marker + 两个辅助）
    _lua=/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
    [ -f "$_lua" ] || _lua=$(find1 /usr/lib/lua/luci/controller appcenter.lua)
    if [ -n "$_lua" ] && [ -f "$_lua" ]; then
        kv patch_lua_path "$_lua"
        kv patch_lua_bytes "$(fbytes "$_lua")"
        kv patch_extra_action "$(num0 "$(grep -c 'nradio_appcenter_extra_action' "$_lua" 2>/dev/null)")"
        kv patch_registry "$(num0 "$(grep -c '_kp_installed_registry' "$_lua" 2>/dev/null)")"
        kv patch_extra_merge "$(num0 "$(grep -c 'nradio_appcenter_extra_installed_merge' "$_lua" 2>/dev/null)")"
        kv patch_install_percent "$(num0 "$(grep -c '_online_install_percent' "$_lua" 2>/dev/null)")"
    else
        err patch_lua "appcenter.lua 未找到"
    fi
    _htm=/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm
    [ -f "$_htm" ] || _htm=$(find1 /usr/lib/lua/luci/view/nradio_appcenter appcenter.htm)
    if [ -n "$_htm" ] && [ -f "$_htm" ]; then
        kv patch_htm_path "$_htm"
        kv patch_htm_bytes "$(fbytes "$_htm")"
        kv patch_aurora_open_app "$(num0 "$(grep -c 'aurora_open_app' "$_htm" 2>/dev/null)")"
    else
        err patch_htm "appcenter.htm 未找到"
    fi

    # opkg 源
    _dfc=/etc/opkg/distfeeds.conf
    if [ -f "$_dfc" ]; then
        kv opkg_lines "$(num0 "$(wc -l < "$_dfc" 2>/dev/null)")"
        kv opkg_snapshot_n "$(num0 "$(grep -c '21.02-SNAPSHOT' "$_dfc" 2>/dev/null)")"
        kv opkg_aliyun_n "$(num0 "$(grep -c 'mirrors.aliyun.com/openwrt/releases/21.02.7' "$_dfc" 2>/dev/null)")"
    else
        err opkg "distfeeds.conf 不存在"
    fi

    # cron / 自启
    _cron=$(crontab -l 2>/dev/null)
    kv cron_lines "$(num0 "$(printf '%s\n' "$_cron" | grep -c .)")"
    kv cron_ocspeed "$(num0 "$(printf '%s\n' "$_cron" | grep -c '#ocspeed-auto')")"
    kv cron_ocspeed_failover "$(num0 "$(printf '%s\n' "$_cron" | grep -c '#ocspeed-failover')")"
    kv rc_local_file "$(present /etc/rc.local)"
    kv rc_local_initd "$(present /etc/init.d/rc.local)"
    kv s95done "$(present /etc/rc.d/S95done)"
    kv rc_local_tail "$(tail -n 20 /etc/rc.local 2>/dev/null | tr '\n' ' ')"

    # 应用商店自身
    kv store_uci "$(present /etc/config/appcenter)"
    kv store_pkg_n "$(num0 "$(awk '/^config package/{n++} END{print n+0}' /etc/config/appcenter 2>/dev/null)")"
    kv kp_store_dir "$(present /etc/kp_store)"
    kv kp_store_files "$(ls -1 /etc/kp_store 2>/dev/null | tr '\n' ',')"
    note "/etc/kp_store 分类：patch-baseline.json（本机基线快照）与 routes.list 属本机正常；installed.list / plugins.json 是 A 机遗留（PC 侧按此单独标注，勿当缺陷）"

    kv maye_state_dir "$(present /root/.nradio-plugin-menu)"
}

# ============================== S5 · 装载余量与可装性对照 ==============================
s5() {
    sec 5 "装载余量与可装性对照"

    kv overlay_avail_kb "$(num0 "$(df -P /overlay 2>/dev/null | tail -n 1 | awk '{print $4}')")"
    kv data_avail_kb "$(num0 "$(df -P /mnt/storage/data 2>/dev/null | tail -n 1 | awk '{print $4}')")"
    kv tmp_avail_kb "$(num0 "$(df -P /tmp 2>/dev/null | tail -n 1 | awk '{print $4}')")"
    kv overlay_dev_used "$(awk '$2=="/overlay"{print $1}' /proc/mounts 2>/dev/null)"

    if [ ! -f /etc/config/appcenter ]; then
        err store_apps "/etc/config/appcenter 不存在，无法做可装性对照"
        return
    fi

    # /etc/config/appcenter 是标准 UCI：config package 块内 option name / option size（字节）
    _apps=$(awk '
      /^config package/ { if (n != "") print n "|" s "|" p; n=""; s=""; p="" }
      /option name /    { v=$3; gsub(/'"'"'/, "", v); n=v }
      /option size /    { v=$3; gsub(/'"'"'/, "", v); s=v }
      /option pkg /     { v=$3; gsub(/'"'"'/, "", v); p=v }
      /option file /    { v=$3; gsub(/'"'"'/, "", v); p=v }
      END { if (n != "") print n "|" s "|" p }
    ' /etc/config/appcenter 2>/dev/null)

    if [ -z "$_apps" ]; then
        err store_apps "未能从 /etc/config/appcenter 解析出 config package 条目"
    else
        printf '%s\n' "$_apps" | while IFS= read -r _row; do
            _anm=${_row%%|*}
            [ -n "$_anm" ] || continue
            _apk=$(printf '%s' "$_row" | awk -F'|' '{print $3}')
            _ains=no
            if [ -n "$_apk" ] && grep -q "^Package: $_apk\$" /usr/lib/opkg/status 2>/dev/null; then
                _ains=yes
            fi
            lst STORE_APP "$_row|$_ains"
        done
    fi
    note "可装性由 PC 侧按「overlay 剩余 ÷ 应用 size」判定（复刻商店原生 check_size 的口径）"
}

# ============================== 主流程 ==============================
printf 'V\tkp-selftest\t%s\n' "$KP_VERSION"

if [ "$(id -u 2>/dev/null)" != "0" ]; then
    err precheck "必须以 root 运行（当前 uid=$(id -u 2>/dev/null)）"
    printf 'Z\tEND\n'
    exit 2
fi

# 降级开关：dockerd 半死时 docker CLI 会挂住 4~9 秒甚至更久，
# 由调用方（PC 侧 --skip-docker）置 KP_SKIP_DOCKER=1 跳过第 2 板块。
[ "${KP_SKIP_DOCKER:-0}" = "1" ] && note "KP_SKIP_DOCKER=1 → 容器板块（第 2 节）被调用方要求跳过"

s1
[ "${KP_SKIP_DOCKER:-0}" = "1" ] || s2
s3
s4
s5

printf 'Z\tEND\n'
exit 0
