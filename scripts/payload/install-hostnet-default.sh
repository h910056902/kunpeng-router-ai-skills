#!/bin/sh
# ============================================================================
# install-hostnet-default.sh —— 让 1Panel 应用默认走 host 网络（设备端执行）
#
# 背景（一句话）：本机内核没有 veth，docker 桥接网络物理不可用，而 1Panel 应用
# 模板一律用 bridge 外部网络 `1panel-network` → 面板装应用必失败。本脚本把
# 「host 网络」做成默认行为（wrapper 拦截），并把已有应用一次性转过来。
#
# 用法（在设备上，与 kp-compose-host.sh / docker-compose.wrapper 同目录）：
#   sh install-hostnet-default.sh              # 安装（幂等）
#   sh install-hostnet-default.sh --dry-run    # 只报告，不写任何文件
#   sh install-hostnet-default.sh --up         # 安装后把存量应用 up 起来
#   sh install-hostnet-default.sh --restore    # 回滚：恢复原 docker-compose
#
# 安装内容：
#   /usr/sbin/kp-compose-host      ← kp-compose-host.sh      转换器
#   /usr/bin/docker-compose.real   ← 原 docker-compose（改名保留，**不删除**）
#   /usr/bin/docker-compose        ← docker-compose.wrapper  包装器
#
# 回滚：--restore 会把 docker-compose.real 还原成 docker-compose
#       （转换器与 .bridge.bak 保留，便于再查）
#
# 兼容：busybox ash —— 不用花括号展开、不用 $LINENO、不认 trap ERR（只用 EXIT）
# ============================================================================

set -u

MODE=install
DO_UP=0
DRY=0
for a in "$@"; do
  case "$a" in
    --restore) MODE=restore ;;
    --dry-run) DRY=1 ;;
    --up)      DO_UP=1 ;;
    -h|--help) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "未知参数: $a（--dry-run / --up / --restore）" >&2; exit 2 ;;
  esac
done

# 脚本自身目录（**禁用 dirname**：本机 bash 工具链缺 dirname，设备端也不保证有）
SRC="${0%/*}"
[ "$SRC" = "$0" ] && SRC="."
KPH_SRC="$SRC/kp-compose-host.sh"
WPR_SRC="$SRC/docker-compose.wrapper"

KPH=/usr/sbin/kp-compose-host
COMPOSE=/usr/bin/docker-compose
REAL=/usr/bin/docker-compose.real
LOG=/tmp/kp-compose.log

say()  { echo "[hostnet] $*"; }
warn() { echo "[hostnet][WARN] $*" >&2; }
die()  { echo "[hostnet][FATAL] $*" >&2; exit 1; }

[ "$(id -u)" = "0" ] || die "必须以 root 运行"

# ---- 1Panel 数据目录：从 1pctl 回读，回读不到就按默认 ----
# ⚠️ 不能假设 `APPS="$BASE/apps"`。1Panel 标准布局是
#     <base_dir>/1panel/{apps,db,resource,conf}
#   而装机时填的"安装目录"可能本身就带 /1panel 后缀（于是根变成 …/1panel/1panel）。
#   实测证据：$BASE_DIR/1panel/db/1Panel.db 存在（7.5M）。
#   所以判据用"根下有 db/ 或 resource/ 或 apps/"，逐个候选试。
BASE="$(sed -n 's/^BASE_DIR=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1)"
BASE="${BASE:-/opt}"
PANEL_ROOT=""
for c in "$BASE/1panel" "$BASE"; do
  if [ -d "$c/db" ] || [ -d "$c/resource" ] || [ -d "$c/apps" ]; then PANEL_ROOT="$c"; break; fi
done
[ -n "$PANEL_ROOT" ] || PANEL_ROOT="$BASE/1panel"
APPS="$PANEL_ROOT/apps"
say "1Panel 根目录: $PANEL_ROOT（应用目录: $APPS）"

# ============================ 回滚分支 ============================
if [ "$MODE" = "restore" ]; then
  [ -x "$REAL" ] || die "找不到 $REAL，无法回滚（可能已经回滚过）"
  if [ "$DRY" = "1" ]; then
    say "DRY-RUN: mv -f $REAL $COMPOSE"
    exit 0
  fi
  mv -f "$REAL" "$COMPOSE" || die "回滚失败：$REAL → $COMPOSE"
  say "已回滚：$COMPOSE 恢复为原始 docker-compose（wrapper 已移除）"
  say "注意：已转换过的 compose 文件仍是 host 模式；需要恢复 bridge 请用同目录的 *.bridge.bak"
  exit 0
fi

# ============================ 安装分支 ============================
[ -f "$KPH_SRC" ] || die "缺少 $KPH_SRC（请把 kp-compose-host.sh 与本脚本放在同一目录）"
[ -f "$WPR_SRC" ] || die "缺少 $WPR_SRC（请把 docker-compose.wrapper 与本脚本放在同一目录）"
[ -x "$COMPOSE" ] || die "未找到 $COMPOSE，请先确认 docker-compose 已安装"

# --- 保护：真件不存在时**绝不能**把 wrapper 写上去（否则 docker-compose 永久失效）
if [ ! -x "$REAL" ]; then
  if head -n 3 "$COMPOSE" 2>/dev/null | grep -q 'kp wrapper'; then
    die "$COMPOSE 已经是 wrapper 但 $REAL 缺失 —— 手动恢复：把备份的 docker-compose 放回 $COMPOSE"
  fi
  say "备份真件: $COMPOSE → $REAL"
  [ "$DRY" = "1" ] || cp -fp "$COMPOSE" "$REAL" || die "真件备份失败"
fi
[ -x "$REAL" ] || [ "$DRY" = "1" ] || die "真件 $REAL 不可执行，中止"

# --- 安装转换器 ---
say "安装转换器: $KPH_SRC → $KPH"
if [ "$DRY" != "1" ]; then
  cp -f "$KPH_SRC" "$KPH" || die "转换器安装失败"
  chmod +x "$KPH" || die "转换器 chmod 失败"
  # 语法自检：绝不让未通过检查的脚本上线
  sh -n "$KPH" || die "转换器语法检查失败（sh -n），已中止，未覆盖任何东西"
fi

# --- 安装 wrapper ---
say "安装 wrapper: $WPR_SRC → $COMPOSE（真件保留在 $REAL）"
if [ "$DRY" != "1" ]; then
  cp -f "$WPR_SRC" "$COMPOSE.kpnew" || die "wrapper 写入临时文件失败"
  sh -n "$COMPOSE.kpnew" || { rm -f "$COMPOSE.kpnew"; die "wrapper 语法检查失败，已中止"; }
  chmod +x "$COMPOSE.kpnew" || die "wrapper chmod 失败"
  mv -f "$COMPOSE.kpnew" "$COMPOSE" || die "wrapper 就位失败"
fi

# --- 转换存量应用 ---
N_ALL=0
N_CONV=0
CONVERTED=""
if [ -d "$APPS" ]; then
  for d in "$APPS"/*/*; do
    [ -d "$d" ] || continue
    f="$d/docker-compose.yml"
    [ -f "$f" ] || continue
    N_ALL=$((N_ALL + 1))
    # ⚠️ 2026-09-19 实测修正：这里原来写的是 `if "$KPH_SRC" --check "$f"`，两个缺陷：
    #   ① 上传到 /tmp 的副本**没有可执行位**（heredoc 落盘），直接执行会 126/127；
    #   ② 于是任何非 0 退出码（含"根本跑不起来"）都被归入 else，打出一整片
    #      「已是 host，跳过」的**假结论**（真机实测：dry-run 说已是 host，
    #      实装却报"本次转换 1"，两次自相矛盾）。
    #   正确做法：用 `sh` 跑（不依赖 +x），并按 kp-compose-host 的退出码契约三分支 ——
    #      0=需要转换 / 1=已是 host / 2=参数或文件错误（**必须报出来，不能当"已是 host"**）。
    if [ "$DRY" = "1" ]; then
      sh "$KPH_SRC" --check "$f" 2>/dev/null
      rc=$?
      if [ "$rc" = "0" ]; then
        say "DRY-RUN: 需要转换: $f"
        N_CONV=$((N_CONV + 1))
      elif [ "$rc" = "1" ]; then
        say "DRY-RUN: 已是 host，跳过: $f"
      else
        warn "DRY-RUN: 检查失败(rc=$rc)，无法判断: $f"
      fi
      continue
    fi
    sh "$KPH" --check "$f" 2>/dev/null
    rc=$?
    if [ "$rc" = "0" ]; then
      if QUIET=1 sh "$KPH" "$f"; then
        N_CONV=$((N_CONV + 1))
        CONVERTED="$CONVERTED $d"
      else
        warn "转换失败: $f"
      fi
    elif [ "$rc" != "1" ]; then
      warn "检查失败(rc=$rc)，跳过: $f"
    fi
  done
else
  warn "应用目录不存在（还没有装过任何应用）: $APPS"
fi

# --- 可选：把转换过的应用拉起来 ---
if [ "$DO_UP" = "1" ] && [ "$DRY" != "1" ]; then
  for d in $CONVERTED; do
    say "启动应用: $d"
    ( cd "$d" && "$COMPOSE" up -d 2>&1 | tail -n 5 )
  done
fi

# --- 验收报告 ---
echo ""
say "===== 验收 ====="
say "转换器: $KPH $([ -x "$KPH" ] && echo OK || echo MISSING)"
say "wrapper: $COMPOSE $([ -x "$COMPOSE" ] && echo OK || echo MISSING)"
if [ -x "$REAL" ]; then
  say "真件版本: $("$REAL" --version 2>/dev/null | head -n1)"
else
  say "真件: MISSING（异常，请立即 --restore 或手工修复）"
fi
say "应用总数 $N_ALL，本次转换 $N_CONV"
say "调用日志: $LOG（wrapper 每次调用记一行，用于确认面板到底调了什么）"
say ""
say "回滚: sh \"$0\" --restore"
say "单文件手工转换: $KPH <docker-compose.yml>   （--check 只判断）"
exit 0
