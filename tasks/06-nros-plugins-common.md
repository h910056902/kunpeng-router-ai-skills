# 任务 06 · 分类一「常用插件安装」（助手菜单 5）

> `id: nros.plugins-common` · `risk: write`（装插件必然写盘：新增 ipk / LuCI 页面 / 应用商店条目）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> **这是第三方 NROS 插件安装器（maye 助手）的第 1 个功能分类。**
> 总入口、通用四关、下载/校验/备份/基线/真终端手法全部在
> [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) —— **本文件只写这一分类特有的东西**，
> 不重复通用流程；两者冲突时以本文件的分类红线为准。
> 对应关系：**助手菜单 `5)` ＝ 上游脚本主菜单 `1. 常用插件安装`**
> 上游真源：`installer.sh:70080-70128`（`common_plugin_menu`）· `installer.sh:69918-70071`（`run_menu_feature`）

---

## 0. 本分类的置顶红线

> 全部为上游源码逐字读出来的，不是推测。通用红线（无备份 / 别卸 Docker）见 tasks/05 §0。

1. 🔴 **不要选 `2. 哈基米` —— 它就是「安装 OpenClash」。**
   上游把 OpenClash 的显示名改了：`OPENCLASH_DISPLAY_NAME="${OPENCLASH_DISPLAY_NAME:-哈基米}"`（`installer.sh:94`），
   菜单项 `2 哈基米` 映射到 feature `2` → `run_recorded_menu_feature "1 > 2" "$OPENCLASH_DISPLAY_NAME 安装" install_openclash`（`installer.sh:69930-69934`）。
   本机 OpenClash 正在跑（`pidof clash` = **16659**，内核 `/etc/openclash/core/clash_meta` 10.75 MB，
   它是**全网出口**）→ 重装会覆盖内核与 LuCI 页面，断网代价高。

2. 🔴 **不要选 `4. AdGuardHome` / `6. MosDNS` —— 它们会接管 DNS 链。**
   上游 AGH 分支实测会改写本机 DNS 链路（`installer.sh:31414-31416`）：
   `DNS: 已写入 dnsmasq:53 -> AdGuardHome:$adg_dns_port -> $OPENCLASH_DISPLAY_NAME:$oc_dns_port`；
   MosDNS 同理（`fallback_dns 114.114.114.114:53`，`installer.sh:35845-35922`）。
   本机去广告走**我们自己的 Docker AGH（`:53` 全网接管）**（见 [`references/adguard-setup.md`](../references/adguard-setup.md)），
   装 native 版＝两套 DNS 抢 53，会直接打掉解析。

3. ⚠️ **`3. ttyd / Web SSH` 是「装完就对外开一个免登录 shell」。**
   上游 V3.0.0 起明确「访问默认免登录，不再生成或传递 Basic Auth 用户名密码」。
   装在 LAN 上等于局域网上任何人可拿到 root shell。**要装就必须同时改回带认证 / 限制来源**，
   或干脆不要它（本任务不做加固，只做提醒）。

4. ⚠️ **`10. Open-Box` 与 `1. swap` 会豁免环境门禁**（feature 33|34 是唯一豁免项，`installer.sh:69889` 与 `:69922`）。
   Open-Box(34) 在**任何机型**上都能选到，它不做机型校验 —— 出问题没有上游兜底。

---

## 1. 上游菜单真源（逐字抄自 `common_plugin_menu`）

```
  1 / 常用插件
   1. swap 虚拟内存（C2000MAX / C2000Ultra）
   2. 哈基米
   3. ttyd / Web SSH
   4. AdGuardHome
   5. OpenList
   6. MosDNS
   7. DDNS-GO
   8. Docker（C5800 系列 / C8-688）
   9. MT5700 WebUI V3.0.0
  10. Open-Box
   0. 返回功能分类
```

| 菜单号 | 名称 | feature | 实现的函数 | 上游行号 |
|---|---|---|---|---|
| 1 | swap 虚拟内存 | 1 | `manage_swapfile` | 69927 · 函数 31745 |
| 2 | 哈基米（＝OpenClash） | 2 | `install_openclash` | 69932 |
| 3 | ttyd / Web SSH | 3 | `install_ttyd_webssh` | 69937 |
| 4 | AdGuardHome | 4 | `install_adguardhome` | 69942 |
| 5 | OpenList | 5 | `install_openlist` | 69947 |
| 6 | MosDNS | 17 | `install_mosdns` | 70012 |
| 7 | DDNS-GO | 18 | `install_ddnsgo` | 70017 |
| 8 | Docker | 22 | `install_docker_plugin` | 70022 · 函数 71439 |
| 9 | MT5700 WebUI V3.0.0 | 30 | `install_mt5700_webui` | 70046 |
| 10 | Open-Box | 34 | `install_openbox` | 70061 |

> 菜单号 ≠ feature 号（例如菜单 `6` 对应 feature `17`）—— 这是上游的内部编号，**照菜单号按就行**。

---

## 2. 本机（NRadio_C2000Ultra）可用子集

**判据全部来自上游函数本体，不是 README 转述：**

| 菜单号 | 本机 | 依据 |
|---|---|---|
| 1 swap | ✅ **本机专属开放** | `c2000_storage_swap_model_supported`（`installer.sh:1242-1247`）只认 `NRadio_C2000MAX\|NRadio_C2000Ultra`；写 `/overlay/swapfile`，菜单上限 **2048 MiB**（`:31751`） |
| 2 哈基米 | 🔴 可用但别选 | 见红线 1 |
| 3 ttyd / Web SSH | ⚠️ 可用（安全代价见红线 3） | feature 3，正常走环境门禁 |
| 4 AdGuardHome | 🔴 可用但别选 | 见红线 2 |
| 5 OpenList | ✅ 可用 | C2000MAX/Ultra 会自动改用 lite 包并把下载/解压放存储卡（上游 V2.0.50 起） |
| 6 MosDNS | 🔴 可用但别选 | 见红线 2 |
| 7 DDNS-GO | ✅ 可用 | feature 18 |
| 8 Docker | ❌ **选不动** | `install_docker_plugin`（`:71441`）首行就 `docker_require_supported_model` → 仅 C5800 系列 / C8-688；本机会提示不支持 |
| 9 MT5700 WebUI | ❌ **没意义** | 本机无 MT5700 模组（它是 5G 模组的 WebUI），装了也打不开 |
| 10 Open-Box | ✅ 可用（无上游兜底，见红线 4） | feature 34，豁免环境门禁 |

**一句话**：本分类在本机真正「值得且安全」的只有 **1 swap / 5 OpenList / 7 DDNS-GO / 10 Open-Box**；
`3` 要自己加认证；`2 / 4 / 6` 是本任务明令不选的；`8 / 9` 选了也白选。

---

## 3. 前置检查（在 tasks/05 §3 那 11 条之外，本分类额外要测）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| a | 目标是「装」还是「换」 | `opkg list-installed \| grep -E 'openlist\|ddns-go\|mosdns\|adguardhome\|ttyd'` | 先看清已装什么 | 已装的装第二遍＝上游直接覆盖，先备份 |
| b | **DNS 谁在管 53** | `netstat -ltnp \| grep ':53 '` | 记下占用者 | 若已是 Docker AGH → 红线 2 生效，不装 native DNS 类插件 |
| c | swap 现状 | `free -k; ls -l /overlay/swapfile 2>&1` | 记下 `Swap:` 总量 | 已有 swap 时上游会问「是否继续修改扩容」→ 由**你**回答 |
| d | OpenClash 基线 | `pidof clash; /etc/init.d/openclash status` | 记下 pid | 用来做跑后对照 |
| e | 存储余量 | `df -h /overlay /tmp/storage /mnt/storage/data` | 至少几百 MB | OpenList 等下载物较大，余量不足先清 |
| f | `8080` 与 `7681` 端口占用 | `netstat -ltnp \| grep -E ':(8080\|7681) '` | 无输出最好 | 被占 → ttyd(7681) / 上游 LuCI8080 会冲突 |

```sh
# 一次性跑完（设备侧，只读）
echo "--- a installed"; opkg list-installed | grep -E 'openlist|ddns-go|mosdns|adguardhome|ttyd' || echo NONE
echo "--- b dns53";     netstat -ltnp 2>/dev/null | grep ':53 ' || echo FREE
echo "--- c swap";      free -k | sed -n '1,3p'; ls -l /overlay/swapfile 2>&1
echo "--- d clash";     pidof clash; /etc/init.d/openclash status
echo "--- e space";     df -h /overlay /tmp/storage /mnt/storage/data 2>/dev/null
echo "--- f ports";     netstat -ltnp 2>/dev/null | grep -E ':(8080|7681) ' || echo FREE
```

---

## 4. 执行

**通用部分照 tasks/05 §4 走**（自备备份 → `snapshot` 拍补丁基线 → 设备侧下载 → `sha256sum` + `sh -n`）。

分类特有的两件事：

### (a) AI 先做

```sh
# ① 本分类要额外备份的对象（上游 AGH/DDNS-GO/OpenList 都会碰 dnsmasq 与 LuCI 路由）
mkdir -p /tmp/kp-maye-bak
for f in /etc/config/dhcp /etc/config/dnsmasq /etc/config/ddns-go \
         /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua \
         /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm; do
    [ -f "$f" ] && cp "$f" "/tmp/kp-maye-bak/$(basename "$f")"
done
sha256sum /etc/config/dhcp /etc/config/dnsmasq 2>/dev/null | tee /tmp/kp-maye-bak/dns.sha256
ls -l /tmp/kp-maye-bak/

# ② 记 DNS 链基线（红线 2 的哨兵；跑完要对上）
cat /etc/config/dhcp | grep -nE "dnsmasq|server|noresolv" | head -20
```

### (b) 然后停下等你 —— 由你在真终端里按

把命令原样贴给你（**结尾不许跟参数**）：

```sh
sh /tmp/ssh-nradio-plugin-installer.sh
```

进菜单后：`1` 进入「常用插件安装」，再按本分类的安全项（**建议只按 1 / 5 / 7 / 10**）。
**AI 不许替你按任何一个编号**（tasks/05 §0 与协议硬约束 9）。

### (c) 你回来后 AI 再跑

```sh
python scripts/adapt_maye_assistant.py check        # 补丁丢了就 check --fix
# 本分类特有的 DNS 链复核
netstat -ltnp 2>/dev/null | grep ':53 '
```

---

## 5. 验证判据

```sh
# ① 通用三条（同 tasks/05 §5 ③④⑤）
grep -c 'mirrors.aliyun.com/openwrt/releases/21.02.7' /etc/opkg/distfeeds.conf   # 期望 3
grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua   # >=1
grep -c 'aurora_open_app'               /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm   # >=1
pidof clash                                                                     # 有输出（本机 16659）

# ② 「装的那个插件」真的活着（按你实际装的选一条）
pidof openlist  || /etc/init.d/openlist  status   2>/dev/null     # OpenList
/etc/init.d/ddns-go  status                       2>/dev/null     # DDNS-GO
curl -s -o /dev/null -w '%{http_code}\n' -m 5 http://127.0.0.1:5244/             # OpenList 默认 5244

# ③ swap 生效（只在按了 1 时看）
free -k | sed -n '3p'

# ④ DNS 链没被抢（只在没按 4/6 时应该是「没变化」）
sha256sum /etc/config/dhcp /etc/config/dnsmasq
```

| 期望 | 说明 |
|---|---|
| 插件进程 / 服务在跑 | 装机成功的最低要求；拿不到就说没装上，**别说「应该好了」** |
| `pidof clash` 与跑前同值 | 你没在它菜单里重装「哈基米」 |
| 三个 marker 仍 ≥1 | 上游商店相关分支会写 appcenter 两文件 |
| DNS 链与跑前一致 | 你没按 4 / 6 |
| `/etc/config/dockerd` 仍在 | 你没误选卸载 Docker |

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 新装的插件 | 用上游自己的卸载链（部分插件有 `通用卸载链`）；或 `opkg remove <包名>` |
| dnsmasq / dhcp 被改 | 用 §4(a) 的备份覆盖；`/etc/init.d/dnsmasq restart` |
| 我们的商店补丁 | `python scripts/adapt_maye_assistant.py check --fix` |
| OpenClash 内核被覆盖 | 重走 [`tasks/01-openclash-install.md`](01-openclash-install.md)（离线素材 `offline/core/`） |
| swap 想撤 | `swapoff /overlay/swapfile && rm -f /overlay/swapfile`，并清掉 `/etc/rc.local` 里的接入行 |
| ttyd 想撤 | `opkg remove ttyd; /etc/init.d/ttyd disable` —— **先确认已停，别留免登录 shell** |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 按了 `8. Docker` 提示机型不支持 | 本机不在 C5800 系列 / C8-688 白名单 | 正常，别硬来；Docker 走我们的 [`tasks/03-docker-1panel-install.md`](03-docker-1panel-install.md) |
| 按了 `9. MT5700` 装完打不开 | 本机无 MT5700 模组 | 别装；要撤就 `opkg remove` + 清 LuCI 路由 |
| 装完网页打不开 / DNS 全挂 | 按了 4 或 6，native DNS 接管了 53 | 用 §4(a) 备份还原 `/etc/config/dhcp`，重启 dnsmasq |
| `3. ttyd` 装完谁都能连 | 上游默认免登录 | 立刻 `opkg remove ttyd` 或加认证 |
| OpenClash 起不来 | 按了 `2. 哈基米` | 用 `offline/core/mihomo-linux-arm64.gz` 重装内核 |
| 商店页面按钮消失 | 插件注册链改写了 appcenter 两文件 | `check --fix` + `rm -rf /tmp/luci-indexcache*` |
| swap 扩容后没生效 | 只写了文件没接入开机 | 上游会写 `/etc/rc.local` 接入；手动核对 |
| 按 `0` 没返回 | 上游部分子菜单按 `0` 是返回上一层而非退出 | 连按到主菜单再按 `0` |

---

## 8. 与其他文件的关系

- 通用四关 / 下载校验 / 真终端手法 / stdin 三种行为 → [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md)
- 上游整体画像与历史 → [`references/maye-assistant.md`](../references/maye-assistant.md)
- 本机去广告正解 → [`references/adguard-setup.md`](../references/adguard-setup.md)
- 菜单协议（AI 怎么被调用）→ [`AGENTS.md`](../AGENTS.md) §8
