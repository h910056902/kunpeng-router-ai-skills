#!/bin/sh
# ============================================================================
# kp-compose-selftest —— 转换器（kp-compose-host）的设备端回归自测
#
# 为什么需要它：转换器是纯文本改写，**换一份输入就可能静默失效**。
# 2026-09-19 真机事故就是这么来的：商店 tarball 模板是 2 空格缩进（测试用），
# 而 1Panel 面板 v1.10 落盘的 compose 是 **4 空格缩进**（重渲染过）→ 旧转换器
# 只删了顶层 networks:，服务里的 networks: 漏网 → 面板装应用报
#   ERROR: Service "alist" uses an undefined network "1panel-network"
# 结论：**样本必须包含"面板实际落盘形态"，不能只测商店 tarball 模板。**
#
# 用法：sh kp-compose-selftest.sh [转换器路径] [fixtures 目录]
#   默认转换器 /usr/sbin/kp-compose-host，fixtures /tmp/kp1pt/fixtures
# 退出码：0 全过 / 1 有失败
# 兼容：busybox ash + busybox awk
# ============================================================================

KPH="${1:-/usr/sbin/kp-compose-host}"
FIX="${2:-/tmp/kp1pt/fixtures}"
T=/tmp/kpconvt
OK=0
FAIL=0

say()  { echo "$*"; }
pass() { OK=$((OK + 1));   say "  [PASS] $*"; }
bad()  { FAIL=$((FAIL + 1)); say "  [FAIL] $*"; }
ck()   { if [ "$2" = "$3" ]; then pass "$1 = $3"; else bad "$1 expect=$2 got=$3"; fi; }

# 与转换器同一套判据的"体检"：数出残留键与已注入行（缩进无关）
probe_file() {
  f="$1"
  nm=$(grep -cE '^[ ]+network_mode:[ ]*host[ ]*$' "$f" 2>/dev/null)
  net=$(grep -cE '^[ ]+networks:' "$f" 2>/dev/null)
  prt=$(grep -cE '^[ ]+ports:' "$f" 2>/dev/null)
  top=$(grep -c '^networks:' "$f" 2>/dev/null)
  case "$nm" in ''|*[!0-9]*) nm=0 ;; esac
  case "$net" in ''|*[!0-9]*) net=0 ;; esac
  case "$prt" in ''|*[!0-9]*) prt=0 ;; esac
  case "$top" in ''|*[!0-9]*) top=0 ;; esac
  echo "$nm $net $prt $top"
}

# 断言一份带 bridge 特征的文件能被干净转换
case_convert() {
  label="$1"; src="$2"
  say "-- $label"
  [ -f "$src" ] || { bad "$label 样本缺失: $src"; return; }
  cp -f "$src" "$T/case.yml"
  rm -f "$T/case.yml.bridge.bak"
  sh "$KPH" --check "$T/case.yml" >/dev/null 2>&1
  ck "$label --check(转换前)" 0 "$?"
  sh "$KPH" "$T/case.yml" > "$T/conv.log" 2>&1
  ck "$label 转换 rc" 0 "$?"
  set -- $(probe_file "$T/case.yml")
  ck "$label network_mode 注入数" 1 "$1"
  ck "$label 残留服务级 networks:" 0 "$2"
  ck "$label 残留服务级 ports:" 0 "$3"
  ck "$label 残留顶层 networks:" 0 "$4"
  # 关键：deploy/environment/volumes 必须原样保留
  ck "$label 保留 deploy 段" "$(grep -c '^[ ]*deploy:' "$src")" "$(grep -c '^[ ]*deploy:' "$T/case.yml")"
  ck "$label 保留 environment 段" "$(grep -c '^[ ]*environment:' "$src")" "$(grep -c '^[ ]*environment:' "$T/case.yml")"
  ck "$label 保留 volumes 段" "$(grep -c '^[ ]*volumes:' "$src")" "$(grep -c '^[ ]*volumes:' "$T/case.yml")"
  ck "$label 行数（只减不增）" 1 "$([ "$(wc -l < "$T/case.yml")" -le "$(wc -l < "$src")" ] && echo 1 || echo 0)"
  sh "$KPH" --check "$T/case.yml" >/dev/null 2>&1
  ck "$label --check(转换后，应已是 host)" 1 "$?"
  # 幂等
  sh "$KPH" "$T/case.yml" > "$T/conv2.log" 2>&1
  ck "$label 二次转换 rc" 0 "$?"
  set -- $(probe_file "$T/case.yml")
  ck "$label 幂等：network_mode 不叠加" 1 "$1"
  ck "$label 幂等：无残留 networks/ports" "0 0 0" "$2 $3 $4"
  say "     (注入行缩进: $(sed -n 's/^\( *\)network_mode: host.*/\1/p' "$T/case.yml" | tr -d '\n' | wc -c))"
}

main() {
  say "=== kp-compose-selftest  KPH=$KPH  FIX=$FIX ==="
  [ -f "$KPH" ] || { say "转换器不存在: $KPH"; exit 1; }
  rm -rf "$T"; mkdir -p "$T" || exit 1

  # 样本 1：商店 tarball 原模板（2 空格）
  case_convert "store-2sp（商店 tarball 原模板）" "$FIX/compose.store2sp.yml"
  # 样本 2：1Panel 面板 v1.10 实际落盘（4 空格 + deploy + ${HOST_IP}）
  case_convert "panel-4sp（面板实际落盘）" "$FIX/compose.panel4sp.yml"
  # 样本 3：3 空格（模拟第三方主题/手改）
  if [ -f "$FIX/compose.weird3sp.yml" ]; then
    case_convert "weird-3sp（非 2/4 幂缩进）" "$FIX/compose.weird3sp.yml"
  fi
  # 样本 4：CRLF 行尾（Windows 编辑过的 compose）
  if [ -f "$FIX/compose.crlf.yml" ]; then
    case_convert "crlf（CRLF 行尾）" "$FIX/compose.crlf.yml"
  fi

  # 已是 host 的文件：--check 必须 rc=1（不能被当成"需要转换"）
  say "-- already-host（已 host 文件）"
  printf 'services:\n    w:\n        image: nginx\n        network_mode: host\n' > "$T/host.yml"
  sh "$KPH" --check "$T/host.yml" >/dev/null 2>&1
  ck "已 host 文件 --check" 1 "$?"

  # 参数/文件错误：rc=2
  say "-- error-path（错误路径）"
  sh "$KPH" --check "$T/definitely-missing.yml" >/dev/null 2>&1
  ck "文件不存在 --check rc" 2 "$?"
  sh "$KPH" >/dev/null 2>&1
  ck "无参数 rc" 2 "$?"

  say ""
  say "=== 汇总: PASS=$OK FAIL=$FAIL ==="
  [ "$FAIL" = "0" ] || exit 1
  exit 0
}

main "$@"
