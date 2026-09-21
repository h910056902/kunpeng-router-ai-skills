---
id: REF-maye
title: "maye 插件安装助手兼容性（nradio.mayebano.shop）"
tags: [maye, third-party, plugin-installer, snapshot]
risk: high
preconditions:
  - "🔴 它不产生任何备份，跑前必须自己备份目标文件"
  - "🔴 严禁在其菜单选「卸载 Docker」"
  - "🔴 严禁在其菜单装 AGH/mosdns（端口与 Docker AGH 冲突）"
  - "改前先 snapshot"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# maye 插件安装助手兼容性（nradio.mayebano.shop）

社区脚本「NRadio 官方系统插件安装助手」（作者 maye），**V3.2.0 / 2026-09-14**，
约 7 万行 sh 菜单式工具。上游 <https://github.com/561410590/ssh-nradio-plugin-installer>
（镜像页 <https://nradio.mayebano.shop/>）。**与我们的商店补丁可共存**。

完整操作流程见 [`tasks/05-nros-plugin-installer.md`](../tasks/05-nros-plugin-installer.md)。

## 三条红线（2026-09-19 实测）

1. **它不产生任何备份。** 脚本第 19 行有 `BACKUP_DIR="/root/nradio-plugin-fix"`，
   但 `backup_file()`（第 2575-2578 行、第 54767-54769 行）是**空实现**，函数体只有 `return 0`，
   注释写「…不在路由器上生成持久备份」。全脚本 100+ 处 `backup_file "..."` 全是空操作，
   没有任何 `mkdir`/`cp` 落到 `$BACKUP_DIR`。真机实测该目录**不存在**。
   → 想回滚只能靠自己跑前备份。（**旧版档案写「自带备份到 `/root/nradio-plugin-fix/`」是错的。**）

2. **别选「卸载 Docker」**（第 4512-4530 行）。它 `rm -f /etc/config/dockerd` 并
   `rm -rf /etc/docker /usr/libexec/docker $DOCKER_ROOT`。本机 `/etc/config/dockerd`（304 B）
   是 Docker `data_root` 与镜像加速源的**唯一载体**（`data_root '/mnt/storage/data/docker'` +
   2 条 `registry_mirrors`），删掉 = 1Panel 的 Docker 环境连带数据一起报废。

3. **别装 AdGuardHome / mosdns**。它给的是 native 版（DNS 端口 554/553 + uci 配置），
   与本机 Docker AGH（`:53` 全网接管）冲突。去广告用我们现成的方案。

额外：**奇游 / 雷神走明文 HTTP 下载后直接 root 执行**
（第 97 行 `http://sd.qiyou.cn`、第 106 行 `http://119.3.40.126/...`），
下载后只做 `grep` 内容检查与 `sh -n` 语法检查，**无校验和/签名**，然后 `sh` 执行 —— 等于远程代码执行面。

## 环境门禁：本机全 PASS（2026-09-19 逐关卡实测）

| 门禁 | 本机结果 |
|---|---|
| 机型归一化 | `HC-WT9500` → `NRadio_C2000Ultra`（第 1209-1210 行） |
| 版本受支持 | `2.3.0.n0.c1` 匹配 `2.*` → PASS（`is_supported_nros_revision` 第 1224-1240 行） |
| SD 卡前置 | `/tmp/storage/mmcblk0p1`，可用 15438 MiB → PASS |
| 商店环境 | profile = `legacy_appcenter`，三路径齐全 → PASS |

⚠️ **最容易误判的坑**：版本判据读的是 `ubus call system board` 的 `release.revision`，
**不是** `/etc/openwrt_release` 的 `DISTRIB_RELEASE`。
本机 `DISTRIB_RELEASE='21.02-SNAPSHOT'`（看着不匹配 `2.*`），但脚本第一优先级读
`ubus` 的 `"revision": "2.3.0.n0.c1"` → 匹配 `2.*` → 放行。

⚠️ **门禁触发时机**：主菜单选分类 `1/2/3/4` 才检查（第 72416 行），
选分类 `5`（设备维护与检测）不检查；`run_menu_feature` 里 feature `33|34` 豁免（第 69922 行）。

## 可用性实测：真终端已跑通（2026-09-19 晚）

PTY 真终端按**正确用法**（**不带参数**）完整走通：
免责声明 → 主菜单 → `1)` 常用插件子菜单 → 返回 → `0` 退出。
菜单顶部是**脚本自己打印**的 `设备 NRadio_C2000Ultra` / `系统 NROS 2.3.0.n0.c1`（与我方探针结论一致）；
选 `1` 时打印 `环境检测: 已检测到 NRadio 应用商店`。
跑后 `pidof clash`（16659）、`/etc/config/dockerd`、`appcenter.lua` / `appcenter.htm`、`distfeeds.conf`
的 sha256 **全部与跑前一致**；`/etc/config`、`/usr/lib/lua/luci`、`/etc/kp_store` 零改动。

⚠️ **运行命令不能带参数**：上游 README 的写法是 `sh ssh-nradio-plugin-installer.sh`。
带仓库 URL 会被当作菜单编号 → `ERROR: 无效编号：https://…` → 退出。合法位置参数只有 `0`~`5`。

⚠️ **状态目录**：`/root/.nradio-plugin-menu/`，内含
`disclaimer_accepted_20260615-v260-model-disclaimer-c2000pro-risk-v1.flag`（27 B，`accepted V3.2.0 2026-09-14`）。
同意一次后不再询问；删掉它下次会重新问。**它不是备份**（见红线 1）。

⚠️ **stdin 三种行为**：`< /dev/null` → `die "input cancelled"`；`exec_command` 不喂不关 → **永久挂住**；
管道喂够 `y`+编号 → 能跑通（rc=0）。**技术可自动化，但流程上必须人工选菜单项**。

## 菜单实测：五大分类逐项核对（2026-09-20，PTY 真终端）

做法：真终端 `invoke_shell(width=210,height=60)` 起脚本 → 接受免责声明 → **只按分类号进子菜单、
只按返回键退出，一个功能项都没选**（装-卸行为零触发）。跑前跑后各采 15 项基线。

**结果：15 项基线里 14 项逐字一致**（`pidof clash` 16659 / `pidof dockerd` 25269 /
`/etc/opkg/distfeeds.conf` sha `aa8c4df33eba8dc4` / `/etc/config/dockerd` sha `ec346b5611ba0178` /
`/etc/rc.local` sha `d413ca6acf54b01d` / `appcenter.htm` sha `34880d1a070d1850` / crontab 3 行 /
appcenter uci 244 行 / `opkg list-installed` 576 / HTTP 200 / 真 DNS 200）。
**唯一变化是状态目录**（见下）。

### 五个分类的真机菜单（本机实际打印）

| 分类 | 标题 | 真机项 | 返回键 | prompt |
|---|---|---|---|---|
| 1 | 常用插件 | `1..10` + `0` | `0` | `0-10` |
| 2 | VPN 与组网 | `1..7` + `0` | `0` | `0-7` |
| 3 | 游戏加速器 | `1..2` + `0` | `0` | `0-2` |
| 4 | 应用商店与页面 | `1..3` + `0` | `0` | `上方编号，0 返回` |
| 5 | 设备维护 | `1..8`、`11`、`12` | **`12`** | `0-8 / 11-12` |

⚠️ **分类 5 的返回键是 `12`，不是 `0`** —— 上游 `maintenance_test_menu` 里
`print_menu_item 12 '返回功能分类'`，`case` 里 `0|12) return 0`。所有分类里只有它这样。

⚠️ **分类 5 跳号（无 9/10）** —— 菜单里 `1..8` 之后直接 `11 硬件加速管理`、`12 返回`。
原因：`9`/`10` 被两个**条件项**占用（`5G 聚合修复检查`、`5G 连接监听`），
本机型两个谓词都为假（不打印），于是编号回收到 8，prompt 随之收成 `0-8 / 11-12`。
这不是 bug，是上游按机型收窄菜单的正常行为。

### 菜单是「机型条件分支 + 顺序编号」，静态并集 ≠ 单机型所见

三类菜单都靠条件分支区分机型，而编号是**顺序推进**的（`next=$((next+1))`），
所以「某个条件项不打印」会让它之后所有项的编号整体前移：

| 菜单 | 分支数 | 真机走哪支 | 并集项数 vs 真机项数 |
|---|---|---|---|
| `common_plugin_menu` | 2（default / C8-788） | default | 13 vs 11 |
| `maintenance_test_menu` | 3（AK68-798 / C8-788 / default） | default | 23 vs 10 |
| `appcenter_polish_menu` | 1 个函数 + 3 个条件块 | 三块全开/全关混合 | 5 vs 4 |

本机（`NRadio_C2000Ultra`）实测为假的谓词共 5 个：
`is_current_model_ak798`、`is_current_model_c8_788`、
`lightweight_appcenter_model_supported`、`nradio_5g_aggregation_model_supported`、
`nradio_cpe_monitoring_model_supported`。

→ 这 5 个已写进 `tasks/footprint.json` 的 `reference_device.assumed_false_conds`，
并据它产出 `menus_reference_projection`（**投影后才与真机屏幕一一对应**）。
`scripts/extract_footprints.py` 里带自校验：投影后 5 个分类的项数必须等于真机实测的
`11 / 8 / 3 / 4 / 10`，不等就报 `★不一致`。

⚠️ **同一个菜单号在不同机型分支指向不同 feature —— 映射表不能用扁平字典。**
分类 5 的 `2)` 就是最典型的坑：

| 分支 | `2)` 的标签 | → feature |
|---|---|---|
| `is_current_model_ak798` | LuCI 首页 CPU 温度显示 | **27** |
| `is_current_model_c8_788` | 风扇控制（C8-688/788、C2000MAX） | **14** |
| default（本机） | 风扇控制（C8-688/788、C2000MAX） | **14** |

（分类 5 的 `4)` 同理：C8-788 分支 → 23，default 分支 → 20。）
所以 `menus.<名>.maps` 必须是**条目列表** `[{no, feature, cond, src}]`，与 items 同粒度；
写成 `{菜单号: feature}` 会被后写的分支**静默覆盖**，看起来一切正常但映射是错的。

另外 item 与 map 的 `cond` **语义不同**：item 的 cond 是「机型条件层次」，
map 的 cond 是「分派支条件」（如 `[ "$UI_READ_RESULT" = "$maintenance_health_choice" ]`）。
两者不能用 cond 直接配对 —— 要用**变量名**配（item 的 `expr="$maintenance_health_choice"`
对上 map cond 里的同名变量），见 `menu_item_features()`。

### 状态目录：只在「接受免责声明」时就创建，与装没装插件无关

真机实测：只进 5 个子菜单、一个功能项都没选，`/root/.nradio-plugin-menu/` 就出现了，
里面只有 `disclaimer_accepted_20260615-v260-model-disclaimer-c2000pro-risk-v1.flag`
（27 B，内容 `accepted V3.2.0 2026-09-14`）。

⚠️ **所以不能用「状态目录存在」判断「maye 已装插件」** —— 用户按一次 `y` 就会误报。
`scripts/adapt_maye_assistant.py` 原先把 `[ -d /root/.nradio-plugin-menu ]` 当「已安装」，
已改为 `maye_footprint()`：状态目录 +「appcenter.htm 里有没有 `Design By MaYe` 产权标识」
两个**互不相同**的事实分开报。

⚠️ **该 flag 是持久的，重启不会重新问** —— `/proc/mounts` 里 `/root` 没有单独挂载，
它就在 overlay 上（`upperdir=/overlay/upper`，实测 `/overlay/upper/root/.nradio-plugin-menu/`
里确实有那个 flag）。flag 名里的 `20260615`/`c2000pro` 是上游固定的模板名，与当前机型无关。

## 卸载语义：上游自己的 `uninstall_*` 函数就是权威答案（2026-09-20）

上游全文有 **32 个**清理/还原函数（`cleanup_*` / `remove_*` / `restore_*` / `uninstall_*`，
清单见 `_footprint_report.txt` 末节）。本项目**不调用**它们，但必须读它们 ——
因为「该删什么」在有些功能上光看写盘足迹判不出来。

### 一类「什么都不建」的功能：feature 26 / 27

| feature | 功能 | 它写了什么 |
|---|---|---|
| 26 | 运营商与卡名显示修复 | 2 个自己的 JS + 往 LuCI 首页模板插一段带 marker 的 `<script>` |
| 27 | LuCI 首页 CPU / 5G 温度切换 | 1 个自己的 JS + 同样的首页注入 |

**不装包、不建目录、不写 uci** —— 静态扫描只看到「一堆变量指向的路径」，
于是全部落进 needs_manual，`post_condition` 为**空**（33 个功能里只有这 2 个没有
任何验收谓词，等于没有验收标准）。

上游 `uninstall_nradio_operator_display_fix`（installer.sh L57420）把正解说清楚了：

```sh
if [ -f "$NRADIO_OPERATOR_FIX_VIEW" ]; then
    rewrite_nradio_operator_display_view remove      # awk 按 marker 摘掉注入段
fi
rm -f "$NRADIO_OPERATOR_FIX_JS" "$NRADIO_SIM_NAME_MAP_JS"
refresh_nradio_operator_display_fix                  # 清 LuCI 缓存 + uhttpd reload
log "结果:   LuCI 运营商与卡名显示修复已移除（卡名配置已保留）"
```

据此得到 4 条正确断言的**卸载后状态**：

| 断言 | 谓词 | 依据 |
|---|---|---|
| 两个 JS 没了 | `absent:/www/luci-static/nradio/js/nradio-{sim-name-map,operator-display-fix}.js` | `rm -f` 目标 |
| 注入段摘干净 | `no_marker:<!-- nradio-operator-display-fix:{start,end} -->` | 上游 selfcheck 也是 `grep -Fc` 数标记 |
| **首页模板回到固件原文** | `matches_baseline:/usr/lib/lua/luci/view/nradio_status/index.htm` | `rewrite_*_view remove` 只摘标记段，摘净后逐字节等于 `/rom` 原文 |
| **LuCI 面板没被弄挂** | `keeps_service:uhttpd` | 我们拒绝停 uhttpd，那验收标准就是「它还活着」 |
| **卡名配置没被误删** | `keeps:/etc/nradio-sim-name.map` | 上游注释原话「卡名配置已保留」 |

feature 27 同理（`uninstall_nradio_home_temperature_switch`，L58420）。

### 三条踩过的坑

1. **`/usr/lib/lua/luci/view/nradio_status/index.htm` 是固件文件**，删了首页就没了。
   卸载动作必须是「摘注入段还原」而不是「删文件」。
2. ⚠️ **「上游没 `rm`」≠「有意保留」**。第一版按这个推，生成 66 条 `keeps:` 谓词，
   其中 feature 5（OpenList）把 `/usr/bin/openlist`、`/etc/init.d/openlist`、
   `openlist.lua`、`/usr/libexec/openlist-sync-config` 全判成「卸载后必须仍在」——
   这些**必须删**，谓词方向完全反了。
   真实原因：上游 cleanup 函数只管**运行时态 / 路由 / 缓存**，插件自己的
   `.lua` 控制器、`init.d` 脚本、商店注册项另有机制负责。
   已收紧为「**源码里写明保留 / keep / preserve 且路径是数据/配置文件形态**」
   → 全库只剩 **1 条**，就是卡名 map。
3. **`/root/nradio-plugin-fix` 是全局 `BACKUP_DIR`**（`backup_file` 的落脚处，
   存各功能的原文件备份）。**不得随单个功能删** —— 删了别功能的回滚就失效了。
   它只出现在单个 feature 的 `writes_unique` 里是「字面量恰好只在该闭包出现」的假象。

### 结果

- `post_condition` 覆盖率 **31/33 → 33/33**
- 全库谓词种类：`lacks_key 109 / absent 54 / not_running 42 / matches_baseline 38 /
  no_store_entry 36 / keeps_service 31 / no_net_rule 23 / no_marker 6 /
  lacks_section 5 / no_block 2 / no_symlink 2 / keeps 1 / no_cron 1`
- 危险项仍为 **0**（固件服务进 stop_services 0 条、容器目录进 remove_paths 0 条）

> ⚠️ 上面这组数字是**那一轮 33 feature 基线的快照**，别当成现状。现状（2026-09-21，
> 41 feature）见本节末「谓词现状」。其中 `no_net_rule 23` 这一类**已被整体淘汰** ——
> 它的参数是命令片段而不是规则特征，属假谓词，已降级为人工提示。

## 菜单是什么结构：六种分派写法（2026-09-21，解析器三次收口后定稿）

只遍历主菜单会**丢掉整批动作**。真实源码里「菜单号 → feature」有六种写法，
解析器（`scripts/extract_footprints.py`）必须全部认：

| # | 写法 | 例子 |
|---|---|---|
| ① | `N) submenu_feature='x'` 赋值 | 主菜单多数项 |
| ② | `N) run_menu_feature x` 直接调 | |
| ③ | `N)` 单独一行 + **隔行** `run_menu_feature x` | 中间夹 printf |
| ④ | 变量比较式 `elif [ "$UI_READ_RESULT" = "$var" ]` | 主菜单靠它兜底 |
| ⑤ | **子菜单 case 直接调处理函数** | `1) qiyou_install_integrated` |
| ⑥ | **代码生成器模式**：handler 只执行 `/usr/libexec/nradio-xxx-uninstall` | 真逻辑在 `xxx_write_uninstall_helper` 的 heredoc 正文里 |

**两层菜单结构**：主菜单 5 类各挂子菜单（奇游 / 雷神 / 轻量应用商店 / 温度 / 硬件加速 / LuCI8080）。
`dispatch` 记录里的 `key` 字段用 `submenu:<menu_fn>:<no>` 表示「子菜单项独立成 feature」；
**没有该 key 的**说明只是父 feature 的内部支路（如 `4›3` LuCI8080 的「安装/卸载」、
`5›8` 温度切换的「安装/移除」、`5›11` 硬件加速的「开/关/查」），
不要再拆成新 feature —— 拆了会重复计数，而且同一动作两处维护必漂移。

**补上分类 3 后**：features 33 → **41**（奇游 35~38、雷神 39~42）。
`menus.*.maps` 必须是**条目列表**而不是 `{菜单号: feature}` 字典 ——
同一个菜单号在不同机型分支指向不同 feature（`5›2`：AK68-798→27 首页温度 / C8-788→14 风扇控制），
扁平字典会被后写分支静默覆盖。

## 代码生成器模式：真逻辑在 heredoc 正文里（2026-09-21）

ttyd / MosDNS / Open-Box / eFanCtrl / MT5700 / 5G 连接监听 走的是
`cat > "$helper" <<'EOF'` 生成一个脚本再执行 —— **真正写盘的动作全在 heredoc 正文**。
只扫函数体外层代码会得到「零写盘足迹」的假象：

- feature 3「ttyd / Web SSH」修复前：`remove_paths=0 / stop_services=0 / uci_reset=0`，
  谓词只剩 3 条商店注册项；
- 装机逻辑整段在 `cat > "$helper" <<'__TTYD_HELPER__'`（L54400~L56654，**2253 行**）里；
- 修复后补回 **25 条足迹**：`stop_services=[ttyd]`、8 个 `ttyd.default.*` uci 键、19 条谓词。

**heredoc 分型判据**（`classify_heredocs()`）：正文**首行是 `#!` → 脚本式**，
按普通代码抽全类别；否则是**数据式**（配置/模板/JSON），只抽 marker。
全库 171 个 heredoc 区、49031 行正文，脚本式只占少数但全是写盘大户。

## 写盘判定的三道闸门（2026-09-21，两个反面教训）

修「只读引用被当写盘」时连撞两次，最终定稿是 **函数级 + 不做不动点传播 + heredoc 分型**。

**闸门一：函数级而非行级。**
第一版做成行级（「这行不含写动词 ⇒ 这行的路径引用是只读」）→ **灾难性漏判**：
上游大量用「封装函数 + 变量实参」写盘，调用行本身看不见路径
（`stop_disable /etc/init.d/openvpn`、`$LEIGOD_INIT enable`、`unified_apply_fix "$target"`）。
后果：feature 13 从 `medium/7 谓词` 掉到 `low/1`，feature 2/5/6/7 的 `stop_services` 全归零。
→ 判据改为 **归属函数的函数体内含不含写动词**（`compute_write_funcs()`）。

**闸门二：刻意不做不动点传播。**
第一版做了传播（「调用了写函数的函数也算写函数」）→ 把纯转发的打印函数
`nradio_print_openclash_brief_summary` 标成写函数，于是它体内的
`openclash_report_storage_location "..." /etc/openclash` 这种**纯传参行**被当写盘 ——
feature 24「封版工具箱」的清除草稿里就冒出了 `remove_paths: ['/etc/openclash']`，
**直接踩用户划的红线**。
→ 去掉传播。代价≈0（纯转发函数体内本来就没有路径字面量）。

**闸门三：heredoc 分型**（见上节）。数据式 heredoc 与只读行同一处理：只留 marker。

`WRITE_VERB_RE` 覆盖范围：
`rm|mv|cp|mkdir|touch|ln|chmod|chown|tee|truncate|dd|swapon|swapoff|unzip|gzip|gunzip|install|tar`
／ `sed -i` ／ `/etc/init.d/xx {start,stop,restart,reload,enable,disable}`
／ `opkg {install,remove,upgrade,download}` ／ `uci {set,add,add_list,delete,rename,commit}`
／ `ubus call` ／ `eval` ／ `cat >`。

**兜底字段 `readonly_refs`**：被只读闸门挡掉、但确实与功能相关的路径**单独留档**，
不让它静默消失（否则「闸门开太大」这类回归没人看得见）。
现状：17 个 feature / 41 条，全部只是「待人工核」，不进删除清单。

**解析缺陷修复进度**（详见工作区 `maye适配-解析缺陷与修复方案-20260920.md`）：

① ✅ **已修（2026-09-21）· `no_net_rule` 假谓词**。它的参数取自 `net` 类正则的
**命中文本**（`fw3 reload` / `iptables` / `ip rule add`），而不是规则特征
（chain / fwmark / CIDR）→ 引擎永远找不到 → **假阳性通过**，26 条。
深挖之后发现「改造它」这条路走不通：上游这些命令的动作对象几乎全是 shell 变量
（`ip rule del to "$remote_subnet" lookup main priority 60`、
`iptables -t nat -D POSTROUTING -s "$local_subnet" -o "$tun_if" -j MASQUERADE`），
抽不出稳定的规则身份；唯一看似可抽的「表 / 链 / 目标」三元组同样**不安全** ——
`nat/POSTROUTING/MASQUERADE` 出厂固件自身就在用，拿它判「没清干净」会在**干净机器上失败**；
而 `fw3 reload` / `mtkhnat` 根本不是规则，是动作与服务。
**结论：这一类整体淘汰。** 抽取器不再产出 `no_net_rule` 谓词，改为输出可操作的人工提示
（点名 `iptables-save` / `ip rule show` / `ip route show` 去核对）。
`_selfcheck.py` §10 已把它移出谓词白名单并加了零残留断言 —— 再出现即报错。
同一轮顺带核过：删掉这 26 条后**没有任何功能掉到零谓词**（最少的还剩 2 条）。

② ◐ **部分修复（2026-09-21 第二轮）· `norm_dir` 粒度**：折叠表（DIR_PREFIXES）
曾混入 7 个红线前缀（`/opt /mnt/storage /overlay /usr/libexec /usr/bin
/usr/lib/lua/luci /usr/share`），把 `/usr/libexec/qy_acc` 归一成 `/usr/libexec` ——
「改某个文件」被放大成「占整个容器目录」。已把这 7 个前缀**移出折叠表**
（只剩 7 个插件自建业务目录），feature 15/17/21/34 的证据现在落成具体文件路径
（如 `absent:/usr/libexec/nradio-multiwan`）。
**仍未修**：业务目录内部的折叠（`/etc/openclash/custom/xxx.list` → `/etc/openclash`）依旧存在。

③ ✅ **已修（2026-09-21 第二轮）· `matches_baseline` 假基线**。真机对账
（4121 条 `/rom` 清单固化到 `scripts/rom_baseline_c2000u.txt`）证明三类假谓词：
(a) `/etc/config/accelerator` 等 48 条参数**根本不在 /rom**（插件自建件，
    逐字节比对必假）—— 曾被 19 个 feature 断言；
(b) `/proc/.../proxy_arp` ×2、`/sys/kernel/debug/hnat/hook_toggle` 落在
    **伪文件系统**，/rom 无原件；
(c) 顺带证伪了「新增 `value_equals` 谓词」的方案：`hook_toggle` 的还原值是
    运行时动态量 `$saved_hook`、proxy_arp 上游只写不还原、真机 cat 为空 ——
    **常量值断言照样是假谓词，未采纳**，降级 needs_manual。
现在 `matches_baseline` **只对 /rom 清单里真实存在的出厂件发射**；伪文件系统与
插件件一律降级 `needs_manual`（并保留 `readonly_refs` 兜底）。`_selfcheck.py`
§10a-3 新增 4 条语义守卫（G1 absent∩matches_baseline 交集为空 / G2 matches_baseline
禁伪文件系统 / G3 两类谓词禁容器目录 / G4 keeps_service∩not_running 交集为空），
全部经过「注入必失败、还原必恢复」的负向验证。

**谓词现状**（2026-09-21 第二轮，41 feature：36 带验收谓词 / 3 只读 /
2 纯人工清单〔1、10〕）：共 **12 类** ——
`absent 168 / lacks_key 120 / matches_baseline 70 / not_running 45 /
no_store_entry 37 / keeps_service 35 / no_marker 6 / lacks_section 5 /
no_block 2 / no_symlink 2 / keeps 1 / no_cron 1`（总 492）。
`no_net_rule` 归零；危险项 0；语义冲突 0；零谓词守卫已收紧为
「零谓词**且零 needs_manual** 才算失败」（features 1/10 写盘目标全是运行时状态
或上游无卸载函数，人工清单即验收）。

## 它改什么（legacy_appcenter 模式，即本机当前画像）

- appcenter.htm：加卸载按钮入口、图标缓存刷新、MaYe 产权标识（增量）
- appcenter.lua：awk 插入 sys_status entry + 追加 sys-status Lua 块、runtime compat 包装（增量）
- C2000Pro/AK798 画像才是整文件替换（compat layer），我们不受影响
- 状态目录 `/root/.nradio-plugin-menu/`（只存免责声明 flag 与菜单偏好，**不是备份**）
- 它有自己的插件清单/卸载体系（`nradio_plugin_uninstall_action` + `plugin_uninstall/start` 异步端点），
  与我们的 `installed.list`/`nradio_appcenter_extra_action` 是**并行的两套**
- `/etc/opkg/distfeeds.conf`：**有守卫**（第 5699-5703 行，遇到规范 `src/gz + http(s)` 源即
  「保留当前固件源」），本机实测**不会被重写**

## 冲突风险点

| 风险 | 说明 | 对策 |
|---|---|---|
| 它升级时重写 controller/htm | 增量补丁可能被覆盖或顺序错乱 | 跑完立刻用 `adapt_maye_assistant.py check` 检测 |
| 它的 AdGuardHome/mosdns 插件 | native 版，DNS 端口 554/553 + uci 配置，与我们的 Docker AGH(:53) 全网接管冲突 | **不要在它菜单里装 AGH/mosdns** |
| 它的 Docker 卸载分支 | `rm -f /etc/config/dockerd` + `rm -rf` Docker 全套 + `cleanup_appcenter_entry` | **不要在它菜单里选卸载 Docker** |
| 奇游/雷神 | 明文 HTTP 下载 + 直接 root 执行，无校验和 | 不要在它菜单里装；要用就自己下、先核对 |
| 它不备份 | 任何改动都无回滚依据 | 跑前自行备份，见 playbook §4① |
| 哈基米等插件 | 与我们的补丁无冲突 | 正常 |

## 标准操作流程

```
0. 🔴 自行备份它可能改到的文件（它自己不备份）
1. python scripts/adapt_maye_assistant.py snapshot   # 跑 maye 之前（已有基线可跳过）
2. 用户在路由器上跑:
     cd /tmp && wget -O ssh-nradio-plugin-installer.sh \
       https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/refs/heads/main/00-current/ssh-nradio-plugin-installer.sh
     sha256sum ssh-nradio-plugin-installer.sh   # 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8
     sh -n ssh-nradio-plugin-installer.sh && sh ssh-nradio-plugin-installer.sh
3. python scripts/adapt_maye_assistant.py check        # 检测 6 个补丁指纹
4. 有丢失 → python scripts/adapt_maye_assistant.py check --fix   # 自动重放对应 patches 脚本
5. 复核: 再跑一次 check; 清缓存 rm -rf /tmp/luci-indexcache*（重放脚本会自己清）
```

> 旧版的下载地址 `https://nradio.mayebano.shop/ssh-nradio-plugin-installer.sh` 已不作为首选 ——
> 实测可用且带完整性对账的是上面的 `ghproxy.vip` 链（配上游 `CHECKSUMS.txt` 校验 sha256）。

## 补丁指纹清单（adapt_maye_assistant.py 的 MARKERS）

- appcenter.lua：extra_installed_merge / extra_action / _kp_installed_registry /
  _online_install_percent / `&& kp-store-register`
- appcenter.htm：aurora_open_app

基线存储：本地 `maye-baseline.json`（与适配器脚本同目录）+ 路由器 `/etc/kp_store/patch-baseline.json`。

> 基线现状（2026-09-20 复核）：本地基线文件与路由器 `/etc/kp_store/patch-baseline.json`
> **均不存在**，`/etc/kp_store/` 里只有 `routes.list`；appcenter 两个文件的三个 marker 全为 0,
> appcenter.htm 的 `Design By MaYe` 计数为 0 —— 即**本机还没跑过我们的商店补丁，也还没被
> maye 改过任何页面**，当前无冲突面。
>
> 更正旧版记录：旧版写「`/root/.nradio-plugin-menu/` 与 `/root/nradio-plugin-fix/` 均不存在」——
> 现在前者**存在**（2026-09-20 真机跑菜单、只接受免责声明就创建了，见上文「状态目录」一节），
> 后者**仍然不存在**（上游死路径，永不创建）。
> 另外旧版提到「已在 C2000 Max 上跑过 V2.9.9」指的是**已下线的另一台机器**，
> 与这台 C2000 U 无关。
