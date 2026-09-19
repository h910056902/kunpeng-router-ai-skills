# C2000 U · OpenClash + ocspeed 部署实录（2026-09-11）

> 设备 B：C2000-798 / HC-WT9500 / OpenWrt 21.02-SNAPSHOT rev 2.3.0.n0.c1 / 992MB
> OpenClash 0.47.156 + Mihomo Meta v1.19.30（linux-arm64, with_gvisor）

## 0 · 结论速览

| 项 | 结果 |
|---|---|
| 安装方式 | 本地 ipk（`luci-app-openclash_0.47.156_all.ipk`）+ 手动部署内核 |
| 依赖 | **厂商预装 `pkg-openclash-dep`**（bash/curl/ip-full/ruby/dnsmasq-full/kmod-tun 全在），只补 ruby-yaml |
| 启动耗时 | ~40s（内核 + GeoSite 10.5MB；老 Max 内存压力下要 2.5 分钟） |
| 运行模式 | fake-ip + dnsmasq redirect（Dnsmasq Redirect 模式，非 TPROXY/TUN） |
| 端口 | http 7890 / mixed 7893 / dns 7874 / api 9090 |
| 代理认证 | A 机 UCI 带来 `Clash:mY6Qm1HL`（7893 裸测必 407） |
| ocspeed | v3.3.1 四件套恢复，cron 每 30 分钟，52 节点测速自动切换正常 |
| 商店注册 | openclash（opkg 源）+ ocspeed（local 源），卡片确认出现 |
| 内存代价 | clash 1412m VSZ / 系统可用 645→576MB |

## 1 · 文件投递：SSH 反向隧道（无 SFTP + Windows 防火墙拦入站的通用解）

两个前提坑：设备无 sftp-server（`open_sftp()` EOF during negotiation）；
PC 防火墙拦 LAN 入站（设备 curl PC 的 HTTP 服务不通，TCP 层直接丢）。

**解法**：paramiko 在已建立的 SSH 连接上开反向端口转发：

```python
class RevTunnel:
    def __init__(self, client, lport, rport):
        self.lp = lport
        t = client.get_transport()
        self.port = t.request_port_forward('127.0.0.1', rport, self._handle)
    # _handle -> 双线程 pump 在 SSH channel 与 PC 127.0.0.1:lport 间对拷
```

配套 PC 侧：`http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)`（随机端口，只绑回环）。

设备侧拉取 + 对账：

```sh
curl -s -m 120 -o /tmp/f -w '%{http_code} %{size_download}' http://127.0.0.1:8899/<name>
md5sum /tmp/f   # 与 PC 侧 hashlib.md5 对账
```

实测吞吐：10.2MB/1.6s、16.6MB/2.2s。**大文件（ipk/内核）不再需要 printf 八进制通道。**
完整实现见仓库 `scripts/revtunnel_put.py`（从 `c2000u_phase4a.py` 提取）。

## 2 · 安装步骤

```sh
# 厂商依赖已全（opkg list-installed | grep -i clash 可见 pkg-openclash-dep）
opkg install /tmp/oc_stage/oc.ipk                       # 零依赖报错
opkg install ruby-yaml                                  # 唯一缺件
gunzip -c mihomo.gz > /etc/openclash/core/clash_meta.new
chmod 755 /etc/openclash/core/clash_meta.new
/etc/openclash/core/clash_meta.new -v                   # 自检
mv -f /etc/openclash/core/clash_meta.new /etc/openclash/core/clash_meta
ln -sf /etc/openclash/core/clash_meta /etc/openclash/core/clash
```

## 3 · 配置恢复（A 机 → B 机整体替换）

A 机备份同版本产物，整体替换最可靠：
`config.openclash-uci → /etc/config/openclash`、`bbydy.yaml → /etc/openclash/config/`。
先 `cp -a /etc/config/openclash /etc/config/openclash.bak-pre-restore-$(date +%Y%m%d_%H%M%S)`。

关键 UCI：`enable=1`、`config_path=/etc/openclash/config/bbydy.yaml`、
`en_mode=fake-ip`、`enable_redirect_dns=1`、`redirect_dns=1`（Dnsmasq Redirect）。

启动与验证：

```sh
/etc/init.d/openclash enable && /etc/init.d/openclash start
# 轮询：pidof clash + curl -H "Authorization: Bearer <dashboard_password>" http://127.0.0.1:9090/version
# 节点数：/proxies → luci.jsonc parse 数 pairs
# 出网：curl -U Clash:mY6Qm1HL -x http://127.0.0.1:7893 https://www.google.com   ← 必须带认证
```

**启动后 30-60s 内防火墙规则未就绪，直连 curl 也可能 000——等它落定再测，别急着回滚。**

## 4 · ocspeed 自动测速恢复

| 文件 | 去处 |
|---|---|
| speedswitch.sh | `/usr/libexec/openclash-helper/speedswitch.sh`（755） |
| ocspeed.lua | `/usr/lib/lua/luci/controller/ocspeed.lua` |
| ocspeed.htm | `/usr/lib/lua/luci/view/ocspeed.htm` |
| config.ocspeed-uci | `/etc/config/ocspeed`（组名=宝贝云，间隔 30 分钟） |

cron 追加：

```
#ocspeed-auto
*/30 * * * * /usr/libexec/openclash-helper/speedswitch.sh run >>/var/log/ocspeed.log 2>&1
```

- lua 只依赖 `nixio.fs`/`luci.jsonc`/`luci.model.uci` —— LuCI 标准库，无 shim
- 脚本内 `timeout` 全是**变量名/curl 参数**（`-m $((t/1000+3))`），不依赖外部 timeout 命令
- 冒烟：`nohup speedswitch.sh run >/dev/null 2>&1 &`，看 `/var/log/ocspeed.log`，
  期望「全量测速 52 节点 → 已切换 宝贝云 → 节点名 (初赛 xx ms)」
- 页面挂在 `admin/services/openclash/ocspeed`（也注册了独立入口 `admin/services/ocspeed`）

## 5 · 商店注册

```
openclash|OpenClash|luci-app-openclash|0.47.156|<ts>|admin/services/openclash|opkg|Mihomo Meta v1.19.30 内核，宝贝云订阅 52 节点
ocspeed|OpenClash 自动测速|ocspeed|3.3.1|<ts>|admin/services/openclash/ocspeed|local|节点定时测速/自动切换/趋势图，每 30 分钟
```

验证（lua 直调比 HTTP grep 可靠）：

```lua
-- cd /www && REQUEST_URI=/cgi-bin/luci/ lua -e '
package.path="/usr/lib/lua/?.lua;/usr/lib/lua/?/init.lua;"..package.path
local ok,m=pcall(require,"luci.controller.nradio_adv.appcenter")
local ok2,r=pcall(m.action_app_list_data)
for _,e in ipairs(r.applist) do
  if e.online_key and e.online_key:match("^extra%-") then print(e.name, e.status, e.has_luci, e.luci_module_route) end
end'
```

## 6 · 踩坑速查

| 症状 | 原因 | 处理 |
|---|---|---|
| `open_sftp()` EOF | 无 sftp-server | SSH 反向隧道 + curl（见 §1） |
| 设备拉不到 PC 的 HTTP | Windows 防火墙拦 LAN 入站 | 同上，反向隧道只走 SSH 22 |
| 7893 代理测 407 | UCI authentication 生效 | curl 加 `-U Clash:<密码>` |
| 启动后 curl 全 000 | 防火墙规则未落定 | 等 30-60s 再测 |
| 脚本 `ValueError: unsupported format character '{'` | curl `-w '%{http_code}'` 撞 Python `%` 格式化 | 字符串拼接代替 `%` |
| opkg 报缺依赖 | 一般是 feed 没开或同名截胡 | 本例厂商 dep 包全齐；stub 流程见 c2000u-docker.md |
| SSH 回传中文乱码 | GBK 终端显示层 | 设备侧 UTF-8 正确，用 lua/base64 验证内容 |

## 7 · AGH 容器接管 53（阶段 5 实录，2026-09-11）

最终链路：`LAN → AGH:53 → (默认) clash:7874 fake-ip`；`[/nradio.cc/] → dnsmasq:5354`；
dnsmasq 只剩 DHCP。dpanel:8080 管 Docker。

### 部署要点

```sh
docker run -d --name adguardhome --restart=unless-stopped --network host -e TZ=Asia/Shanghai \
  -v /mnt/storage/data/docker/agh/work:/opt/adguardhome/work \
  -v /mnt/storage/data/docker/agh/conf:/opt/adguardhome/conf \
  adguard/adguardhome:latest

# 初始化必须 JSON（form 报 415）：
curl -X POST http://127.0.0.1:3000/control/install/configure -H 'Content-Type: application/json' \
  -d '{"username":"admin","password":"xxx","web":{"ip":"0.0.0.0","port":3000},"dns":{"ip":"0.0.0.0","port":5353},"listen_interface":"0.0.0.0"}'
```

切 53 顺序（不可反）：改 AGH yaml `port:` → dnsmasq 降 5354（uci commit dhcp）→ restart AGH。
AGH 改配置一律 **先 `docker stop` 再改 yaml 再 start**（停止时会写回内存态，顺序反了改动被覆盖）。

### 踩坑（阶段 5 实测）

| 坑 | 细节 | 对策 |
|---|---|---|
| YAML flow-sequence | 上游行 `[/nradio.cc/]127.0.0.1:5354` 不加引号 → AGH crash loop，**53 无人监听全屋断网** | 一律 `'[/xxx/]...'` 单引号包裹；出事先 `docker logs` 看 parse error 的行号 |
| yaml 二级键缩进 | `upstream_dns:`/`bootstrap_dns:` 是 `dns:` 段下 2 空格缩进键 | 脚本匹配用 `^%s*upstream_dns:` 或直接 sed；行首锚点匹配不到 |
| AGH 登录 API | form POST 返回 400（本版行为） | 别死磕 API——**yaml 是权威配置**，stop→sed→start 同样生效 |
| 上传 lua 补丁失败 | `put_text_verified`（heredoc 整写+分块）对多行 lua 两次静默失败，远端无文件 | 改配置优先**设备端短 sed 逐条改 + grep 验证**；脚本文件走反向隧道 HTTP 或 printf 八进制 |

sed 实改四条（stop 后执行）：

```sh
sed -i 's|    - https://dns10.quad9.net/dns-query|    - 127.0.0.1:7874|' AdGuardHome.yaml
sed -i "\|^  upstream_dns:\$|a\\    - '[/nradio.cc/]127.0.0.1:5354'" AdGuardHome.yaml
sed -i 's|    - 9.9.9.10|    - 223.5.5.5|; s|    - 149.112.112.10|    - 119.29.29.29|; \|    - 2620:fe::10\$|d; \|    - 2620:fe::fe:10\$|d' AdGuardHome.yaml
sed -i 's|url: https://adguardteam.github.io/HostlistsRegistry/assets/filter_1.txt|url: https://anti-ad.net/easylist.txt|; s|name: AdGuard DNS filter|name: anti-AD|' AdGuardHome.yaml
```

### 验证清单（全过 = 链路正确）

```sh
nslookup www.google.com 127.0.0.1   # 198.18.x（fake-ip → clash 已接上）
nslookup doubleclick.net 127.0.0.1  # 0.0.0.0（anti-AD 拦截）
nslookup nradio.cc 127.0.0.1        # 192.168.66.1（定向保留）
curl -o /dev/null -w '%{http_code}' https://www.baidu.com    # 200
curl -U Clash:<密码> -x http://127.0.0.1:7893 https://www.google.com  # 200
```

PC 客户端侧（PowerShell）：`Resolve-DnsName <域名> -Server 192.168.66.1 -DnsOnly` 同样四项。

### dpanel

```sh
docker run -d --name dpanel --restart=always --network host \
  -e APP_NAME=dpanel -e TZ=Asia/Shanghai \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /mnt/storage/data/docker/dpanel:/dpanel dpanel/dpanel:latest
```
host 模式监听 8080；与自建 LuCI 面板（dockerpanel）并存不冲突。

---

## 八、免 SSH 排障：mihomo 控制 API（2026-09-11 实战新增）

### 通道（不需要 SSH，PC 直接打）

mihomo 的 `external-controller` 默认对外监听 **`:9090`**，从 LAN 客户端可直接访问：

```python
# 鉴权就是 OpenClash 的 dashboard 密码（UCI: openclash.config.dashboard_password）
GET  http://192.168.66.1:9090/version            → {"meta":true,"version":"v1.19.30"}
GET  http://192.168.66.1:9090/proxies            → 全部组/节点 + history[-1].delay（0 = 超时不可用）
GET  http://192.168.66.1:9090/proxies/GLOBAL     → now / all
GET  http://192.168.66.1:9090/proxies/<名>/delay?url=http://www.gstatic.com/generate_204&timeout=5000
PUT  http://192.168.66.1:9090/proxies/GLOBAL     body {"name":"延迟最低"}   → 204 = 成功
Header: Authorization: Bearer <dashboard 密码>
```

> PowerShell 不方便时用 `scripts/` 思路写 Python 零依赖脚本即可（工作区 `clash_api.py` / `clash_fix.py` 是现成模板）。

### ⭐ 症状「只有境外网站打不开，国内正常」= 先看 GLOBAL

分流规则兜底（`MATCH`）落在 **`GLOBAL`** 这个 Selector 上。
**`GLOBAL.now == DIRECT` 就是元凶** —— 境外流量全部直连 → 被墙打不开；国内本来就是直连 → 照常通。

成因：**ocspeed `#ocspeed-auto` 每 30 分钟全量测速**，节点大面积超时时把 GLOBAL 落到 DIRECT
（实测 54 节点里 49 个 `delay=0`）。整点触发 → 表现为「每隔一阵子境外就断」。

修复路径（全走 API，30 秒搞定）：

1. `GET /proxies` → 看 `GLOBAL.now`，并统计 `delay=0` 的节点数
2. 对候选节点 `GET /proxies/<名>/delay?url=…&timeout=5000` 实测（**历史 delay 不可信，必须现测**）
3. `PUT /proxies/GLOBAL {"name":"延迟最低"}` → **交给 URLTest 策略组自动选优 + 自动故障转移**
   （别钉单个节点：节点池延迟波动大，钉死会反复失效）
4. 复验：`www.google.com` / `www.youtube.com` / `www.wikipedia.org` 走 fake-ip 发 HTTPS
   （wikipedia 返回 403 也是**连通正常**，那是站点自己回的）

**根治**：关掉或调长 ocspeed 自动测速（改 cron `#ocspeed-auto` / UCI `ocspeed`），
否则下一轮整点它还会把 GLOBAL 切走。

### 两个易错点

| 点 | 说明 |
|---|---|
| **别用 ping / TCP 握手判断出网** | fake-ip + TUN 会本地接管：`ping 223.5.5.5` 0% 丢包、TCP 到外网 IP **0.00s 连上**都是假象。必须发真 HTTP/HTTPS 看响应码 |
| **节点列表里混着"广告/信息"条目** | 订阅把 `剩余流量：926.38 GB`、`套餐到期：2026-09-15`、`邀请好友返佣25%` 之类也当节点；Fallback 组全超时时会选中它们。测速/切组要按真节点名挑 |

### 症状「手机（或某台设备）上不了外网，PC 却正常」= 它没走路由器 DNS

**万能判据：`GET /connections` 按 `metadata.sourceIP` 归因**，对比两台设备：

| 特征 | 正常（走路由器 DNS） | 异常（绕过） |
|---|---|---|
| `metadata.host` | **有域名**（`mtalk.google.com`） | **空**（只有 `destinationIP`） |
| 命中规则 | `DomainSuffix` / `DomainKeyword` / `GeoSite` | **只有 `GeoIP`** |
| 结果 | 该代理的进代理组（如 `宝贝云`） | 一律 `DIRECT` |

→ **只要某台设备的连接全部「无域名 + rule=GeoIP + DIRECT」，就是它的 DNS 没走路由器**，
fake-ip 拿不到域名、域名规则全部失效，境外必然打不开。

**实测案例（荣耀 Magic7）**：手机连接里出现 `119.29.29.99:443` = **腾讯 DNSPod 的 DoH**，
手机自己做了加密 DNS → 拿到真实/被污染 IP → 境外全挂。
修法（手机侧，秒改）：
`设置 → 更多连接 → 私有 DNS/加密 DNS → 关闭` +
`WLAN → 长按当前网络 → 修改网络 → 高级：IP=DHCP、DNS=自动`，然后断开 Wi-Fi 重连清缓存。
（荣耀部分版本还有"安全 DNS"开关，默认会指到 DNSPod，一并关掉。）

**路由器侧加固（2026-09-11 已实装，见 §9.3）**：53 劫持其实一直在（`PREROUTING --dport 53 → REDIRECT`），
**明文 DNS 是拦得住的**；真正绕过的是 DoH/DoT。已加两条 fw3 规则：`REJECT 853`（DoT，通用安全）
+ `REJECT` DNSPod 的 DoH IP（`119.29.29.99 / 119.29.29.29 / 119.28.28.28 / 182.254.116.116`，针对性）。
实测生效后手机侧 `119.29.x` 连接降到 0 条。
⚠️ 只拦这几个 IP 是**权衡**：全量拦 DoH 要维护 ipset/域名列表，且误伤 CDN，成本高。够用即可。

---

## 九、「只有境外打不开」的真正机制（2026-09-11 23:30-00:10 复盘，推翻前两次归因）

### 9.1 两次错误归因（务必别再犯）

| 轮次 | 当时的结论 | 为什么错 |
|---|---|---|
| 第 1 次 | ocspeed 每 30 分钟自动测速把 `GLOBAL` 切成了 DIRECT | ❌ ocspeed 只切 `ocspeed.main.group`（=**宝贝云**）。日志 16:00-23:30 全是「已切换 宝贝云 …」；脚本第 572 行还有 `case "$cur" in GLOBAL\|DIRECT\|...\|宝贝云) return 0` 的**显式保护** |
| 第 2 次 | 我把 `GLOBAL` 改成「延迟最低」后 google 通了，所以是修好了 | ❌ **安慰剂**。规则里压根没引用 GLOBAL（yaml 里 grep 不到，它是 mihomo **内核内置组**）。真正生效的是 ocspeed 在 23:01 把 `宝贝云` 切到了健康节点 |

**教训**：改完一个东西「看起来好了」，必须证明**因果**（改之前后各测 3 次 + 确认该对象真在流量路径上），否则就是安慰剂。

### 9.2 真实链路与真实故障点

```
rules:  … → GEOIP,CN,DIRECT → MATCH,宝贝云      ← 兜底指向订阅的代理组，不是 GLOBAL
```
`MATCH` 走到 `宝贝云`（Selector），ocspeed 每 30 分钟全量测速并 `PUT` 切换它。
**故障触发**：出现「决赛全部未通过，按初赛排名兜底」（实测 22:43:13 发生过一次）→
选了一个初赛有分、决赛不通的节点（如 `L1|新加坡02|直连|流媒体|2x`，决赛未通过）→ 全网境外挂。

**定位命令（免 SSH）**
```bash
P=$(uci get openclash.config.dashboard_password)   # 设备侧；PC 侧直接用 <你的Clash面板密码>
curl -s -H "Authorization: Bearer $P" http://127.0.0.1:9090/proxies/宝贝云 | grep -o '"now":"[^"]*"'
tail -n 40 /var/log/ocspeed.log                    # 看有没有「决赛全部未通过」
```

**治本：启用 ocspeed 自带的故障转移**（比手工切靠谱，且是官方能力）
```bash
uci set ocspeed.main.failover_enable='1'   # 每分钟 failover_check，坏节点自动换
uci set ocspeed.main.backup_enable='1'     # 每 90 分钟预探测候选池写 backup.json
uci commit ocspeed
/usr/libexec/openclash-helper/speedswitch.sh enable
```
⚠️ **没有 `cron` 子命令**（会打印 usage 并 rc=1）。可用子命令只有：
`run | test | testnode | switchnode | status | nodes | enable | disable | failover | backup | backupnow`
——**只有 `enable` / `disable` 会调用 `cron_apply` 重建 crontab**。
重建后 crontab 应出现 `#ocspeed-failover`、`#ocspeed-backup` 两段每分钟任务。

### 9.3 防火墙 reload 的副作用：AGH 被旁路（已修）

`/etc/init.d/openclash` 第 2177 行：`DNSPORT=$(uci -q get dhcp.@dnsmasq[0].port)`。
阶段 5 把 dnsmasq 挪到 5354 后，**每次 firewall/openclash 重载，53 劫持就会重新指向 5354**，
把 AGH 整条旁路（DNS 照常通、过滤静默失效，极易漏判）。

**修法（用 OpenClash 官方钩子，可持久化）** —— 写入
`/etc/openclash/custom/openclash_custom_firewall_rules.sh`（该脚本在 OpenClash 自身规则**之后**执行）：
```sh
AGH_PORT=53
if netstat -lntup 2>/dev/null | grep -q ":$AGH_PORT .*AdGuardHome"; then
   iptables -t nat -I PREROUTING -p udp --dport 53 -j REDIRECT --to-ports $AGH_PORT -m comment --comment "KP-DNS-Hijack-to-AGH"
   iptables -t nat -I PREROUTING -p tcp --dport 53 -j REDIRECT --to-ports $AGH_PORT -m comment --comment "KP-DNS-Hijack-to-AGH"
fi
```
（用 `-I` 插到最前，才能压过 OpenClash 那条。）
校验：`iptables -t nat -S PREROUTING | grep -n 'dport 53'` —— **KP 规则行号必须小于 OpenClash 的**。
实测：KP 在 2/3 位、OpenClash 在 4/5 位；`nslookup www.google.com 192.168.66.1` → `198.18.0.74`（fake-ip）。

**DoH/DoT 拦截（同一轮加的 fw3 规则）**
```bash
uci set firewall.block_dot=rule
uci set firewall.block_dot.name='Block-DoT-853'
uci set firewall.block_dot.src='lan'; uci set firewall.block_dot.dest='wan'
uci set firewall.block_dot.proto='tcp udp'; uci set firewall.block_dot.dest_port='853'
uci set firewall.block_dot.target='REJECT'; uci set firewall.block_dot.family='ipv4'

uci set firewall.block_doh=rule
uci set firewall.block_doh.name='Block-DoH-DNSPod'
uci set firewall.block_doh.src='lan'; uci set firewall.block_doh.dest='wan'
uci set firewall.block_doh.proto='tcp udp'
uci set firewall.block_doh.target='REJECT'; uci set firewall.block_doh.family='ipv4'
uci add_list firewall.block_doh.dest_ip='119.29.29.99'
uci add_list firewall.block_doh.dest_ip='119.29.29.29'
uci add_list firewall.block_doh.dest_ip='119.28.28.28'
uci add_list firewall.block_doh.dest_ip='182.254.116.116'
uci commit firewall && /etc/init.d/firewall reload
```
备份：`/etc/config/firewall.bak-20260911_2340`、`/etc/config/ocspeed.bak-20260911_2340`、
`/etc/crontabs/root.bak-20260911_2340`。
回滚：`uci delete firewall.block_dot; uci delete firewall.block_doh; uci commit firewall; /etc/init.d/firewall reload`

### 9.4 本轮验证结果（00:05）
- 百度 200/0.2s、google **204/0.75s**、youtube **200/0.9s**（各测 2 次，稳定）
- `宝贝云`=新加坡04中转、`延迟最低`=香港02中转(254ms)、`GLOBAL`=延迟最低
- 手机 `192.168.66.197` 的 `119.29.x` 连接**降到 0 条**（拦截生效）；带域名连接待用户重连 Wi-Fi 后复现

---

## 十、ocspeed 分类测速 UI 重构（2026-09-16）

### 界面改动（分类聚拢 + 延迟热力）

- 原：6 列域名平铺，每格一个延迟条。新：按 **视频/流媒体/AI/其他** 聚拢成
  带 `colspan` 的分组表头；每格用**底色**表达快慢（heat `h0`–`h4`）；超时只留一个 `–`
  （十几个「超时」会压成一片红字）；加「综合」（各站中位数）列 + 每列最快标记 +
  顶部「分类最佳节点」结论条；名次写在 `data-rk` 上、由 CSS `attr()` 渲染。
- **分类映射只在 `speedswitch.sh` 的 `site_meta()` 维护一份**，写进 `sites.json`
  （新增 `cats` / `urls`）下发给页面 —— 两边各存一份必然漂移。域名子串要**收窄**
  （`*max.com*` / `*amazon*` 会把一堆无关域名吃进「流媒体」），宁可落「其他」。
- `sites.json` 先写 `.tmp` 再 `mv`（半截 JSON 会让整块分类表消失）。

### 踩坑（LuCI / Lua 特有，可复用）

| 坑 | 现象 | 对策 |
|---|---|---|
| **LuCI 不认 `<%--` 注释** | 模板 500，日志 `Syntax error in xxx.htm:N: unexpected symbol near '-'` | 解析器把 `<%-` 当成**空白裁剪标记**，剩下的裸 `-` 成了非法字符。注释只能写在 `<% ... %>` 代码块里用 Lua 行注释 `--`，且块内别出现裸 `%>` |
| 模板编译校验用错 API | `template.render()` 报 `attempt to index field 'viewns' (a nil value)` | 那需要 dispatcher 上下文。**只校验语法**用 `require("luci.template.parser").parse_string(src)` |
| 分组表头排序错位 | 点表头排序，列对不上 | `colspan`/`rowspan` 会让「第几个 `data-sort` 表头」≠「第几个 td」。**给每个 th 显式写 `data-col="N"`**，JS 用 `getAttribute('data-col')` 定位 |
| 中位数算错（静默） | `[120,null,860,90,440,1500]` 的中位数算成 120（应 440） | Lua `ipairs`/`#t` **遇 nil 就停**。先 `densify(v,n)` 抽成紧凑数组再排序取中位——**必须用合成数据带一个超时格才测得出来** |
| 热力底纹与延迟条打架 | 分类表叠了底色又叠延迟条 → 糊成一片 | 分类格带 `data-heat="1"`，`decorateDelay` 选择器加 `:not([data-heat])` 跳过 |
| 排序后名次徽标自相矛盾 | 第 1 行挂着 3 号徽标 | 排序完清掉整列 `data-rk`（`removeAttribute`）——徽标只在原始排序下有意义 |

### 部署路径与 MD5 复核

- `speedswitch.sh → /usr/libexec/openclash-helper/`；`ocspeed.lua → /usr/lib/lua/luci/controller/`；
  `ocspeed.htm` / `nodetest.htm → /usr/lib/lua/luci/view/`；
  数据落 `/etc/openclash-helper/sites.json`（`DATA=/etc/openclash-helper`）。
- 收尾复核：设备四件套 `md5sum` 与本地仓库逐一比对（本地按 LF 归一化后再算），
  再带 LuCI cookie 抓一次页面数结构串（`table class="sites"` / `catbest` / `data-rk=` /
  `data-heat="1"` / `data-col="`），确认渲染即部署。
- ⚠️ 运维脚本的**静态负向断言别被自己的注释绊倒**：`!file.includes('*max.com*')` 会因
  代码注释里在解释「为什么不这么写」而误报，应改盯 case 分支形态（`*max.com*)`）。
