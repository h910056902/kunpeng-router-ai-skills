#!/bin/sh
# ============================================================================
# kp-1panel-test.sh —— 「1Panel 到底能不能装容器」设备端测试 harness
#
# 由 PC 侧 kp-1panel-install-test.py 通过 SSH 推送后逐阶段调用：
#     sh /tmp/kp1pt/kp-1panel-test.sh <stage>
#
# 阶段：
#   probe            只读基线（不写任何东西）
#   pull             拉 alist 镜像（含磁盘红线）
#   control          无 wrapper 对照组（预期复现 veth 错误）
#   hostnet-install  装 wrapper（改名真件 + 转换存量应用）
#   hostnet-restore  回滚 wrapper
#   install          复刻 1Panel 调用形态真装 alist（走 wrapper）
#   panelcheck       采集「面板是否真的调了 compose」的证据
#   verify           重启持久性 / 落点核查
#   uninstall        停掉并删除 alist 容器（数据目录保留）
#
# 输出约定（供 PC 侧解析，全部单行）：
#   @@SECTION <名字>      段落
#   @@KV <键> <值>        键值（值已换行折叠为空格）
#   @@OK <说明>           判据成立
#   @@FAIL <说明>         判据不成立
#   @@INFO <说明>         中性信息
#
# 退出码：0 = 正常跑完（判据看 @@OK/@@FAIL）／2 = 环境错误
#
# 兼容铁律（busybox ash 5.4 内核）：
#   - 不用 `local`（不是所有 ash 都稳）
#   - 不认 `trap ... ERR`，只用 EXIT
#   - 不认 {a,b,c} 花括号展开
#   - **方括号里绝不写 \t**（POSIX bracket expression 里的反斜杠转义是未定义行为，
#     会被某些 awk 当成字母 t → 以 t 开头的服务名静默漏匹配），一律用字面空格类
#   - 无 jq / timeout / python3 / od / base64；判活用 pidof 不用 pgrep -c
# ============================================================================
set -u

STAGE="${1:-}"
WORK="${KP_WORK:-/tmp/kp1pt}"
NAME="${KP_APP:-alist}"            # 1Panel 应用 key
INST="${KP_INSTNAME:-alist-test}"  # 安装实例名（对应 ${CONTAINER_NAME}）
TMPL="$WORK/compose.orig.yml"      # 未改造的原始 bridge 模板（PC 侧推送）
ENVF="$WORK/app.env"               # 1Panel 会生成的 .env（PC 侧按 data.yml 合成）

LOG=/tmp/kp-compose.log
KPH=/usr/sbin/kp-compose-host
WPR=/usr/bin/docker-compose
REAL=/usr/bin/docker-compose.real

sec() { echo "@@SECTION $*"; }
ok()  { echo "@@OK $*"; }
bad() { echo "@@FAIL $*"; }
die() { echo "@@FAIL $*"; exit 2; }
kv()  { echo "@@KV $1 $(echo "$2" | tr '\n' ' ')"; }
inf() { echo "@@INFO $*"; }

[ -n "$STAGE" ] || die "未指定阶段"
[ "$(id -u)" = "0" ] || die "必须以 root 运行"

# ---------------------------------------------------------------- 路径探测
# 1Panel 标准布局是 <base_dir>/1panel/{apps,db,resource,conf}。
# 但本机 base_dir 可能是 /mnt/storage/data 也可能是 /mnt/storage/data/1panel
# （取决于装机时填的安装目录），所以**必须实测**而不是假设：
# 证据是 $BASE_DIR/1panel/db/1Panel.db 确实存在（7.5M）。
BASE="$(sed -n 's/^BASE_DIR=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1)"
BASE="${BASE:-/opt}"
ROOT=""
for c in "$BASE/1panel" "$BASE"; do
  if [ -d "$c/db" ] || [ -d "$c/resource" ] || [ -d "$c/apps" ]; then ROOT="$c"; break; fi
done
[ -n "$ROOT" ] || ROOT="$BASE/1panel"
APPS="$ROOT/apps"
RES="$ROOT/resource"
APPDIR="$APPS/$NAME/$INST"

is_wrapper() { head -n 5 "$1" 2>/dev/null | grep -q 'kp wrapper'; }
avail_k()    { df -k "$1" 2>/dev/null | tail -n1 | awk '{print $4}'; }

# 原始模板里「容器侧端口」= ports 行冒号后的数字（host 模式下真正生效的那个）
container_ports() {
  [ -f "$TMPL" ] || return 0
  awk '/^[[:space:]]+-[[:space:]]*"/ { n = split($0, a, ":");
        if (n > 1) { p = a[n]; gsub(/[^0-9]/, "", p); if (p != "") print p } }' "$TMPL" \
    | sort -u | tr '\n' ' '
}

# 把模板 + .env 铺进 1Panel 的应用目录（复刻 1Panel 装应用后的落盘形态）
lay_template() {
  mkdir -p "$APPDIR/data/data" "$APPDIR/data/mnt" 2>/dev/null || die "建目录失败: $APPDIR"
  cp -f "$TMPL" "$APPDIR/docker-compose.yml" || die "铺设 compose 失败"
  if [ -f "$ENVF" ]; then
    cp -f "$ENVF" "$APPDIR/.env" || inf "写 .env 失败（非致命）"
  else
    inf "没有 $ENVF —— compose 里的 \${CONTAINER_NAME} 之类变量会解析失败"
  fi
}

# ============================================================== probe
st_probe() {
  sec "环境与目录"
  kv base_dir "$BASE"
  kv panel_root "$ROOT"
  kv apps_dir "$APPS"
  kv resource_dir "$RES"
  kv app_install_dir "$APPDIR"
  kv apps_exists "$([ -d "$APPS" ] && echo yes || echo no)"
  kv installed_app_dirs "$(ls -1 "$APPS" 2>/dev/null | wc -l)"

  sec "1Panel 面板"
  kv panel_version "$(1pctl version 2>/dev/null | grep -oE 'v[0-9][0-9A-Za-z.-]*' | head -n1)"
  kv panel_port "$(sed -n 's/^ORIGINAL_PORT=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1)"
  kv panel_entrance "$(sed -n 's/^ORIGINAL_ENTRANCE=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1)"
  kv panel_user "$(sed -n 's/^ORIGINAL_USERNAME=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1)"
  kv panel_pw_len "$(sed -n 's/^ORIGINAL_PASSWORD=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1 | wc -c)"
  kv paneld_running "$(pidof 1panel >/dev/null 2>&1 && echo yes || echo no)"

  sec "docker 与 compose"
  kv docker_ver "$(docker version --format '{{.Server.Version}}' 2>/dev/null)"
  kv docker_root "$(docker info --format '{{.DockerRootDir}}' 2>/dev/null)"
  kv docker_driver "$(docker info --format '{{.Driver}}' 2>/dev/null)"
  kv docker_arch "$(docker info --format '{{.Architecture}}' 2>/dev/null)"
  kv compose_ver "$($WPR --version 2>&1 | head -n1)"
  kv compose_is_wrapper "$(is_wrapper "$WPR" && echo yes || echo no)"
  kv compose_real_present "$([ -x "$REAL" ] && echo yes || echo no)"
  kv converter_present "$([ -x "$KPH" ] && echo yes || echo no)"
  kv dockerd_running "$(pidof dockerd >/dev/null 2>&1 && echo yes || echo no)"

  sec "镜像加速源（只有 UCI 是真生效的，daemon.json 没人读）"
  kv uci_mirrors "$(uci -q get dockerd.globals.registry_mirrors 2>/dev/null | tr '\n' ',')"
  kv etc_daemon_json "$([ -f /etc/docker/daemon.json ] && echo exists || echo absent)"
  kv dockerd_config_file "$(ps w 2>/dev/null | grep -o 'config-file=[^ ]*' | head -n1)"
  kv tmp_daemon_json "$(grep -o '"registry-mirrors"[^]]*]' /tmp/dockerd/daemon.json 2>/dev/null | head -n1)"

  sec "现有镜像与容器"
  kv images "$(docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null | tr '\n' ';')"
  kv containers "$(docker ps -a --format '{{.Names}}={{.Status}}' 2>/dev/null | tr '\n' ';')"

  sec "1Panel 应用商店本地缓存"
  if [ -d "$RES/apps" ]; then
    kv res_apps_count "$(ls -1 "$RES/apps" 2>/dev/null | wc -l)"
    inf "res/apps 前 20 项: $(ls -1 "$RES/apps" 2>/dev/null | head -n 20 | tr '\n' ' ')"
    for p in "$RES/apps/$NAME" "$RES/apps/local/$NAME"; do
      [ -d "$p" ] && inf "本地模板命中: $p -> $(ls -1 "$p" 2>/dev/null | tr '\n' ' ')"
    done
  else
    kv res_apps_count 0
    inf "没有 $RES/apps —— 应用商店可能从未同步过（面板打开商店才会同步）"
  fi
  kv res_tree "$(ls -1 "$RES" 2>/dev/null | tr '\n' ' ')"

  sec "1panel 二进制是否调用外部 docker-compose（方案 A 成立的前提）"
  PB=""
  for c in /usr/local/bin/1panel /usr/bin/1panel; do
    [ -f "$c" ] && { PB="$c"; break; }
  done
  if [ -n "$PB" ]; then
    kv panel_bin "$PB"
    kv panel_bin_MB "$(( $(ls -l "$PB" | awk '{print $5}') / 1048576 ))"
    kv grep_docker_compose "$(grep -a -c 'docker-compose' "$PB" 2>/dev/null)"
    kv grep_compose_go "$(grep -a -c 'compose-go' "$PB" 2>/dev/null)"
    kv grep_1panel_network "$(grep -a -c '1panel-network' "$PB" 2>/dev/null)"
  else
    bad "找不到 1panel 二进制，无法验证调用形态"
  fi

  sec "网络可达性（401 = 通，registry 无凭据本来就返回 401）"
  for u in \
    https://docker.1ms.run/v2/ \
    https://docker.m.daocloud.io/v2/ \
    https://registry-1.docker.io/v2/ \
    https://apps-assets.fit2cloud.com/stable/1panel.json.zip \
    https://resource.fit2cloud.com/ ; do
    c=$(curl -sS -o /dev/null -m 12 -w '%{http_code}' "$u" 2>/dev/null)
    [ -n "$c" ] || c=000
    inf "curl $c  $u"
  done

  sec "资源"
  kv mem "$(free -k 2>/dev/null | awk 'NR==2{print "total=" $2 " used=" $3 " avail=" $7}')"
  kv avail_data_k "$(avail_k /mnt/storage/data)"
  kv avail_overlay_k "$(avail_k /)"
  inf "df: $(df -h / /mnt/storage/data 2>/dev/null | tail -n +2 | tr '\n' ';')"

  sec "并发保护（有没有别的会话在动同一批东西）"
  kv running_kp_install "$(ps w 2>/dev/null | grep -c '[k]p-install.sh')"
  kv running_compose "$(ps w 2>/dev/null | grep -c '[d]ocker-compose')"
  kv running_docker_pull "$(ps w 2>/dev/null | grep -c '[d]ocker pull')"

  sec "模板指纹"
  if [ -f "$TMPL" ]; then
    kv tmpl_md5 "$(md5sum "$TMPL" 2>/dev/null | awk '{print $1}')"
    kv tmpl_image "$(grep -E '^[[:space:]]+image:' "$TMPL" | head -n1 | awk '{print $2}')"
    kv tmpl_container_ports "$(container_ports)"
    kv tmpl_has_1panel_network "$(grep -c '1panel-network' "$TMPL")"
    kv tmpl_has_ports "$(grep -cE '^[ ]+ports:' "$TMPL")"
  else
    bad "缺少模板 $TMPL"
  fi
  sec "转换器回归自测（缩进无关，含面板 4 空格样本）"
  # ⚠️ 2026-09-19 真机事故的教训：只测「商店 tarball 模板」是不够的。
  #    商店包是 2 空格缩进，而面板 v1.10 落盘的 compose 是 **4 空格 + deploy 段**，
  #    旧转换器按 2/4 写死 → 面板装应用报 Service "x" uses an undefined network。
  #    所以回归样本必须包含 fixtures/compose.panel4sp.yml（面板实际落盘形态）。
  if [ -f "$WORK/kp-compose-selftest.sh" ] && [ -f "$WORK/fixtures/compose.panel4sp.yml" ]; then
    sh "$WORK/kp-compose-selftest.sh" "$WORK/kp-compose-host.sh" "$WORK/fixtures" > "$WORK/convselftest.log" 2>&1
    ST_RC=$?
    kv conv_selftest_rc "$ST_RC"
    inf "自测汇总: $(grep -E '汇总: PASS=' "$WORK/convselftest.log" 2>/dev/null | tail -n1)"
    if [ "$ST_RC" = "0" ]; then
      ok "转换器回归自测全过（含面板 4 空格样本）"
    else
      bad "转换器回归自测有失败项 —— 面板装应用会复现 undefined network 类问题"
      inf "失败明细: $(grep '\[FAIL\]' "$WORK/convselftest.log" 2>/dev/null | head -n 5 | tr '\n' '|')"
    fi
  else
    inf "跳过转换器回归自测（缺 $WORK/kp-compose-selftest.sh 或 fixtures/；由 PC 驱动推送）"
  fi
  ok "probe 完成"
}

# ============================================================== pull
st_pull() {
  [ -f "$TMPL" ] || die "缺少模板 $TMPL"
  IMG=$(grep -E '^[[:space:]]+image:' "$TMPL" | head -n1 | awk '{print $2}' | tr -d '"' | tr -d "'")
  [ -n "$IMG" ] || die "模板里解析不出 image"

  sec "拉取镜像"
  kv image "$IMG"
  kv avail_before_k "$(avail_k /mnt/storage/data)"

  inf "清理同名旧镜像（有容器占用时会失败，非致命）"
  docker rmi "$IMG" >/dev/null 2>&1 || :

  T0=$(date +%s)
  docker pull "$IMG" > "$WORK/pull.log" 2>&1
  RC=$?
  T1=$(date +%s)
  kv pull_rc "$RC"
  kv pull_seconds "$((T1 - T0))"
  inf "pull 输出尾部: $(tail -n 3 "$WORK/pull.log" 2>/dev/null | tr '\n' '|')"

  sec "复核"
  kv images_after "$(docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null | tr '\n' ';')"
  AV=$(avail_k /mnt/storage/data)
  kv avail_after_k "$AV"

  if [ "$RC" = "0" ]; then
    ok "镜像拉取成功"
  else
    bad "镜像拉取失败（rc=$RC）"
  fi

  # 磁盘红线：p2 只有 3.5G，余量必须保 1G
  if [ -n "$AV" ] && [ "$AV" -ge 1048576 ] 2>/dev/null; then
    ok "磁盘余量 ${AV}K ≥ 1G"
  else
    bad "磁盘余量 ${AV}K 低于 1G 红线"
  fi
}

# ============================================================== control
st_control() {
  [ -f "$TMPL" ] || die "缺少模板 $TMPL"

  # 用真件（绕过 wrapper）= 对照组
  BIN="$REAL"
  if [ ! -x "$BIN" ]; then
    if is_wrapper "$WPR"; then
      die "$WPR 已是 wrapper 但 $REAL 缺失 —— 环境异常，先 --restore"
    fi
    BIN="$WPR"
  fi
  sec "对照组（故意绕过 wrapper）"
  kv compose_bin_used "$BIN"

  lay_template
  # 1Panel 装应用前会建好外部网络；bridge 创建本身通常不需要 veth
  NET_OWN=0
  if docker network inspect 1panel-network >/dev/null 2>&1; then
    kv net_pre_existing yes
  else
    docker network create 1panel-network > "$WORK/netcreate.log" 2>&1
    kv net_create_rc "$?"
    inf "network create 输出: $(cat "$WORK/netcreate.log" 2>/dev/null | tr '\n' '|')"
    NET_OWN=1
  fi

  ( cd "$APPDIR" && "$BIN" -f docker-compose.yml up -d ) > "$WORK/control.log" 2>&1
  RC=$?
  kv control_rc "$RC"
  inf "对照组输出: $(head -c 900 "$WORK/control.log" 2>/dev/null | tr '\n' '|')"

  if grep -q 'operation not supported' "$WORK/control.log" 2>/dev/null; then
    ok "复现 veth 错误（预期）—— 反证 bridge 路不通"
  elif grep -q 'veth' "$WORK/control.log" 2>/dev/null; then
    ok "命中 veth 相关错误 —— bridge 路不通"
  elif [ "$RC" = "0" ]; then
    bad "对照组竟然成功 —— 本机网络能力有变，整个 host 化前提需重新评估"
  else
    bad "对照组失败但原因不是 veth，需人工判断（见上方输出）"
  fi

  sec "清理对照组现场"
  ( cd "$APPDIR" && "$BIN" -f docker-compose.yml down ) >/dev/null 2>&1 || :
  docker rm -f "$INST" >/dev/null 2>&1 || :
  if [ "$NET_OWN" = "1" ]; then
    docker network rm 1panel-network >/dev/null 2>&1 || :
    inf "已移除本次创建的 1panel-network"
  fi
  kv containers_after_cleanup "$(docker ps -a --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
}

# ============================================================== hostnet
st_hostnet_install() {
  for f in install-hostnet-default.sh kp-compose-host.sh docker-compose.wrapper; do
    [ -f "$WORK/$f" ] || die "缺少 $WORK/$f（应由 PC 侧推送）"
  done
  sec "预演 --dry-run"
  sh "$WORK/install-hostnet-default.sh" --dry-run 2>&1 | sed 's/^/@@INFO /'

  sec "实装"
  sh "$WORK/install-hostnet-default.sh" 2>&1 | sed 's/^/@@INFO /'
  kv install_rc "$?"

  sec "验收"
  kv compose_is_wrapper "$(is_wrapper "$WPR" && echo yes || echo no)"
  kv compose_real_executable "$([ -x "$REAL" ] && echo yes || echo no)"
  kv compose_version_through_wrapper "$($WPR --version 2>&1 | head -n1)"
  kv converter_present "$([ -x "$KPH" ] && echo yes || echo no)"
  kv real_version "$("$REAL" --version 2>&1 | head -n1)"

  if is_wrapper "$WPR" && [ -x "$REAL" ]; then
    ok "wrapper 就位且真件可执行"
  else
    bad "wrapper 未就位或真件缺失 —— 立即用 --restore 回滚"
  fi
  if $WPR --version >/dev/null 2>&1; then
    ok "docker-compose 链路未被打断"
  else
    bad "docker-compose --version 失败，链路被破坏"
  fi
}

st_hostnet_restore() {
  [ -f "$WORK/install-hostnet-default.sh" ] || die "缺少 install-hostnet-default.sh"
  sh "$WORK/install-hostnet-default.sh" --restore 2>&1 | sed 's/^/@@INFO /'
  sec "回滚后验收"
  kv compose_is_wrapper "$(is_wrapper "$WPR" && echo yes || echo no)"
  kv compose_real_present "$([ -x "$REAL" ] && echo yes || echo no)"
  kv compose_version "$($WPR --version 2>&1 | head -n1)"
  if is_wrapper "$WPR"; then
    bad "回滚失败，仍指向 wrapper"
  else
    ok "回滚成功，已恢复原始 docker-compose"
  fi
}

# ============================================================== install
st_install() {
  [ -f "$TMPL" ] || die "缺少模板 $TMPL"
  sec "复刻 1Panel 调用形态装 $NAME"
  lay_template
  : > "$LOG" 2>/dev/null || :

  ( cd "$APPDIR" && "$WPR" -f docker-compose.yml up -d ) > "$WORK/up.log" 2>&1
  RC=$?
  kv up_rc "$RC"
  inf "up 输出: $(cat "$WORK/up.log" 2>/dev/null | tr '\n' '|')"

  sec "转换结果自检（期望：network_mode=1，ports/networks 全 0）"
  kv nm_host_count "$(grep -cE '^[ ]+network_mode:[ ]*host' "$APPDIR/docker-compose.yml" 2>/dev/null)"
  kv residual_ports "$(grep -cE '^[ ]+ports:' "$APPDIR/docker-compose.yml" 2>/dev/null)"
  kv residual_networks "$(grep -cE '^[ ]+networks:' "$APPDIR/docker-compose.yml" 2>/dev/null)"
  kv top_networks "$(grep -c '^networks:' "$APPDIR/docker-compose.yml" 2>/dev/null)"
  kv backup_created "$([ -f "$APPDIR/docker-compose.yml.bridge.bak" ] && echo yes || echo no)"

  sec "容器状态"
  kv container "$(docker ps --format '{{.Names}}={{.Status}}' 2>/dev/null | grep "^$INST=" || echo none)"
  kv network_mode "$(docker inspect -f '{{.HostConfig.NetworkMode}}' "$INST" 2>/dev/null)"
  kv restart_policy "$(docker inspect -f '{{.HostConfig.RestartPolicy.Name}}' "$INST" 2>/dev/null)"
  kv container_image "$(docker inspect -f '{{.Config.Image}}' "$INST" 2>/dev/null)"
  inf "docker ps -a: $(docker ps -a --format '{{.Names}}={{.Status}}' 2>/dev/null | tr '\n' ';')"

  sec "真实访问（host 模式下以镜像默认端口为准）"
  for p in $(container_ports) 5244; do
    c=$(curl -sS -o /dev/null -m 8 -w '%{http_code}' "http://127.0.0.1:$p/" 2>/dev/null)
    [ -n "$c" ] || c=000
    inf "http://127.0.0.1:$p/ -> $c"
    if [ "$c" = "200" ] || [ "$c" = "302" ] || [ "$c" = "307" ]; then
      kv reachable_port "$p"
    fi
  done

  sec "幂等回归（面板反复装/升级不应该叠出重复键）"
  ( cd "$APPDIR" && "$WPR" -f docker-compose.yml up -d ) > "$WORK/up2.log" 2>&1
  kv up2_rc "$?"
  kv nm_host_count_after_second_up "$(grep -cE '^[ ]+network_mode:[ ]*host' "$APPDIR/docker-compose.yml" 2>/dev/null)"
  inf "第二次 up 输出: $(cat "$WORK/up2.log" 2>/dev/null | tr '\n' '|')"

  sec "资源账本"
  kv avail_data_after_k "$(avail_k /mnt/storage/data)"
  kv mem_after "$(free -k 2>/dev/null | awk 'NR==2{print "avail=" $7}')"
  inf "docker system df: $(docker system df 2>/dev/null | tr '\n' ';')"

  sec "wrapper 调用日志"
  kv log_exists "$([ -f "$LOG" ] && echo yes || echo no)"
  kv log_lines "$(wc -l < "$LOG" 2>/dev/null || echo 0)"
  inf "日志尾部: $(tail -n 6 "$LOG" 2>/dev/null | tr '\n' ' | ')"

  # 判据汇总
  if [ "$(grep -cE '^[ ]+network_mode:[ ]*host' "$APPDIR/docker-compose.yml" 2>/dev/null)" -ge 1 ] \
     && [ "$(grep -cE '^[ ]+ports:' "$APPDIR/docker-compose.yml" 2>/dev/null)" = "0" ]; then
    ok "compose 已被自动 host 化（零手工干预）"
  else
    bad "compose 没有被正确 host 化"
  fi
}

# ============================================================== panelcheck
st_panelcheck() {
  sec "面板调用证据（回答「面板到底调了什么」）"
  kv log_exists "$([ -f "$LOG" ] && echo yes || echo no)"
  kv log_lines "$(wc -l < "$LOG" 2>/dev/null || echo 0)"
  if [ -f "$LOG" ] && [ -s "$LOG" ]; then
    inf "--- /tmp/kp-compose.log 全文 ---"
    sed 's/^/@@INFO /' "$LOG"
    ok "wrapper 日志非空 —— 有进程调过 docker-compose"
  else
    bad "wrapper 日志为空 —— 1Panel 可能没走 PATH 里的 docker-compose，方案 A 前提存疑"
  fi

  sec "面板是否真的装了应用（找 createdBy=Apps 标签）"
  FOUND=0
  for d in "$APPS"/*/*; do
    [ -f "$d/docker-compose.yml" ] || continue
    if grep -q 'createdBy' "$d/docker-compose.yml" 2>/dev/null; then
      FOUND=$((FOUND + 1))
      inf "1Panel 装出来的应用: $d"
      inf "  是否已 host 化: $(grep -cE '^[ ]+network_mode:[ ]*host' "$d/docker-compose.yml" 2>/dev/null)"
    fi
  done
  kv panel_managed_apps "$FOUND"
  kv containers_all "$(docker ps -a --format '{{.Names}}={{.Status}}' 2>/dev/null | tr '\n' ';')"

  sec "面板进程与监听"
  kv paneld_running "$(pidof 1panel >/dev/null 2>&1 && echo yes || echo no)"
  kv panel_port_listen "$(netstat -ltn 2>/dev/null | grep -c ':10090')"
}

# ============================================================== verify
st_verify() {
  sec "落点与持久性"
  kv wrapper_path "$WPR"
  kv wrapper_on_fs "$(df "$WPR" 2>/dev/null | tail -n1 | awk '{print $1, $6}')"
  kv converter_path "$KPH"
  kv app_dir "$APPDIR"
  kv app_dir_fs "$(df "$APPDIR" 2>/dev/null | tail -n1 | awk '{print $1, $6}')"
  inf "注意：wrapper 与转换结果都落在 overlay（TF p1）内，重建 overlay 会丢 —— 一键链必须包含 hostnet 阶段"

  sec "当前状态快照"
  kv containers "$(docker ps -a --format '{{.Names}}={{.Image}}={{.Status}}' 2>/dev/null | tr '\n' ';')"
  kv images "$(docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' 2>/dev/null | tr '\n' ';')"
  kv avail_data_k "$(avail_k /mnt/storage/data)"
  kv mem "$(free -k 2>/dev/null | awk 'NR==2{print "avail=" $7}')"
  if [ -d "$APPDIR" ]; then
    inf "应用目录内容: $(ls -1 "$APPDIR" 2>/dev/null | tr '\n' ' ')"
    kv data_persisted "$([ -d "$APPDIR/data/data" ] && echo yes || echo no)"
  fi
}

# ============================================================== uninstall
st_uninstall() {
  sec "卸载测试实例 $INST"
  if [ -d "$APPDIR" ] && [ -f "$APPDIR/docker-compose.yml" ]; then
    ( cd "$APPDIR" && "$WPR" -f docker-compose.yml down ) 2>&1 | sed 's/^/@@INFO /'
  fi
  docker rm -f "$INST" >/dev/null 2>&1 || :
  if [ "${KP_RMI:-0}" = "1" ]; then
    IMG=$(grep -E '^[[:space:]]+image:' "$TMPL" 2>/dev/null | head -n1 | awk '{print $2}' | tr -d '"' | tr -d "'")
    [ -n "$IMG" ] && docker rmi "$IMG" >/dev/null 2>&1 || :
    inf "已尝试删除镜像 $IMG"
  fi
  kv containers_after "$(docker ps -a --format '{{.Names}}' 2>/dev/null | tr '\n' ' ')"
  inf "数据目录保留未动: $APPDIR"
  ok "卸载完成"
}

# ============================================================== dispatch
case "$STAGE" in
  probe)           st_probe ;;
  pull)            st_pull ;;
  control)         st_control ;;
  hostnet-install) st_hostnet_install ;;
  hostnet-restore) st_hostnet_restore ;;
  install)         st_install ;;
  panelcheck)      st_panelcheck ;;
  verify)          st_verify ;;
  uninstall)       st_uninstall ;;
  *)               die "未知阶段: $STAGE" ;;
esac
exit 0
