# 任务 02 · 装 ocspeed（OpenClash 自动测速插件）

> `id: ocspeed.install` · `risk: write`
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，OpenWrt 21.02）
> 目标：五件套落盘、LuCI 多出「服务 → OpenClash → 自动测速」页面、cron 三条任务就位。
> 参考档案：[`references/c2000u-openclash.md`](../references/c2000u-openclash.md) §四/§九/§十、
> [`references/one-command-restore.md`](../references/one-command-restore.md) §十一/§十二。

---

## 0. 它是什么（先搞清楚再装）

**ocspeed 是 OpenClash 的自动测速 / 自动切换节点的自建 LuCI 插件，不在任何 opkg 源里。**

- 每 N 分钟把目标策略组里的节点全量测一遍延迟，`PUT` 切换该策略组到最快的那个；
- 另外挂两条**可选** cron：故障自动切换（failover）、备用节点预选（backup）；
- 装好后 LuCI 里多一页：**服务 → OpenClash → 自动测速**。

**为什么单独拆一个任务**：它跟着 overlay 走 —— 重建 TF 卡 / 换卡 / 扩容之后
`/usr/libexec/openclash-helper/`、`controller/ocspeed.lua`、`view/ocspeed.htm`、`/etc/config/ocspeed`
**会一起消失**，而且 `opkg install` 查无此包。所以恢复流程里必须显式装一次。
（2026-09-16 实测：16G 扩容重建后整目录没了。）

**与 OpenClash 的依赖关系：强依赖。**
它直接调 mihomo 控制 API（`GET /proxies`、`/proxies/<名>/delay`、`PUT /proxies/<组>`）做测速与切组，
端口与密钥**从 `uci openclash.config.{cn_port,dashboard_password}` 动态读取**（所以改面板密码不会静默失效）。
LuCI 控制器挂在 `admin/services/openclash/ocspeed`。

---

## 1. 前置检查

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| 1 | OpenClash 已装 | `test -x /etc/init.d/openclash && echo ok` | `ok` | 先做 [`tasks/01-openclash-install.md`](01-openclash-install.md)；`kp-ocspeed.sh` 自己也会检测并优雅跳过 |
| 2 | OpenClash 在跑 | `pidof clash` | 有输出 | 先起 OpenClash，否则装完没有可切目标 |
| 3 | 有可用策略组名 | `uci -q get ocspeed.main.group`（未装时为空） | 知道自己的兜底组名 | 装完必须在页面里点选；组名错误 = 静默切到不存在的组 |
| 4 | 数据盘可用 | `df -k /mnt/storage/data \| tail -1` | 有剩余 | 备份目录要落在这里，断了网还能原地恢复 |
| 5 | 可用内存 | `free -k \| awk '/MemAvailable/{print $2}'` | > 40000 | ocspeed 自己很轻，但一轮全量测速要并行 curl 几十个节点 |

```sh
# 一次性跑完（设备侧，只读）
echo "--- 1 openclash"; test -x /etc/init.d/openclash && echo ok || echo MISSING
echo "--- 2 running";   pidof clash || echo "not running"
echo "--- 3 group";     uci -q get openclash.config.config_path || echo "(no config_path)"
echo "--- 4 data";      df -k /mnt/storage/data | tail -1
echo "--- 5 mem";       free -k | awk '/MemAvailable/{print $2}'
```

---

## 2. 五件套落盘路径（**唯一权威表**）

| 文件 | 去处 | 权限 |
|---|---|---|
| `speedswitch.sh` | `/usr/libexec/openclash-helper/speedswitch.sh` | 755 |
| `ocspeed.lua` | `/usr/lib/lua/luci/controller/ocspeed.lua` | 644 |
| `ocspeed.htm` | `/usr/lib/lua/luci/view/ocspeed.htm` | 644 |
| `nodetest.htm` | `/usr/lib/lua/luci/view/nodetest.htm` | 644 |
| `config.ocspeed` | `/etc/config/ocspeed` | 644 |

**数据与状态目录（不要搞混，写混了会得到"全 FAIL"的假象）**

| 路径 | 放什么 |
|---|---|
| `$DATA=/etc/openclash-helper` | **持久数据**：`nodes.json` / `status.json` / `sites.json` / `backup.json` / `history.log` / `last_run` |
| `$DIR=/tmp/ocspeed` | **临时**：工作文件、`lock/`、`progress.json`（tmpfs，重启即清） |
| `/var/log/ocspeed.log` | 运行日志（`run` 的 stdout 是空的，**要看结果只能 tail 这个文件**） |

另有一份**数据盘备份**（断网时的原地恢复源）：`/mnt/storage/data/ocspeed-backup/`。

---

## 3. 素材位置（本仓库 `offline/ocspeed/`）

| 文件 | 大小 | md5 |
|---|---|---|
| `speedswitch.sh` | 57 KB (v3.4) | `9544e0b38b29bb146690535466913f00` |
| `ocspeed.lua` | 31 KB | `ea0fc06440268c99a91f705887889228` |
| `ocspeed.htm` | 109 KB (v3.5 UI) | `0f512a333d139a4b58945bf7a2c67397` |
| `nodetest.htm` | 4.5 KB (v3.5 UI) | `e857abd6577c4094f1bec743745193ec` |
| `config.ocspeed` | 1 KB | `22ac5f0fe2c6ea32bdd7a2fabc86f384` |
| `kp-ocspeed.sh` | 10 KB | `4055f2aa1702a7326681e5fcbcaedce5` |

> 🔴 **不要用工作区 `http_stage/` 的旧 v3.3 `ocspeed.lua`** —— 它第 153 行硬编码了
> `Authorization: Bearer <旧面板密码>`，改过面板密码的机器上页面会**静默显示陈旧数据**
> （有 `if cur == "" then cur = st.now end` 兜底，肉眼看不出来）。
> 本目录用的是 `nros-panel` 的版本，已改成从 UCI 动态取。

---

## 4. 两条安装路径

### 路径 A —— 一键脚本（有网，推荐）

```sh
# 在设备上
wget -qO /tmp/kp.sh https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh
SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh                       # 只装 ocspeed

# 可选参数（都是环境变量透传）
OCS_GROUP=宝贝云 OCS_INTERVAL=30 OCS_RUN=1 SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh
```

`kp-ocspeed.sh` 会：投递五件套 → 落盘 → 清 LuCI 缓存 → 备份到数据盘 →
`enable` 重建 cron → （可选）立刻跑一次 → 注册进鲲鹏商店。
**幂等**：重复执行只覆盖文件，`/etc/config/ocspeed` 里用户改过的值会保留。

### 路径 B —— 离线逐文件投递（无网 / 想精确控制）

```bash
# PC 侧，仓库根目录
export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<设备密码>
python scripts/revtunnel_put.py offline/ocspeed/speedswitch.sh  /tmp/oc_ocs/
python scripts/revtunnel_put.py offline/ocspeed/ocspeed.lua     /tmp/oc_ocs/
python scripts/revtunnel_put.py offline/ocspeed/ocspeed.htm     /tmp/oc_ocs/
python scripts/revtunnel_put.py offline/ocspeed/nodetest.htm    /tmp/oc_ocs/
python scripts/revtunnel_put.py offline/ocspeed/config.ocspeed  /tmp/oc_ocs/
```

```sh
# 设备侧落盘
mkdir -p /usr/libexec/openclash-helper /etc/openclash-helper /tmp/ocspeed /var/log
mkdir -p /usr/lib/lua/luci/controller /usr/lib/lua/luci/view

cp -f /tmp/oc_ocs/speedswitch.sh /usr/libexec/openclash-helper/speedswitch.sh
chmod 0755                        /usr/libexec/openclash-helper/speedswitch.sh
cp -f /tmp/oc_ocs/ocspeed.lua   /usr/lib/lua/luci/controller/ocspeed.lua
cp -f /tmp/oc_ocs/ocspeed.htm   /usr/lib/lua/luci/view/ocspeed.htm
cp -f /tmp/oc_ocs/nodetest.htm  /usr/lib/lua/luci/view/nodetest.htm
[ -f /etc/config/ocspeed ] || cp -f /tmp/oc_ocs/config.ocspeed /etc/config/ocspeed

# 指定目标策略组（只有显式设过才覆盖，否则沿用已有值）
uci -q set ocspeed.main.group='<你的兜底组名>'
uci -q set ocspeed.main.enabled='1'
uci -q commit ocspeed

# 清 LuCI 缓存（不做这一步页面不会出现）
rm -f  /tmp/luci-indexcache /tmp/luci-indexcache.*
rm -rf /tmp/luci-modulecache
/etc/init.d/uhttpd restart

# 数据盘留一份备份（断网时能原地 cp 回来）
mkdir -p /mnt/storage/data/ocspeed-backup
cp -f /usr/libexec/openclash-helper/speedswitch.sh /mnt/storage/data/ocspeed-backup/
cp -f /usr/lib/lua/luci/controller/ocspeed.lua     /mnt/storage/data/ocspeed-backup/
cp -f /usr/lib/lua/luci/view/ocspeed.htm           /mnt/storage/data/ocspeed-backup/
cp -f /usr/lib/lua/luci/view/nodetest.htm          /mnt/storage/data/ocspeed-backup/
cp -f /etc/config/ocspeed                          /mnt/storage/data/ocspeed-backup/config.ocspeed
```

> ⚠️ **上传必须按行分块（每块 ≤ 2.5 KB）。**
> 单条 `exec_command` 超过约 8 KB 会被 dropbear reset —— 36 KB / 109 KB 的脚本整块一次传
> **会把 SSH 通道撑爆**，表现为「脚本直接退 1、没有任何报错」。
> 用 `scripts/rtr_lib.py` 的 `put_text_verified`（2026-09-19 已修：捕获连接重置后自动降级分块），
> 或 PC 侧 `http.server` + 设备 `curl` 反向拉。

### 路径 C —— ipk 一键安装（2026-09-23 新增，iStoreOS 24.10 实测通过）

`offline/ocspeed/luci-app-ocspeed_3.5-1_all.ipk`（架构无关，21.02/24.10 通用；由
`scripts/build_ocspeed_ipk.py` 从本目录五件套打包，md5 见 `offline/checksums.md5`）。

> **v3.5-1（2026-09-24）**：`ocspeed.htm` / `nodetest.htm` 整体换装 **OpenClash 原生配色**
> （浅色默认：`--bg-white #fff / --primary #3b82f6 / --success #059669 …`，
> 暗色挂 `html[data-darkmode="true"]` 开关、与 OpenClash oc.css 同名同值令牌），
> 删除原深色 Apple/Linear 风覆写层；布局与 JS 逻辑不动。
> 升级安装后浏览器 **Ctrl+F5 强刷**一次（旧 CSS 可能被缓存）。

```sh
opkg install /tmp/luci-app-ocspeed_3.5-1_all.ipk     # postinst 自动清 LuCI 缓存 + 重启 rpcd/uhttpd
```

- `/etc/config/ocspeed` 已声明为 **conffile**，升级重装不覆盖用户改动；
- **装完不会自动建 cron**，仍需手动 `speedswitch.sh enable`；
- 卸载：`opkg remove luci-app-ocspeed`（postrm 清缓存；`/etc/openclash-helper/` 数据保留）。
- 在 iStoreOS 旁路由（192.168.100.1）实测：安装 RC=0，`status` 出 JSON，
  `test` 全量测速 72 节点（真节点 65 / 可用 34 / 失效 31 / 假节点 7），`switch=0` 不切组。

**打包格式四大坑（重打 ipk 必读）**：
1. **现代 OpenWrt 的 ipk 是 tar.gz 不是 ar 归档**：外层 tar.gz 内含 `./debian-binary`(内容"2.0")
   + `./control.tar.gz` + `./data.tar.gz`；手工拼 ar 归档会被 opkg 报 `Malformed package file`。
2. **data.tar.gz 里父目录必须显式写成 DIRTYPE 条目**（名字带 `/` 且 `type=DIRTYPE`），
   否则 `/usr/libexec/openclash-helper` 这类不存在的父目录会被建成**空文件**，speedswitch.sh 落盘报 `Not a directory`。
3. **依赖名是 `luci-app-openclash` 不是 `openclash`**（设备上 opkg 登记的包名），写错会报
   `cannot find dependency openclash`。
4. **必须带 `/usr/share/rpcd/acl.d/luci-app-<pkg>.json`，且 postinst 要重启 rpcd**
   （2026-09-24 实测：缺 ACL 文件时 dispatcher 树里有节点、`satisfied:true`，但客户端渲染的 LuCI
   会**隐藏会话 access-group 里没有的菜单项** → "装了但服务页面里看不到"。
   排障手段：登录 ubus 看 `session.login` 返回的 `acls.access-group` 有没有包名）。
   装完/升级后浏览器要**退出重登**一次，老会话的 ACL 是登录时固化的。

### 4.3 建 cron（**关键：没有 `cron` 子命令**）

```sh
/usr/libexec/openclash-helper/speedswitch.sh enable
```

可用子命令只有：
`run | test | testnode | switchnode | status | nodes | enable | disable | failover | backup | backupnow`

**只有 `enable` / `disable` 会调用 `cron_apply` 重建 crontab。** 敲 `cron` 子命令只会打印 usage 并 `rc=1`。
**也别手工改 `/etc/crontabs/root`** —— 下次 `enable` 会覆盖它。

重建后 crontab 应出现三段：

```
#ocspeed-auto
#ocspeed-failover      （failover_enable=1 时才有）
#ocspeed-backup        （backup_enable=1 时才有）
```

---

## 5. 验证判据

```sh
# ① 文件在位且可执行
ls -l /usr/libexec/openclash-helper/speedswitch.sh
ls -l /usr/lib/lua/luci/controller/ocspeed.lua /usr/lib/lua/luci/view/ocspeed.htm /usr/lib/lua/luci/view/nodetest.htm
# ② 脚本可用
/usr/libexec/openclash-helper/speedswitch.sh status
# ③ cron 已建
crontab -l | grep -c '#ocspeed-auto'
# ④ 页面存在（未登录 403 = 页面存在，404 才是真没有）
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1/cgi-bin/luci/admin/services/openclash/ocspeed
# ⑤ 跑一轮（可选，72 节点实测约 92 秒）
/usr/libexec/openclash-helper/speedswitch.sh run ; tail -n 20 /var/log/ocspeed.log
```

| 期望 | 说明 |
|---|---|
| ① 文件 755 / 644 齐全 | 缺 `nodetest.htm` 会让节点测试页 500 |
| ② `status` 有输出 | 无输出说明脚本本身没跑起来（先 `sh -n` 校验语法） |
| ③ ≥ 1 | 0 说明没走 `enable`，或手工改过 crontab 被覆盖了 |
| ④ **403** | 403 = 页面存在（LuCI 保护未登录）；404 = 控制器没注册上，回去清缓存 |
| ⑤ 日志出现「全量测速 N 节点 → 已切换 <组名> → 节点名 (初赛 xx ms)」 | 日志**只有这个文件有**，`run` 的 stdout 是空的，RC=0 且无输出是正常的 |

---

## 6. 回滚

```sh
/usr/libexec/openclash-helper/speedswitch.sh disable      # 清 cron
rm -f /usr/libexec/openclash-helper/speedswitch.sh
rm -f /usr/lib/lua/luci/controller/ocspeed.lua
rm -f /usr/lib/lua/luci/view/ocspeed.htm /usr/lib/lua/luci/view/nodetest.htm
rm -f /etc/config/ocspeed
rm -f  /tmp/luci-indexcache /tmp/luci-indexcache.*; rm -rf /tmp/luci-modulecache
/etc/init.d/uhttpd restart
```
`/etc/openclash-helper/`（历史数据）与 `/mnt/storage/data/ocspeed-backup/`（备份）**保留** ——
它们是下一次恢复的来源。

---

## 7. 已知坑速查（本任务相关）

| 症状 | 原因 | 修法 |
|---|---|---|
| **整个 ocspeed 消失、`opkg install` 查无此包** | 它是自建插件，全跟着 overlay 走；重建卡 / 换卡 / 扩容后一起没了 | 用本任务重装；数据盘备份目录可原地 `cp` 回来 |
| 上传脚本「退 1 但无任何报错」 | 36 KB 整块 heredoc 撑爆 SSH 通道 | 按行分块 ≤2.5 KB；或用 `rtr_lib.put_text_verified` |
| 重跑后文件字节数没变、装的还是旧版 | `kp-ocspeed.sh` 曾在 tmpfs 缓存 `fetch_oc()` | 旧版已修（改成下 `.new` 成功才 `mv`）；排查先看 `/tmp/kp-nros/ocspeed/` 缓存，再看 CDN 边缘延迟 |
| 页面显示的数据是陈旧的 | `ocspeed.lua` 曾硬编码 `Bearer <固定密钥>`，改过面板密码后那条查询 401，被 `cur == st.now` 兜底掩盖 | 用本仓库的版本（从 UCI 动态取） |
| 手工加了 cron，过一阵又没了 | `enable` 会重建 crontab 覆盖手工改动 | 只改 UCI（`uci set ocspeed.main.*`）再 `enable` |
| 「只有境外网站打不开」每隔一阵就来一次 | 全量测速出现「决赛全部未通过」时按初赛排名兜底 → 选到一个其实不通的节点 | 治本 = 开故障转移：`uci set ocspeed.main.failover_enable=1; uci set ocspeed.main.backup_enable=1; uci commit ocspeed; speedswitch.sh enable` |
| 页面偶发空白、刷新又好了 | `nodes.json` / `status.json` 是几十次 `printf` 追加写出来的，读取时撞上半截 JSON | 已修为 `tmp + mv` 原子写；若复现先查是否装了旧版 |
| `jsonfilter` 报错说 JSON 非法 | 可能是探针路径写错了 —— `nodes.json` 在 `$DATA` 而不是 `$DIR` | 路径从脚本变量定义里抄：`grep -n '^DIR=\|^DATA=' speedswitch.sh` |
| 机场 60 个节点但只认 44 个 | 节点 `type` 大小写与白名单不符（`Tuic` vs `TUIC`），整类静默不参与测速 | 已改为小写归一后比对；日志里没有任何线索，只能靠这个特征识别 |

---

## 8. 完成后

1. `md5sum` 比对设备上四件套与 `offline/ocspeed/`（本地按 LF 归一化后再算）
2. 复核 `free -k`；跑过一轮测速后内存会明显回落
3. 向用户报告：装了什么、cron 在哪几条、怎么回滚

**延伸**：ocspeed 的故障转移与备用预选 → `tasks/index.json` 的 `clash.failover-enable` 条目。
