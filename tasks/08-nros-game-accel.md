# 任务 08 · 分类三「游戏加速器」（助手菜单 7）

> `id: nros.game-accel` · `risk: destructive`（**明文 HTTP 下载 root 脚本直接执行 ＝ 中间人可替换成任意代码，且会改路由/注册应用商店条目**）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> **这是第三方 NROS 插件安装器（maye 助手）的第 3 个功能分类。**
> 总入口、通用四关、下载/校验/备份/基线/真终端手法全部在
> [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) —— 本文件只写这一分类特有的东西。
> 对应关系：**助手菜单 `7)` ＝ 上游脚本主菜单 `3. 游戏加速器`**
> 上游真源：`installer.sh:72172-72196`（`game_accelerator_menu`）· `installer.sh:72100-72171`（两个子菜单）

---

## 0. 本分类的置顶红线

> 🔴 **这是全脚本唯一「下明文 HTTP 的裸脚本、检查两句就 root 执行」的分类。默认不做。**

1. 🔴 **下载链路是明文 HTTP，其中一条是裸 IP。**
   ```sh
   QIYOU_INSTALLER_URL="${QIYOU_INSTALLER_URL:-http://sd.qiyou.cn}"                                            # installer.sh:97
   LEIGOD_INSTALLER_URL="${LEIGOD_INSTALLER_URL:-http://119.3.40.126/router_plugin_new/plugin_install.sh}"    # installer.sh:106
   ```
   雷神那条连域名都没有，直接是 `http://119.3.40.126/...`。

2. 🔴 **执行前的「检查」形同虚设 —— 只有两句，且不含任何校验和/签名。**
   ```sh
   download_file "$QIYOU_INSTALLER_URL" "/tmp/qiyou-install.sh" || die "下载奇游入口脚本失败"
   grep -q 'qyplug.sh' /tmp/qiyou-install.sh 2>/dev/null || die "奇游入口脚本内容异常，已停止执行"   # installer.sh:71783
   sh -n /tmp/qiyou-install.sh >/dev/null 2>&1 || die "奇游入口脚本语法异常，已停止执行"             # installer.sh:71784
   ...
   sh /tmp/qiyou-install.sh || die "奇游官方安装脚本执行失败"                                          # installer.sh:71789
   ```
   `grep` 只找一个字符串、`sh -n` 只查语法 —— **任何内容都能通过**。中间人替换脚本体 = 直接 root 代码执行。
   （上游 V2.9.5 起**主动撤除了**奇游/雷神的固定 MD5/SHA256 门禁，现在确实没有哈希校验。）

3. ⚠️ **它会把条目写进应用商店（＝碰我们补丁的载体）。**
   装完会走 `game_accel_set_appcenter_entry …` + `refresh_luci_appcenter`（`installer.sh:71773-71774`），
   后者会清 `/tmp/luci-indexcache`、重启 `infocd` 与 `appcenter`、`reload uhttpd`，
   并写奇游/雷神自己的 LuCI controller 与 view（`qiyou_write_controller` / `qiyou_write_view`，`:71770-71771`）。
   → 跑完**必须** `python scripts/adapt_maye_assistant.py check`。

4. ⚠️ **加速器本体也会动网络。** 装完还会 `opkg install curl kmod-tun ip-full`（`:71787`）并起自己的隧道/规则，
   与 OpenClash 全网出口（TUN + fake-ip）叠加，属「两个东西抢流量」。

---

## 1. 上游菜单真源（逐字抄自源码）

主菜单 `3. 游戏加速器`（`game_accelerator_menu`）只有两项：

```
  3 / 游戏加速器
   1. 奇游联机宝
   2. 雷神加速器
   0. 返回功能分类
```

点进去各自还有二级菜单：

```
  3 / 游戏加速器 / 奇游                    |    3 / 游戏加速器 / 雷神
   1. 安装奇游并接入应用商店                |     1. 安装雷神并接入应用商店
   2. 查看奇游状态                          |     2. 接入已安装的雷神
   3. 卸载奇游联机宝                        |     3. 查看雷神状态
   4. 刷新设备识别与插件页面                |     4. 卸载雷神加速器
   0. 返回游戏加速器                        |     0. 返回游戏加速器
```

| 菜单号 | 名称 | 实现的函数 | 上游行号 |
|---|---|---|---|
| 3-1 | 奇游联机宝 | `qiyou_integrated_menu` | 72100 |
| 3-1-1 | 安装奇游并接入应用商店 | `qiyou_install_integrated` | 71777（子菜单 72113） |
| 3-2 | 雷神加速器 | `leigod_integrated_menu` | 72136 |
| 3-2-1 | 安装雷神并接入应用商店 | `leigod_install_integrated` | 子菜单 72149 |
| 3-1-2 / 3-2-3 | 查看状态 | `qiyou_show_status` / 雷神同类 | 71797 |
| 3-1-3 / 3-2-4 | 卸载 | 上游卸载链 | —— |
| 3-x-4 | 刷新设备识别与插件页面 | `refresh_luci_appcenter` 类 | 17415 |

> 本分类**没有 feature 号**（不走 `run_menu_feature`），是直接函数调用。

---

## 2. 本机（NRadio_C2000Ultra）可用子集

| 菜单项 | 本机 | 说明 |
|---|---|---|
| 奇游：装 / 看状态 / 卸载 / 刷新 | ⚠️ 技术上可用 | 前置 `game_accel_require_appcenter`（`installer.sh:70218`）只要 OEM 应用商店 → 本机有，能过 |
| 雷神：装 / 接入已装 / 看状态 / 卸载 | ⚠️ 技术上可用 | 同上 |

**「技术上可用」不等于「建议做」**：本分类的两条安装路径都满足红线 1+2。
本任务的默认立场是 **不做**；如果你确实要用加速器，走下面 §4 的「人工替代路径」。

---

## 3. 前置检查（在 tasks/05 §3 那 11 条之外，本分类额外要测）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| a | 是否已经装过 | `ls -l /etc/qy/qy_acc.sh 2>&1; opkg list-installed \| grep -iE 'qiyou\|leigod\|qy_\|leishen'` | 记下来 | 已装就别再装；加速器叠加会更乱 |
| b | 明文 HTTP 能不能出网 | `wget -q -T 8 -O /dev/null http://sd.qiyou.cn && echo REACHABLE \|\| echo UNREACHABLE` | 能通说明「无 TLS 保护的地下链路是活的」 | 通不通都要提醒：**这条链路上任何一跳都能改脚本** |
| c | 加速器相关进程 | `pidof qy_acc; pidof leigod; ls /etc/qy 2>&1` | 记下 | —— |
| d | 网络基线 | 同 [`tasks/07-nros-network-route.md`](07-nros-network-route.md) §3（`pidof clash` / `ip -4 rule` / 默认路由 / 真 HTTP） | 全部记录 | 加速器也会动流量，必须有基线 |
| e | 商店补丁基线 | `python scripts/adapt_maye_assistant.py snapshot` | 基线写入 | 先 snapshot 再跑（红线 3） |
| f | opkg 源可用 | `opkg update` 能跑通 | rc=0 | 上游会 `ensure_opkg_update` 并装 `curl kmod-tun ip-full`（`:71786-71787`），源不通会直接 die |

```sh
# 一次性跑完（设备侧，只读）
echo "--- a installed"; ls -l /etc/qy/qy_acc.sh 2>&1; opkg list-installed | grep -iE 'qiyou|leigod' || echo NONE
echo "--- b http";      wget -q -T 8 -O /dev/null http://sd.qiyou.cn && echo REACHABLE || echo UNREACHABLE
echo "--- c procs";     pidof qy_acc; pidof leigod
echo "--- d net";       pidof clash; ip -4 route show default; curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
```

---

## 4. 执行

> ⚠️ **本分类在「按它给的路径跑」与「人工替代路径」之间，优先后者。**

### (a) 推荐路径：人工替代（AI 全程只帮你取证，不让你按下那个安装项）

思路：既然它的检查本来就只有两句，那就不如**我们自己把检查做足**再执行。

```sh
# ① AI 先做：把脚本下到设备并「原样」抓给你审（先不执行）
wget -O /tmp/qiyou-install.sh http://sd.qiyou.cn          # 雷神换 http://119.3.40.126/router_plugin_new/plugin_install.sh
sha256sum /tmp/qiyou-install.sh | tee /tmp/kp-maye-bak/qiyou.sha256
wc -c /tmp/qiyou-install.sh
head -60 /tmp/qiyou-install.sh        # 给你看头部；要看全文就 cat，别用管道喂给 sh

# ② 备份（加速器会写 /etc/qy、LuCI 路由、应用商店条目）
mkdir -p /tmp/kp-maye-bak/qy
for f in /etc/config/dhcp /etc/config/network \
         /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua \
         /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm; do
    [ -f "$f" ] && cp "$f" /tmp/kp-maye-bak/qy/
done

# ③ 你确认脚本内容没问题之后，才由你在真终端执行（**AI 不代跑**）
sh /tmp/qiyou-install.sh
```

> 这里的关键差异：`sha256` 由我们记录、脚本内容由**你**过目，而不是「只 grep 一个字符串就 root 跑」。

### (b) 或者走上游菜单（你要走这条的话，AI 的职责只剩「提醒 + 事后校验」）

```sh
sh /tmp/ssh-nradio-plugin-installer.sh      # 结尾不许跟参数
```

进菜单 `3` → `1`（奇游）或 `2`（雷神）→ 再按安装项。
**AI 不许替你按任何编号**；按之前 AI 必须把红线 1+2 完整讲一遍并提醒先备份。

### (c) 完之后 AI 必须跑

```sh
python scripts/adapt_maye_assistant.py check      # 红线 3：商店条目被写过
pidof clash
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
ls -l /etc/qy/qy_acc.sh 2>&1
```

---

## 5. 验证判据

| 判据 | 期望 | 说明 |
|---|---|---|
| 你的 `sha256` 记录 | 与执行前那份一致 | 若你执行的是上游下载的那份，则用 `/tmp/kp-maye-bak/qiyou.sha256` 对 |
| 安装痕迹 | `/etc/qy/qy_acc.sh` 存在（奇游）；雷神对应文件存在 | 上游装完自己会检查这一条（`:71791`） |
| 服务状态 | 上游「查看状态」项能给结果 / `pidof` 有输出 | 拿不到就说没装上 |
| 应用商店条目 | 商店里能看到奇游/雷神卡片 | 看不到说明接入失败（上游 `game_accel_set_appcenter_entry`） |
| 三个补丁 marker | 仍 ≥1 | 被写了就 `check --fix` |
| `pidof clash` | 与跑前同值 | 网络没被抢 |
| 真 HTTP | `200` | **不要用 ping/TCP 判活** |

```sh
# 一次性判据（设备侧）
echo "--- files"; ls -l /etc/qy/qy_acc.sh 2>&1
echo "--- clash"; pidof clash
echo "--- http";  curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com
echo "--- mark";  grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
```

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 卸载加速器 | 走上游卸载链（雷神有「卸载残留清理」历史更新）；或手动停服务 + 删 `/etc/qy` 等目录 |
| `/etc/qy` 与 LuCI 页面 | 用 §4(a)② 的备份覆盖相关文件；`rm -rf /etc/qy /usr/lib/lua/luci/controller/nradio_adv/qiyou.lua` 等它写入的件 |
| 应用商店条目残留 | 上游有「刷新设备识别与插件页面」；或 `check --fix` 后 `rm -rf /tmp/luci-indexcache*` |
| 我们的商店补丁 | `python scripts/adapt_maye_assistant.py check --fix` |
| 网络被改 | 见 [`tasks/07-nros-network-route.md`](07-nros-network-route.md) §6 |
| 装进去的 `curl/kmod-tun/ip-full` | 一般留着无害；要撤就 `opkg remove`（`kmod-tun` 可能被 OpenClash 依赖，**先查 `opkg depends`**） |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 下载成功但执行后系统异常 | 明文 HTTP 被中间人替换 | 立刻断网 → 比对 `/tmp/qiyou-install.sh` 的 sha256 → 用备份回滚 |
| `grep`/`sh -n` 都过了，脚本却是恶意的 | 那两句检查**设计上就拦不住** | 这就是红线 2；只能靠「人工审源码 + 记哈希」 |
| 商店页面按钮消失 / 卡片错位 | 加速器写入件 + `refresh_luci_appcenter` 冲掉我们补丁 | `check --fix` + 清 `/tmp/luci-indexcache*` |
| `安装 curl/kmod-tun/ip-full 失败` | opkg 源不通 | 先 `opkg update`；源被改就用备份还原 |
| 加速器装上后 OpenClash 分流乱了 | 两套隧道抢流量 | 二选一，别叠加 |
| 卸载后商店里还有卡片 | 应用商店条目没清 | 按「刷新设备识别与插件页面」，再清 LuCI 缓存 |

---

## 8. 与其他文件的关系

- 通用四关 / 下载校验 / 真终端手法 / stdin 三种行为 → [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md)
- 网络平面变更与回滚 → [`tasks/07-nros-network-route.md`](07-nros-network-route.md)
- 应用商店补丁与还原 → [`tasks/09-nros-appcenter-polish.md`](09-nros-appcenter-polish.md) · [`references/store-patching.md`](../references/store-patching.md)
- 菜单协议（AI 怎么被调用）→ [`AGENTS.md`](../AGENTS.md) §8
