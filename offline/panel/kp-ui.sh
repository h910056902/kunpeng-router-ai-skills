#!/bin/sh
# ============================================================================
#  kp-ui.sh  v2.1.0 —— 鲲鹏脚本套件共用的「终端界面库」
#
#  只有「打印」，没有任何业务逻辑。换配色/符号/版式只改这一个文件。
#
#  ── v2.1 相对 v2.0 的变化（真机第二轮验证后的修正）────────────────────
#   * _ui_wipe 改用 ANSI EL0（ESC[0m ESC[2K \r）：清行不再依赖猜宽度，
#     每条长任务少吐 71 字节；无色环境自动退回空格铺盖。
#   * 真机确认：设备 busybox **没有 stty**，宽度永远走 72 回落；
#     要窄屏必须显式传 UI_W（已在下方注释里写明）。
#
#  ── v2 相对 v1 的变化（全部向后兼容，v1 的调用一行都不用改）──────────
#   + 宽度自适应（stty size → 上限 76；非 tty 固定 72，与 PC 端 python 对齐）
#   + 进度条左对齐到固定列 —— 阶段标题长度不再影响条形起始位置
#   + ui_run   长任务实时反馈（进行中 → ✓ + 耗时 / ✗ + 日志尾部）
#   + ui_confirm 统一 y/n 交互（非 tty 且未 --yes 时安全中止）
#   + ui_menu  菜单渲染（把助手菜单收进同一套设计语言）
#   + ui_section / ui_legend / ui_hint
#   + ui_die 与 ui_fail 拆开（ui_fail 不再替调用方 exit，见下）
#   + UI_ASCII=1 纯 ASCII 降级（终端不支持 UTF-8 时用）
#   + 四态符号统一为 ✓ · ! ✗，与 device-selftest.py 的 [ OK ]/[WARN]/[FAIL] 语义一一对应
#
#  ── 三条硬约束（v1 踩出来的，v2 一条都没破）──────────────────────────
#   1. 只用 busybox sh + printf。没有 tput，不保证有 bash 数组。
#   2. 中文占 2 列但 ${#s} 按字节算 —— 两者不一致。
#      因此版式一律左对齐，绝不做「右边框 / 右对齐」。
#      v2 的进度条靠「固定列」而不是「算宽度」来对齐，同样不碰这条线。
#   3. 输出被重定向时自动关色（[ -t 1 ] 判断）；UI_COLOR=always|never 可强制。
#
#  ── 用法 ───────────────────────────────────────────────────────────
#   KP_DIR=${0%/*}; [ "$KP_DIR" = "$0" ] && KP_DIR=.
#   . "$KP_DIR/kp-ui.sh"
#
#   ui_init "标题" "副标题"
#   ui_meta 设备 "NRadio C2000 U · aarch64"
#   ui_hr
#   ui_stage 1 4 "环境预检"          # 进度条 + 开始计时
#     ui_ok   "源已切换"
#     ui_run  "拉取镜像 alist" docker pull xhofe/alist
#     ui_warn "veth 未编入"
#     ui_note "这是硬件限制，不是故障。"
#   ui_stage_end                     # 本阶段耗时
#   ...
#   ui_done                          # 收尾（后面接几行 ui_kv）
#   ui_kv 面板 "http://…"
#   ui_hr2
#
#   失败退出：  ui_fail "原因" "怎么办"      # v2：打印后 exit 1（与 v1 同）
#   只想打印：  ui_err  "原因"               # 不退出，由调用方决定
#
#   完整效果预览：  UI_COLOR=always sh preview-v2.sh
# ============================================================================

KP_UI_VERSION=2.1.0

# ============================== 配色 ==============================
case "${UI_COLOR:-auto}" in
  always) _uic=1 ;;
  never)  _uic=0 ;;
  *)      if [ -t 1 ]; then _uic=1; else _uic=0; fi ;;
esac
if [ "$_uic" = 1 ]; then
  C='\033[36m'    # 青 —— 主色：标题、阶段号、进度条
  B='\033[1m'     # 粗 —— 强调
  D='\033[2m'     # 灰 —— 次要信息、说明
  G='\033[32m'    # 绿 —— 成功
  Y='\033[33m'    # 黄 —— 警告
  R='\033[31m'    # 红 —— 失败
  Z='\033[0m'     # 复位
else
  C=; B=; D=; G=; Y=; R=; Z=
fi

# ============================== 符号（ASCII 降级）==============================
if [ "${UI_ASCII:-0}" = 1 ]; then
  S_OK='+'; S_INFO='-'; S_WARN='!'; S_ERR='x'; S_TIME='>'
  S_ON='#'; S_OFF='-'; S_HR='-'; S_HR2='='
else
  S_OK='✓'; S_INFO='·'; S_WARN='!'; S_ERR='✗'; S_TIME='↳'
  S_ON='█'; S_OFF='░'; S_HR='─'; S_HR2='═'
fi

# ============================== 内部状态 ==============================
UI_T0=$(date +%s)         # 脚本起始时间
_ui_t0=0                  # 当前阶段起始时间
_ui_spent=0               # 已完成阶段累计秒数
_ui_done_n=0              # 已完成阶段数
UI_LOG=${UI_LOG:-/tmp/kp-ui.log}

# 宽度：UI_W 显式给定就听它的；否则自适应
# ⚠️ 2026-09-23 真机修正：设备端 busybox **没有 stty**（`busybox stty size` →
#    `stty: applet not found`，/bin /usr/bin /usr/sbin 下也都找不到），
#    且 `TERM`/`COLUMNS` 在 exec 通道里都是 unset。所以 stty 这条路在真机上
#    永远拿不到值 —— 保留它只是为了兼容「有 stty 的宿主环境」（如 PC 侧 bash），
#    真机上会稳定回落到 72。要窄屏就显式传 UI_W。
_ui_pick_w() {
  if [ -n "${UI_W:-}" ]; then
    case "$UI_W" in ''|*[!0-9]*) UI_W=72 ;; esac
    return
  fi
  _w=''
  if command -v stty >/dev/null 2>&1; then
    _w=$(stty size 2>/dev/null </dev/tty | awk 'NF==2{print $2}')
  fi
  case "$_w" in ''|*[!0-9]*) _w=${COLUMNS:-0} ;; esac
  case "$_w" in ''|*[!0-9]*) _w=0 ;; esac
  if [ "$_w" -ge 44 ]; then
    _w=$((_w - 4))
    [ "$_w" -gt 76 ] && _w=76
  else
    _w=72
  fi
  UI_W=$_w
}
_ui_pick_w

# ============================== 底料 ==============================
_rep() {
  printf "$2"
  n=$UI_W
  while [ "$n" -gt 0 ]; do printf '%s' "$1"; n=$((n - 1)); done
  printf "$Z\n"
}

ui_hr()  { _rep "$S_HR"  "$D"; }   # 细线：段落分隔
ui_hr2() { _rep "$S_HR2" "$G"; }   # 粗线：整体收尾

ui_hms() {
  if [ "$1" -lt 60 ]; then printf '%ss' "$1"
  else printf '%dm%02ds' "$(( $1 / 60 ))" "$(( $1 % 60 ))"; fi
}

# 剩余时间粗估：按已完成阶段的平均耗时外推
# 只在「阶段均耗时 ≥ 5s 且剩余 ≥ 3s」时才显示 —— 秒级脚本上标 ETA 是噪音
_ui_eta() {
  [ "$_ui_done_n" -lt 1 ] && return
  _tot=$1; _avg=$(( _ui_spent / _ui_done_n ))
  [ "$_avg" -lt 5 ] && return
  _left=$(( ($_tot - $_ui_done_n) * _avg ))
  [ "$_left" -ge 3 ] && printf '%s' " · 预计还需 $(ui_hms $_left)"
}

# ============================== 头部 ==============================
ui_init() {
  printf '\n'
  ui_hr
  printf "  $B$C%s$Z\n" "$1"
  [ -n "${2:-}" ] && printf "  $D%s$Z\n" "$2"
  ui_hr
}

ui_meta() { printf "  $D%s$Z  %s\n" "$1" "$2"; }   # 标签统一 2 个汉字才对齐

# 一行提示（用于说明强制开关，如 UI_COLOR）
ui_hint() { printf "  $D%s$Z\n" "$*"; }

# ============================== 阶段 ==============================
# 进度条固定画在 [ %2s/%2s] 之后的第 8 列 —— 标题再长也不影响条形起始位置
ui_stage() {
  _ui_t0=$(date +%s)
  printf "\n$B$C[%2s/%-2s]$Z " "$1" "$2"
  ui_bar "$1" "$2"
  printf "  $B%s$Z$D%s$Z\n" "$3" "$(_ui_eta "$2")"
}

# ⚠️ 2026-09-23 真机修正：< 1s 也打耗时。原来显示「↳ 完成」，但设备端快阶段
#    极多，一屏里挤满「完成」反而看不出哪个阶段真慢 —— 统一成数字更可读。
ui_stage_end() {
  _d=$(( $(date +%s) - _ui_t0 ))
  _ui_spent=$((_ui_spent + _d)); _ui_done_n=$((_ui_done_n + 1))
  printf "  $D%s %s$Z\n" "$S_TIME" "$(ui_hms $_d)"
}

ui_bar() {
  n=20
  f=$(( n * $1 / $2 ))
  printf "$C"
  i=0; while [ "$i" -lt "$f" ]; do printf '%s' "$S_ON";  i=$((i + 1)); done
  printf "$D"
  i=$f; while [ "$i" -lt "$n" ]; do printf '%s' "$S_OFF"; i=$((i + 1)); done
  printf "$Z"
}

# ============================== 条目 ==============================
ui_ok()   { printf "  $G%s$Z %s\n" "$S_OK"   "$*"; }
ui_info() { printf "  $D%s$Z %s\n" "$S_INFO" "$*"; }
ui_warn() { printf "  $Y%s$Z %s\n" "$S_WARN" "$*"; }
ui_err()  { printf "  $R%s$Z %s\n" "$S_ERR"  "$*" >&2; }
ui_note() { printf "    $D%s$Z\n" "$*"; }
ui_kv()   { printf "  $D%s$Z  %s\n" "$1" "$2"; }
ui_gap()  { printf '\n'; }

# ============================== 长任务 ==============================
# ⚠️ 2026-09-23 真机修正（第 2 版）：清行用 ANSI 的「抹到行尾」EL0（ESC[2K）。
#
#   为什么不用 v2 初版的 '\r + 79 空格 + \r'：
#     它在功能上是对的，但每条长任务都要多吐 81 个字节，而且**只清到第 79 列**。
#     更关键的是，它清不掉「比 79 列更宽的超宽终端」上的残留。
#
#   为什么 EL0 是对的：
#     ESC[2K 让**终端自己**把光标到行尾整段抹掉，服务端一个字节都不用算宽度。
#     真机 PTY 实测（80 列，四候选并排对照）：
#       A \r+79空格+\r   渲染干净，+81B
#       B ESC[2K + \r    渲染干净，+5B     ← 采用
#       D ESC[0m+ESC[2K+\r  渲染干净，+10B ← 采用（多一个复位，见下）
#     三种在真终端上观感无差别，B/D 字节数少一个数量级。
#
#   为什么最终选 D（先复位再抹）而不是裸 B：
#     若上一段输出把前景/背景色留在「激活」状态，ESC[2K 会用**那个背景色**去填抹掉
#     的区域，某些终端上会留下一条色带。先 ESC[0m 复位再抹，这是唯一稳妥的顺序。
#
#   兜底：ESC[2K 依赖终端实现（ECMA-48，PuTTY/Windows Terminal/SecureCRT/iTerm2/
#     xterm 全都支持）。若关掉了颜色（UI_COLOR=never / 非 tty），说明我们不确定
#     对方是不是 ANSI 终端，这时退回空格铺盖 —— 此时输出本来就是给人看的管道/日志，
#     多一点空格无害。
if [ "$_uic" = 1 ]; then
  # 彩色 => 确定是 ANSI 终端 => 用最省的 EL0
  _ui_wipe() { printf '\033[0m\033[2K\r'; }
else
  # 无色 => 可能是不认 ANSI 的环境 => 空格铺盖（\r 只回列首，必须自己盖满）
  _ui_wipe() { printf '\r%-79s\r' ''; }
fi

# ui_run "标签" 命令 参数…   —— 进行中 → 成功 ✓ + 耗时 / 失败 ✗ + 日志尾部
# 输出默认写 $UI_LOG（默认 /tmp/kp-ui.log），只回显尾部，避免刷屏
ui_run() {
  _lbl=$1; shift
  _t=$(date +%s)
  if [ "$_uic" = 1 ]; then
    printf "  $D%s$Z %s …" "$S_INFO" "$_lbl"
  else
    printf "  %s %s ...\n" "$S_INFO" "$_lbl"
  fi
  : > "$UI_LOG" 2>/dev/null
  if "$@" >>"$UI_LOG" 2>&1; then _rc=0; else _rc=$?; fi
  _d=$(( $(date +%s) - _t ))
  [ "$_uic" = 1 ] && _ui_wipe
  if [ "$_rc" = 0 ]; then
    ui_ok "$_lbl$([ "$_d" -ge 1 ] && printf '  %s' "$(ui_hms $_d)")"
  else
    ui_err "$_lbl 失败（rc=$_rc）"
    _tail=$(tail -n 3 "$UI_LOG" 2>/dev/null)
    [ -n "$_tail" ] && printf '%s\n' "$_tail" | while IFS= read -r _l; do
      [ -n "$_l" ] && ui_note "$_l"
    done
  fi
  return $_rc
}

# ============================== 交互 ==============================
# ui_confirm "问题" ["说明"] —— 返回 0 同意 / 1 不同意
#   KP_YES=1  → 全部自动同意（无人值守/自动化用），不读 stdin
#   非 tty 且未设 KP_YES → 一律拒绝，绝不静默继续
ui_confirm() {
  _q=$1; _note=${2:-}
  if [ "${KP_YES:-0}" = 1 ]; then
    printf "  $G%s$Z %s  $D（KP_YES=1 自动确认）$Z\n" "$S_OK" "$_q"
    return 0
  fi
  if [ ! -t 0 ]; then
    ui_warn "$_q —— 当前非交互环境，默认拒绝"
    [ -n "$_note" ] && ui_note "$_note"
    ui_note "要跳过确认请显式加 KP_YES=1"
    return 1
  fi
  printf "  $Y?$Z %s " "$_q"
  [ -n "$_note" ] && printf "\n    $D%s$Z\n  " "$_note"
  printf "$D[y/N]$Z "
  read -r _a 2>/dev/null || _a=n
  case "$_a" in y|Y|yes|YES) printf "  $G%s 已确认$Z\n" "$S_OK"; return 0 ;;
  *)                        printf "  $D%s 已取消$Z\n" "$S_INFO"; return 1 ;;
  esac
}

# ============================== 菜单 ==============================
# 把项目自己的助手菜单收进同一套设计语言（原来菜单是裸文本，与安装流程两套观感）
ui_menu_head() {
  printf '\n'
  printf "  $B$C%s$Z\n" "$1"
  [ -n "${2:-}" ] && printf "  $D%s$Z\n" "$2"
  printf "  $D"
  n=$((UI_W - 2)); while [ "$n" -gt 0 ]; do printf '%s' "$S_HR"; n=$((n - 1)); done
  printf "$Z\n"
}
ui_menu_item() { printf "  $C%2s$Z) $B%s$Z  $D%s$Z\n" "$1" "$2" "${3:-}"; }
ui_menu_off()  { printf "  $D%2s$Z) %s   $D%s$Z\n" "$1" "$2" "${3:-（尚未开放）}"; }
ui_menu_foot() { printf '\n' ; printf "  $D%s$Z\n" "${1:-多选：空格分隔，如 2 5；直接回车执行默认项}"; }

# ============================== 分段 / 图例 ==============================
ui_section() { printf "\n  $B%s$Z\n" "$1"; printf "  $D"; n=$((UI_W - 2)); while [ "$n" -gt 0 ]; do printf '%s' "$S_HR"; n=$((n - 1)); done; printf "$Z\n"; }

ui_legend() {
  printf "  $D图例$Z   $G%s$Z 通过   $D%s$Z 中性   $Y%s$Z 建议   $R%s$Z 必须处理\n" \
    "$S_OK" "$S_INFO" "$S_WARN" "$S_ERR"
}

# ============================== 收尾 ==============================
# 只打印不退出（供自定义处理）
ui_fail_soft() {
  printf "\n  $R$B%s %s$Z\n" "$S_ERR" "$1" >&2
  [ -n "${2:-}" ] && printf "    $D→ %s$Z\n" "$2" >&2
}

# 打印 + 退出（v1 的 ui_fail 行为，保持不变）
ui_fail() {
  ui_fail_soft "$1" "${2:-}"
  printf "  $D脚本已停止。修好后重跑即可 —— 本套件幂等，不会重复安装。$Z\n\n" >&2
  exit 1
}

ui_done() {
  printf '\n'
  printf "  $B$G%s 全部完成$Z   $D总用时 %s$Z\n" "$S_OK" "$(ui_hms $(( $(date +%s) - UI_T0 )))"
  ui_hr
}
