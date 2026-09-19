#!/bin/sh
# ============================================================================
# kp-compose-host —— 把 docker-compose 文件改写为 host 网络模式（幂等、缩进无关）
#
# 为什么必须有它：鲲鹏 C2000 U（厂商内核 5.4.281）的
#   CONFIG_VETH / MACVLAN / IPVLAN 全部 not set（厂商 kmod-veth 还是空包），
#   docker 桥接网络**物理不可用** —— 任何走 bridge 的 compose 都会停在
#     failed to add the host (veth...) <=> sandbox (veth...) pair interfaces:
#     operation not supported
#   而 1Panel 应用商店的模板一律引用外部 bridge 网络 `1panel-network`，
#   所以「面板装应用」100% 失败。改 daemon.json / UCI 都救不了（内核能力缺失）。
#
# 本脚本做四件事（全部幂等，重复跑结果一致）：
#   1. 删掉每个服务里的 network_mode / networks / ports 段（含其子项）
#   2. 在**每个服务名下**注入 network_mode: host（缩进与服务其它属性对齐）
#   3. 删掉顶层 networks: 段（外部网络声明）
#   4. 服务里出现 redis-server 时，补上 5.4 内核必需的 --ignore-warnings ARM64-COW-BUG
#
# ⚠️ 缩进无关（2026-09-19 真机踩坑后重写）：
#   同一份 1Panel 应用，**商店 tarball 与面板落盘的缩进不一样**：
#     - 商店包 alist/3.64.0/docker-compose.yml : 2 空格（服务名 ind=2，属性 ind=4）
#     - 面板 v1.10 装出来的 docker-compose.yml: 4 空格（服务名 ind=4，属性 ind=8）
#       且多了 deploy.resources.limits、端口带 ${HOST_IP}: 前缀、networks 段排在最前
#   （面板是"解析模板 → 套 formField → 用 Go yaml 重新序列化"，不是照抄 tarball）
#   旧版把「2 空格服务名 / 4 空格属性」写死，结果只删掉列 0 的顶层 networks:，
#   服务里的 networks: 原样保留、network_mode 也没注入，面板装应用直接报：
#     ERROR: Service "alist" uses an undefined network "1panel-network"
#   现在改为**先从文件里量出 svc_ind / prop_ind**，再据此删与注入，任意缩进单位都吃。
#
# 用法：
#   kp-compose-host <file.yml>            # 就地改写（首次会留 <file>.bridge.bak）
#   kp-compose-host --check <file.yml>    # 只判断是否需要改写，不改文件
#   QUIET=1 kp-compose-host <file.yml>    # 静默
#
# 退出码：
#   0  已处理 / 无需处理
#   1  --check 且「已是 host，无需改写」
#   2  参数、文件或转换失败
#
# 注意：本文件也内联/复制于 nros-panel 仓库 tools/ 下，**两份改动必须同步**。
# 兼容：busybox ash + busybox awk（不用花括号展开、不用 $LINENO、不用 trap ERR）
# ============================================================================

QUIET="${QUIET:-0}"
CHECK=0

[ "$1" = "--check" ] && { CHECK=1; shift; }

F="$1"
[ -n "$F" ] || { echo "usage: kp-compose-host [--check] <docker-compose.yml>" >&2; exit 2; }
[ -f "$F" ] || { echo "kp-compose-host: no such file: $F" >&2; exit 2; }

log() { [ "$QUIET" = "1" ] || echo "[kp-compose-host] $*"; }

# ---- ① 量缩进：svc_ind = 服务名缩进，prop_ind = 服务属性缩进 ----
# 判据：进入 `services:` 后，第一条"纯键行"（无值、以冒号结尾）= 服务名；
#       其后第一条缩进更大的行 = 服务属性。
IND=$(awk '
  function ind(s,   m) { match(s, /^[ ]*/); return RLENGTH }
  BEGIN { in_svc = 0; svc = 0; prop = 0 }
  /^[^ ]/ {
    if ($0 ~ /^services:/) { in_svc = 1; next }
    in_svc = 0; next
  }
  in_svc {
    if ($0 ~ /^[ ]*$/) next
    if ($0 ~ /^[ ]*#/) next
    i = ind($0)
    if (svc == 0) {
      if ($0 ~ /^[ ]*[^ #][^ :]*:[[:space:]]*$/) { svc = i }
    } else if (i > svc && prop == 0) {
      prop = i
    }
  }
  END { printf "%d %d\n", svc + 0, prop + 0 }
' "$F" 2>/dev/null)

SVC_IND=$(echo "$IND" | awk '{print $1}')
PROP_IND=$(echo "$IND" | awk '{print $2}')
case "$SVC_IND" in ''|*[!0-9]*) SVC_IND=2 ;; esac
case "$PROP_IND" in ''|*[!0-9]*) PROP_IND=0 ;; esac
[ "$SVC_IND" -gt 0 ] || SVC_IND=2
[ "$PROP_IND" -gt "$SVC_IND" ] || PROP_IND=$((SVC_IND + 2))

# ---- ② 是否需要转换（缩进无关判据）----
# 已 host 的判据要三条同时成立：
#   ① 有过服务 ② 每个服务都有 network_mode: host ③ 没有残留 networks/ports 键、没有顶层 networks:
CNT=$(awk -v SVC="$SVC_IND" '
  function ind(s,   m) { match(s, /^[ ]*/); return RLENGTH }
  BEGIN { in_svc = 0; svc = 0; nm = 0; bad = 0 }
  /^[^ ]/ {
    if ($0 ~ /^services:/) { in_svc = 1; next }
    in_svc = 0; next
  }
  in_svc {
    if ($0 ~ /^[ ]*$/) next
    i = ind($0)
    if (i == SVC && $0 ~ /^[ ]*[^ #][^ :]*:[[:space:]]*$/) { svc++; next }
    if (i > SVC) {
      if ($0 ~ /^[ ]*network_mode:[[:space:]]*host[[:space:]]*$/) { nm++ }
      else if ($0 ~ /^[ ]*(networks|ports):/) { bad++ }
    }
  }
  END { printf "%d %d %d\n", svc, nm, bad }
' "$F" 2>/dev/null)

SVC_N=$(echo "$CNT" | awk '{print $1}')
NM_N=$(echo "$CNT" | awk '{print $2}')
BAD_N=$(echo "$CNT" | awk '{print $3}')
case "$SVC_N" in ''|*[!0-9]*) SVC_N=0 ;; esac
case "$NM_N"  in ''|*[!0-9]*) NM_N=0  ;; esac
case "$BAD_N" in ''|*[!0-9]*) BAD_N=1 ;; esac
TOP_N=$(grep -c '^networks:' "$F" 2>/dev/null)
case "$TOP_N" in ''|*[!0-9]*) TOP_N=1 ;; esac

NEED=1
if [ "$SVC_N" -gt 0 ] && [ "$NM_N" -ge "$SVC_N" ] && [ "$BAD_N" = "0" ] && [ "$TOP_N" = "0" ]; then
  NEED=0
fi

if [ "$CHECK" = "1" ]; then
  [ "$NEED" = "1" ] && exit 0
  exit 1
fi

if [ "$NEED" = "0" ]; then
  log "已是 host 模式，跳过: $F"
  exit 0
fi

# ---- 备份（只留第一次的原件，避免被二次转换污染）----
[ -f "$F.bridge.bak" ] || cp -f "$F" "$F.bridge.bak" || exit 2

# ---- ③ 转换（缩进无关：删除一律按"缩进 > svc_ind"、注入一律按 prop_ind）----
# YAML 结构（面板 4 空格 / 商店 2 空格都吃）：
#   services:               ← 0 缩进 = 顶层
#     alist:                ← svc_ind   = 服务名        ★注入点
#       networks:           ← prop_ind  = 要删的键      ★删除点
#         - 1panel-network  ← prop_ind+ = 子项（一并删）
awk -v SVC="$SVC_IND" -v PROP="$PROP_IND" '
  function ind(s,   m) { match(s, /^[ ]*/); return RLENGTH }
  function pad(n,   s, i) { s = ""; for (i = 0; i < n; i++) s = s " "; return s }
  BEGIN { in_svc = 0; skip_top = 0; skip_key = 0; skip_ind = 0 }
  # --- 顶层行（0 缩进）---
  /^[^ ]/ {
    if ($0 ~ /^networks:/) { skip_top = 1; in_svc = 0; next }   # 顶层 networks: 段整体丢弃
    skip_top = 0
    if ($0 ~ /^services:/) { in_svc = 1; print; next }
    in_svc = 0                                                  # 其它顶层段（volumes/configs/…）
    print; next
  }
  skip_top { next }
  # --- 其余所有行 ---
  {
    if ($0 ~ /^[ ]*$/) { if (skip_key) next; print; next }      # 空行：在删除块里则跟随删除
    if (in_svc) {
      i = ind($0)
      if (skip_key) {
        if (i > skip_ind) { next }                              # 被删键的子项
        skip_key = 0
      }
      if (i == SVC && $0 ~ /^[ ]*[^ #][^ :]*:[[:space:]]*$/) {   # 服务名行
        print
        print pad(PROP) "network_mode: host"
        next
      }
      if (i > SVC && $0 ~ /^[ ]*(network_mode|networks|ports):/) {
        skip_key = 1; skip_ind = i; next
      }
    }
    print
  }
' "$F" > "$F.kpnew" 2>/dev/null

if [ ! -s "$F.kpnew" ]; then
  rm -f "$F.kpnew"
  echo "kp-compose-host: 转换输出为空，已放弃（原文件未动）: $F" >&2
  exit 2
fi

mv -f "$F.kpnew" "$F" || { rm -f "$F.kpnew"; exit 2; }
log "已转换为 host 网络（缩进 svc=$SVC_IND prop=$PROP_IND）: $F"

# ---- ④ redis 内核兼容 ----
# ARM64-COW-BUG 自检早于配置文件加载，写进 redis.conf 无效，只能命令行传；
# ignore-warnings 是可变参数指令，必须放在 conf 路径**之后**，且 sed 不能加 g
# （否则会污染 volumes 行里的同名路径）。
if grep -q 'redis-server' "$F" 2>/dev/null; then
  sed -i 's| --ignore-warnings ARM64-COW-BUG||g' "$F" 2>/dev/null || :
  sed -i '/^[[:space:]]*command:/ s|/etc/redis/redis.conf|/etc/redis/redis.conf --ignore-warnings ARM64-COW-BUG|' "$F" 2>/dev/null || :
  if grep -q 'ignore-warnings' "$F" 2>/dev/null; then
    log "已注入 Redis 内核兼容参数: $F"
  else
    log "检测到 redis-server，但 command 行不是默认 conf 路径，未注入（需人工确认）"
  fi
fi

exit 0
