# 任务 11 · 设备状态与环境自检（助手菜单 11）

> `id: device.selftest` · `risk: read`（**纯只读**：设备侧采集器一行写盘都没有）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> 目标：**一条命令跑完全机状态** —— 系统资源与环境 · 容器梳理 · 网络与信号（含 5G/CPE）·
> 服务与补丁状态 · 装载余量与可装性对照，输出人话结论与四态标记。
> PC 侧唯一入口：[`scripts/device-selftest.py`](../scripts/device-selftest.py)
> 设备侧采集器：[`scripts/payload/kp-selftest.sh`](../scripts/payload/kp-selftest.sh)
> ⚠️ **这不是 maye 助手的分类**，是本仓自研项 —— 与菜单 `9)` 的边界见 §1。

---

## 0. 置顶红线（三条，违反即失去 `risk: read` 的资格）

1. 🔴 **只读**。设备侧脚本全文**不得出现**：`>` / `>>` / `tee` / `uci set` / `opkg install|remove|update` /
   `docker rm|stop|kill|prune|rmi` / `/etc/init.d/* start|stop|restart|enable` / `fw3 reload` /
   `mkdir` / `touch` / `rm` / `mv` / `cp`。
   **连 `/tmp` 都不落中间文件。**
   （唯一例外：PC 侧把采集器推到 `/tmp/kps/`，那是 tmpfs，重启即失，且是「推送」而不是「设备自己写」。）
2. 🔴 **不修复**。发现问题只输出**建议**，由使用者决定是否执行。该真修的走
   [`tasks/01-openclash-install.md`](01-openclash-install.md)、[`tasks/02-ocspeed-install.md`](02-ocspeed-install.md)、
   [`tasks/03-docker-1panel-install.md`](03-docker-1panel-install.md)、
   [`tasks/06`](06-nros-plugins-common.md) ~ [`tasks/10`](10-nros-maintenance.md)。
   **不提供 `--fix`，不自动改任何配置。**
3. 🔴 **不打扰**。不发任何 AT 指令（默认只数 `/dev/ttyUSB*` 的个数）、不 `fw3 reload`、
   不重启任何服务、不碰防火墙；连通性判定**只用** `curl -m 8`（禁 ping / TCP 探测，原因见 §7 坑 6）。

> 这三条是「可以随时跑、跑完不用管」的前提。任何一条被破坏，这个功能就从「体检」变成「操作」。

---

## 1. 它是什么 / 与菜单 9) 的边界（**必读，最易混淆**）

菜单里 `9)` 与 `11)` 都带「检测 / 维护」字样，但**归属、交互、写盘、跑法四项全不同**：

| | `9)` `nros.maintenance` | `11)` `device.selftest` |
|---|---|---|
| 归属 | 第三方 maye 助手的**分类五** | **本仓自研**（不是分类） |
| 权威真源 | `installer.sh` 上游脚本 | 本仓 `scripts/device-selftest.py` |
| 交互 | **交互式真终端**，由人按键选择 `1`~`8` | **非交互**，AI 全自动跑完 |
| 写盘 | **有**（`5 › 11` 硬件加速会 `fw3 reload`；`5 › 3` 改在跑的 OpenClash YAML） | **零写盘**（见 §0 红线 1） |
| 跑法 | 必须套 [`tasks/05`](05-nros-plugin-installer.md) §8.6 的「第②关拆两半」——停下等使用者按键 | 四关照跑，**不需要**「停下等使用者」 |
| 参数 | 跟着上游菜单动态编号走（本机 `0-8 / 11-12`，9/10 是空跳号） | 只有 `--skip-docker` 一个降级开关 |
| 菜单编号 | 助手菜单 **9** | 助手菜单 **11**（**10 预留给「清除 / 卸载」引擎**） |

**结论：两者互不替代。** 需要「修」的时候（改配置、重载防火墙）走 9)；只想「看」的时候走 11)。
11) **不套** `tasks/05` §8.6 的两关拆解，也**不进** §8.6.1 的「五个分类差异速查」表 —— 那张表是给
maye 五个分类用的，11) 不是分类。

---

## 2. 输出协议（TSV 七种记录 + 结束哨兵）

设备侧只做**哑采集**（吐事实），**全部判定在 PC 侧**。这样阈值可以离线单测、可以随时改而不动设备。

```
V<TAB>kp-selftest<TAB>1.0.0        版本握手（第 1 行，恒定）
S<TAB><板块号><TAB><板块名>         板块开始（1..5）
K<TAB><键><TAB><值>                键值（值内 TAB/换行已折叠为空格，截 200 字节；空值写 (空)）
L<TAB><组名><TAB><f1>|<f2>|…       列表行（容器 / 镜像 / 端口 / 温度 / 商店应用…）
E<TAB><键><TAB><错误摘要>           采集失败 —— 与「本来就是空」**显式区分**
N<TAB><说明>                       中性备注（如「本机未装 Docker，属预期」）
Z<TAB>END                          结束哨兵
```

**为什么必须有 `Z` 哨兵**：dropbear 在长输出时会 reset 连接，`Rtr.run()` 又**丢 stderr、不看退出码**
（`scripts/rtr_lib.py:114-117`）。没有哨兵就无法诚实区分「跑完了但确实没数据」与「跑到一半被截断」。
**PC 侧解析不到 `Z\tEND` 一律判环境错误（退出码 2），绝不许报成功。**

**四态语义（这是本功能可信度的根）**

| 标记 | 含义 | 例 |
|---|---|---|
| `[ OK ]` | 采到了，且符合期望 | 机型归一化命中、内存够、HTTP 200 |
| `[WARN]` | 采到了，但不理想 / 需要留意 | CPU 72 °C、HTTP 三次中一次失败、补丁 marker 缺失 |
| `[FAIL]` | 采到了，且不符合期望；或**采集失败** | 机型不认识、WAN 未拨号、`E` 记录 |
| `[ SKIP ]` | **本机没有这个对象**，判定不适用 | 未装 Docker、未装 1Panel、5G 未拨号 |

> ⚠️ **只有「采到但不符合期望」才 FAIL/WARN**。「没装 / 没跑 / 没数据」一律 SKIP。
> 本机是**有线 WAN** 出口，5G 未拨号是正常态 —— 若把 CPE 无数据判成 FAIL，这个功能在正常机器上
> 会天天报红，那就彻底失去意义。

**`(空)` 与 `E 采集失败` 是两件事**（硬要求）

- 某板块一条记录都没有 → 渲染 `  (空)`（真无数据）
- 有 `E` 记录 → 渲染 `  [FAIL] 采集失败: <key> —— <err>`（没采到）
- 把这两者混同，就等于「静默地把故障说成正常」。

---

## 3. 前置检查

| # | 检查 | 命令 / 判据 | 不满足怎么办 |
|---|---|---|---|
| 1 | 凭据已给 | `ROUTER_PW` 环境变量，或 `--pw` / `--cred-file`（KEY=VALUE 文本，默认 `~/.workbuddy/kunpeng-router.env`） | 脚本**不给默认密码**，缺就退出码 2；设备档案见 [`AGENTS.md`](../AGENTS.md) §1 |
| 2 | 设备可达 | `ssh root@192.168.66.1`（本机实测可连） | 连不上见 [`references/no-ssh-recovery.md`](../references/no-ssh-recovery.md) |
| 3 | **设备侧语法门禁** | `sh -n /tmp/kps/kp-selftest.sh && echo SYNTAX_OK` | **必须拿到 `SYNTAX_OK` 才允许往下**；PC 侧已内建这道门，不通过直接退出码 2 |
| 4 | 机型归一化 | `/tmp/sysinfo/model` → `HC-WT9500` ⇒ 归一化 `NRadio_C2000Ultra` | 不认识就 WARN；完全读不到就 FAIL（任务包适用性未知） |
| 5 | 版本判据 | `ubus -t 10 call system board` 的 `release.revision`，期望匹配 `^2\.` | **绝不用 `/etc/openwrt_release` 的 `DISTRIB_RELEASE`** —— 那是构建基线的 `21.02-SNAPSHOT`，把两个数混了会得出错误结论 |
| 6 | overlay 载体 | `/proc/mounts` 里 `/overlay` 的设备，期望 `/dev/mmcblk0p1` | 不是它 ⇒ FAIL，且第 5 板块的「可装性」整节作废（只剩 2 MB ramdisk 什么都装不下） |

```sh
# 前三项一次跑完（PC 侧，只读）
python scripts/device-selftest.py --help        # 4 秒确认 CLI 与路径
sh -n scripts/payload/kp-selftest.sh && echo SYNTAX_OK   # 本机语法预检（需 bash）
```

---

## 4. 执行

### (a) PC 侧：一条命令（唯一入口）

```sh
# 凭据走环境变量（推荐，不落盘）
export ROUTER_PW=<密码>
python scripts/device-selftest.py

# 或者显式传
python scripts/device-selftest.py --pw <密码>
python scripts/device-selftest.py --cred-file ~/.workbuddy/kunpeng-router.env

# 降级：dockerd 半死时 docker CLI 会挂住 4~9 秒甚至更久
python scripts/device-selftest.py --skip-docker
```

内部流程（`scripts/device-selftest.py`）：

1. `mkdir -p /tmp/kps` → `put_text_verified` 推送采集器（md5 对账，>4 KB 自动分块）；
2. **设备侧语法门禁**：`sh -n` 未输出 `SYNTAX_OK` ⇒ 立即退出码 2；
3. `sh /tmp/kps/kp-selftest.sh`（`--skip-docker` 时前置 `KP_SKIP_DOCKER=1`）；
4. 解析 TSV → 判定 → 渲染四态；
5. 按 FAIL 计数返回退出码。

**输出形态只有一种**：终端人类可读。不产 JSON、不写 markdown、不落盘任何报告（红线）。

### (b) 设备侧到底跑了什么（逐板块命令清单）

| 板块 | 关键探针 | 命令要点 | 为什么这么写 |
|---|---|---|---|
| **1 系统资源与环境** | 机型 / 版本 / 内存 / 温度 / 存储 / 日志 | `cat /tmp/sysinfo/model` · `ubus -t 10 call system board` · **一次 awk 读 `/proc/meminfo`** · `for z in /sys/class/thermal/thermal_zone*; do cat $z/type,$z/temp` · `awk '$2=="/overlay"{print $1}' /proc/mounts` · `dmesg \| grep -iE '<异常关键字>' \| tail -n8` | 温度单位是 **mdegC**（48000 = 48.0 °C）；日志扫描只看「OOM / f2fs / mmc / segfault / oops」这几类硬故障 |
| **2 容器梳理** | dockerd / docker / 容器 / 镜像 / 1Panel | `pidof dockerd` → 空则整节 `N` 跳过 · `docker ps -a --format '{{.Names}}\|{{.Status}}\|{{.Image}}\|{{.Networks}}'` · `docker images --format '{{.Repository}}:{{.Tag}}'` | **整块守卫**：dockerd 没跑就完全不碰 docker CLI（半死时会挂住） |
| **3 网络与信号** | WAN / 路由 / 代理端口 / HTTP / 5G-CPE | `ubus -t 10 call network.interface.wan status` · `netstat -lnt \| grep -E ':(7890\|7891\|7892\|7893\|7874\|9090) '` · `curl -s -o /dev/null -m 8 -w '%{http_code}' http://www.baidu.com` ×3 · `ubus -t 15 call infocd cpestatus '{"name":"cpe","sync":1}'`（失败再试 `cpe1`） | 真 HTTP 才是判活；CPE 走 ubus 而不是 AT（发 AT 会打扰 5G 模块） |
| **4 服务与补丁状态** | 出厂服务 / 商店补丁 marker / opkg 源 / cron / rc.local / kp_store | `pidof <svc>` + `/etc/init.d/<svc> enabled` · `grep -c '<marker>' appcenter.lua` · `grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf` · `crontab -l` · `tail -n 20 /etc/rc.local` | 判活**只用 `pidof`**；72 个出厂服务绝不能停，只断言「还活着 + 还 enable」 |
| **5 装载余量与可装性对照** | 三把尺子 + 商店应用体积 | `df -P /overlay \| tail -n1 \| awk '{print $4}'` · `awk` 解析 `/etc/config/appcenter` 的 `config package` 块（`option name` / `option size` 字节）· `grep -q "^Package: $pkg$" /usr/lib/opkg/status` | **磁盘这把尺子是「商店自己会怎么判」的复刻**，不是自造 |

### (c) 降级路径

| 症状 | 处理 |
|---|---|
| 输出缺 `Z\tEND`（被截断） | PC 侧立即判退出码 2 并打印末行；先重跑一次，仍截断就加 `--skip-docker` 缩小输出 |
| 第 2 板块明显变慢 / 卡住 | `--skip-docker`（置 `KP_SKIP_DOCKER=1`，设备侧直接不打第 2 节） |
| SSH 中途被 reset | `rtr_lib` 的 `ensure()` 自带断线重连；分块写每块前都会确认连接活着 |
| 设备完全连不上 | 走 [`references/no-ssh-recovery.md`](../references/no-ssh-recovery.md) 的取数通道 |

---

## 5. 验证判据

**通过的定义（缺一不可）**

- [ ] 输出以 `V\tkp-selftest\t1.0.0` 起，**末行为 `Z\tEND`**；
- [ ] 恰好 **5 条 `S` 记录**（`KP_SKIP_DOCKER=1` 时是 4 条，且必须有对应 `N` 说明）；
- [ ] 汇总行四个计数齐全，**`FAIL = 0`**（WARN / SKIP 允许）；
- [ ] 退出码：`0` = 无 FAIL；`1` = 存在 FAIL；`2` = 环境错误（缺凭据 / 连不上 / 推送失败 / 语法门禁未过 / **输出截断**）；
- [ ] **未装 Docker ⇒ 第 2 板块输出 `[ SKIP ]` 而不是 `[FAIL]`**；
- [ ] **有线 WAN 导致 5G/CPE 无数据 ⇒ 对应项 `[ SKIP ]` 而不是 `[FAIL]`**；
- [ ] `(空)` 只出现在**真无数据**的板块，`E` 记录只出现在**采集失败**处；
- [ ] **跑前后零副作用**：设备无新增文件（`/tmp/kps` 除外）、关键服务 pid 不变。

**断言命令（PC 侧）**

```sh
python scripts/device-selftest.py > _out.txt 2>&1; echo "exit=$?"
# 需要逐行核对时再读 _out.txt（PowerShell 下必须重定向到文件再读，直接看 stdout 会被吞）
```

**离线阈值验证**：判定层（`parse_stream` / `verdicts` / `evaluate` / `render`）是纯函数，可用固定 TSV 夹具
覆盖全部阈值分支 —— 包括真机上**无法安全复现**的「overlay 丢失」与「内存熔断」。
覆盖点：正常流 FAIL=0 · 缺哨兵必须退出码 2 · 零记录板块 `(空)` · `E` → `[FAIL] 采集失败` ·
overlay 载体写成 `mtdblock8` → 整节可装性 FAIL · `size` 超剩余 → 装不下 / 1.2 倍 → 余量偏紧 ·
可用内存 28000 kB → 熔断分支 · CPU 76 °C → 过热 / 72 °C → 偏热 / Wi-Fi 81 °C **不**按 CPU 阈值判 FAIL ·
容器非 host → FAIL / `Exited (137)` → 疑似 OOM · 机型未知 → FAIL。

---

## 6. 回滚

**无需回滚** —— 这正是它相对其它任务的特殊之处：

- 设备侧采集器只落在 `/tmp/kps/`（**tmpfs，重启即失**），不写任何设备文件、不启停任何服务、不改任何 UCI；
- PC 侧**不落盘任何报告**；
- 因此本任务**不产生任何回滚对象**，也就不需要「备份 → 还原」流程。

可选清理（想立刻抹掉痕迹时）：

```sh
rm -rf /tmp/kps
```

> 注意：上面这条是**替代方案**里的可选动作，**不在**本任务自动执行范围内（红线 1 禁止 `rm`）。

---

## 7. 已知坑速查（症状 → 原因 → 修法）

| # | 症状 | 原因 | 修法 |
|---|---|---|---|
| 1 | 所有服务都报 NOT RUNNING | 本固件 **`pgrep -c` 恒返回 0** | 判活**只用 `pidof`**；`pgrep` 一律不用 |
| 2 | 内存数差了 1000 倍 | **`free -m` 在本机不认 `-m`**，照样吐 kB | 只读 `/proc/meminfo`，或用 `free -k` |
| 3 | JSON 取值取不到 / 取串 | 本机 **无 `jq`**，且 **`grep -o` 行为有差异** | 用 `sed -n 's/…/p'` 或 `awk` 从 JSON 里抠标量 |
| 4 | 脚本报 `timeout/stat/base64/openssl/xxd/tput/lsblk` not found | 这些**本机全都没有** | 超时自管（`curl -m` / `ubus -t`）、文件属性走 `ls -l --full-time` 或 `md5sum` |
| 5 | 采集到一半就断了，后半段是空的 | **dropbear 对长输出会 reset**，且 `sh` 单发命令 >8 KB 直接被丢 | 有 `Z` 哨兵兜底；PC 侧见哨兵缺失即判退出码 2；输出太大就 `--skip-docker` |
| 6 | ping 显示 0% 丢包但网页打不开 / 反之 | 本机跑 **fake-ip + TUN**，ping 与 TCP 探测会被本地接管，结果不反映真实连通性 | 判活**只用真 HTTP**：`curl -s -o /dev/null -m 8 -w '%{http_code}'` 期望 `200`；境外 `generate_204` 期望 `204` |
| 7 | 以为 `/etc/kp_store` 缺文件是故障 | 本机只有 `routes.list` 是**正常形态**；`installed.list` / `plugins.json` 是另一台机器的遗留 | 只在备注里说明，**不判 FAIL** |
| 8 | 只看磁盘，觉得「还空着 12 GB 随便装」 | 本机 **992 MB 内存、无 swap**，内存才是真瓶颈 | 第 5 板块必须**内存档位与磁盘判定并列**给出结论 |
| 9 | 误把商店 `app_id` 当应用标识 | `1Panel` 的 `app_installs` 表里 **`name` 才是应用 key**，`app_id` 是数字 | 只读展示时以 `name` 为准 |
| 10 | 终端中文列表对不齐 | 设备侧 `${#s}` 按**字节**算，中文占 2 列 | 设备侧**不做右对齐**；对齐放 PC 侧用 `unicodedata.east_asian_width` 计算显示宽度 |
| 11 | Docker 板块卡死几分钟 | **`{{json .}}` 在 Docker 20.10 上卡死**；`{{.Size}}` 在 vfs 下 200 s 不返回；`docker system df` 少报 7.5 GB 孤儿层 | 三条全部硬禁用，只取 `Names/Status/Image/Networks` 与 `Repository:Tag` |
| 12 | `{{.Networks}}` 看着没用就删掉了 | 本机**内核无 veth**，非 `host` 网络的容器**必然起不来** | 该字段是「容器为什么起不来」的第一判据，**不能删** |

---

## 8. 与其他文件的关系

| 文件 | 关系 |
|---|---|
| [`AGENTS.md`](../AGENTS.md) §8.2 | 菜单原文里 `11)` 这一项的**唯一真源**；本文件的编号与标题必须与它逐字一致 |
| [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) | maye 总入口。**11) 不套它的 §8.6 两关拆解**，也不进 §8.6.1 的五分类速查表 |
| [`tasks/10-nros-maintenance.md`](10-nros-maintenance.md) | 菜单 `9)` 的权威真源。**需要「修」时走那边**；11) 只报不修 |
| [`references/store-patching.md`](../references/store-patching.md) | 第 5 板块「可装性对照」的语义来源（商店原生 `check_size()` / `get_overlay_free_memory()` / `get_app_required_bytes()`） |
| [`references/script-ui.md`](../references/script-ui.md) | 设备侧输出纪律（busybox `printf`、中文按字节计宽） |
| [`references/pc-toolchain-limits.md`](../references/pc-toolchain-limits.md) | PC 侧工具链限制（Bash 失效、编码乱码的正确判读方式） |
| [`scripts/rtr_lib.py`](../scripts/rtr_lib.py) | 推送与执行通道（无 SFTP → heredoc + md5 对账；超 4 KB 自动分块） |

**与本任务职责重叠的既有脚本**（**保留不动**，仅在此标注为历史）：

- [`scripts/healthcheck_c2000u.py`](../scripts/healthcheck_c2000u.py)：13 板块全量只读巡检 ——
  职责已被本任务收拢，**新工作优先用 `device-selftest.py`**。
- [`scripts/kp-1panel-status.py`](../scripts/kp-1panel-status.py)：只读盘点 1Panel 容器 ——
  容器部分已并入本任务第 2 板块；它仍有「1Panel 面板库 `app_installs` 对照」这一段独有能力，
  **需要面板记账对账时仍用它**。

> [`scripts/kp-1panel-install-test.py`](../scripts/kp-1panel-install-test.py) 与
> `scripts/payload/` 下的 compose 回归自测**不属于**被取代范围 —— 它们会写盘，
> 是「装 / 验证」类工具，与本任务的「只读体检」用途不同。
