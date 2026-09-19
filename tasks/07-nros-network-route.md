# 任务 07 · 分类二「VPN / 组网 / 路由向导」（助手菜单 6）

> `id: nros.network-route` · `risk: destructive`（**碰策略路由＝可能中断全网，而本机 OpenClash 是全网出口**）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> **这是第三方 NROS 插件安装器（maye 助手）的第 2 个功能分类。**
> 总入口、通用四关、下载/校验/备份/基线/真终端手法全部在
> [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) —— 本文件只写这一分类特有的东西。
> 对应关系：**助手菜单 `6)` ＝ 上游脚本主菜单 `2. VPN / 组网 / 路由向导`**
> 上游真源：`installer.sh:70130-70158`（`network_route_menu`）· `installer.sh:69918-70071`（`run_menu_feature`）

---

## 0. 本分类的置顶红线

1. 🔴 **这是全脚本唯一「改动网络平面」的分类 —— 本机做它要单独开一次、网络空闲时做。**
   上游的向导会往策略路由表里插规则，实读到的写入语句（EasyTier 分支，`installer.sh:39448-39452`）：
   ```sh
   ip rule add  to "$ET_ROUTE_REMOTE_SUBNET" lookup main priority 60
   ip rule add  iif "$ET_ROUTE_LAN_IF" to "$ET_ROUTE_REMOTE_SUBNET" lookup main priority 70
   ip rule add  from "$ET_ROUTE_LOCAL_SUBNET" to "$ET_ROUTE_REMOTE_SUBNET" lookup main priority 196
   ```
   OpenVPN 分支同类（`configure_openvpn_routes`，写入前会先 `ip rule del … priority 60/70/196` 清理，`installer.sh:3501-3503`、`39222-39224`）。
   **本机现状**：OpenClash 在用 TUN + fake-ip（`198.18.0.0/16`）做**全网出口**（`pidof clash` = **16659**），
   新增 `ip rule` 会改变流量走向 → **断网风险最高的一个分类**。

2. 🔴 **安装 = 新增虚拟网卡 + 常驻服务。**
   ZeroTier / EasyTier 都会建自己的网卡与 init 服务。本机历史上装过 ZeroTier（TAP 早已断开），
   再装一遍是**新开一条常驻隧道**，不是恢复旧状态。

3. 🔴 **向导里的「本地 LAN / 远端子网 / 接口名」必须由你回答，AI 不许代填。**
   上游是 `prompt_with_default '本地 LAN 接口' "$lan_if_default"` 这类交互（`installer.sh:39532-39533`），
   填错＝把整段流量导进隧道。AI 只能把「该填什么」讲清楚，值由你敲。

4. ⚠️ **`7. OpenVPN 自检` 是唯一只读项**（feature 12 → `run_openvpn_selfcheck`，`installer.sh:69980-69982`），
   但**前提是已装过 OpenVPN**；没装会直接报缺文件。想「先看一眼」的话，它不产生写入。

---

## 1. 上游菜单真源（逐字抄自 `network_route_menu`）

```
  2 / VPN 与组网
   1. ZeroTier
   2. EasyTier
   3. OpenVPN
   4. OpenVPN 向导配置并运行
   5. OpenVPN 路由表向导
   6. EasyTier 路由表向导
   7. OpenVPN 自检
   0. 返回功能分类
```

| 菜单号 | 名称 | feature | 实现的函数 | 上游行号 | 写盘？ |
|---|---|---|---|---|---|
| 1 | ZeroTier | 6 | `install_zerotier` | 69950-69954 | 装包 + 建网卡 + 服务 |
| 2 | EasyTier | 7 | `install_easytier` | 69955-69959 | 装包 + `/etc/easytier/config.toml` + `/etc/init.d/easytier` |
| 3 | OpenVPN | 8 | `install_openvpn` | 69960-69964 | 装包 + LuCI 页面 |
| 4 | OpenVPN 向导配置并运行 | 9 | `configure_openvpn_runtime` | 69965-69969 | 写配置 + 起服务 |
| 5 | OpenVPN 路由表向导 | 10 | `configure_openvpn_routes` | 69970-69974 | **写 `ip rule`（60/70/196）** |
| 6 | EasyTier 路由表向导 | 11 | `configure_easytier_routes` | 69975-69979 · 函数 39515 | **写 `ip rule` + 生成开机脚本**（`:39448` 起） |
| 7 | OpenVPN 自检 | 12 | `run_openvpn_selfcheck` | 69980-69983 | 只读 |

> 前三个（6/7/8）不是 feature 号，菜单号与 feature 号在这里刚好错开，**照菜单号按**。

---

## 2. 本机（NRadio_C2000Ultra）可用子集

本分类**没有机型白名单**（不像 swap / eMMC 有 `*_model_supported`），
只要过了 `require_nradio_menu_environment`（主菜单选 `2` 会触发，`installer.sh:72416`）就都能进。

| 菜单号 | 本机 | 说明 |
|---|---|---|
| 1 ZeroTier | ⚠️ 可用，风险中 | 打开即是一条常驻隧道；本机历史上装过（TAP 已断开） |
| 2 EasyTier | ⚠️ 可用，风险中 | 需要填组网参数；会写 `/etc/easytier/config.toml` |
| 3 OpenVPN | ⚠️ 可用，风险中 | 装包本身不动路由 |
| 4 OpenVPN 向导 | 🔴 可用但高危 | 向导会把流量导进隧道 |
| 5 OpenVPN 路由表向导 | 🔴 可用但高危 | 直接改 `ip rule` |
| 6 EasyTier 路由表向导 | 🔴 可用但高危 | 直接改 `ip rule` 并生成开机重放脚本 |
| 7 OpenVPN 自检 | ✅ 只读 | 未装 OpenVPN 时会报缺文件，无副作用 |

**一句话**：本分类在「OpenClash 全网出口」的设备上**默认不做**；
真要做，只做 **1/2/3（装、不配路由）**，`4/5/6` 属于网络平面变更，必须单独一次、你在场、做完立刻复验。

---

## 3. 前置检查（在 tasks/05 §3 那 11 条之外，本分类额外要测）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| a | **网络基线（最重要）** | `pidof clash; ip -4 rule \| wc -l; ip -4 route show \| head -20` | 全部记录成基线 | 没基线就没法判断是不是它干的 |
| b | 默认路由出口 | `ip -4 route show default` | 记下（本机是 OpenClash 的 TUN） | 跑完这条不能变 |
| c | 已有隧道进程 | `pidof zerotier-one; pidof easytier-core; pidof openvpn` | 无输出最好 | 有＝已装过，别重复装 |
| d | 已有网卡 | `ip -o link show \| awk -F': ' '{print $2}'` | 记下清单（本机有 `tun`/`tap` 历史残留可能） | 有旧网卡先搞清楚是什么 |
| e | mwan3 状态 | `uci -q show mwan3 \| head; mwan3 status 2>/dev/null \| head` | 记录 | 多线负载均衡与策略路由会互相干扰 |
| f | 真 HTTP 基线 | `curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com` | `200` | 起跑前必须通，否则后面分不清是谁弄断的 |

```sh
# 一次性跑完（设备侧，只读）—— 这份输出就是「网络基线」，务必存档
echo "--- a clash";  pidof clash; ip -4 rule | wc -l
echo "--- b default"; ip -4 route show default
echo "--- c procs";  for p in zerotier-one easytier-core openvpn; do printf '%s=' "$p"; pidof $p || echo none; done
echo "--- d links";  ip -o link show | awk -F': ' '{print $2}'
echo "--- e mwan3";  uci -q show mwan3 2>/dev/null | head -5 || echo NO_MWAN3
echo "--- f http";   curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
```

---

## 4. 执行

**通用部分照 tasks/05 §4 走**（自备备份 → `snapshot` → 下载 → `sha256sum` + `sh -n`）。

### (a) AI 先做

```sh
# ① 本分类要额外备份的对象（路由/防火墙/网络配置是本分类的全部影响面）
mkdir -p /tmp/kp-maye-bak/net
for f in /etc/config/network /etc/config/firewall /etc/config/dhcp /etc/config/mwan3; do
    [ -f "$f" ] && cp "$f" /tmp/kp-maye-bak/net/
done
ip -4 rule        > /tmp/kp-maye-bak/net/ip-rule.before.txt
ip -4 route show  > /tmp/kp-maye-bak/net/ip-route.before.txt
ip -6 rule        > /tmp/kp-maye-bak/net/ip6-rule.before.txt 2>/dev/null
ls -l /tmp/kp-maye-bak/net/
#   建议立刻拉到 PC：scp root@192.168.66.1:/tmp/kp-maye-bak/net/* ./

# ② 记远端子网/接口基线（向导会问这些，先把「现在是什么」查清楚给你看）
ip -4 addr show | grep -E 'inet |^[0-9]+:' | head -20
uci -q get network.lan.ipaddr 2>/dev/null; uci -q get network.lan.netmask 2>/dev/null
```

### (b) 然后停下等你 —— 由你在真终端里按

```sh
sh /tmp/ssh-nradio-plugin-installer.sh
```

进菜单后 `2` →「VPN / 组网 / 路由向导」。
**建议只按 `1 / 2 / 3`（装，不配路由）**；`4 / 5 / 6` 要动路由，按之前先跟 AI 说一声。
AI **不许**替你按任何编号，也不许替你回答向导里的子网/接口（协议硬约束 3 与 9）。

### (c) 你回来后 AI 立刻跑（顺序不能颠倒）

```sh
# ① 先看网还在不在
pidof clash
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com     # 期望 200
ip -4 route show default

# ② 再对比策略路由差异（本分类的「有没有乱改」证据）
ip -4 rule        > /tmp/kp-maye-bak/net/ip-rule.after.txt
diff -u /tmp/kp-maye-bak/net/ip-rule.before.txt /tmp/kp-maye-bak/net/ip-rule.after.txt && echo RULE_UNCHANGED

# ③ 最后才跑补丁校验
python scripts/adapt_maye_assistant.py check
```

---

## 5. 验证判据

| 判据 | 期望 | 拿不到怎么办 |
|---|---|---|
| `pidof clash` | 与跑前**同值**（本机 16659） | 立刻按 §6 回滚路由 |
| 真 HTTP | `200` | 同上；**不要用 ping/TCP 判断**（fake-ip + TUN 会本地接管） |
| `ip -4 route show default` | 与跑前一致 | 说明默认出口被改了 → 回滚 `/etc/config/network` |
| `ip -4 rule` 差异 | 只有你**主动**做向导时才会变 | 没做向导却变了 → 直接回滚 |
| 该装的服务的状态 | `pidof zerotier-one` / `pidof easytier-core` 有输出 | 拿不到就说没装上，**别说「应该好了」** |
| 新网卡 | `ip -o link show` 里能看到对应隧道网卡 | —— |
| 三个补丁 marker | 仍 ≥1 | `check --fix` |

```sh
# 一次性判据（设备侧）
echo "--- clash";   pidof clash
echo "--- http";    curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
echo "--- default"; ip -4 route show default
echo "--- rules";   ip -4 rule
echo "--- svc";     pidof zerotier-one; pidof easytier-core
```

---

## 6. 回滚

> 本分类的回滚**比别的分类更紧急**：网络一断，SSH 也可能一起没。所以备份必须在跑之前做。
> 若 SSH 也断了 → 走 [`references/no-ssh-recovery.md`](../references/no-ssh-recovery.md)。

| 想恢复什么 | 怎么做 |
|---|---|
| 策略路由被写乱 | 逐条删掉上游加的那三条：`ip rule del to <远端子网> lookup main priority 60` 等（对应 `installer.sh:39448-39452` 的反向） |
| network / firewall 被改 | 用 §4(a) 的备份覆盖 → `/etc/init.d/network reload` + `/etc/init.d/firewall reload` |
| mwan3 被重启打乱 | `/etc/init.d/mwan3 restart`；多线策略见 [`references/c2000u-media.md`](../references/c2000u-media.md) |
| EasyTier 开机脚本残留 | 上游会生成开机重放脚本（`installer.sh:39448` 区块是它写进脚本里的原文）→ 找到并删除该脚本，否则重启后规则又回来 |
| 新装的 VPN 包 | `opkg remove`；`/etc/init.d/<svc> disable && stop` |
| OpenClash 断了 | `/etc/init.d/openclash restart`，等 30–60 秒防火墙规则落定（期间 curl 全 000 属正常） |
| 我们的商店补丁 | `python scripts/adapt_maye_assistant.py check --fix` |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 跑完 SSH 也断了 | 默认路由被策略规则抢走 | 走 `references/no-ssh-recovery.md`；LAN 口直连 + 串口/救砖流程 |
| `curl` 全 `000`，但 ping 通 | fake-ip + TUN 本地接管，ping 不能判活 | 换成真 HTTP（`http_code`）判断 |
| 规则删了但重启又回来 | EasyTier 向导生成了开机重放脚本 | 找到那个脚本删掉（见 §6） |
| 远端子网填错 | 向导交互是 `prompt_with_default`，AI 代填过 | 按 §6 删规则重来；**向导一律你自己填** |
| mwan3 与策略路由互相打架 | 多线负载均衡也在写 mangle/rule | 先 `mwan3 status` 看清，再决定要不要做向导 |
| OpenClash 起不来的假象 | 启动后 30–60 秒防火墙规则才落定 | 等，别急着回滚 |
| ZeroTier 装完一直 offline | 需要去 ZeroTier 控制台授权节点 | 属正常，不是脚本 bug |

---

## 8. 与其他文件的关系

- 通用四关 / 下载校验 / 真终端手法 / stdin 三种行为 → [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md)
- 网络类故障恢复 → [`references/no-ssh-recovery.md`](../references/no-ssh-recovery.md) · [`references/one-command-restore.md`](../references/one-command-restore.md)
- OpenClash 与代理接管 → [`references/c2000u-openclash.md`](../references/c2000u-openclash.md)
- 菜单协议（AI 怎么被调用）→ [`AGENTS.md`](../AGENTS.md) §8
