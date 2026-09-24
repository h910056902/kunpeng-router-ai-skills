#!/bin/sh
# OpenClash 自动测速切换 v3.4 — 全量测速 + 分类测速(视频/流媒体/AI) + 备用节点预选 + 故障转移 + WebUI
#
# v3.4 故障转移增强 (P0+P1)
#   P0-1 failover_enable / backup_enable 打开, cron 三段齐全 → MTTR 由最坏 30 分钟降到 <60s
#   P0-2 本地链路对照探针 local_link_ok(): 出口/本机链路本身断了就不切节点(切了也没用)
#   P0-3 代理层对照探针: 当前节点全探针无响应 + 至少一个对照节点有响应 = 真故障;
#                        若对照节点也全挂 = 探测通道/整体出口问题, 只告警不切
#   P0-4 硬故障突破静默期: 上面这条真故障判据成立时立刻转, 不等 failover_quiet
#   P1-1 备用池同源约束: 同一落地最多 1 个, 且优先避开当前节点所在落地
#   P1-2 切换净收益: 同时满足「提升 ≥ switch_min_gain」且「≤ 当前延迟的 switch_good_ratio%」
#   P1-3 切换后验证 + 劣化回滚: 切完 3s 复测, 仍不可用则试下一个(最多 3 个), 全失败回滚
#   P1-4 备用名单探测并行化: 4 路并发, 探测耗时从 ~7s 降到 ~3s
#   XX   切换限速 switch_min_interval(分钟): 只限速「执行切换」, 不影响每分钟一次的检测;
#        真故障例外, 否则 MTTR 会被拖到限速窗口那么长
#
#   新增 UCI(全部有默认值, 不写也能跑, 关掉只需置 0):
#     local_ifaces            本地出口接口列表(竖线分隔), 默认 'cpe|wan'
#     failover_local_check    本地链路对照, 默认 1
#     failover_local_ping     直连探测目标(不能是域名), 默认 223.5.5.5
#     failover_refnodes       对照节点个数, 默认 3
#     failover_maxalt         故障通道内的探测点回退次数, 默认 1(压 MTTR, 见下方注释)
#     failover_hard_break     硬故障突破静默期, 默认 1
#     failover_avoid_same_landing  备用池同源约束, 默认 1
#     failover_verify         切换后复测验证, 默认 1
#     failover_verify_tries   验证最多试几个候选, 默认 3
#     failover_rollback       切完明显更差则回滚, 默认 1
#     switch_min_gain         绝对收益下限(ms), 默认 30
#     switch_good_ratio       相对收益上限(%), 默认 70
#     switch_min_interval     两次切换最小间隔(分钟), 默认 120(0=不限)
#
# v3.3 修复 (全部是「功能静默失效」类缺陷):
#   - 每 backup_interval 分钟主动探测一批候选节点, 把最快的若干个写入 $DATA/backup.json
#   - failover_check 故障时优先逐个验证这张短名单, 命中即切, 省掉当场串行探测 Top5 的十几秒
#   - 所有状态一律放 $DATA (overlay, 跨每天 02:00 自动重启保留);
#     /tmp 是 tmpfs, 重启即清空, 只放临时中间文件
#
# v3.3 修复 (全部是「功能静默失效」类缺陷):
#   1. [P0] $DATA/running 残留会让备用预选与故障转移双双永久停摆, 且不写任何日志。
#      改为写入时间戳 + 超时自愈, trap 同步清理。
#   2. [P0] 节点属性错位: name/type 各 62 条而 alive 有 245 条(每个节点的 history 数组里
#      也有 alive), 按行号配对整体错位约 26%, 健康的当前节点被记成 a:false 而永久进不了
#      备用池。改为按花括号深度解析 JSON。
#   3. [P0] 决赛(gemini)延迟抖动达 2.3 倍却用它排名 -> 50% 的切换是劣化。
#      改为: 排名一律用初赛(gstatic, 稳定), 决赛只当可用性闸门且失败重试一次。
#   4. [P1] 备用候选池 head -N 取的是订阅书写顺序而非最快 -> 改成按上次延迟升序取。
#   5. [P1] testnode 的 printf 多传一个参数, POSIX printf 复用格式串吐出多余对象,
#      只要有一个站点超时, 整次返回非法 JSON。
#   6. [P1] 历史记录取的是最旧 10 条(head -10) -> 改 tail -10。
# 端口与密钥从 OpenClash 配置动态读取（重置/改密后不会静默失效），原值兜底
_OC_PORT=$(uci -q get openclash.config.cn_port 2>/dev/null)
[ -z "$_OC_PORT" ] && _OC_PORT=9090
_OC_SECRET=$(uci -q get openclash.config.dashboard_password 2>/dev/null)
# 未设置 dashboard_password 时按无密钥访问；切勿把真实密钥写死进仓库
API=http://127.0.0.1:$_OC_PORT
SECRET=$_OC_SECRET
DIR=/tmp/ocspeed
DATA=/etc/openclash-helper
LOG=/var/log/ocspeed.log
# running 标记的最大存活秒数。一轮全量测速实测约 2 分钟, 给 15 分钟做兜底。
RUNNING_MAX=900

mkdir -p $DIR $DATA

log() { echo "$(date '+%F %T') [$1] $2" >> $LOG; }

# JSON 字符串转义。
# 节点名 / 策略组名 / 站点 URL 都是外部数据，直接拼进 JSON 正文时，一个 " 或 \
# 就能让整个文件解析失败 —— 页面退化成「暂无数据」，切换到 mihomo 的请求也会
# 被当成非法 JSON 拒绝。URL 场景早就有 urlenc()，JSON 正文却一直没有对应处理。
# 实测本机场的节点名是 "L1|新加坡05|中转|流媒体|4x" 这种不含引号的格式，所以
# 至今没爆过；换一个用引号/反斜杠命名的机场就会立刻出问题。
#   · \ 与 " 必须转义（改成 \\ 和 \"），否则 JSON 结构被破坏
#   · TAB / 换行 / 回车直接删除：它们是 JSON 字符串里不允许的裸控制字符。
#     代价是名字会被改动 —— 但本套件全流程用 TAB 作字段分隔符，含 TAB 的名字
#     在上游 collect_all_nodes 解析 TSV 时就已经表达不了了，这一层不必再兜。
json_esc() { printf '%s' "$1" | tr -d '\n\r\t' | sed 's/\\/\\\\/g; s/"/\\"/g'; }

# ---- $DATA/running 生命周期 ----
# 背景: running 放在 overlay 上, 被 kill / 掉电后不会消失, 而互斥用的 $DIR/lock 在
# tmpfs 上、重启即清。二者不一致 -> 一次异常退出就会让 backup_select 和 failover_check
# 永远 return 0(静默停摆)。写入时间戳 + 超时自愈即可根治。
run_mark_set()   { date +%s > $DATA/running; }
run_mark_clear() { rm -f $DATA/running 2>/dev/null; }
# 返回 0 = 忙(有实例在跑), 1 = 空闲
run_busy() {
  [ -f $DATA/running ] || return 1
  local ts=$(cat $DATA/running 2>/dev/null)
  case "$ts" in
    ''|*[!0-9]*) run_mark_clear; return 1 ;;
  esac
  local now=$(date +%s)
  if [ $((now - ts)) -gt ${RUNNING_MAX:-900} ]; then
    log lock "清除残留 running 标记 (已存在 $((now - ts))s > ${RUNNING_MAX:-900}s)"
    run_mark_clear
    return 1
  fi
  return 0
}
get() { uci -q get ocspeed.main.$1 2>/dev/null; }
api_get() { curl -s -m 10 -H "Authorization: Bearer $SECRET" "$API$1" 2>/dev/null; }
urlenc() {
  printf '%s' "$1" | hexdump -v -e '1/1 "%02X"' | awk '{
    out = ""
    for (i = 1; i <= length($0); i += 2) {
      h = substr($0, i, 2)
      v = (index("0123456789ABCDEF", substr(h, 1, 1)) - 1) * 16 + index("0123456789ABCDEF", substr(h, 2, 1)) - 1
      if ((v >= 65 && v <= 90) || (v >= 97 && v <= 122) || (v >= 48 && v <= 57) || v == 45 || v == 46 || v == 95 || v == 126)
        out = out sprintf("%c", v)
      else
        out = out "%" h
    }
    printf "%s", out
  }'
}
set_progress() { # phase msg pct
  printf '{"phase":"%s","msg":"%s","pct":%s}' "$1" "$2" "$3" > $DIR/progress.json 2>/dev/null
}

node_delay() { # name url timeout -> ms or empty
  local n="$1" u="$2" t="$3" r d
  r=$(curl -s -m $((t/1000+3)) -H "Authorization: Bearer $SECRET" "$API/proxies/$(urlenc "$n")/delay?url=$(urlenc "$u")&timeout=$t" 2>/dev/null)
  d=$(echo "$r" | grep -o '"delay":[0-9]*' | head -1 | cut -d: -f2)
  [ -n "$d" ] && echo "$d"
}

# 多探测点回退: 主 test_url 拿不到延迟时, 依次换 testsites 里的备用站点重试。
# 原逻辑只用单一探测点(gstatic generate_204), 该 URL 一旦被干扰或短暂不可达,
# 全部节点都会返回空 -> 被统一判定成「所有节点都挂了」, 而实际上是探测点本身的问题。
# max_alt 限制回退次数, 避免把 11 个站点全试一遍拖垮每分钟一次的 failover。
probe_delay_multi() { # name timeout [max_alt]
  local n="$1" t="$2" maxalt="${3:-3}" d alt i=0
  local tu=$(get test_url); [ -z "$tu" ] && tu='https://www.gstatic.com/generate_204'
  d=$(node_delay "$n" "$tu" "$t")
  if [ -n "$d" ]; then echo "$d"; return 0; fi
  for alt in $(get testsites | tr '|' ' '); do
    [ -z "$alt" ] && continue
    [ "$alt" = "$tu" ] && continue
    [ "$i" -ge "$maxalt" ] && break
    i=$((i+1))
    d=$(node_delay "$n" "$alt" "$t")
    if [ -n "$d" ]; then
      log failover "探测点回退: $n 改经 $alt 得到 ${d}ms (主探测点 $tu 无响应)"
      echo "$d"
      return 0
    fi
  done
  return 1
}

# ---------- 节点名结构 ----------
# 订阅节点名形如 L1|新加坡01|中转|流媒体|4x : 字段 2 = 落地, 字段 3 = 线路类型。
# 流媒体专线是 4 段(L1|新加坡06|流媒体|3x), 字段 2 仍是落地, 不影响这里的使用。
node_landing() { printf '%s' "$1" | cut -d'|' -f2; }

# ---------- 切换限速 (用户要求: 两次切换至少间隔 N 分钟) ----------
# 只限速「真正执行切换」这一个动作, 不影响每分钟一次的检测。
# 背景: 全量测速每 30 分钟一轮, 而 top5 本身的离散度就在几十毫秒量级,
# 「有节点比当前快 50ms 就切」几乎每轮都成立 —— 15 轮里切了 8 轮。
# 每次切换都会打断所有已建立的 TCP 连接(视频重新缓冲、下载中断),
# 代价远大于那几十毫秒的收益。
# 真故障例外(见 failover_check): 故障转移不受此限速, 否则 MTTR 会被拖到限速窗口那么长。
switch_allowed() { # -> 0=可切, 1=限速窗口内
  local mi=$(get switch_min_interval); [ -z "$mi" ] && mi=120
  case "$mi" in ''|*[!0-9]*) mi=120 ;; esac
  [ "$mi" -le 0 ] && return 0
  local lt=$(cat $DATA/last_switch 2>/dev/null || echo 0)
  case "$lt" in ''|*[!0-9]*) lt=0 ;; esac
  local now=$(date +%s)
  if [ $((now - lt)) -lt $((mi * 60)) ]; then
    log switch "切换限速: 距上次切换 $(( (now - lt) / 60 )) 分钟 < ${mi} 分钟, 本轮不切"
    return 1
  fi
  return 0
}
mark_switch() { date +%s > $DATA/last_switch 2>/dev/null; }

# ---------- P1-2 切换净收益判据 ----------
# 「有收益」必须同时满足两条, 只满足其一不算:
#   绝对: curd - bestd >= switch_min_gain      (默认 30ms)
#   相对: bestd <= curd * switch_good_ratio%   (默认 70%)
# 前者挡住噪声内的抖动, 后者挡住「900ms 换 850ms」这种只有 5% 提升、却要打断全部连接的切换。
# 当前节点初赛无结果(=已不可用)时不看收益, 无脑切。
worth_switching() { # curd bestd -> 0=值得切, 1=不值
  local c="$1" b="$2"
  [ -z "$c" ] && return 0
  case "$b" in ''|*[!0-9]*) return 0 ;; esac
  local g=$(get switch_min_gain); [ -z "$g" ] && g=30
  local r=$(get switch_good_ratio); [ -z "$r" ] && r=70
  [ "$b" -gt $(( c * r / 100 )) ] && return 1
  [ $((c - b)) -lt "$g" ] && return 1
  return 0
}

# ---------- P0-2 本地链路对照探针 ----------
# 作用: 把「代理侧故障」和「本机 / 光猫 / 上游链路故障」区分开。
# 只有本机出口正常时换节点才可能有用; 出口本身断了, 切一百次也是白切 ——
# 既浪费一个冷却周期, 又白白打断一遍所有已建立的 TCP 连接。
#
# 判据: (a) 至少一个出口接口 up  且  (b) 直连 ping 得通
# ⚠️ 不要用 DNS 做这个判断: mihomo 劫持了 DNS(enable_redirect_dns=1, dns-port 7874),
#    DNS 走代理、会跟着代理一起挂, 拿它当对照等于没有对照。
# ⚠️ 出口接口不能直接写死 wan: 本机真正的出口是 cpe(proto=wwan, 设备 eth3),
#    wan(eth0) 恒为 up:false 也没有默认路由 —— 照 wan 判断会把所有转移永久拦死。
local_link_ok() { # -> 0=本机出口正常(可以切), 1=本机/上游故障(不要切)
  [ "$(get failover_local_check)" = "0" ] && return 0
  local iflist=$(get local_ifaces); [ -z "$iflist" ] && iflist='cpe|wan'
  local seen=0 any=0 iface st
  for iface in $(echo "$iflist" | tr '|' ' '); do
    [ -z "$iface" ] && continue
    st=$(ubus call network.interface."$iface" status 2>/dev/null \
         | tr -d ' \t\n' | grep -oE '"up":(true|false)' | head -1)
    [ -z "$st" ] && continue            # 接口不存在 → 视为未知, 不参与判定
    seen=$((seen+1))
    case "$st" in '"up":true') any=1 ;; esac
  done
  # 列出的接口一个都不存在 → 无从判定, 放行(不因为自己探不了就拦住转移)
  if [ "$seen" -gt 0 ] && [ "$any" -eq 0 ]; then
    log failover "本地链路: 出口接口全部 down ($iflist), 属本机/上游故障, 本次不切换"
    return 1
  fi
  local pt=$(get failover_local_ping); [ -z "$pt" ] && pt='223.5.5.5'
  if ! ping -c 2 -W 2 "$pt" >/dev/null 2>&1; then
    log failover "本地链路: 直连 ping $pt 不通, 属本机/上游故障, 本次不切换"
    return 1
  fi
  return 0
}

# ---------- P0-3 代理层对照探针 ----------
# 「当前节点测不通」本身不足以证明节点故障 —— 测速尾巴、探测点被干扰、整体出口拥塞,
# 都会让所有节点在同一时刻一起返回空, 这时换成谁都一样。
# 判定真故障必须有一个对照组: 同一时刻再去探几个别的节点,
#   对照节点有响应       → 探测通道和本机出口都是好的, 故障确实落在当前节点上 → 可以切
#   对照节点也全部无响应 → 更像探测通道/整体链路的问题, 换节点无意义 → 只告警不切
ref_nodes_alive() { # cur -> 0=真故障(可切), 1=整体不可用(不切)
  local cur="$1"
  local want=$(get failover_refnodes); [ -z "$want" ] && want=3
  local tu=$(get test_url); [ -z "$tu" ] && tu='https://www.gstatic.com/generate_204'
  local TAB=$(printf '\t') n=0 name
  : > $DIR/ref_list.txt
  # 对照节点优先取备用名单(它是最近 90 分钟内实测最快的几个), 退回 nodes.json 的的健康节点
  if [ -f $DATA/backup.json ]; then
    grep -o '"n":"[^"]*"' $DATA/backup.json 2>/dev/null | sed 's#"n":"##; s#"$##' \
      | grep -vxF "$cur" | head -$want >> $DIR/ref_list.txt
  fi
  [ -s $DIR/ref_list.txt ] || {
    tr '{' '\n' < $DATA/nodes.json 2>/dev/null \
      | grep '"d":[0-9]*,"s":"ok"' \
      | sed 's#.*"n":"\([^"]*\)".*"d":\([0-9]*\).*#\2'"$TAB"'\1#' \
      | sort -n | grep -vF "$cur" | cut -f2 | head -$want >> $DIR/ref_list.txt
  }
  [ -s $DIR/ref_list.txt ] || { log failover "对照探针: 找不到对照节点, 无法判定单节点故障"; return 1; }
  : > $DIR/ref_res.txt
  while read -r name; do
    [ -z "$name" ] && continue
    ( d=$(node_delay "$name" "$tu" 4000)
      [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/ref_res.txt ) &
    n=$((n+1))
    [ $((n % 4)) -eq 0 ] && wait
  done < $DIR/ref_list.txt
  wait
  if [ -s $DIR/ref_res.txt ]; then
    sort -n $DIR/ref_res.txt | head -1 > $DIR/ref_best.txt
    log failover "对照探针: $(cut -f2 $DIR/ref_res.txt | tr '\n' ' ')有响应 -> 确认单节点故障"
    return 0
  fi
  log failover "对照探针: 对照节点同样全部无响应 ($(tr '\n' ' ' < $DIR/ref_list.txt)), 更像整体链路/探测通道问题, 本次不切换"
  return 1
}

# ---------- P1-1 备用池同源约束 ----------
# 从已按延迟升序排好的 TSV(延迟<TAB>节点名)里, 按「同一落地最多收录 1 个」挑出 keep 个。
# 按延迟排序时, 同一落地的中转/直连两条线路往往紧挨在一起,
# 不加约束备用池会变成「同一个落地的两条线」—— 该落地一挂就全军覆没。
pick_diverse() { # infile keep [exclude_landing] -> stdout
  local in="$1" keep="$2" ex="$3"
  local TAB=$(printf '\t') got=0 dd nm ld
  : > $DIR/div_seen.txt
  while IFS="$TAB" read -r dd nm; do
    [ -z "$nm" ] && continue
    [ "$got" -ge "$keep" ] && break
    ld=$(printf '%s' "$nm" | cut -d'|' -f2)
    [ -n "$ex" ] && [ "$ld" = "$ex" ] && continue
    grep -qxF "$ld" $DIR/div_seen.txt 2>/dev/null && continue
    printf '%s\t%s\n' "$dd" "$nm"
    printf '%s\n' "$ld" >> $DIR/div_seen.txt
    got=$((got+1))
  done < "$in"
  return 0
}

# ---------- P1-4 并行探测一批节点 ----------
# 把 (name列表) 逐个 node_delay 的活儿摊到 4 路并发上, 结果写 $2(延迟<TAB>节点名)。
# 串行时 3 个备用节点要 ~7s, 备用名单过期退回 Top5 串行更是 15s+,
# 而 MTTR 的目标是一分钟以内 —— 这一点必须省出来。
probe_list_parallel() { # listfile outfile [width] [maxalt]
  local list="$1" out="$2" w="${3:-4}" ma="${4:-2}" n=0 name
  : > "$out"
  : > $DIR/pl_par.out
  : > $DIR/pl_dead.txt
  while read -r name; do
    [ -z "$name" ] && continue
    ( d=$(probe_delay_multi "$name" 5000 "$ma")
      [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/pl_par.out
      [ -z "$d" ] && printf '%s\n' "$name" >> $DIR/pl_dead.txt ) &
    n=$((n+1))
    [ $((n % w)) -eq 0 ] && wait
  done < "$list"
  wait
  cat $DIR/pl_par.out >> "$out" 2>/dev/null
  rm -f $DIR/pl_par.out
  sort -n "$out" > $DIR/pl_sort.tmp 2>/dev/null && mv $DIR/pl_sort.tmp "$out"
  return 0
}

# 按花括号深度解析 /proxies: 只在 depth==3(某个 proxy 对象内部) 取 name/type/alive。
# 不能用「三次 grep -o 再按行号配对」——每个节点的 history 数组里也有 alive 字段,
# 实测 name/type 各 62 条而 alive 有 245 条, 按下标配对会整体错位约 26%。
# 决定性对照: 台湾01 的 alive 原文是 false, 旧方法把它记成 true;
# 而当前节点(139ms, 全场最快)真实 alive=true 却被记成 false, 于是永远当不了备用节点。
json_nodes_tsv() {
  awk '
  { s = s $0 }
  END {
    n = length(s); depth = 0; instr = 0; esc = 0; mode = 0
    key = ""; val = ""; nm = ""; tp = ""; al = ""
    for (i = 1; i <= n; i++) {
      c = substr(s, i, 1)
      if (instr) {
        if (esc) { esc = 0; if (mode == 1) key = key c; else if (mode == 2) val = val c; continue }
        if (c == "\\") { esc = 1; if (mode == 1) key = key c; else if (mode == 2) val = val c; continue }
        if (c == "\"") {
          instr = 0
          if (mode == 1) { mode = 3 }
          else if (mode == 2) {
            mode = 0
            if (depth == 3) {
              if (key == "name") nm = val
              else if (key == "type") tp = val
            }
          }
          continue
        }
        if (mode == 1) key = key c
        else if (mode == 2) val = val c
        continue
      }
      # mode==4 = 「刚读完冒号, 接下来是值」。此时遇到引号必须切成 mode=2(读值字符串)
      # 且保留 key; 若一律重置成 mode=1, 值会被当成键来读, name/type 永远取不到。
      if (c == "\"") { instr = 1; if (mode == 4) { mode = 2; val = "" } else { mode = 1; key = ""; val = "" } continue }
      if (c == ":") { if (mode == 3) { mode = 4; val = "" } continue }
      if (c == "{") { depth++; mode = 0; continue }
      if (c == "}") {
        if (mode == 4 && depth == 3 && key == "alive") al = val
        if (depth == 3 && nm != "") {
          printf "%s\t%s\t%s\n", nm, al, tp
          nm = ""; tp = ""; al = ""
        }
        depth--; mode = 0; continue
      }
      if (c == ",") {
        if (mode == 4 && depth == 3 && key == "alive") al = val
        mode = 0; val = ""; continue
      }
      if (mode == 4) val = val c
    }
  }' "$1"
}

collect_all_nodes() {
  api_get /proxies > $DIR/proxies.json
  json_nodes_tsv $DIR/proxies.json > $DIR/nt.tsv
  # 兜底: 万一深度解析零输出(上游结构变了), 退回旧的 grep 配对,
  # 宁可拿到错位的数据, 也不能一个节点都收集不到导致整轮空跑。
  if [ ! -s $DIR/nt.tsv ]; then
    log collect "深度解析无输出, 退回 grep 配对(结果可能错位)"
    grep -o '"name":"[^"]*"' $DIR/proxies.json | sed 's/"name":"//;s/"$//' > $DIR/names.txt
    grep -o '"alive":[a-z]*' $DIR/proxies.json | sed 's/"alive"://' > $DIR/alive.txt
    grep -o '"type":"[^"]*"' $DIR/proxies.json | sed 's/"type":"//;s/"$//' > $DIR/types.txt
    awk 'FILENAME==ARGV[1]{n[FNR]=$0;next} FILENAME==ARGV[2]{a[FNR]=$0;next} {print n[FNR]"\t"a[FNR]"\t"$0}' $DIR/names.txt $DIR/alive.txt $DIR/types.txt > $DIR/nt.tsv
  fi
  # names.txt 后面还要用来判断策略组是否存在, 从解析结果里保持一致地生成
  cut -f1 $DIR/nt.tsv > $DIR/names.txt
  : > $DIR/allnodes.txt
  TAB=$(printf '\t')
  # 真实出站节点类型（小写，供上面循环归一后比对）
  NODE_TYPES="vless vmess trojan hysteria hysteria2 tuic wireguard snell shadowsocks ss ssr socks5 http mieru ssh anytls shadowtls"
  while IFS="$TAB" read -r name alive type; do
    # 只收「真实出站节点」类型，策略组（Selector/URLTest/Fallback/LoadBalance/
    # Relay/Direct/Reject…）必须排除，否则会拿组名去测延迟。
    # 这份名单要跟着 mihomo 走：漏掉新协议 = 该类节点一个都进不了候选池，
    # 表现为"机场明明有 60 个节点，测速只认 44 个"，且日志里毫无线索。
    # mihomo 的 type 是 Go 常量，大小写拼法不统一、还随版本变过（Tuic / ShadowTLS /
    # AnyTLS / Mieru / SSH…），而 ash 的 case 区分大小写 —— 写死一种拼法就整类漏光。
    # 所以统一转小写再比：只会多命中，不会少命中。
    # 已核对：策略组类型（Selector / URLTest / Fallback / LoadBalance / Relay / Direct /
    # Reject / Compatible / Pass / Dns）小写后与下面任何一项都不重合，不会误收组名。
    low=$(printf '%s' "$type" | tr 'A-Z' 'a-z') || low=""
    case " $NODE_TYPES " in
      *" $low "*) ;;
      *) continue ;;
    esac
    printf '%s\t%s\t%s\n' "$name" "$type" "$alive" >> $DIR/allnodes.txt
  done < $DIR/nt.tsv
}

is_fake() {
  local name="$1" kw
  local exc=$(get exclude)
  for kw in $exc; do
    [ -z "$kw" ] && continue
    case "$name" in *"$kw"*) return 0 ;; esac
  done
  return 1
}

build_candidates() {
  : > $DIR/candidates.txt
  local TAB=$(printf '\t')
  while IFS="$TAB" read -r name type alive; do
    is_fake "$name" && continue
    echo "$name" >> $DIR/candidates.txt
  done < $DIR/allnodes.txt
  # 持久化一份到 overlay: /tmp 是 tmpfs, 每天 02:00 自动重启后候选池会被清空,
  # 故障转移的兜底路径原本会因为这个拿不到任何节点
  cp $DIR/candidates.txt $DATA/candidates.txt 2>/dev/null
}

speedtest() { # url timeout outfile [total]
  local u="$1" t="$2" out="$3" total="$4" i=0 d cnt
  [ -z "$total" ] && total=0
  : > $out
  : > $DIR/par_$$.out
  while read -r name; do
    [ -z "$name" ] && continue
    ( d=$(node_delay "$name" "$u" "$t"); [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/par_$$.out ) &
    i=$((i+1))
    if [ $i -ge 4 ]; then
      wait; i=0
      if [ "$total" -gt 0 ] 2>/dev/null; then
        cnt=$(wc -l < $DIR/par_$$.out)
        set_progress "testing" "全量测速中 ($cnt/$total)" $((40 + cnt*35/total))
      fi
    fi
  done < $DIR/allnodes.list
  wait
  cat $DIR/par_$$.out >> $out 2>/dev/null
  rm -f $DIR/par_$$.out
  sort -n $out > $out.tmp 2>/dev/null && mv $out.tmp $out
}

# 注意: trap 必须同时清 running —— 只清 lock 的话, lock 在 tmpfs 上重启即没,
# 而 running 在 overlay 上会一直留着, 下一次 backup_select / failover_check 就永远跳过。
lock_acquire() {
  mkdir $DIR/lock 2>/dev/null || { log lock "已有实例运行, 跳过"; exit 0; }
  trap 'rmdir $DIR/lock 2>/dev/null; rm -f $DATA/running 2>/dev/null' EXIT INT TERM
}

build_nodes_json() {
  local n_all=$(wc -l < $DIR/allnodes.txt)
  local TAB=$(printf '\t')
  # 必须先写 .tmp 再 mv: 这个文件是几十次 printf 追加出来的, 而 run 跑着的时候
  # 页面会通过 status/nodes 子命令实时读它 —— 不加原子性就会读到半截文件,
  # 表现为页面偶发"当前节点"空白/报错, 刷新一下又好了, 极难复现。
  # 2026-09-19 隔离副本实测(把输入放大到 4000 节点, 写窗口从几毫秒拉到秒级, 同进程内密集读):
  #   直写 > 和 >>: 合法读 5~10 次 / 撕裂读 3413~4351 次
  #   tmp+mv     : 合法读 24132~26034 次 / 撕裂读 0 次
  # 线上只有 72 节点、写窗口几毫秒, 撞上的概率低, 但代价只是一次 mv。
  # sites.json 早就是 tmp+mv, 这里补齐。
  local NJ=$DATA/nodes.json.tmp
  printf '{"ts":%s,"total":%s,"nodes":[' "$(date +%s)" "$n_all" > $NJ
  local first=1
  while IFS="$TAB" read -r name type alive; do
    local d s
    d=$(awk -F '\t' -v n="$name" '$2==n{print $1; exit}' $DIR/allresults.txt 2>/dev/null)
    if is_fake "$name"; then s="fake"
    elif [ -n "$d" ]; then s="ok"
    else s="dead"; fi
    [ $first -eq 0 ] && printf ',' >> $NJ
    first=0
    if [ -n "$d" ]; then
      printf '{"n":"%s","t":"%s","a":%s,"d":%s,"s":"%s"}' \
        "$(json_esc "$name")" "$(json_esc "$type")" "$alive" "$d" "$s" >> $NJ
    else
      printf '{"n":"%s","t":"%s","a":%s,"d":null,"s":"%s"}' \
        "$(json_esc "$name")" "$(json_esc "$type")" "$alive" "$s" >> $NJ
    fi
  done < $DIR/allnodes.txt
  printf ']}' >> $NJ
  mv $NJ $DATA/nodes.json
}

# 站点 → 「分类 + 显示名」。分类只影响展示（视频/流媒体/AI 分组带），不参与任何判定。
# 匹配的是域名子串，所以词要收窄：*max.com* 会把一堆无关域名吃进「流媒体」，
# *amazon* 同理（amazonaws 也是 amazon）。宁可落到「其他」，也别错归。
site_meta() { # url -> "分类<TAB>显示名"
  local d
  d=$(printf '%s' "$1" | sed 's|^https://||; s|^http://||; s|/.*||; s|^www\.||')
  local cat="其他" disp="$d"
  case "$d" in
    *youtube*|*youtu.be*)    cat="视频";   disp="YouTube" ;;
    *bilibili*)              cat="视频";   disp="Bilibili" ;;
    *iqiyi*)                 cat="视频";   disp="爱奇艺" ;;
    *youku*)                 cat="视频";   disp="优酷" ;;
    *v.qq.com*)              cat="视频";   disp="腾讯视频" ;;
    *netflix*)               cat="流媒体"; disp="Netflix" ;;
    *disney*)                cat="流媒体"; disp="Disney+" ;;
    *hbomax*)                cat="流媒体"; disp="HBO Max" ;;
    *primevideo*)            cat="流媒体"; disp="Prime Video" ;;
    *hulu*)                  cat="流媒体"; disp="Hulu" ;;
    *spotify*)               cat="流媒体"; disp="Spotify" ;;
    *gemini*|*bard*)         cat="AI";     disp="Gemini" ;;
    *openai*|*chatgpt*)      cat="AI";     disp="ChatGPT" ;;
    *claude*|*anthropic*)    cat="AI";     disp="Claude" ;;
    *copilot*)               cat="AI";     disp="Copilot" ;;
    *perplexity*)            cat="AI";     disp="Perplexity" ;;
    *grok*)                  cat="AI";     disp="Grok" ;;
  esac
  printf '%s\t%s\n' "$cat" "$disp"
}

# 文件 → JSON 字符串数组。站点名可能带引号/反斜杠（用户手填的 URL），先剔掉再入 JSON，
# 否则一个带 " 的 URL 就能让整个 sites.json 解析失败、页面退化成「暂无数据」。
json_strarray() { # file
  local first=1 l
  printf '['
  while IFS= read -r l; do
    [ -z "$l" ] && continue
    l=$(printf '%s' "$l" | tr -d '"\\')
    [ -z "$l" ] && continue
    [ $first -eq 0 ] && printf ','
    first=0
    printf '"%s"' "$l"
  done < "$1"
  printf ']'
}

build_sites_json() {
  local sites=$(get sites)
  [ -z "$sites" ] && sites='https://www.youtube.com|https://www.netflix.com|https://www.disneyplus.com|https://gemini.google.com|https://chatgpt.com|https://claude.ai'
  printf '%s' "$sites" | tr '|' '\n' | grep . > $DIR/sites.list
  head -5 $DIR/stage1.txt | cut -f2 > $DIR/top5nodes.txt

  # 域名→分类的映射只在这里维护一份，写进 sites.json 让页面直接照着渲染。
  # 两侧各存一份必然漂移（改了一边忘了另一边，分组带就和实际站点对不上）。
  : > $DIR/site_cats.txt
  : > $DIR/site_disp.txt
  while IFS= read -r s; do
    [ -z "$s" ] && continue
    site_meta "$s" | cut -f1 >> $DIR/site_cats.txt
    site_meta "$s" | cut -f2 >> $DIR/site_disp.txt
  done < $DIR/sites.list

  local idx=0
  while read -r s; do
    idx=$((idx+1))
    : > $DIR/site_$idx.txt
    while read -r name; do
      ( d=$(node_delay "$name" "$s" 5000); [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/site_$idx.txt ) &
    done < $DIR/top5nodes.txt
    wait
  done < $DIR/sites.list

  local grp=$(get group); [ -z "$grp" ] && grp='宝贝云'
  local d
  # 先写临时文件再 mv: 页面直接读这个文件, 中途崩溃留下的半截 JSON
  # 会让分类表整块退化成「暂无数据」, 而 mv 是原子的。
  {
    printf '{"ts":%s,"group":"%s","cats":' "$(date +%s)" "$(json_esc "$grp")"
    json_strarray $DIR/site_cats.txt
    printf ',"sites":'
    json_strarray $DIR/site_disp.txt
    printf ',"urls":'
    json_strarray $DIR/sites.list
    printf ',"data":['
    local j=0
    while read -r name; do
      [ -z "$name" ] && continue
      [ $j -gt 0 ] && printf ','
      printf '{"n":"%s","d":[' "$(json_esc "$name")"
      local k=0
      while read -r s; do
        k=$((k+1))
        [ $k -gt 1 ] && printf ','
        d=$(awk -F '\t' -v n="$name" '$2==n{print $1; exit}' $DIR/site_$k.txt 2>/dev/null)
        if [ -n "$d" ]; then printf '%s' "$d"; else printf 'null'; fi
      done < $DIR/sites.list
      printf ']}'
      j=$((j+1))
    done < $DIR/top5nodes.txt
    printf ']}'
  } > $DATA/sites.json.tmp
  mv $DATA/sites.json.tmp $DATA/sites.json
}

speedtest_full() {
  local do_switch_allowed="$1"
  lock_acquire
  run_mark_set
  set_progress "start" "开始测速" 3
  v=$(api_get /version)
  if ! echo "$v" | grep -q version; then
    run_mark_clear
    log run "OpenClash API 不可达, 中止"
    exit 1
  fi

  group=$(get group);       [ -z "$group" ] && group='宝贝云'
  test_url=$(get test_url); [ -z "$test_url" ] && test_url='https://www.gstatic.com/generate_204'
  gemini_url=$(get gemini_url); [ -z "$gemini_url" ] && gemini_url='https://gemini.google.com'
  timeout=$(get timeout);   [ -z "$timeout" ] && timeout=4000
  threshold=$(get threshold); [ -z "$threshold" ] && threshold=50

  collect_all_nodes
  set_progress "collect" "节点收集完成" 15
  grep -qx "$group" $DIR/names.txt || { run_mark_clear; log run "策略组 $group 不存在, 中止"; exit 1; }
  n_all=$(wc -l < $DIR/allnodes.txt)
  build_candidates
  n_cand=$(wc -l < $DIR/candidates.txt)
  log run "全量测速: $n_all 节点 (真节点 $n_cand, 目标组=$group)"

  cut -f1 $DIR/allnodes.txt > $DIR/allnodes.list
  set_progress "testing" "全量测速中 ($n_all 节点)" 40
  speedtest "$test_url" "$timeout" $DIR/allresults.txt $n_all
  if [ ! -s $DIR/allresults.txt ]; then
    run_mark_clear
    log run "全部节点测速超时"
    exit 0
  fi
  build_nodes_json
  set_progress "nodes" "节点状态已生成" 60

  now=$(api_get "/proxies/$group" | grep -o '"now":"[^"]*"' | head -1 | cut -d'"' -f4)

  : > $DIR/stage1.txt
  local TAB=$(printf '\t')
  while IFS="$TAB" read -r name type alive; do
    is_fake "$name" && continue
    d=$(awk -F '\t' -v n="$name" '$2==n{print $1; exit}' $DIR/allresults.txt 2>/dev/null)
    [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/stage1.txt
  done < $DIR/allnodes.txt
  sort -n $DIR/stage1.txt > $DIR/stage1.tmp 2>/dev/null && mv $DIR/stage1.tmp $DIR/stage1.txt

  # ---- 决赛: 只当可用性闸门, 不再参与排名 ----
  # 排名一律用初赛(gstatic generate_204): 它极其稳定, 同节点相邻两轮实测 151/152ms。
  # 决赛目标是 gemini.google.com, 国内不可达、必须走代理, 抖动可达 2.3 倍
  # (实测同节点两轮 908ms / 2108ms), 而切换阈值只有 50ms —— 拿它排名等于掷骰子。
  # 后果: 历史 8 次切换里 4 次是劣化, 152ms 的节点被 656ms 的顶掉, 半小时后又切回来。
  cp $DIR/stage1.txt $DIR/top5d.txt                   # v1.0: 闸门扩到全部候选(仍按初赛升序)
  cut -f2 $DIR/top5d.txt > $DIR/top5.txt
  : > $DIR/stage2.txt
  local gtotal=$(wc -l < $DIR/top5.txt 2>/dev/null)
  [ -z "$gtotal" ] && gtotal=1
  local gi=0
  while read -r name; do
    [ -z "$name" ] && continue
    gi=$((gi+1))
    set_progress "nodes" "Gemini 准入探测 ($gi/$gtotal)" $((60 + gi*10/gtotal))
    d=$(node_delay "$name" "$gemini_url" 6000)
    # 失败重试一次: 抖动是常态, 重试能滤掉大部分假阴性, 且只有失败时才多花时间
    [ -z "$d" ] && d=$(node_delay "$name" "$gemini_url" 6000)
    [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/stage2.txt
  done < $DIR/top5.txt
  sort -n $DIR/stage2.txt > $DIR/stage2.tmp 2>/dev/null && mv $DIR/stage2.tmp $DIR/stage2.txt
  cut -f2 $DIR/stage2.txt > $DIR/stage2_names.txt 2>/dev/null

  # 按初赛顺序过闸门, 第一个通过决赛的就是目标
  : > $DIR/best_order.txt
  while IFS="$TAB" read -r d nm; do
    [ -z "$nm" ] && continue
    grep -qx "$nm" $DIR/stage2_names.txt || continue
    printf '%s\t%s\n' "$d" "$nm" >> $DIR/best_order.txt
  done < $DIR/top5d.txt

  # 闸门全灭时退回初赛第一名, 保证永远有目标
  best=$(head -1 $DIR/best_order.txt 2>/dev/null | cut -f2)
  bestd=$(head -1 $DIR/best_order.txt 2>/dev/null | cut -f1)
  if [ -z "$best" ]; then
    log run "决赛全部未通过, 按初赛排名兜底"
    best=$(head -1 $DIR/top5d.txt | cut -f2)
    bestd=$(head -1 $DIR/top5d.txt | cut -f1)
  fi
  bestdf=$(awk -F '\t' -v n="$best" '$2==n{print $1; exit}' $DIR/stage2.txt 2>/dev/null)
  bestfin="未通过"
  [ -n "$bestdf" ] && bestfin="${bestdf} ms"

  local mingain=$(get switch_min_gain); [ -z "$mingain" ] && mingain=30
  local minratio=$(get switch_good_ratio); [ -z "$minratio" ] && minratio=70

  switched=0
  if [ "$do_switch_allowed" = "1" ] && [ -n "$best" ]; then
    if [ "$now" = "$best" ]; then
      log run "无需切换: $now 已是最快 (初赛 $bestd ms, 决赛 $bestfin)"
    else
      dosw=1
      # 比较依据同样换成初赛延迟。原先比的是决赛延迟, 当前节点一旦决赛探测超时
      # (curd 为空) 就会被无脑换掉, 哪怕它初赛是全场最快 —— 这正是劣化切换的主因。
      curd1=$(awk -F '\t' -v n="$now" '$2==n{print $1; exit}' $DIR/stage1.txt 2>/dev/null)
      curdf=$(awk -F '\t' -v n="$now" '$2==n{print $1; exit}' $DIR/stage2.txt 2>/dev/null)
      curdfin="未通过"
      [ -n "$curdf" ] && curdfin="${curdf} ms"
      if [ -n "$curd1" ]; then
        # P1-2 净收益判据取代原先的「比当前快 threshold 毫秒就切」:
        # 必须同时满足 提升≥${mingain}ms 且 新延迟≤当前×${minratio}%。
        if ! worth_switching "$curd1" "$bestd"; then
          dosw=0
          log run "保持当前: $now 初赛${curd1}ms/决赛${curdfin} vs 最快 $best 初赛${bestd}ms/决赛${bestfin} (需提升≥${mingain}ms 且 ≤${minratio}%)"
        fi
      else
        log run "当前 $now 初赛无结果(失效或被排除), 将切到 $best (初赛${bestd}ms)"
      fi
      # 切换限速: 两次真实切换之间至少间隔 switch_min_interval 分钟(0=不限)。
      # 只压住「优化类切换」, 故障转移走另一条路径并不受它约束。
      if [ $dosw -eq 1 ] && ! switch_allowed; then dosw=0; fi
      if [ $dosw -eq 1 ]; then
        curl -s -m 8 -X PUT -H "Authorization: Bearer $SECRET" -H 'Content-Type: application/json' -d "{\"name\":\"$(json_esc "$best")\"}" "$API/proxies/$group" >/dev/null 2>&1
        switched=1
        mark_switch
        # 日志补齐 curd1, 事后才分得清「真的更快」还是「当前节点决赛没测出来」
        log run "已切换 $group: $now (初赛${curd1:-无}) -> $best (初赛${bestd}ms, 决赛${bestfin})"
      fi
    fi
  fi

  # 分类测速 (视频/流媒体/AI)
  set_progress "sites" "分类测速(视频/流媒体/AI)" 78
  build_sites_json

  set_progress "switch" "计算最快节点并切换" 90

  # 状态 JSON: top 按初赛排名输出, d=初赛延迟(排名依据), f=决赛延迟(null=未过闸门)
  # 同样 tmp+mv: 页面读的就是这个文件, 半截 JSON 会让 jsonfilter 直接报错。
  # （撕裂读实测数据见 build_nodes_json 的注释）
  local SJ=$DATA/status.json.tmp
  printf '{"ts":%s,"group":"%s","now":"%s","switched":%s,"candidates":%s,"top":[' "$(date +%s)" "$(json_esc "$group")" "$(json_esc "$best")" "$switched" "$n_cand" > $SJ
  i=0
  while IFS="$TAB" read -r d nm; do
    [ -z "$nm" ] && continue
    fd=$(awk -F '\t' -v n="$nm" '$2==n{print $1; exit}' $DIR/stage2.txt 2>/dev/null)
    [ $i -gt 0 ] && printf ',' >> $SJ
    if [ -n "$fd" ]; then
      printf '{"d":%s,"f":%s,"n":"%s"}' "$d" "$fd" "$(json_esc "$nm")" >> $SJ
    else
      printf '{"d":%s,"f":null,"n":"%s"}' "$d" "$(json_esc "$nm")" >> $SJ
    fi
    i=$((i+1))
  done < $DIR/top5d.txt
  printf ']}' >> $SJ
  mv $SJ $DATA/status.json

  top5line=$(head -5 $DIR/top5d.txt | cut -f2 | tr '\n' ' ')   # 历史行只记 Top5
  okn=$(grep -o '"s":"ok"' $DATA/nodes.json | wc -l)
  deadn=$(grep -o '"s":"dead"' $DATA/nodes.json | wc -l)
  faken=$(grep -o '"s":"fake"' $DATA/nodes.json | wc -l)
  echo "$(date '+%F %T') switch=$switched group=$group best=$best $bestd ms 可用=$okn 失效=$deadn 假节点=$faken 决赛=${bestdf:-未通过}ms top: $top5line" >> $DATA/history.log
  tail -50 $DATA/history.log > $DATA/history.tmp 2>/dev/null && mv $DATA/history.tmp $DATA/history.log

  sz=$(wc -c < $LOG 2>/dev/null || echo 0)
  [ "$sz" -gt 204800 ] && mv $LOG $LOG.old
  set_progress "done" "测速完成" 100
  run_mark_clear
  # 记录本轮结束时刻: failover 据此避开测速后的探测拥塞尾巴(见其「静默期」判断)
  date +%s > $DATA/last_run 2>/dev/null
  return 0
}

# ---------- 备用节点预选 ----------
# 把 $DIR/bak_top.txt (延迟<TAB>节点名, 已排序) 写成 $DATA/backup.json
write_backup_json() { # group now probed_count
  local group="$1" now="$2" probed="$3"
  local TAB=$(printf '\t')
  local j=0
  printf '{"ts":%s,"group":"%s","now":"%s","probed":%s,"list":[' "$(date +%s)" "$(json_esc "$group")" "$(json_esc "$now")" "$probed" > $DATA/backup.json
  while IFS="$TAB" read -r d nm; do
    [ -z "$nm" ] && continue
    [ $j -gt 0 ] && printf ',' >> $DATA/backup.json
    printf '{"n":"%s","d":%s}' "$(json_esc "$nm")" "$d" >> $DATA/backup.json
    j=$((j+1))
  done < $DIR/bak_top.txt
  printf ']}' >> $DATA/backup.json
  date +%s > $DATA/last_backup
}

backup_do() {
  v=$(api_get /version)
  if ! echo "$v" | grep -q version; then
    log backup "OpenClash API 不可达, 跳过"
    return 1
  fi

  local group=$(get group); [ -z "$group" ] && group='宝贝云'
  local tu=$(get test_url); [ -z "$tu" ] && tu='https://www.gstatic.com/generate_204'
  local thr=$(get failover_threshold); [ -z "$thr" ] && thr=3000
  local probe=$(get backup_probe); [ -z "$probe" ] && probe=8
  local keep=$(get backup_keep); [ -z "$keep" ] && keep=3
  local to=$(get timeout); [ -z "$to" ] && to=4000

  local cur=$(api_get "/proxies/$group" | grep -o '"now":"[^"]*"' | head -1 | cut -d'"' -f4)
  local TAB=$(printf '\t')
  # cur 为空时 grep -vF "" 会把所有行都过滤掉, 用一个不可能出现的哨兵兜住
  local curf="$cur"
  [ -z "$curf" ] && curf='__none__'

  # 候选池: 优先持久化的 nodes.json (带上次延迟, 跨重启可用), 退回持久化的 candidates.txt
  # 必须按上次延迟升序再取前 probe 个 —— 原先直接 head -probe 取的是 nodes.json 的书写
  # 顺序(也就是订阅顺序), 实测会漏掉比入选者更快的中转节点, 「预选最快节点」名不副实。
  : > $DIR/bak_cand.txt
  tr '{' '\n' < $DATA/nodes.json 2>/dev/null \
    | grep '"d":[0-9]*,"s":"ok"' \
    | sed 's#.*"n":"\([^"]*\)".*"d":\([0-9]*\).*#\2'"$TAB"'\1#' \
    | sort -n | grep -vF "$curf" | cut -f2 | head -$probe > $DIR/bak_cand.txt
  [ -s $DIR/bak_cand.txt ] || {
    grep -vF "$curf" $DATA/candidates.txt 2>/dev/null | head -$probe > $DIR/bak_cand.txt
  }
  [ -s $DIR/bak_cand.txt ] || { log backup "无候选节点, 跳过"; return 1; }

  local n_total=$(wc -l < $DIR/bak_cand.txt)
  : > $DIR/bak_res.txt
  : > $DIR/bak_par.out
  local i=0
  while read -r name; do
    [ -z "$name" ] && continue
    # 不再按 failover_threshold 预筛: 阈值内的节点常常只有一两个,
    # 一旦它们也超时就没有退路。备用池改为「有响应即收录, 按延迟升序保留」,
    # 真断网时一个 3 秒的节点也强过没有节点。
    ( d=$(node_delay "$name" "$tu" "$to")
      [ -n "$d" ] && printf '%s\t%s\n' "$d" "$name" >> $DIR/bak_par.out ) &
    i=$((i+1))
    [ $i -ge 4 ] && { wait; i=0; }
  done < $DIR/bak_cand.txt
  wait
  cat $DIR/bak_par.out >> $DIR/bak_res.txt 2>/dev/null
  rm -f $DIR/bak_par.out
  sort -n $DIR/bak_res.txt > $DIR/bak_res.tmp 2>/dev/null && mv $DIR/bak_res.tmp $DIR/bak_res.txt

  # P1-1 同源约束: 同一落地最多收录 1 个, 并且尽量避开当前节点所在的落地。
  # 候选不足时降级允许同落地 —— 宁可同源也不要空池。
  if [ "$(get failover_avoid_same_landing)" != "0" ]; then
    pick_diverse $DIR/bak_res.txt "$keep" "$(node_landing "$cur")" > $DIR/bak_top.txt
    if [ "$(wc -l < $DIR/bak_top.txt)" -lt "$keep" ]; then
      log backup "备用池: 异落地候选不足, 降级允许与 $cur 同落地的节点"
      pick_diverse $DIR/bak_res.txt "$keep" "" > $DIR/bak_top.txt
    fi
  else
    head -$keep $DIR/bak_res.txt > $DIR/bak_top.txt
  fi
  local n_keep=$(wc -l < $DIR/bak_top.txt)
  write_backup_json "$group" "$cur" "$n_total"

  if [ "$n_keep" -gt 0 ]; then
    log backup "已预选 $n_keep 个备用节点 (探测 $n_total): $(cut -f2 $DIR/bak_top.txt | tr '\n' ' ')| 当前 $cur"
  else
    log backup "候选节点全部超时 (探测 $n_total), 未选出备用节点"
  fi
  return 0
}

# cron 每分钟唤起, 这里按 backup_interval 自检时间戳决定是否真跑。
# 不用 */90: cron 分钟字段最大 59, 写不出 90 分钟周期。
# 自检还有个好处 —— 设备每天 02:00 自动重启, 固定时间点会被跳过, 自检不会。
backup_select() {
  [ "$(get backup_enable)" = "0" ] && return 0
  # 残留自愈必须排在间隔检查【之前】: 否则间隔没到就提前 return,
  # 陈旧标记会一直挂着, 最长要等一个完整间隔(90 分钟)才被清掉。
  # 与主测速互斥: 两边都用 mkdir 锁 + $DATA/running 标记(带超时自愈)
  run_busy && return 0
  local iv=$(get backup_interval); [ -z "$iv" ] && iv=90
  local now=$(date +%s)
  local last=$(cat $DATA/last_backup 2>/dev/null || echo 0)
  [ $((now - last)) -lt $((iv * 60)) ] && return 0
  mkdir $DIR/lock 2>/dev/null || return 0
  trap 'rmdir $DIR/lock 2>/dev/null; rm -f $DATA/running 2>/dev/null' EXIT INT TERM
  run_mark_set
  backup_do
  local rc=$?
  run_mark_clear
  return $rc
}

# 把策略组切到指定节点。集中一处是为了让切换/验证/回滚三处用同一段 escaping,
# 免得哪天某个节点名带引号时只有一条路径漏掉 json_esc。
do_switch_node() { # group name
  [ -z "$2" ] && return 1
  curl -s -m 8 -X PUT -H "Authorization: Bearer $SECRET" -H 'Content-Type: application/json' \
    -d "{\"name\":\"$(json_esc "$2")\"}" "$API/proxies/$1" >/dev/null 2>&1
}

failover_check() { # 断线自动故障转移
  run_busy && return 0
  local now=$(date +%s)
  # 冷却时间戳放 overlay: 原先在 /tmp, 每天 02:00 重启后被清零, 冷却形同虚设
  local last=$(cat $DATA/last_failover 2>/dev/null || cat $DIR/last_failover 2>/dev/null || echo 0)
  local cd=$(get failover_cooldown); [ -z "$cd" ] && cd=120
  [ $((now - last)) -lt $cd ] && return 0
  v=$(api_get /version)
  echo "$v" | grep -q version || { log failover "API不可达, 跳过"; return 0; }
  local group=$(get group); [ -z "$group" ] && group='宝贝云'
  local cur=$(api_get "/proxies/$group" | grep -o '"now":"[^"]*"' | head -1 | cut -d'"' -f4)
  [ -z "$cur" ] && return 0
  case "$cur" in GLOBAL|DIRECT|REJECT|REJECT-DROP|COMPATIBLE|PASS|PASS-RULE|自动选择|延迟最低|宝贝云) return 0 ;; esac
  # 静默期: 一轮 65+ 节点全量测速结束后, mihomo 的延迟探测通道会留下十几秒的
  # 拥塞尾巴, 此时连刚测过、延迟正常的节点都会返回超时。
  # 对照日志可见: 20:09:46 测速 -> 20:11:01 全超时, 20:11:21 测速 -> 20:14:20 全超时。
  # v3.4 起它只记一个标记、不再直接 return —— 硬故障必须能越过它(见 P0-4 判定)。
  local lr=$(cat $DATA/last_run 2>/dev/null || echo 0)
  local quiet=$(get failover_quiet); [ -z "$quiet" ] && quiet=90
  local inquiet=0
  if [ "$lr" -gt 0 ] && [ $((now - lr)) -lt $quiet ]; then
    inquiet=1
  fi
  local thr=$(get failover_threshold); [ -z "$thr" ] && thr=3000
  local tu=$(get test_url); [ -z "$tu" ] && tu='https://www.gstatic.com/generate_204'
  local TAB=$(printf '\t')
  # 故障通道里的回退次数压到 1(可用 failover_maxalt 调)。
  # probe_delay_multi 每次尝试最坏 8s, 默认最多 4 次 —— 死节点要连吃 32s 才肯认输,
  # 而这里一分钟内要跑完「首探 + 复测 + 对照 + 候选 + 验证」五段。
  # 省掉的是死节点的等待: 活节点第一次就返回, 根本用不到回退。
  local ma=$(get failover_maxalt); [ -z "$ma" ] && ma=1
  local d=$(probe_delay_multi "$cur" 5000 "$ma")
  if [ -z "$d" ] || [ "$d" -gt "$thr" ]; then
    # 抖动过滤: 首探失败不立刻判故障, 隔 3 秒复测一次。
    # 单次超时常常只是瞬时拥塞(测速尾巴、上游抖动), 一次就切换既没必要,
    # 还容易从 270ms 的好节点切到 800ms 的差节点。
    sleep 3
    local d2=$(probe_delay_multi "$cur" 5000 "$ma")
    if [ -n "$d2" ] && [ "$d2" -le "$thr" ]; then
      log failover "瞬时抖动已恢复: $cur 首探${d:-超时}ms -> 复测 ${d2}ms"
      return 0
    fi
    d="$d2"
  fi
  if [ -n "$d" ] && [ "$d" -le "$thr" ]; then
    log failover "正常: $cur $d ms"
    return 0
  fi
  log failover "异常: $cur ${d:-超时}ms (阈值$thr ms, 已二次复测), 开始故障判定"

  # ---- P0-2 / P0-3 / P0-4: 三层对照, 决定「该不该切」 ----
  # 「当前节点测不通」本身不足以证明节点故障 —— 本机链路断了、探测点被干扰、
  # 整体出口拥塞、刚跑完一轮全量测速, 都会让所有节点在同一时刻一起返回空。
  # 三条同时成立才认定硬故障, 缺一条都不切、只记日志:
  #   1. 本地链路正常(出口接口 up 且直连 ping 通) —— 排除拔网线 / 光猫 / 上游故障
  #   2. 对照节点有响应                          —— 排除探测点与整体链路问题
  #   3. 当前节点全部探针无响应(上面已二次复测)   —— 排除单探针单次抖动
  # 好处: 原先靠「静默期 + 冷却」硬挡的测速尾巴伪故障, 现在被第 2 条自动吸收,
  #       于是静默期不必再把真故障一起挡在外面。
  local hard=0
  if local_link_ok; then
    if ref_nodes_alive "$cur"; then hard=1; fi
  fi
  if [ "$hard" -eq 0 ]; then
    local short=$cd; [ "$short" -gt 60 ] && short=60
    if ! date -d "@$(( now - (cd - short) ))" +%s > $DATA/last_failover 2>/dev/null; then
      date +%s > $DATA/last_failover
    fi
    log failover "判定: 非单节点故障(本地链路/对照探针未通过), 保持 $cur 不动, ${short}s 后重判"
    return 0
  fi
  [ "$inquiet" -eq 1 ] && log failover "硬故障成立, 越过静默期 (全量测速刚结束 $((now-lr))s)"

  local best="" bestd=0 bsrc=""
  : > $DIR/fo_probe.txt

  # 优先用预先选好的备用节点短名单: 每个只需一次探测, 比当场探测 Top5 快一个量级。
  if [ "$(get backup_enable)" != "0" ] && [ -f $DATA/backup.json ]; then
    local biv=$(get backup_interval); [ -z "$biv" ] && biv=90
    local bts=$(grep -o '"ts":[0-9]*' $DATA/backup.json 2>/dev/null | head -1 | cut -d: -f2)
    local bage=$((now - ${bts:-0}))
    # 名单最多接受 3 倍间隔的陈旧度; 超期说明预选已停摆, 数据不可信, 退回实时探测
    if [ -n "$bts" ] && [ "$bage" -le $((biv * 60 * 3)) ]; then
      grep -o '"n":"[^"]*","d":[0-9]*' $DATA/backup.json 2>/dev/null \
        | sed 's#"n":"##; s#","d".*##' | grep -vxF "$cur" > $DIR/bak_list.txt
      # P1-4 改成 4 路并发: 串行时 3 个节点要 ~7s, 名单过期走 Top5 更要 15s+,
      # 而 MTTR 的目标是一分钟以内。
      # 不再按 failover_threshold 预筛 —— 阈值内的节点常常只有一两个, 一旦它们
      # 也超时就没有退路; 有响应即收录, 最后统一按延迟升序排。
      : > $DIR/pl_dead.txt
      probe_list_parallel $DIR/bak_list.txt $DIR/fo_probe.txt 4 "$ma"
      [ -s $DIR/fo_probe.txt ] && bsrc="备用名单"
      [ -s $DIR/fo_probe.txt ] || log failover "备用名单节点全部无响应 ($(tr '\n' ' ' < $DIR/bak_list.txt))"
    else
      log failover "备用名单已过期 (${bage}s), 改用实时探测"
    fi
  fi

  # 备用名单没命中, 退回原有逻辑: 从上次全量结果里取 Top5 当场探测
  if [ ! -s $DIR/fo_probe.txt ]; then
    tr '{' '\n' < $DATA/nodes.json 2>/dev/null \
      | grep '"d":[0-9]*,"s":"ok"' \
      | sed 's#.*"n":"\([^"]*\)".*"d":\([0-9]*\).*#\2'"$TAB"'\1#' \
      | sort -n | grep -vF "$cur" | cut -f2 | head -5 > $DIR/failover_list.txt
    [ -s $DIR/failover_list.txt ] || {
      cp $DATA/candidates.txt $DIR/failover_list.txt 2>/dev/null
      [ -s $DIR/failover_list.txt ] || cp $DIR/candidates.txt $DIR/failover_list.txt 2>/dev/null
      grep -vF "$cur" $DIR/failover_list.txt > $DIR/failover_list.tmp 2>/dev/null && mv $DIR/failover_list.tmp $DIR/failover_list.txt
    }
    probe_list_parallel $DIR/failover_list.txt $DIR/fo_probe.txt 4 "$ma"
    [ -s $DIR/fo_probe.txt ] && bsrc="实时探测"
  fi

  # ---- P1-3 逐个候选切换 + 切换后验证 ----
  # 原先是「探测出一个最快的就切」, 切完不管: 历史上有相当比例的切换最后是劣化,
  # 甚至切到一个同样不可用的目标。现在按延迟升序最多试 failover_verify_tries 个,
  # 每切一个都复测一次确认真的通了才收工。
  local tries=$(get failover_verify_tries); [ -z "$tries" ] && tries=3
  [ "$(get failover_verify)" = "0" ] && tries=1
  local verify=$(get failover_verify); [ -z "$verify" ] && verify=1
  local tried=0 done_sw=0 nm dd
  while IFS="$TAB" read -r dd nm; do
    [ -z "$nm" ] && continue
    [ "$nm" = "$cur" ] && continue
    [ "$tried" -ge "$tries" ] && break
    tried=$((tried+1))
    # </dev/null: 这个循环正在从 fo_probe.txt 读, 万一将来某条命令去啃 stdin,
    # 剩下的候选会整段读歪(静默少试几个节点)。这一行是保险丝。
    do_switch_node "$group" "$nm" </dev/null
    if [ "$verify" != "0" ]; then
      sleep 3
      local vd=$(probe_delay_multi "$nm" 5000 2)
      if [ -z "$vd" ]; then
        log failover "候选不可用: $nm 切换后复测仍无响应, 试下一个"
        continue
      fi
      log failover "候选已验证: $nm 复测 ${vd}ms"
      dd=$vd
    fi
    best="$nm"; bestd=$dd; done_sw=1
    break
  done < $DIR/fo_probe.txt

  if [ "$done_sw" -eq 1 ] && [ -n "$best" ]; then
    # P1-3 劣化回滚: 如果刚被判死的原节点转眼就恢复了, 而且明显更快(≥2 倍),
    # 说明刚才那一下更像瞬时抖动, 切回去。2 倍的门槛足够宽, 不会来回抖。
    if [ "$verify" != "0" ] && [ "$(get failover_rollback)" != "0" ]; then
      local od=$(probe_delay_multi "$cur" 5000 2)
      if [ -n "$od" ] && [ $((od * 2)) -le "$bestd" ]; then
        do_switch_node "$group" "$cur"
        sleep 2
        local od2=$(probe_delay_multi "$cur" 5000 2)
        if [ -n "$od2" ]; then
          log failover "回滚: 原节点 $cur 已恢复且明显更快 (${od}ms vs $best ${bestd}ms), 已切回"
          best="$cur"; bestd=$od2; bsrc="$bsrc+回滚"
        else
          log failover "回滚失败: 原节点 $cur 复测又断了, 保持 $best"
          do_switch_node "$group" "$best"
        fi
      fi
    fi
    date +%s > $DATA/last_failover
    mark_switch
    # 备用名单已被消耗 (切换目标成了新的当前节点), 下一分钟立刻重新预选
    rm -f $DATA/last_backup 2>/dev/null
    log failover "已故障转移($bsrc): $cur -> $best ($bestd ms)"
  else
    # 切换失败只压短冷却: 原逻辑在这里同样写满 failover_cooldown(默认120s),
    # 结果是最需要重试的时刻反而等待最久。
    local short=$cd; [ "$short" -gt 30 ] && short=30
    if ! date -d "@$(( now - (cd - short) ))" +%s > $DATA/last_failover 2>/dev/null; then
      date +%s > $DATA/last_failover
    fi
    log failover "无可用备用节点, 保持 $cur (${short}s 后重试)"
    log failover "诊断: 备用节点全部无响应且切换均未通过验证, 更像机场侧整体故障"
  fi
}

cron_apply() {
  local iv
  iv=$(get interval); [ -z "$iv" ] && iv=30
  sed -i '/ocspeed-auto/d; /ocspeed-failover/d; /ocspeed-backup/d; /speedswitch.sh run/d; /speedswitch.sh failover/d; /speedswitch.sh backup/d' /etc/crontabs/root 2>/dev/null
  if [ "$(get enabled)" = "1" ]; then
    echo "#ocspeed-auto" >> /etc/crontabs/root
    echo "*/$iv * * * * /usr/libexec/openclash-helper/speedswitch.sh run >>/var/log/ocspeed.log 2>&1" >> /etc/crontabs/root
  fi
  if [ "$(get failover_enable)" = "1" ]; then
    echo "#ocspeed-failover" >> /etc/crontabs/root
    echo "* * * * * /usr/libexec/openclash-helper/speedswitch.sh failover >>/var/log/ocspeed.log 2>&1" >> /etc/crontabs/root
  fi
  # 备用节点预选: cron 每分钟唤起, 由脚本自检时间戳决定是否真跑
  if [ "$(get backup_enable)" != "0" ]; then
    echo "#ocspeed-backup" >> /etc/crontabs/root
    echo "* * * * * /usr/libexec/openclash-helper/speedswitch.sh backup >>/var/log/ocspeed.log 2>&1" >> /etc/crontabs/root
  fi
  /etc/init.d/cron restart >/dev/null 2>&1
}

web_status() {
  echo '{'
  echo -n '"running":'; if run_busy; then echo 'true,'; else echo 'false,'; fi
  echo -n '"enabled":'; [ "$(get enabled)" = "1" ] && echo 'true,' || echo 'false,'
  echo -n '"failover_enable":'; [ "$(get failover_enable)" = "1" ] && echo 'true,' || echo 'false,'
  echo -n '"failover_threshold":"'; echo -n "$(get failover_threshold)"; echo '",'
  echo -n '"last_failover":'; cat $DATA/last_failover 2>/dev/null || echo 0
  echo ','
  echo -n '"last_switch":'; cat $DATA/last_switch 2>/dev/null || echo 0
  echo ','
  echo -n '"switch_min_interval":"'; echo -n "$(get switch_min_interval)"; echo '",'
  echo -n '"switch_min_gain":"'; echo -n "$(get switch_min_gain)"; echo '",'
  echo -n '"switch_good_ratio":"'; echo -n "$(get switch_good_ratio)"; echo '",'
  echo -n '"local_ifaces":"'; echo -n "$(json_esc "$(get local_ifaces)")"; echo '",'
  echo -n '"backup_enable":'; [ "$(get backup_enable)" != "0" ] && echo 'true,' || echo 'false,'
  echo -n '"backup_interval":"'; echo -n "$(get backup_interval)"; echo '",'
  echo -n '"backup":'
  cat $DATA/backup.json 2>/dev/null || echo 'null'
  echo ','
  echo -n '"interval":"'; echo -n "$(get interval)"; echo '",'
  echo -n '"threshold":"'; echo -n "$(get threshold)"; echo '",'
  echo -n '"group":"'; echo -n "$(json_esc "$(get group)")"; echo '",'
  echo -n '"test_url":"'; echo -n "$(json_esc "$(get test_url)")"; echo '",'
  echo -n '"gemini_url":"'; echo -n "$(json_esc "$(get gemini_url)")"; echo '",'
  echo -n '"exclude":"'; echo -n "$(json_esc "$(get exclude)")"; echo '",'
  now=$(api_get "/proxies/$(get group)" 2>/dev/null | grep -o '"now":"[^"]*"' | head -1 | cut -d'"' -f4)
  echo -n '"current":"'; echo -n "$(json_esc "$now")"; echo '",'
  echo -n '"last":'
  cat $DATA/status.json 2>/dev/null || echo 'null'
  echo ','
  if [ -f $DATA/nodes.json ]; then
    totaln=$(grep -o '"n":"' $DATA/nodes.json | wc -l)
    okn=$(grep -o '"s":"ok"' $DATA/nodes.json | wc -l)
    deadn=$(grep -o '"s":"dead"' $DATA/nodes.json | wc -l)
    faken=$(grep -o '"s":"fake"' $DATA/nodes.json | wc -l)
    echo -n '"nodes":{"total":'$totaln',"ok":'$okn',"dead":'$deadn',"fake":'$faken'},'
  else
    echo -n '"nodes":{"total":0,"ok":0,"dead":0,"fake":0},'
  fi
  echo -n '"history":['
  if [ -f $DATA/history.log ]; then
    # 逐行转义后再包引号：日志行里含节点名，直接 sed 's/^/"/' 遇到引号就破 JSON
    tail -10 $DATA/history.log | while IFS= read -r hl; do
      printf '"%s",' "$(json_esc "$hl")"
    done | sed 's/,$//'
  fi
  echo ']'
  echo '}'
}

testnode() {
  local name="$1"
  local sites=$(get testsites)
  [ -z "$sites" ] && sites='https://www.baidu.com|https://www.bilibili.com|https://www.taobao.com|https://www.qq.com|https://www.google.com|https://www.youtube.com|https://www.netflix.com|https://github.com|https://gemini.google.com|https://chatgpt.com|https://claude.ai'
  printf '%s' "$sites" | tr '|' '\n' | grep . > $DIR/tsites.list
  printf '{"node":"%s","results":[' "$(json_esc "$name")"
  local i=0
  while read -r s; do
    [ -z "$s" ] && continue
    local label=$(echo "$s" | sed 's|https://||; s|/.*||; s|^www\.||')
    local d=$(node_delay "$name" "$s" 2000)
    [ $i -gt 0 ] && printf ','
    if [ -n "$d" ]; then printf '{"site":"%s","d":%s}' "$(json_esc "$label")" "$d"; else printf '{"site":"%s","d":null}' "$(json_esc "$label")"; fi
    i=$((i+1))
  done < $DIR/tsites.list
  printf ']}'
}

switchnode() {
  local name="$1"
  local group=$(get group); [ -z "$group" ] && group='宝贝云'
  curl -s -m 8 -X PUT -H "Authorization: Bearer $SECRET" -H 'Content-Type: application/json' -d "{\"name\":\"$(json_esc "$name")\"}" "$API/proxies/$group"
}

case "$1" in
  run)     speedtest_full 1 ;;
  testnode) testnode "$2" ;;
  switchnode) switchnode "$2" ;;
  test)    speedtest_full 0 ;;
  nodes)   cat $DATA/nodes.json 2>/dev/null || echo '{"ts":0,"total":0,"nodes":[]}' ;;
  enable)  uci -q set ocspeed.main.enabled='1'; uci commit ocspeed; cron_apply; log cron "已启用自动测速"; echo '{"ok":true}' ;;
  disable) uci -q set ocspeed.main.enabled='0'; uci commit ocspeed; cron_apply; log cron "已停用自动测速"; echo '{"ok":true}' ;;
  status)  web_status ;;
  failover) failover_check ;;
  backup)  backup_select ;;
  backupnow) if run_busy; then
               echo '{"ok":false,"busy":true,"msg":"已有测速在运行"}'
             else
               rm -f $DATA/last_backup 2>/dev/null
               backup_select
               echo '{"ok":true}'
             fi ;;
  backupjson) cat $DATA/backup.json 2>/dev/null || echo '{"ts":0,"group":"","now":"","probed":0,"list":[]}' ;;
  progress) cat $DIR/progress.json 2>/dev/null || echo '{"phase":"idle","msg":"空闲","pct":0}' ;;
  *) echo "usage: $0 run|test|status|nodes|enable|disable|failover|backup|backupnow"; exit 1 ;;
esac
