# 任务 10 · 分类五「设备维护与检测」（助手菜单 9）

> `id: nros.maintenance` · `risk: write`（多数项只读，但**「硬件加速管理」会 `fw3 reload` ＝重建 nat 链，在网络出口机器上属高危**）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> **这是第三方 NROS 插件安装器（maye 助手）的第 5 个功能分类。**
> 总入口、通用四关、下载/校验/备份/基线/真终端手法全部在
> [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) —— 本文件只写这一分类特有的东西。
> 对应关系：**助手菜单 `9)` ＝ 上游脚本主菜单 `5. 设备维护与检测`**
> 上游真源：`installer.sh:72198-72338`（`maintenance_test_menu`）· `installer.sh:69918-70071`（`run_menu_feature`）

---

## 0. 本分类的置顶红线

1. 🔴 **`11. 硬件加速管理` 会重载防火墙 —— 本机是全网出口，断网代价高。**
   `manage_nradio_hardware_acceleration`（`installer.sh:69846-69875`）+ `nradio_hwaccel_set`（`:69736-69751`）实读：
   ```sh
   uci set firewall.@defaults[0].flow_offloading=1        # 或 flow_offloading_hw
   uci commit firewall
   uci set mtkhnat.global.mode=0|2                        # 开=0 关=2
   uci set mtkhnat.global.enable=1
   uci commit mtkhnat
   fw3 reload                                             # <-- 重建 nat 链
   /etc/init.d/mtkhnat enable
   /etc/init.d/mtkhnat restart
   ```
   offload 与代理接管是已知冲突项（`installer.sh:20077-20086` 与 `:69742-69749`）。
   ⚠️ 注意它**自带**专用配置备份（`HWACCEL_BACKUP`，与空实现的 `backup_file()` 不同）——
   所以「想撤」是有依据的，但**做的时机**仍必须挑网络空闲时。

2. 🔴 **`3. 哈基米傻瓜分流助手` 会改正在运行的 OpenClash 配置。**
   `run_hakimi_easy_rule_helper`（`installer.sh:23047`）实读：
   ```sh
   config_path="$(unified_get_openclash_config_path)"          # 取当前 OpenClash 的 YAML
   hakimi_build_policy_menu "$config_path" "$policy_file"      # 从 YAML 解析出可用分流目标
   log "说明: 分流规则、订阅下载策略与域名 DNS 可联动保存，供重载时应用"
   ```
   → 它读的就是本机在跑的那份订阅配置（`pidof clash` = **16659**）。
   改坏＝代理挂了＝全网出口挂了。跑前必须备份当前 YAML。

3. ⚠️ **`2. 风扇控制` 与 `4. eMMC 存储扩展` 在本机是「能看见但做不了」。**
   - 风扇：`install_fanctrl` 只认 `NRadio_C8-688|NRadio_C2000MAX|NRadio_C8-788`，
     本机走 `*)` 分支，只打印「当前机型不支持增强风扇控制」+ 原始识别信息就返回（`installer.sh:39107-39117`），**不改盘**。
   - eMMC：`manage_rootfs_2nd_storage_expand`（`:34528`）内部 `require_rootfs_2nd_storage_capable`（`:31877`）
     只认 `NRadio_C5800-650|C5800-688|C8-688|NBCPE`，本机**直接 `die "当前机型不支持 eMMC 存储扩展"`**。
   这两项别浪费时间，也别因为「菜单里有」就以为能用。

4. ⚠️ **`5 › 9` 与 `5 › 10` 在本机是空的跳号。**
   本机维护菜单是**动态编号**（`installer.sh:72249-72299`）：`5G 聚合修复检查`（feature 21）与
   `5G 连接监听`（feature 29）两项在本机不打印（机型判据分别只认 C5800 系列/C8-688 与 C5800 系列/C2000MAX），
   于是编号直接跳到固定的 `11 硬件加速管理` / `12 返回功能分类`，提示行是 `0-8 / 11-12`。
   **→ 「按顺序数第 9 项」会按到不存在的编号。这正是「AI 不许替人按菜单」的活例子。**

5. ✅ **本分类不触发环境门禁**（主菜单只在选 `1|2|3|4` 时检查，`installer.sh:72416`），
   且 feature `33|34` 额外豁免（`:69889`、`:69922`）。只想体检的话，链路最干净。

---

## 1. 上游菜单真源（本机 = 非 AK68-798 / 非 C8-788 的动态编号分支）

`maintenance_test_menu` 对普通机型按顺序编号，实际渲染出来是：

```
  5 / 设备维护
   1. 统一体检增强版
   2. 风扇控制（C8-688/788、C2000MAX）
   3. 哈基米傻瓜分流助手
   4. eMMC 存储扩展
   5. 哈基米依赖检查修复
   6. 封版工具箱
   7. 运营商与卡名显示修复
   8. 首页 CPU / 5G 温度切换
  11. 硬件加速管理
  12. 返回功能分类
选择 [0-8 / 11-12]:
```

> `5G 聚合修复检查` / `5G 连接监听` 在本机**不打印**，所以 9、10 是空的（见红线 4）。

| 菜单号 | 名称 | feature | 实现的函数 | 上游行号 | 本机 |
|---|---|---|---|---|---|
| 1 | 统一体检增强版 | 13 | `run_unified_test_mode` | 69984-69986 · 函数 23165 | ✅ 主要只读 |
| 2 | 风扇控制 | 14 | `install_fanctrl` | 69988-69990 · 函数 39099 | ❌ 仅提示不支持 |
| 3 | 哈基米傻瓜分流助手 | 19 | `run_hakimi_easy_rule_helper` | 69992-69993 · 函数 23047 | 🔴 改 OpenClash 配置 |
| 4 | eMMC 存储扩展 | 20 | `manage_rootfs_2nd_storage_expand` | 69995-69996 · 函数 34528 | ❌ `die` 不支持 |
| 5 | 哈基米依赖检查修复 | 23 | `run_openclash_dependency_repair_check` | 70025-70027 · 函数 22890 | ✅ 检查/修复 OpenClash 依赖 |
| 6 | 封版工具箱 | 24 | `run_final_stability_toolbox` | 70029-70030 · 函数 2955 | ✅ **只读** |
| 7 | 运营商与卡名显示修复 | 26 | `manage_nradio_operator_display_fix` | 70032-70033 · 函数 57471 | ✅ 改 LuCI 页面 |
| 8 | 首页 CPU / 5G 温度切换 | 27 | `manage_nradio_home_temperature_switch` | 70035-70036 · 函数 58472 | ✅ 改首页 |
| 11 | 硬件加速管理 | 33 | `manage_nradio_hardware_acceleration` | 70057-70058 · 函数 69846 | 🔴 见红线 1 |
| 12 | 返回功能分类 | —— | —— | 72301 | —— |
| （本机不显示） | 5G 聚合修复检查 | 21 | `run_5g_aggregation_repair_check` | 69998-69999 · 判据 19196 | ❌ 仅 C5800/C8-688 |
| （本机不显示） | 5G 连接监听 | 29 | `manage_nradio_cpe_connection_monitoring` | 70041-70042 · 判据 58517 | ❌ 仅 C5800 系列/C2000MAX |

### 三个二级菜单（都要再按一层）

```
封版工具箱（6）                    运营商与卡名（7）              首页温度（8）
 1. 导出脱敏诊断报告               1. 安装或更新修复               1. 安装或更新
 2. 查看备份清单                   2. 查看修复状态                 2. 查看安装详情
 3. 查看动作日志                   3. 移除修复                     3. 移除温度切换
 0. 返回设备维护与检测             4. 配置当前 SIM 卡名            0. 返回设备维护
                                   0. 返回设备维护与检测

硬件加速管理（11）
 1. 开启硬件加速
 2. 关闭硬件加速（保留软件加速）
 3. 查看当前状态
 0. 返回设备维护
```

---

## 2. 本机可用子集小结

**默认只做 `1 / 6`（体检 + 工具箱，基本只读）**：
- `1 统一体检增强版` —— 26 PASS / 2 WARN / 0 FAIL / 4 SKIP 这类汇总报告（上游在 C5800-688 上实跑过）
- `6 封版工具箱` —— 导出脱敏诊断报告 / 备份清单 / 动作日志，**全是读取**

**按需做 `5 / 7 / 8`**（都是可逆的页面级改动）：
- `5 哈基米依赖检查修复` —— 检查 OpenClash 配置/服务/核心/`ASN.mmdb`/`Model.bin`，缺什么补什么
- `7 运营商与卡名显示修复` —— 有「移除修复」项
- `8 首页 CPU / 5G 温度切换` —— 有「移除温度切换」项

**谨慎做 `3`**（改 OpenClash 分流配置，必须先备份 YAML）。

**不要做 `11`**（红线 1）；`2 / 4` 做不了（红线 3）。

---

## 3. 前置检查（在 tasks/05 §3 那 11 条之外，本分类额外要测）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| a | **体检前基线** | `pidof clash; pidof dockerd; free -k \| sed -n '1,3p'; df -h /overlay` | 全部记录 | 用来做跑后对照 |
| b | 硬件加速现状（只想做了解决定的话） | `uci -q show firewall \| grep flow_offloading; uci -q show mtkhnat; ls -l /etc/init.d/mtkhnat /sbin/mtkhnat` | 记下 | —— |
| c | 硬件加速能力自检判据 | 上游 `nradio_hwaccel_capabilities`（`:69547-69557`）要求：`uci fw3 iptables awk cmp mktemp` + `/etc/init.d/mtkhnat` + `/sbin/mtkhnat` + `/sys/kernel/debug/hnat/hook_toggle`（可读写） | 全在 | 缺任一项它自己会报缺失 |
| d | **OpenClash 配置路径（只做 3 之前必查）** | `uci -q get openclash.config.config_path; ls -l <该文件>` | 存在且非空 | 路径取不到 → `run_hakimi_easy_rule_helper` 会 `die` |
| e | 依赖件是否在位（只做 5 之前看） | `ls -l /etc/openclash/ASN.mmdb /etc/openclash/Model.bin /etc/openclash/core/clash_meta 2>&1` | 三个都在 | 缺了正好由 5 来补 |
| f | 温度显示组件现状（只做 8 之前看） | `ls -l /usr/lib/lua/luci/view/admin_status/ 2>/dev/null \| head` | 记下 | 有「移除温度切换」可回退 |
| g | 内存余量 | `free -k` 看 `MemAvailable` | >100 MB | 体检会跑很多命令，别在紧内存时做 |

```sh
# 一次性跑完（设备侧，只读）
echo "--- a base"; pidof clash; pidof dockerd; free -k | sed -n '1,3p'; df -h /overlay
echo "--- b hwaccel"; uci -q show firewall | grep flow_offloading || echo NO_OFFLOAD_OPT
echo "                   "; uci -q show mtkhnat 2>&1 | head -8
echo "--- c cap"; for c in uci fw3 iptables awk cmp mktemp; do printf '%s=' "$c"; command -v $c || echo MISSING; done
echo "             "; ls -l /etc/init.d/mtkhnat /sbin/mtkhnat /sys/kernel/debug/hnat/hook_toggle 2>&1
echo "--- d oc cfg"; uci -q get openclash.config.config_path
echo "--- e deps"; ls -l /etc/openclash/ASN.mmdb /etc/openclash/Model.bin /etc/openclash/core/clash_meta 2>&1
echo "--- g mem"; free -k | sed -n '2p'
```

---

## 4. 执行

**通用部分照 tasks/05 §4 走**（自备备份 → `snapshot` → 下载 → `sha256sum` + `sh -n`）。

### (a) AI 先做

```sh
# ① 本分类的备份对象（按你打算做哪几项挑）
mkdir -p /tmp/kp-maye-bak/maint
cp /etc/config/firewall /tmp/kp-maye-bak/maint/ 2>/dev/null
cp /etc/config/mtkhnat  /tmp/kp-maye-bak/maint/ 2>/dev/null
#   OpenClash 当前 YAML（做 3 之前必须，路径来自 §3(d)）
OC_CFG="$(uci -q get openclash.config.config_path)"
[ -n "$OC_CFG" ] && cp "$OC_CFG" /tmp/kp-maye-bak/maint/openclash-config.bak.yml
#   LuCI 页面（做 7 / 8 之前）
cp -r /usr/lib/lua/luci/view/admin_status /tmp/kp-maye-bak/maint/admin_status.bak 2>/dev/null
#   温度/卡名相关 UCI
uci -q show nradio > /tmp/kp-maye-bak/maint/nradio.uci.txt 2>/dev/null
ls -lR /tmp/kp-maye-bak/maint | head -30

# ② 拍我们的补丁基线
python scripts/adapt_maye_assistant.py snapshot

# ③ 网络基线（红线 1 的哨兵）
pidof clash > /tmp/kp-maye-bak/maint/clash.before.txt
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
```

### (b) 然后停下等你 —— 由你在真终端里按

```sh
sh /tmp/ssh-nradio-plugin-installer.sh      # 结尾不许跟参数
```

进菜单 `5` →「设备维护与检测」。**建议只按 `1`、`6`**（只读体检 + 工具箱）。
按 `3 / 5 / 7 / 8` 前先跟 AI 说一声；**`11` 硬件加速一律先拦一下**（红线 1）。
⚠️ 注意本机提示是 `0-8 / 11-12` —— **9 和 10 不存在**，别按（红线 4）。
AI **不许**替你按任何编号（协议硬约束 9）。

### (c) 你回来后 AI 立刻跑

```sh
# ① 网络没断（做 11 的人必看；做别的也应该看）
pidof clash
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com      # 期望 200

# ② OpenClash 配置没被改坏（做了 3 才需要重点看）
OC_CFG="$(uci -q get openclash.config.config_path)"
[ -n "$OC_CFG" ] && sha256sum "$OC_CFG"
diff -q "$OC_CFG" /tmp/kp-maye-bak/maint/openclash-config.bak.yml || echo "OC 配置有变化 → 逐行 diff 看清"

# ③ 我们的补丁
python scripts/adapt_maye_assistant.py check

# ④ 硬件加速后置（做了 11 才需要）
uci -q show firewall | grep flow_offloading
uci -q show mtkhnat
```

---

## 5. 验证判据

| 判据 | 期望 | 说明 |
|---|---|---|
| 体检输出 | 有完整 PASS/WARN/FAIL/SKIP 汇总 | 拿不到汇总＝没跑完，别说「体检通过」 |
| `pidof clash` | 与跑前**同值**（本机 16659） | 做了 `3` 或 `11` 时尤其要盯 |
| 真 HTTP | `200` | **别用 ping/TCP 判活**（fake-ip + TUN 会本地接管） |
| OpenClash YAML | 与备份一致（除非你在 3 里**主动**改了分流） | 不一致就 diff 看是预期内还是被写坏 |
| 三个补丁 marker | 仍 ≥1 | 本分类一般不碰商店，变了要查 |
| `/etc/config/dockerd` | 仍在且含 `data_root` | 兜底哨兵 |
| 做了 `11` 后 | `uci show mtkhnat` 有值、`/etc/init.d/mtkhnat status` 正常、真 HTTP 仍 200 | fw3 reload 后要等规则落定 |
| 做了 `7 / 8` 后 | 有对应的「移除」入口可用 | 证明改动是可逆的 |

```sh
# 一次性判据（设备侧）
echo "--- clash"; pidof clash
echo "--- http";  curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
echo "--- mark";  grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
echo "--- dock";  grep -nE 'data_root|registry_mirrors' /etc/config/dockerd
```

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 硬件加速被改乱 | 上游自己保留 `HWACCEL_BACKUP`；或 `cp /tmp/kp-maye-bak/maint/firewall /etc/config/firewall` + `uci -q show mtkhnat` 对照还原 → `fw3 reload` → `/etc/init.d/mtkhnat restart` |
| OpenClash 分流被改坏 | 用 §4(a)① 的 `openclash-config.bak.yml` 覆盖 → `/etc/init.d/openclash restart`（等 30–60 秒规则落定） |
| 页面温度 / 卡名显示 | 走它自己的「移除」入口（`8 → 3`、`7 → 3`）；或用 `admin_status.bak` 覆盖 |
| 我们的商店补丁 | `python scripts/adapt_maye_assistant.py check --fix` |
| OpenClash 核心被误动 | 重走 [`tasks/01-openclash-install.md`](01-openclash-install.md)（离线素材 `offline/core/`） |
| 断网了 | [`references/no-ssh-recovery.md`](../references/no-ssh-recovery.md) · [`references/one-command-restore.md`](../references/one-command-restore.md) |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 按 `9` 或 `10` 报「无效编号」 | 本机这两项不打印（跳号，见红线 4） | 按 `0-8` / `11-12` 范围内的编号 |
| `风扇控制` 只打印一段提示就返回 | 本机机型不在风扇白名单（红线 3） | 正常，别反复试 |
| `eMMC 存储扩展` 直接 `die` | 本机机型不在 rootfs_2nd 白名单（红线 3） | 正常；存储扩展走 [`references/tf-partition-resize.md`](../references/tf-partition-resize.md) |
| 选 `11` 之后网页卡一下 / 短暂不通 | `fw3 reload` 重建 nat 链 | 等规则落定再测；之后必须复验 DNS 与 clash pid |
| 选 `3` 之后 OpenClash 分流异常 | 傻瓜分流助手改了订阅 YAML | 用备份还原 YAML → `openclash restart` |
| 体检里 `pgrep -c` 全报 NOT RUNNING | busybox 不支持 `pgrep -c` | 判活一律用 `pidof`（上游体检也可能有同类项，注意区分） |
| `哈基米依赖检查修复` 报缺 `ASN.mmdb` | 分流数据库缺失（扩展盘迁移后常见） | 由它补，或见 [`references/c2000u-openclash.md`](../references/c2000u-openclash.md) |
| 体检耗时长 | 它会跑很多只读命令 | 属正常，别中途 Ctrl-C（可能留下锁） |

---

## 8. 与其他文件的关系

- 通用四关 / 下载校验 / 真终端手法 / stdin 三种行为 → [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md)
- 硬件加速面 → 协议硬约束第 7 条第 ⑤ 类（[`AGENTS.md`](../AGENTS.md) §8.7）
- OpenClash 维护与依赖 → [`references/c2000u-openclash.md`](../references/c2000u-openclash.md)
- 存储 / 分区 → [`references/tf-partition-resize.md`](../references/tf-partition-resize.md)
- 菜单协议（AI 怎么被调用）→ [`AGENTS.md`](../AGENTS.md) §8
