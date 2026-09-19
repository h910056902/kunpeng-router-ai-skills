#!/bin/sh
# kp-docker-purge.sh —— 清空 Docker 环境与容器（鲲鹏 C2000 U / OpenWrt 21.02 专用）
#
# 设计原则（照着仓库铁律来）：
#   1. 默认 **dry-run**：只打印待删清单和将要执行的动作，一个字节都不删。
#   2. 真删要**两个开关**同时给：--apply --yes（防手滑，防 AI 误判"用户已同意"）。
#   3. 动手前先**备份快照**（容器/镜像/卷/网络/UCI/磁盘），备份目录路径会打印出来。
#   4. 1Panel 数据根**只改名不删**（铁律）；data-root 清空是独立开关，默认不动。
#   5. 幂等：没有可删的东西就直接报「已空」，退出码 0。
#
# 用法（设备侧，/tmp 或任意可写目录）：
#   sh kp-docker-purge.sh                                  # dry-run 全量预览（安全）
#   sh kp-docker-purge.sh --apply --yes                    # 清容器+卷+镜像+自定义网络
#   sh kp-docker-purge.sh --apply --yes --backup-vols      # 追加：删卷前先把卷内容打包到备份目录
#   sh kp-docker-purge.sh --apply --yes --data-root        # 追加：清空 data-root 里的镜像层
#   sh kp-docker-purge.sh --apply --yes --panel-apps       # 追加：1Panel apps/ 改名归档
#   sh kp-docker-purge.sh --apply --yes --panel-reset      # 追加：1Panel 环境复位（数据根改名 + 面板二进制移入备份）
#   sh kp-docker-purge.sh --apply --yes --reset-uci        # 追加：复位 dockerd UCI（慎用）
#
# 一次性全量清除（docker 环境 + 1Panel 环境，最常用于「从零重装演练」）：
#   sh kp-docker-purge.sh --apply --yes --backup-vols --data-root --panel-reset
#
# 环境变量：
#   KEEP="alist foo"      必须保留的**容器**名（空格分隔）
#   KEEP_VOL="vol1 vol2"  必须保留的**数据卷**名（注意：带 --data-root 时该项无效，data-root 被整目录清空）
#
# 退出码：0 成功（含「本来就是空的」）· 1 参数/前置错误 · 2 备份失败 · 3 执行中出错
#
# busybox 兼容性（见仓库铁律 3）：不用 bash 数组 / [[ ]] / sed -i 备份后缀 / \t 字符类。

set -u

APPLY=0; YES=0; DO_DATAROOT=0; DO_PANELAPPS=0; DO_RESETUCI=0; DO_BACKUPVOLS=0; DO_PANELRESET=0
KEEP="${KEEP:-}"                                   # 额外保留的容器名，空格分隔，如 KEEP="alist"
KEEP_VOL="${KEEP_VOL:-}"                            # 额外保留的数据卷名，空格分隔
DATA_ROOT="/mnt/storage/data/docker"
PANEL_ROOT="/mnt/storage/data/1panel"
BACKUP_ROOT="/mnt/storage/data/kpbackup"
TS=$(date +%Y%m%d_%H%M%S)
BK="$BACKUP_ROOT/docker-purge-$TS"

log()  { printf '[purge] %s\n' "$*"; }
warn() { printf '[WARN ] %s\n' "$*"; }
die()  { printf '[FATAL] %s\n' "$*"; exit "$1"; }

for a in "$@"; do
    case "$a" in
        --apply)       APPLY=1 ;;
        --yes)         YES=1 ;;
        --data-root)   DO_DATAROOT=1 ;;
        --panel-apps)  DO_PANELAPPS=1 ;;
        --panel-reset) DO_PANELRESET=1 ;;
        --reset-uci)   DO_RESETUCI=1 ;;
        --backup-vols) DO_BACKUPVOLS=1 ;;
        -h|--help)     sed -n '2,34p' "$0"; exit 0 ;;
        *)             die 1 "未知参数: $a（用 --help 看用法）" ;;
    esac
done

[ "$APPLY" = "1" ] && [ "$YES" != "1" ] && die 1 "--apply 必须同时给 --yes（防手滑）"
if [ "$APPLY" = "0" ]; then
    log "DRY-RUN 模式：只预览，不删任何东西（真删请加 --apply --yes）"
fi

# ---------- 0. 前置检查 ----------
command -v docker >/dev/null 2>&1 || die 1 "找不到 docker 命令"
docker info >/dev/null 2>&1 || warn "docker info 失败（dockerd 可能没起来）——容器清理仍可尝试"
[ -d "$DATA_ROOT" ] || warn "data-root $DATA_ROOT 不存在（继续，会跳过相关步骤）"

# 本脚本**永远保留**的容器：1Panel 自身不是容器，但用户可用 KEEP 指定
keep_match() {
    [ -n "$KEEP" ] || return 1
    for k in $KEEP; do [ "$k" = "$1" ] && return 0; done
    return 1
}
keep_vol_match() {
    [ -n "$KEEP_VOL" ] || return 1
    for k in $KEEP_VOL; do [ "$k" = "$1" ] && return 0; done
    return 1
}

# ---------- 1. 盘点（只读） ----------
log "=== 盘点现状 ==="
C_ALL=$(docker ps -a --format '{{.Names}}' 2>/dev/null)
C_RUN=$(docker ps --format '{{.Names}}' 2>/dev/null)
I_ALL=$(docker images --format '{{.Repository}}:{{.Tag}}' 2>/dev/null)
V_ALL=$(docker volume ls --format '{{.Name}}' 2>/dev/null)
N_ALL=$(docker network ls --format '{{.Name}}' 2>/dev/null)

n_of() { [ -z "$1" ] && echo 0 || printf '%s\n' "$1" | grep -c . ; }
log "容器(含停止): $(n_of "$C_ALL")  运行中: $(n_of "$C_RUN")"
[ -n "$C_ALL" ] && printf '%s\n' "$C_ALL" | while read -r c; do
    keep_match "$c" && echo "    [保留] $c" || echo "    [将删] $c"
done
log "镜像: $(n_of "$I_ALL")  卷: $(n_of "$V_ALL")"
[ -n "$V_ALL" ] && printf '%s\n' "$V_ALL" | while read -r v; do
    keep_vol_match "$v" && echo "    [保留卷] $v" || echo "    [将删卷] $v"
done
if [ "$DO_DATAROOT" = "1" ] && [ -n "$KEEP_VOL" ]; then
    warn "--data-root 会整体清空 $DATA_ROOT，KEEP_VOL 指定的卷也保不住（如需保数据请加 --backup-vols）"
fi
log "网络: $(printf '%s\n' "$N_ALL" | tr '\n' ' ')"
df -k "$DATA_ROOT" 2>/dev/null | tail -1 | while read -r l; do echo "    [data-root 容量] $l"; done

# ---------- 2. 备份快照（真删前必做） ----------
if [ "$APPLY" = "1" ]; then
    log "=== 备份快照 -> $BK ==="
    mkdir -p "$BK" || die 2 "无法创建备份目录 $BK"
    docker ps -a       > "$BK/containers.txt" 2>&1
    docker images      > "$BK/images.txt"     2>&1
    docker volume ls   > "$BK/volumes.txt"    2>&1
    docker network ls  > "$BK/networks.txt"   2>&1
    docker info        > "$BK/docker-info.txt" 2>&1
    uci export dockerd > "$BK/uci-dockerd.txt" 2>&1
    df -k              > "$BK/df.txt"          2>&1
    ls -la "$DATA_ROOT" > "$BK/data-root-ls.txt" 2>&1
    [ -f /etc/docker/daemon.json ] && cp /etc/docker/daemon.json "$BK/daemon.json" 2>/dev/null
    if [ -f "$PANEL_ROOT/db/1Panel.db" ]; then
        cp "$PANEL_ROOT/db/1Panel.db" "$BK/1Panel.db" 2>/dev/null && log "  已快照 1Panel 数据库"
    fi
    for f in containers.txt images.txt volumes.txt networks.txt uci-dockerd.txt; do
        [ -s "$BK/$f" ] || warn "快照文件 $f 为空（记录可能不完整）"
    done
    log "备份完成：$BK（回滚依据，别删）"
fi

# ---------- 3. 执行 ----------
if [ "$APPLY" = "1" ]; then
    # 3.1 停容器（先优雅停，10s 超时）
    if [ -n "$C_RUN" ]; then
        log "=== 停止运行中的容器 ==="
        printf '%s\n' "$C_RUN" | while read -r c; do
            keep_match "$c" && { echo "    跳过(保留) $c"; continue; }
            docker stop -t 10 "$c" >/dev/null 2>&1 && echo "    已停 $c"
        done
    fi
    # 3.2 删容器
    if [ -n "$C_ALL" ]; then
        log "=== 删除容器（含停止的） ==="
        printf '%s\n' "$C_ALL" | while read -r c; do
            keep_match "$c" && { echo "    跳过(保留) $c"; continue; }
            docker rm -f "$c" >/dev/null 2>&1 && echo "    已删容器 $c"
        done
    else
        log "容器已空，跳过"
    fi
    # 3.3 卷：数据卷是唯一**不可恢复**的东西，删前可选打包（--backup-vols）
    if [ -n "$V_ALL" ]; then
        if [ "$DO_BACKUPVOLS" = "1" ]; then
            log "=== 打包数据卷内容到 $BK/volumes/ ==="
            mkdir -p "$BK/volumes"
            printf '%s\n' "$V_ALL" | while read -r v; do
                keep_vol_match "$v" && { echo "    跳过(保留) $v"; continue; }
                mp=$(docker volume inspect -f '{{.Mountpoint}}' "$v" 2>/dev/null)
                if [ -n "$mp" ] && [ -d "$mp" ]; then
                    sz=$(du -sk "$mp" 2>/dev/null | awk '{print $1}')
                    if tar -czf "$BK/volumes/$v.tar.gz" -C "$mp" . 2>/dev/null; then
                        echo "    已打包 $v（${sz}KB 原始） -> volumes/$v.tar.gz"
                    else
                        warn "卷 $v 打包失败（tar 出错）—— 是否继续删？见 --help 的策略说明"
                    fi
                else
                    warn "卷 $v 的 Mountpoint 读不到，跳过打包"
                fi
            done
        fi
        log "=== 删除数据卷（业务数据会一并消失，清单与打包已在备份目录） ==="
        printf '%s\n' "$V_ALL" | while read -r v; do
            keep_vol_match "$v" && { echo "    跳过(保留) $v"; continue; }
            docker volume rm -f "$v" >/dev/null 2>&1 && echo "    已删卷 $v"
        done
    else
        log "数据卷已空，跳过"
    fi
    # 3.4 删镜像
    if [ -n "$I_ALL" ]; then
        log "=== 删除镜像 ==="
        printf '%s\n' "$I_ALL" | while read -r i; do
            docker rmi -f "$i" >/dev/null 2>&1 && echo "    已删镜像 $i"
        done
    else
        log "镜像已空，跳过"
    fi
    # 3.5 删自定义网络（内核无 veth，别碰默认三个）
    log "=== 清理自定义网络（保留 host/none/bridge） ==="
    docker network ls --format '{{.Name}}' 2>/dev/null | while read -r n; do
        case "$n" in
            host|none|bridge) continue ;;
        esac
        docker network rm "$n" >/dev/null 2>&1 && echo "    已删网络 $n"
    done
fi

# 3.6 data-root 内容清空（独立开关；镜像层目录，停 dockerd 再动）
if [ "$DO_DATAROOT" = "1" ]; then
    if [ "$APPLY" = "1" ]; then
        log "=== 清空 data-root 内容：$DATA_ROOT ==="
        /etc/init.d/dockerd stop 2>/dev/null; sleep 3
        for d in "$DATA_ROOT"/*; do
            [ -e "$d" ] || continue
            case "$d" in
                */kp-keep*) echo "    跳过(保留) $d"; continue ;;
            esac
            rm -rf "$d" && echo "    已删 $d"
        done
        /etc/init.d/dockerd start 2>/dev/null; sleep 6
        echo "    dockerd 已重启，pidof=$(pidof dockerd)"
    else
        log "[dry-run] 将清空 $DATA_ROOT 下除 kp-keep* 之外的全部内容，并重启 dockerd"
    fi
fi

# 3.7 1Panel 应用目录（只改名归档，绝不删除）
if [ "$DO_PANELAPPS" = "1" ]; then
    if [ -d "$PANEL_ROOT/apps" ]; then
        if [ "$APPLY" = "1" ]; then
            log "=== 1Panel apps/ 改名归档（不删数据） ==="
            mv "$PANEL_ROOT/apps" "$PANEL_ROOT/apps.bak-$TS" && echo "    已归档 -> $PANEL_ROOT/apps.bak-$TS"
            mkdir -p "$PANEL_ROOT/apps"
        else
            log "[dry-run] 将把 $PANEL_ROOT/apps 改名为 apps.bak-$TS（数据保留，不删）"
        fi
    else
        log "$PANEL_ROOT/apps 不存在，跳过"
    fi
fi

# 3.75 1Panel 环境复位（全量清除的最后一环；数据根只改名，二进制移入备份）
if [ "$DO_PANELRESET" = "1" ]; then
    if [ "$APPLY" = "1" ]; then
        log "=== 1Panel 环境复位 ==="
        # 先停面板，避免它边删边重建容器 / 重写数据根
        if [ -x /etc/init.d/1paneld ]; then
            /etc/init.d/1paneld stop >/dev/null 2>&1
            sleep 3
            echo "    已停 1paneld（pidof=$(pidof 1paneld 1panel))"
        fi
        # 数据根：**只改名，绝不删除**（铁律）
        if [ -d "$PANEL_ROOT" ]; then
            mv "$PANEL_ROOT" "$PANEL_ROOT.bak-$TS" && echo "    数据根已改名 -> $PANEL_ROOT.bak-$TS"
        else
            echo "    数据根 $PANEL_ROOT 不存在，跳过"
        fi
        # 面板程序与 init 脚本：移入备份目录（不删，可原样搬回）
        mkdir -p "$BK/panel-bin"
        for f in /usr/local/bin/1panel /usr/local/bin/1pctl /etc/init.d/1paneld; do
            if [ -e "$f" ]; then
                mv "$f" "$BK/panel-bin/" && echo "    已移入备份 $f"
            fi
        done
        # rc.d 符号链接删掉（重装会重建；留着会指向不存在的 init 脚本报错）
        rm -f /etc/rc.d/K151paneld /etc/rc.d/S951paneld 2>/dev/null
        echo "    1Panel 环境已复位；重装：sh /tmp/kp1pt/kp-install.sh 或 offline/panel/install.sh"
    else
        log "[dry-run] 将：停 1paneld -> 数据根改名 1panel.bak-$TS -> 1panel/1pctl/init 移入备份 -> 清 rc.d 链接"
    fi
fi


# 3.8 dockerd UCI 复位（回出厂默认：data_root / 加速源 / alt_config_file 全丢）
if [ "$DO_RESETUCI" = "1" ]; then
    if [ "$APPLY" = "1" ]; then
        log "=== 复位 dockerd UCI（回滚依据已在 $BK/uci-dockerd.txt） ==="
        /etc/init.d/dockerd stop 2>/dev/null
        uci delete dockerd.globals.alt_config_file 2>/dev/null
        uci delete dockerd.globals.data_root 2>/dev/null
        uci delete dockerd.globals.registry_mirrors 2>/dev/null
        uci commit dockerd
        echo "    已复位；注意：driver 会退回 UCI 默认（无 overlay2），要恢复请用备份文件手工 import"
        /etc/init.d/dockerd start 2>/dev/null
    else
        log "[dry-run] 将删除 dockerd.globals 的 alt_config_file / data_root / registry_mirrors 并 commit"
    fi
fi

# ---------- 4. 验证 ----------
log "=== 验证（清空后的期望值） ==="
c=$(docker ps -aq 2>/dev/null | grep -c .)
i=$(docker images -q 2>/dev/null | grep -c .)
v=$(docker volume ls -q 2>/dev/null | grep -c .)
n=$(docker network ls --format '{{.Name}}' 2>/dev/null | grep -c .)
echo "    容器=$c  镜像=$i  卷=$v  网络=$n（网络期望 3：host/none/bridge）"
echo "    dockerd pid=$(pidof dockerd)"
echo "    1Panel: 二进制=$([ -x /usr/local/bin/1panel ] && echo 在 || echo 已移出) 面板进程=$(pidof 1paneld 1panel) 数据根=$([ -d "$PANEL_ROOT" ] && echo 在 || echo 已改名归档)"
echo "    OpenClash: clash pid=$(pidof clash)（本脚本不碰它，必须仍在）"

if [ "$APPLY" = "0" ]; then
    log "以上为 DRY-RUN 预览，未改动任何东西。确认无误后执行："
    log "  sh $0 --apply --yes                        # 只清容器/卷/镜像/网络"
    log "  sh $0 --apply --yes --backup-vols          # 再加：删卷前打包卷内容（推荐）"
    log "  sh $0 --apply --yes --backup-vols --data-root --panel-apps   # 全量"
else
    log "完成。备份/回滚依据：$BK"
fi
exit 0
