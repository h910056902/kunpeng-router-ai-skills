#!/bin/sh
# kp-clean.sh —— 鲲鹏路由器「写盘足迹」只读审计器（v1.0.1）
#
# 定位：本项目要求「清除逻辑全部自写」，而自写的前提是**先精确知道盘上有什么**。
# 本脚本只做一件事：把设备上「与插件有关的对象」逐条查出来，**绝不改动任何东西**。
#
# 用法（busybox ash 兼容）：
#   sh kp-clean.sh --help              看用法
#   sh kp-clean.sh --list              自发现：把本机可审计对象列出来（设备 → 足迹 方向）
#   sh kp-clean.sh --audit CASES.tsv   按用例文件逐条审计（足迹 → 设备 方向）
#
# 用例文件格式（制表符分隔，PC 侧从 tasks/footprint.json 生成）：
#   KIND<TAB>VALUE<TAB>FEATURE
#   例：path<TAB>/etc/openclash<TAB>2
#
# 输出格式（制表符分隔，便于 PC 侧解析）：
#   R<TAB>KIND<TAB>VALUE<TAB>STATE<TAB>EXTRA
#   STATE ∈ present|absent|running|stopped|enabled|disabled|unknown
#
# 硬约束：
#   · 全程只读；不写文件、不改 uci、不启停服务
#   · 不做任何网络访问
#   · 任何单条失败都不能中断整体（unknown 也要有输出）

KP_VERSION="1.0.1"

# 已知 marker 字面量（上游补丁的「指纹」）
KP_MARKERS="Design By MaYe nradio_appcenter_extra_action EASYTIER_ROUTE_WIZARD OPENVPN_ROUTE_WIZARD _kp_installed_registry aurora_open_app"
# marker 可能在的文件（只读扫描）
KP_MARKER_FILES="/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm /etc/rc.local /etc/crontabs/root"
# 自发现时扫描的目录
# 补过一轮：首跑只扫了 /etc/openclash，漏了 **/etc/openclash-helper**（ocspeed 的持久数据目录：
# nodes.json / status.json / sites.json / history.log / last_run），反向对账因此看不见它。
# 这是「用 `[ -nt ]` 找比 marker 新的文件」时才暴露出来的 —— 见 _residue_probe 记录。
KP_SCAN_DIRS="/etc/openclash /etc/openclash-helper /etc/openlist /etc/docker /etc/mosdns /etc/ddnsgo /etc/adguardhome /etc/qy /etc/qyplug /etc/acc /etc/kp_store /opt /usr/libexec /usr/lib/lua/luci/controller /usr/lib/lua/luci/controller/nradio_adv /usr/lib/lua/luci/model/cbi /usr/lib/lua/luci/view/nradio_adv /usr/lib/lua/luci/view/openclash /www/luci-static/nradio"

usage() {
    cat <<'EOF'
kp-clean.sh —— 写盘足迹只读审计器

  --help              显示本帮助
  --version           显示版本
  --list              自发现本机可审计对象（设备 → 足迹）
  --audit <文件>      按用例文件逐条审计（足迹 → 设备）
  --audit -           从 stdin 读用例

只读；不写盘、不改配置、不启停服务。
EOF
}

emit() {
    # kind value state extra
    printf 'R\t%s\t%s\t%s\t%s\n' "$1" "$2" "$3" "$4"
}

# 固件自带判定：OpenWrt 的 /rom 是只读的出厂根，/rom<path> 存在 = 出厂就有。
# 这是**不需要重刷机就能拿到的「原始基线」** —— 反向对账全靠它把固件预装排除掉。
rom_has() {
    [ -e "/rom$1" ] && echo yes || echo no
}

# ---------------------------------------------------------------- 单条审计
audit_one() {
    kind="$1"
    val="$2"
    feat="$3"

    case "$kind" in
    path)
        if [ -e "$val" ]; then
            rom=$(rom_has "$val")
            if [ -d "$val" ]; then
                n=$(ls -1 "$val" 2>/dev/null | wc -l)
                emit "$kind" "$val" present "dir:${n}项 rom=$rom"
            elif [ -L "$val" ]; then
                emit "$kind" "$val" present "symlink rom=$rom"
            else
                sz=$(wc -c <"$val" 2>/dev/null || echo '?')
                emit "$kind" "$val" present "file:${sz}B rom=$rom"
            fi
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    service)
        if [ -x "/etc/init.d/$val" ]; then
            # rom 标志**必须发**。首跑漏了它，结果 uhttpd / dnsmasq / firewall /
            # odhcpd / mtkhnat / cpesel / dropbear 这些固件自带服务全被判成
            # 「固件里没有 + 仅被独有认领」→ 涌进「① 该清」桶（40 条里占 6 条），
            # 连 firewall 都差点成了卸载目标。缺 rom 时 PC 侧无法区分固件与后加。
            rom=$(rom_has "/etc/init.d/$val")
            if /etc/init.d/"$val" enabled >/dev/null 2>&1; then
                en="enabled"
            else
                en="disabled"
            fi
            if pidof "$val" >/dev/null 2>&1; then
                st="running"
            else
                st="stopped"
            fi
            emit "$kind" "$val" "$st" "$en rom=$rom"
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    rcdir)
        # 值形如 S99qy_acc.boot / S95dockerd
        hits=""
        nhits=0
        romhits=0
        for p in /etc/rc.d/S* /etc/rc.d/K*; do
            [ -e "$p" ] || continue
            case "$(basename "$p")" in
            *"$val"*)
                hits="$hits $(basename "$p")"
                nhits=$((nhits + 1))
                [ -e "/rom$p" ] && romhits=$((romhits + 1))
                ;;
            esac
        done
        if [ -n "$hits" ]; then
            # 全部命中都在 /rom 里才算「出厂自带」；只要有一条是后加的，就按「非固件」处理
            if [ "$nhits" -gt 0 ] && [ "$romhits" -eq "$nhits" ]; then
                r=yes
            else
                r=no
            fi
            emit "$kind" "$val" present "rc.d:$hits rom=$r"
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    uci)
        # 值是配置键或 section，如 openclash.config.enable_meta_sniffer
        #
        # 也带 rom 标志，取「该键所属的配置文件」是否出厂就有：
        #   dhcp / firewall / luci / mtkhnat / fanctrl → 固件已有 → 该键只能**重置**
        #   dockerd / openclash / ocspeed            → 后来才有 → 才可能整段删掉
        # 语义上这是对的：/etc/config/dhcp 永远不能删文件，只能把键改回去。
        cfg=$(printf '%s' "$val" | sed 's/^@//; s/[.@].*$//')
        rom=$(rom_has "/etc/config/$cfg")
        if uci -q get "$val" >/dev/null 2>&1; then
            v=$(uci -q get "$val" 2>/dev/null | head -c 40)
            emit "$kind" "$val" present "$v rom=$rom"
        else
            # 也可能是 section 存在但属性不同，退回 show
            if uci -q show "$val" 2>/dev/null | grep -q "^$val"; then
                emit "$kind" "$val" present "section rom=$rom"
            else
                emit "$kind" "$val" absent "-"
            fi
        fi
        ;;

    pkg)
        if opkg list-installed 2>/dev/null | awk -v p="$val" '$1==p{found=1} END{exit !found}'; then
            v=$(opkg list-installed 2>/dev/null | awk -v p="$val" '$1==p{print $3; exit}')
            emit "$kind" "$val" present "ver:$v"
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    marker)
        where=""
        for f in $KP_MARKER_FILES; do
            [ -f "$f" ] || continue
            if grep -qF -- "$val" "$f" 2>/dev/null; then
                n=$(grep -cF -- "$val" "$f" 2>/dev/null)
                where="$where $(basename "$f"):$n"
            fi
        done
        f2="/root/.nradio-plugin-menu"
        if [ -d "$f2" ]; then
            if grep -rqF -- "$val" "$f2" 2>/dev/null; then
                where="$where .nradio-plugin-menu"
            fi
        fi
        if [ -n "$where" ]; then
            emit "$kind" "$val" present "hit:$where"
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    cron)
        if crontab -l 2>/dev/null | grep -qF -- "$val"; then
            n=$(crontab -l 2>/dev/null | grep -cF -- "$val")
            emit "$kind" "$val" present "条目:${n}"
        else
            emit "$kind" "$val" absent "-"
        fi
        ;;

    net)
        # 值形如 rule / route / nat / offload
        case "$val" in
        rule)
            n=$(ip rule show 2>/dev/null | wc -l)
            emit "$kind" "$val" present "规则数:${n}"
            ;;
        offload)
            o1=$(uci -q get firewall.@defaults[0].flow_offloading 2>/dev/null)
            o2=$(uci -q get firewall.@defaults[0].flow_offloading_hw 2>/dev/null)
            emit "$kind" "$val" present "sw=${o1:-?} hw=${o2:-?}"
            ;;
        *)
            n=$(iptables -S 2>/dev/null | grep -cF -- "$val")
            if [ "$n" -gt 0 ] 2>/dev/null; then
                emit "$kind" "$val" present "命中:${n}"
            else
                emit "$kind" "$val" absent "-"
            fi
            ;;
        esac
        ;;

    store)
        # 值形如 appcenter 段名 / routes.list
        if echo "$val" | grep -q '/'; then
            if [ -e "/etc/kp_store/$val" ]; then
                emit "$kind" "$val" present "file"
            else
                emit "$kind" "$val" absent "-"
            fi
        else
            if uci -q show "appcenter.$val" 2>/dev/null | grep -q "^appcenter\.$val"; then
                emit "$kind" "$val" present "uci段"
            elif uci -q show appcenter 2>/dev/null | grep -q "\.name='$val'"; then
                emit "$kind" "$val" present "uci段(name)"
            else
                emit "$kind" "$val" absent "-"
            fi
        fi
        ;;

    *)
        emit "$kind" "$val" unknown "未知类别"
        ;;
    esac
}

# ---------------------------------------------------------------- 自发现
do_list() {
    printf 'L\theader\t%s\n' "kp-clean.sh $KP_VERSION 只读自发现"
    printf 'L\tinfo\tuname\t%s\n' "$(uname -s)"
    printf 'L\tinfo\trelease\t%s\n' "$(sed -n "s/.*DISTRIB_REVISION='\([^']*\)'.*/\1/p" /etc/openwrt_release 2>/dev/null)"
    printf 'L\tinfo\tmodel\t%s\n' "$(sed -n "s/.*DISTRIB_DESCRIPTION='\([^']*\)'.*/\1/p" /etc/openwrt_release 2>/dev/null)"
    printf 'L\tinfo\trom_available\t%s\n' "$([ -d /rom ] && echo yes || echo no)"

    # 服务（带固件标志：rom=yes 的是出厂就有，不可能是插件引入的）
    for p in /etc/init.d/*; do
        [ -e "$p" ] || continue
        printf 'L\tservice\t%s\trom=%s\n' "$(basename "$p")" "$(rom_has "$p")"
    done

    # rc.d 软链
    for p in /etc/rc.d/*; do
        [ -e "$p" ] || continue
        printf 'L\trcdir\t%s\trom=%s\n' "$(basename "$p")" "$(rom_has "$p")"
    done

    # uci 配置
    for p in /etc/config/*; do
        [ -e "$p" ] || continue
        printf 'L\tuci_config\t%s\trom=%s\n' "$(basename "$p")" "$(rom_has "$p")"
    done

    # 关注目录（存在才列，只列一层；带固件标志）
    for d in $KP_SCAN_DIRS; do
        [ -d "$d" ] || continue
        printf 'L\tscan_dir\t%s\trom=%s\n' "$d" "$(rom_has "$d")"
        for c in "$d"/*; do
            [ -e "$c" ] || continue
            printf 'L\tscan_entry\t%s\trom=%s\n' "$c" "$(rom_has "$c")"
        done
    done

    # cron
    crontab -l 2>/dev/null | while IFS= read -r line; do
        [ -n "$line" ] || continue
        printf 'L\tcron\t%s\n' "$line"
    done

    # 网络规则
    ip rule show 2>/dev/null | while IFS= read -r line; do
        printf 'L\tnetrule\t%s\n' "$line"
    done

    # 已装包（只列「非基础」的可疑项，按前缀过滤，避免 300+ 行）
    opkg list-installed 2>/dev/null | awk '{print $1}' | grep -E '^(luci|kmod|docker|openclash|mosdns|ddns|adguard|openlist|ttyd|zerotier|easytier|openvpn|openbox|mt5700|qy|acc|nradio)' | while IFS= read -r pk; do
        printf 'L\tpkg\t%s\n' "$pk"
    done

    # marker
    for m in $KP_MARKERS; do
        for f in $KP_MARKER_FILES; do
            [ -f "$f" ] || continue
            if grep -qF -- "$m" "$f" 2>/dev/null; then
                printf 'L\tmarker\t%s@%s\n' "$m" "$f"
            fi
        done
    done

    printf 'L\tfooter\t%s\n' "END"
}

# ---------------------------------------------------------------- audit
do_audit() {
    src="$1"
    n=0
    # 注意：不能写 IFS='\t' —— 那是「反斜杠 + 字母 t」两个字符，不是制表符。
    TAB=$(printf '\t')
    if [ "$src" = "-" ]; then
        while IFS="$TAB" read -r k v f; do
            [ -n "$k" ] || continue
            case "$k" in '#'*) continue ;; esac
            audit_one "$k" "$v" "$f"
            n=$((n + 1))
        done
    else
        [ -f "$src" ] || {
            printf 'E\tcases\t文件不存在: %s\n' "$src"
            return 1
        }
        while IFS="$TAB" read -r k v f; do
            [ -n "$k" ] || continue
            case "$k" in '#'*) continue ;; esac
            audit_one "$k" "$v" "$f"
            n=$((n + 1))
        done <"$src"
    fi
    printf 'R\t_summary\taudited\t%d\t条\n' "$n"
}

# ---------------------------------------------------------------- 入口
case "$1" in
--help | -h | "")
    usage
    exit 0
    ;;
--version | -V)
    echo "kp-clean.sh $KP_VERSION"
    exit 0
    ;;
--list)
    do_list
    exit 0
    ;;
--audit)
    if [ -z "$2" ]; then
        echo "用法: sh kp-clean.sh --audit <用例文件|->" >&2
        exit 2
    fi
    do_audit "$2"
    exit 0
    ;;
*)
    echo "未知参数: $1（--help 看用法）" >&2
    exit 2
    ;;
esac
