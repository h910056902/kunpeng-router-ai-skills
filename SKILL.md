---
name: kunpeng-router-tuning
description: 鲲鹏无限/NRadio 鲲鹏 C2000 Max OpenWrt 路由器深度定制技能。触发词：鲲鹏路由器、鲲鹏C2000 Max、NRadio、192.168.66.1、OpenWrt 21.02.7、在线应用商店、kp_store、appcenter、Docker 移植、stub ipk、AdGuard Home、AGH、去广告规则、DNS 接管、dnsmasq、OpenClash 分流、NAS、ksmbd/samba、U盘挂载、USB 存储、aria2、minidlna。覆盖：LuCI 补丁、安装百分比、已安装注册表、Docker host 模式、AGH 全网 DNS、国内过滤清单、NAS 升级路线。
agent_created: true
---

# 鲲鹏路由器深度定制 (kunpeng-router-tuning)

> 你（AI）正在操作一台真实的路由器。执行任何写操作前，先读完本文的「铁律」，再按「任务路由表」找到对应 playbook。

## 设备档案（硬编码事实，直接引用）

> ⚠️ **2026-09-11 起 `192.168.66.1` 是 B 机（C2000 U），不是 A 机**。
> 下表描述的是 **A 机（C2000 Max，493MB / eMMC）**，它**已不在链路里**。
> B 机的参数见文末「第二台设备」行 —— 两者内存/存储/LuCI 版本都不同，**别混用**。

### A 机：鲲鹏 C2000 Max（已不在链路，仅作历史参考）

| 项 | 值 |
|---|---|
| SSH | `root@192.168.66.1:22`，密码从 `ROUTER_PW` 环境变量读，**绝不写入文件** |
| 固件 | OpenWrt 21.02.7，aarch64_cortex-a53（mt7987 定制），内核 5.4.281 |
| 内存 | 493MB，可用常年 30~80MB；**写操作前必查** `free -k` |
| 存储 | eMMC，overlay 27.8G 空闲，f2fs 原生挂载 `/tmp/storage/mmcblk0p1` |
| 商店后端 | `/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua`（Lua） |
| 商店前端 | `/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm`（htm 模板） |
| LuCI 版本 | **git-26.224（新世代）**：`cbi.lua`/`model/network.lua`/`view/cbi/*` 由 luci-compat 提供 → **禁止装 21.02.7 的旧版 luci-compat（git-22.046），装了必崩** |
| 已装注册表 | `/etc/kp_store/installed.list`，`|` 分隔 8 字段：`id|名称|pkg|版本|时间|route|source|简介` |
| 商店清单源 | `/etc/kp_store/plugins.json`（本地清单） |
| DNS 链路 | 设备 → AGH(:53) → OpenClash(:7874) → 上游；dnsmasq 退 :5354 只管 DHCP |
| AGH | Docker host 模式，管理页 :3000，凭据走 `AGH_USER`/`AGH_PASS` 环境变量 |
| OpenClash | Mihomo 内核 Fake-IP；`raw.githubusercontent.com` 经它可达，jsdelivr/gitee 不可达 |
| USB/NAS | USB 3.0 口（xHCI 正常）；**未装 usb-storage 驱动**，外接盘不出现 /dev/sda；源里有 ksmbd/aria2/minidlna/nfs 全套可装 |
| 硬盘格式 | 内核支持 ext4/f2fs/vfat/fuseblk(NTFS via ntfs-3g)；**不支持 exFAT**（内核无驱动+无 fuse 版） |
| 温度 | 待机 ~62°C，7x24 挂盘注意通风 |
| GitHub 仓库 | **公开**：https://github.com/h910056902/kunpeng-router-ai-skills （本技能包，已脱敏）<br>**私有**：https://github.com/h910056902/kunpeng-router-tuning （完整档案：memory/ 日志、src/ 源码、HANDOFF/PROGRESS） |
| 接手文档 | 仓库根 [`AGENTS.md`](AGENTS.md)（**AI 机器可读入口，先读这个**）+ [`README.md`](README.md)；任务入口见 `tasks/index.json` |
| 记忆归档 | 私有仓库 `memory/`：`PROJECT-MEMORY.md`（长期）+ 每日日志（公开仓库不含，含真实内网细节） |
| 源码归档 | 私有仓库 `src/dockerpanel/`：dpctl / dpapi.lua / controller / htm 路由器端源码副本 |
| 部署脚本 | 私有仓库 `src/deploy/`：41 个部署/验证/测试脚本 + `README.md` 部署手册 |
| PC 侧脚本库 | `C:/Users/91005/Desktop/鲲鹏无限路由器美化/patches/`（paramiko + Python） |
| **第二台设备** | 鲲鹏 **C2000 U**（产品名 `C2000-798`，板型 `HC-WT9500`，MT7987，**992MB 内存**，7.5G **TF 卡**，内核 5.4.281 同源，LuCI git-26.253）。**Docker 已实装：overlay2 + data-root `/mnt/storage/data/docker` + 开机自启**（2026-09-11）。⚠️ **2026-09-14 更正：厂商源 `kmod-veth` 是空包（装完无任何 .ko），内核 `CONFIG_VETH/MACVLAN/IPVLAN` 全部 not set → 桥接网络物理不可用，Docker 只能用 host 网络，别再指望装 kmod 解决**。**1Panel v1.10.34-lts 已原生装成**（端口 10090，procd 服务，静态二进制跑 musl，凭据在路由器 `/root/1panel-credentials.txt`）。详见 **`references/c2000u-docker.md`** 与 **`references/c2000u-1panel.md`**。
⚠️ 三条实测硬事实（2026-09-11）：**① `/etc/kp_store/` 不存在** —— 商店从未初始化、后端 `appcenter.lua` 是原版（474 行/15057 B，增强标记全 0），要"注册进商店"必须先建骨架+打补丁；**② `usb-storage.ko` 缺失** —— `kmod-usb-storage` 只装了 modprobe 配置没装模块，**外接盘不可用**；**③ TPROXY 与 TUN 都可加载** —— `modprobe tun`/`xt_TPROXY` 实测 OK，OpenClash 两条路都通 |

## ⭐ A 机全套工作产物在 PC 侧（做 B 机时先来这里找，别从零写）

路径：**`%USERPROFILE%\Desktop\鲲鹏无限路由器美化\`**（这是 **kunpeng-istoreos** 项目，与技能包仓库不同）

| 资产 | 位置 | 用途 |
|---|---|---|
| **12 个商店增强补丁脚本** | `patches/*.py` | fix_install_backend / patch_backend_tags / build_depcache / patch_list_depcache / patch_register / patch_ver_fix / patch_extra_plugins / patch_extra_installed / patch_online_ui / patch_install_percent / patch_store_open_url |
| `kp-areuok` 本体 | `patches/kp-areuok.sh` | 部署到 `/usr/bin/kp-areuok`（Are-u-ok .run 下载/安装/卸载） |
| Are-u-ok 插件管理器 | `patches/areuok_plugin.py` | 11 个 .run 插件（kms/nps/openclash/mosdns/unblockneteasemusic/passwall…） |
| **6 个 stub ipk（5.4.281-1 aarch64）** | `patches/_stubs/*.ipk` | kmod-veth/br-netfilter/ikconfig/nf-ipvs/fs-btrfs/dm —— **同内核同架构，两台机器通用** |
| **OpenClash 配置备份** | `ocspeed-bbydy-backup/openclash/config.openclash-uci` + `bbydy.yaml` | 装 OpenClash 时的 UCI/订阅参考 |
| iStore 安装脚本 | `kunpeng-istore.sh` | 装 iStore + Argon（**不碰 appcenter.lua**） |
| 网易云解锁 CBI 垫片 | `patches/unm_luci_shim.py` + `unm_luci_shim/` | NROS 不支持 menu.d → 补经典控制器 |
| **kp-webui 独立控制台** | `src/kpwebui/` + `scripts/deploy_kpwebui.py` + `references/kpwebui.md` | iStoreOS 风格 WebUI（uhttpd 第二实例 + ash CGI），`:10086+1=10087`，6 个页面，零常驻开销 |
| **nr_webui 逆向档案** | `references/nr-webui-reverse.md` + `scripts/restore_nrwebui.py` | 第三方 nr_webui 的完整解析（架构/22 个 API/短信转发/OTA/门户劫持/安全观察）+ 一键还原 |

**改造点（必做）**：这 12 个脚本**一律用 `c.open_sftp()`**，而固件**没有 sftp-server** →
必须统一改用技能包 `scripts/rtr_lib.py`；另外脚本里硬编码了 HOST/密码，要改成环境变量。

**已知硬缺口**：`iStore 在线集成` 那段后端 Lua **无存档**
（`kunpeng-istore.sh` 里 grep `appcenter|online` 只命中 3 处、都不相关；全盘只有"修改它"的脚本、没有"生成它"的脚本）。
要拿到 146 个在线应用必须**从零重建这层**；否则只能做"注册表→原生商店"的最小闭环。

## 商店机制真相（2026-09-11 实测，与直觉不同）

- **数据源是 ubus，不是文件**：`ubus call appcenter list` → `{"parameter":{"appstore_code":5,"applist":[...]}}`
- **配置在 `/etc/config/appcenter`（标准 UCI）**，指向厂商源
  `https://www.appstore.vapyun.com/nradio-appstore/aarch64_cortex-a53/<应用名>/<版本>/<包>.ipk`
- `action_app_list_data()` 只做 i18n 翻译后 `return applist.parameter`，**没有任何 merge**
- → 要接 iStore / Are-u-ok **必须在 Lua 层聚合**（C 程序 `appcenter` 不认）
- → 往 `/etc/config/appcenter` 塞 `config package` / `config package_list` 条目**已验证可用**（2026-09-16）：写 UCI → `uci commit appcenter` → `/etc/init.d/appcenter restart`，`ubus call appcenter list` 立刻能看到。**不需要** plugins.json / installed.list（那是 A 机那套 12 补丁的老机制，与本机现状是两条互不相干的路，别混用）
  - 「已安装」由守护进程对每个 `package_list` 子包名跑 **`opkg info`** 实时判定（不是读 UCI 里的 status）
  - 「打开」= iframe 加载 `luci_module_route`，但**守护进程只给远程目录里的应用下发这个字段**，UCI 里手写的会被它重写丢弃 → 见下方 routes.list 行
  - 「卸载」真跑 `opkg remove` → 非 opkg 安装的应用（1Panel / ocspeed）必须造**空占位 ipk** 让 opkg 认账
- **原版补丁锚点**（B 机确认存在）：`function action_app_list_data()` 尾部 `return applist.parameter`、
  `function action_app_core(name,action)`、`function action_app_uninstall()`

## 铁律（违反即翻车）

1. **改 Lua/htm 前必备份**：时间戳后缀 `file.bak-标签-YYYYMMDD_HHMMSS`；回滚选备份时按时间戳**倒序**找含全部关键补丁的最新份（字母序会退回最老版本）
2. **Lua 改动走暂存校验**：先写 `/tmp/xxx_new` → `lua -e "assert(loadfile('/tmp/xxx_new'))"` 通过 → 再落盘正式路径
3. **改完必清缓存**：`rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache`，否则前端/控制器不生效
4. **写后必验证**：读回文件本体（grep）确认落盘，sftp 曾出现只写了备份没写正本的静默失败
5. **凭据零落盘**：SSH/AGH 密码只经环境变量，不写进脚本、补丁、日志
6. **不可逆操作先问用户**：卸载、覆盖、重启网络服务（DNS 断网风险）需先说明影响
7. **不要拿卸载路由做测试**：商店卸载接口对任意 action 都会真删

## 任务路由表

### 一键任务包（面向 Agent 的机读 playbook，优先入口）

| ID | 任务 | 任务包 | 关键输入 |
|---|---|---|---|
| T1 | OpenClash 安装 + 内核拉取 | `tasks/01-openclash-install.md` | `offline/openclash/` + `offline/core/` + `offline/stubs/` |
| T2 | ocspeed 安装 | `tasks/02-ocspeed-install.md` | `offline/ocspeed/`（五件套 + `kp-ocspeed.sh`） |
| T3 | Docker + 1Panel 安装 | `tasks/03-docker-1panel-install.md` | `offline/panel/`（nros-panel 安装链） |
| T4 | 清空 Docker 环境与容器（重装前置） | `tasks/04-docker-purge.md` | `scripts/payload/kp-docker-purge.sh`（dry-run 默认） |

> 任务包内含前置检查 / 步骤 / 验证判据 / 回滚与风险点；机器索引：`tasks/index.json`（id、前置、脚本、风险、验证）。
> 三大任务在 B 机（C2000 U）上均已实装验证；任务包兼作「从零复现」与「幂等核对」双用途。
> **T4 是 `destructive`**：必须先 dry-run 出清单交用户逐条确认，且只能 `--apply --yes` 双开关执行。

### 按场景路由（A–V）

| ID | 任务 | playbook 概要 | 详见 |
|---|---|---|---|
| A | 商店加插件/改条目/改简介/卸载 | 注册表是 `installed.list`，改第 2 列名称/第 8 列简介（split 后 f[1]/f[7]）；source=docker 条目免 opkg 校验 | `references/store-patching.md` |
| B | 商店后端/前端打补丁 | 定位 appcenter.lua/htm → 备份 → /tmp 校验 → 落盘 → 清缓存 → grep 验证 | `references/store-patching.md` |
| C | 安装进度显示 | 后端 `_online_install_percent()` 已内置（日志阶段加权+时间兜底），前端读 `percent` 字段 | `references/store-patching.md` |
| D | 装/配 Docker 或容器 | 全部 host 网络（无 veth）；新依赖缺失 → 造 stub ipk（老式 tar.gz 嵌套格式） | `references/docker-porting.md` |
| E | AGH 改端口/接管 DNS/回滚 | 只能 sed `AdGuardHome.yaml` 的 `dns.port`；切换顺序：先迁 dnsmasq → 再重启 AGH | `references/adguard-setup.md` |
| F | 加/换去广告过滤清单 | 先 `scripts/probe_filterlists.py` 探测可达性 → `scripts/add_filterlists.py` 走 API 添加；内存 <30MB 别加大清单 | `references/adguard-setup.md` |
| G | DNS 不通/被劫持排查 | 查链路四段：53 是否 AGH 在听 → AGH 上游 → OpenClash 7874 → dnsmasq 5354 | `references/adguard-setup.md` |
| H | NAS 升级（挂盘/共享/下载机/媒体） | 先 `scripts/probe_nas.py` 探硬件 → 按 U 盘格式选挂载方案（exFAT 挂不了！）→ ksmbd 共享 → aria2/minidlna 原生服务 | `references/nas-upgrade.md` |
| I | 技能包/仓库同步 | 公开仓库 `kunpeng-router-ai-skills` 由构建脚本从私有技能包生成（脱敏）；私有仓库 `kunpeng-router-tuning` 承载完整档案（memory/、src/、HANDOFF/PROGRESS） | `AGENTS.md` |
| J | maye 插件助手兼容 | 跑社区脚本 `nradio.mayebano.shop/ssh-nradio-plugin-installer.sh` 前后：snapshot → 用户跑脚本 → check → 丢补丁 check --fix 重放；**禁在其菜单装 AGH/mosdns（native:554 与我们 Docker AGH:53 冲突）** | `references/maye-assistant.md` |
| K | 装 iStore 商店 / 1Panel | iStore 框架可装（手动解包 ipk），与鲲鹏商店并存；**1Panel 已原生装成（v1.10.34-lts，端口 10090，官方包自带 procd init，二进制静态链接可跑 musl）** | `references/istore-integration.md` + `references/c2000u-1panel.md` |
| K2 | **让 1Panel 应用"默认"走 host 网络（无 veth 内核必做）** | 1Panel 模板一律引用 bridge 外部网络 `1panel-network` → 本机装必挂在 veth pair。**正路是换 `/usr/bin/docker-compose` 为 wrapper**（真件改名 `.real`），调用前把 `-f` 的 compose 幂等 host 化 → 面板/商店/手工全生效，且容器由 1Panel 自己 up（会进「已安装应用」）。配套转换器 `kp-compose-host`（含 Redis 5.4 内核兼容参数）。⚠️ **转换器必须缩进无关**：面板 v1.10 落盘的 compose 是 **4 空格缩进 + 多一个 `deploy` 段**，商店 tarball 是 2 空格 —— 写死缩进会让面板装应用报 `Service "x" uses an undefined network`（2026-09-19 真机事故）。回归自测：`kp-compose-selftest.sh` + `fixtures/` | `references/1panel-hostnet-default.md`（§九·补 必读） |
| K3 | **测「1Panel 能不能装容器」** | 一条命令跑完 `probe→pull→control→[授权]→hostnet-install→install→panel→panelcheck→verify`：拉 alist 真镜像、无 wrapper 对照组复现 veth 错、装 wrapper、复刻 1Panel 调用形态装起来并验 HTTP 5244。面板 API 自动化不可靠（v1.10 登录要 RSA+AES 加密）→ 会降级成"你在浏览器点一次 + 脚本自动收尾取证"，证据源是 `/tmp/kp-compose.log` | `scripts/kp-1panel-install-test.py` + `scripts/payload/kp-1panel-test.sh` + `references/1panel-hostnet-default.md` §七~九 |
| K4 | **查「现在到底有哪些 1Panel 容器」** | 一条只读命令出全景：`python kp-1panel-status.py` → 容器清单（state/exit/**OOMKilled**/nm/restart 策略）+ 面板 `app_installs` 记账对照 + 磁盘应用实例是否已 host 化 + 宿主端口监听 + host 化装置是否在位 + **dmesg OOM 归属**（`task_memcg=/docker/<id前缀>` 直接指认是哪个容器被杀）+ 内存红线判读。**两个必知陷阱**：① 面板库表 `app_installs` 里 `name` 才是应用 key，`app_id` 是数字；② 本固件 busybox `free -m` 不认 `-m`，照样吐 kB → 改读 `/proc/meminfo`。⚠️ **1GB 内存设备上 DSH 这类 649MB 镜像会被全局 OOM 杀掉，而面板仍显示「运行中」** | `scripts/kp-1panel-status.py` + `references/1panel-hostnet-default.md` §十一 |
| L | Portainer 汉化 | 官方 i18n 是半成品（locales 仅 765B）；走「静态 JS 替换 + 挂载卷」，1872 处已落地；**正则必须处理 `\"` 转义否则全盘错位**；小写词（no/host/container）禁翻 | `references/portainer-i18n.md` |
| M | Docker 面板（自建） | **读数据一律走 Lua `socket.unix` 直连 Docker HTTP API（0.03-0.3s），绝不用 docker CLI（冷态 4-9s）；`curl` 不支持 `--unix-socket` 但 LuaSocket 支持。** 禁 `docker ps --format {{.Size}}`（vfs 下 200s 不返回）；`du` 扫描必须用 `mkdir` 原子锁防轮询叠加；**bridge 网络不可用，只能用 host 模式**；加速源要写 UCI `dockerd.globals.registry_mirrors`（`/tmp/dockerd/daemon.json` 每次启动重生成） | `references/docker-panel.md` |
| M2 | **Docker 面板部署** | 4 文件上传（`dpctl`→`/usr/sbin/`、`dpapi.lua`→`/usr/lib/lua/`、controller、htm）→ 配上 UCI 加速源 → 清 LuCI 缓存。**上传必须强制 `\r\n`→`\n`**（CRLF 毁 shebang 报 `dpctl: not found`）；验证分水岭是 `lua -e 'require("dpapi").get("/version")'` 是否返回 JSON。一键脚本 `src/deploy/dp_deploy.py` | `references/docker-deploy.md` + `src/deploy/README.md` |
| N | 省内存 / 停插件 | 停 Docker 全家 + `mosquitto mqttagent miniupnpd telnetd wifidogx xl2tpd igmpproxy` → 可用内存 47→150MB、**swap 178→32MB**、出网 0.25→0.046s。**绝不能停** network/firewall/dnsmasq/uhttpd/dropbear。面板内可一键启停 Docker（`docker_service`） | `references/docker-panel.md` §八 |
| O | PC 侧工具链故障 / 编码乱码 | **Bash 工具已失效**（`dirname`/`cut`/`env` 全缺，返回 127）→ 改用 Python subprocess；PowerShell 回显中文乱码**不等于**数据损坏，核对编码必须走字节层；`Out-File -Encoding utf8` 会写 BOM | `references/pc-toolchain-limits.md` |
| P | **第二台设备 C2000 U 的 Docker 实装** | **已装好，复现用 `scripts/setup_docker_c2000u.py`**（6 步：换源→造 stub→装包→配 alt_config_file→开自启→冒烟）。要点：**配置必须走 `uci set dockerd.globals.alt_config_file`**（UCI 生成器不支持 storage-driver/bridge）；**装 stub 前先移走 `/var/opkg-lists`**（否则被 feed 同名包截胡）；**本机无 SFTP**，传二进制只能 `printf '\\NNN...'`；data-root 必须在 `/mnt/storage/data`（裸 f2fs）才有 overlay2，放 `/opt/docker` 只能 vfs | `references/c2000u-docker.md` |
| Q | **NAS 影视墙容器（B 机）** | 全部 `--network host`。实测可用：**alist:5244(129MB)**、**navidrome:4533(232MB)**、**filebrowser:8082(36MB)**；**jellyfin(867MB) 能拉但启动要求 config 分区可用空间 ≥2GiB 且 RSS 218MB**，992MB 内存机器上要权衡。脚本：`kp-docker1panel/media-pull-test.sh` | `references/c2000u-media.md` |
| R | 省内存（B 机容器侧） | 先删 Exited 死容器，再停最重的容器（jellyfin 218MB 是典型大头）；1Panel 面板 RSS ~70MB、openclash clash ~65MB、dockerd ~40MB。巡检脚本 `kp-docker1panel/mem-report.sh`（进程 RSS Top + 自启服务） | 本表 Q + N |
| S | **无 SSH / 22 连不上 / 存储掉线** | ① `curl -v telnet://IP:22` 区分 **refused**(无监听) / **timed out**(防火墙 DROP)，并与本机 `nc 127.0.0.1 22` 对照 → 若本机通而外部 refused，就是 `firewall` 的 `config rule 'ssh'` 在拦；② LuCI 能登就**先直接 GET `/admin/status/dmesg` 与 `/admin/status/syslog`**（服务端渲染的 textarea，**零延迟、不用等 cron**，实测 1382 行/117KB），再不够用才**借 crontab 页面当命令通道**（multipart：`token`+`cbi.submit=1`+`cbid.crontab.1.crons`，输出写 `/www/*.txt` 再 HTTP 读回，收尾用**一条自清理 cron**）；③ 软重启真接口是 `POST /admin/system/reboot/call`（带 `token`，**chunked 流式 200 = 已触发**），`/admin/system/reboot` 那个 URL 是假的（渲染的是 flashops）；④ **存储是可插拔 TF 卡**，卡掉线时**软件层无法复位**（`mtk-msdc` unbind/rebind 无效、无软件可控稳压器）→ 只能物理断电 + 重插卡 | `references/no-ssh-recovery.md` |
| T | 写/改运维脚本的终端界面 | 输出抽到独立 `kp-ui.sh`，脚本只调 `ui_*` 不写 printf。三条硬约束：busybox sh + printf（无 tput/数组）；**中文占 2 列但 `${#s}` 按字节算 → 禁止右边框和右对齐**；非 tty 自动关色。取脚本目录**禁用 `dirname`**（用 `${0%/*}`）。阶段编号只给真阶段，收尾汇总不占编号 | `references/script-ui.md` |
| U | **一条命令重装三大件（换卡 / 卡被重置 / overlay 丢失后）** | 仓库 **`h910056902/nros-panel`**（public、已脱敏）。入口：`wget -qO /tmp/kp.sh https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh && sh /tmp/kp.sh` —— 自动判断：存储没就绪就先分区+重启，重启后**自动续跑**装完。五条关键事实：① **出厂 6 个 opkg 源全部失效（`000`，不是 404）→ 必须整体换阿里云 21.02.7**；② 设备上 **curl 拉 raw 必失败、同一地址 wget 可以 → 下载须 curl/wget 双栈**；③ 跨重启续跑靠**预置新卡 p1 的 `upper/etc/rc.local`**（执行 rc.local 的是 `/etc/init.d/done`，`S95done` 在只读 `/rom` 里）；④ **`dockerd` 装不上报 `incompatible with the architectures configured` 是假象** —— 真因是 6 个 kmod（veth/dm/fs-btrfs/br-netfilter/ikconfig/nf-ipvs）在厂商内核上根本不存在，opkg **在"选候选包"阶段就失败，`--force-depends` 完全无效**（那开关只管"装包时"的检查）→ 必须造只声明 `Provides` 的桩包把依赖链闭合；⑤ **dockerd 配置只认 UCI**（`/etc/init.d/dockerd` 把 UCI 渲染到 `/tmp/dockerd/daemon.json`），写 `/etc/docker/daemon.json` **没人读** → 实测 Root Dir 仍是 `/opt/docker`、驱动退化 `vfs`、拉镜像 15s 超时；改 UCI 的 `data_root`/`registry_mirrors` 后立即正常（`pull hello-world` 5.1s） | `references/one-command-restore.md` |
| V | **系统分区（/overlay）不够大，要原地扩容** | `resize.f2fs` **拒绝对已挂载的 fs 操作**（内含硬错误串 `Not available on mounted device!`），而 `/overlay` 就是 `/` 永远挂着；`pivot_tf_overlay()` 又**硬编码 `/dev/mmcblk0p1`**（overlay 不能挪分区）→ **唯一窗口是"NOR 窗口"**：开机瞬间系统落在 `/dev/mtdblock8`（2MB jffs2）上、卡还没挂载。四步：**在线改分区表（p1 起始扇区必须保持 16）→ 把 `/mnt/mtdblock8/upper/etc/config/fstab` 的 `/overlay` 设 `enabled=0` 并预置 `kp-resize.sh`+`rc.local` → reboot → 窗口内先 umount 热插拔挂的 p1 再 `resize.f2fs` → 恢复 fstab 再 reboot**。实测 4G→16G，数据零丢失。⚠️ 最容易漏的一步是**先 umount `/tmp/storage/mmcblk0p1`**，否则 resize 照样以 mounted 拒绝 | `references/tf-partition-resize.md` |

## ⚠️ 高危操作禁令（血泪教训）

1. **绝不装旧版 luci-compat**：本机 LuCI 是 git-26.224，旧包（git-22.046）`--force-overwrite` 装上去会污染 luci-base，卸载时还会删走系统必需的 `cbi.lua`/`model/network.lua`/`view/cbi/*` → **整个 LuCI 502，所有页面打不开**
2. **`opkg --force-overwrite` 前必备份** `/usr/lib/lua/luci`；卸载一个曾 overwrite 安装过的包 = 可能删掉别的包的文件
3. **LuCI 崩了用 `/rom` 救**：固件只读副本里有一切原始文件，只补不覆盖地同步回 `/usr/lib/lua/luci` 即可全量恢复（命令见 `references/istore-integration.md`）
4. 崩溃定位：`cd /www && REQUEST_URI='/cgi-bin/luci/admin/system' lua /www/cgi-bin/luci 2>&1 | head -15`

```bash
cd ~/.workbuddy/skills/kunpeng-router-tuning
git add -A && git commit -m "..."
# 关键：沙箱代理对 github CONNECT 可能返回 502，去掉 proxy 环境变量走直连；网络偶发抖动，失败重试 2-4 次
for i in 1 2 3 4; do env -u http_proxy -u https_proxy -u HTTP_PROXY -u HTTPS_PROXY git push origin main && break; sleep 3; done
```
- 两个仓库分工：`kunpeng-router-ai-skills`（**public，已脱敏**，= 本技能包）/ `kunpeng-router-tuning`（**private**，完整档案）
- 认证：`gh.exe` 在 `C:\tmp\bin\gh.exe`，已登录（scope 含 `repo`），同时是 git 的 github.com credential helper
- 改仓库描述/可见性：`gh api -X PATCH repos/<owner>/<repo> -f description="..." -F private=true`
- ⚠️ **推公开仓库前必须过一遍脱敏扫描**：密码 / 入口码 / dashboard secret 一律替换成占位符，真实值只走环境变量

## 执行模式（所有远程操作的标准姿势）

```python
# PC 侧用 paramiko，密码走环境变量；模板见 scripts/probe_filterlists.py
import os, paramiko
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ['ROUTER_HOST'], 22, os.environ['ROUTER_USER'], os.environ['ROUTER_PW'], timeout=12)
_, o, _ = c.exec_command("命令; echo EXIT:$?", timeout=60)   # 超时必须设
```

- 长命令给足 `exec_command` timeout；远端 curl **必须带 `-m`**，否则远端挂起会拖死通道
- 环境变量：`ROUTER_HOST/ROUTER_USER/ROUTER_PW`、`AGH_USER/AGH_PASS`
- AGH API 模式：`POST /control/login` 拿 cookie（`curl -c`），后续 `-b` 带 cookie；**刚加完清单 API 会短暂无响应**，等 10 秒再查

## 踩坑速查（症状 → 原因 → 修法）

| 症状 | 原因 | 修法 |
|---|---|---|
| opkg 报 `Malformed` 拒装自造 ipk | tarfile 默认 PAX 格式，此固件 opkg 只认老式 gzip+tar 嵌套 | 用 GNU/USTAR 格式重造，外层结构 data.tar.gz+control.tar.gz 再 gzip 成 ipk |
| Python `tarfile.open()` 打不开厂商 ipk（`invalid header`） | 厂商 ipk 可能是 **ar 格式**（deb 风格：文件头 `!<arch>`，成员 debian-binary / control.tar.gz / data.tar.gz，GNU ar 名字带尾 `/`） | 先 `head -c 8` 判断：`!<arch>` 用手写 ar 解析（8 字节魔数 + 60B 头循环：name[16] size[48:58]，数据按 2 字节对齐） |
| **ar 格式 ipk 装不上：`pkg_init_from_file: Malformed package file`** | **此固件 opkg 只认老式 gzip+tar 嵌套，ar 格式（deb 风格）一律拒收**（2026-09-12 B 机实测，厂商自己的 ar 包也拒） | PC 侧重打包：ar 里抽出 control.tar.gz/data.tar.gz/debian-binary → 外层用 `tarfile.GNU_FORMAT` 打包三成员 → gzip 压缩成新 ipk，md5 对账后再传 |
| 第三方"装内核"脚本报 `gzip: invalid magic`（下载 100% 完成后） | 脚本 `OUT="${TMP%.gz}"`，但下载名带 `.$$` 后缀（`xxx.gz.30523`）不以 `.gz` 结尾 → `%` 匹配失败 → OUT==TMP → `gzip -dc 读的同时 > 截断写同一文件` | sed 改 `OUT="${TMP%.gz.*}"`（备份原脚本），再重跑其 update-core；SHA-256 校验逻辑不受影响 |
| busybox `sed '/p/a\ text'` 追加行带前导空格，YAML 直接报废（`mapping values are not allowed in this context`） | GNU sed 会吞 `a\` 后的一个空白，busybox sed 原样保留 → 缩进错位的 mapping 行插进了标量值后面 | 追加行一律顶格写（`a\text`），或事后 `sed -i 's/^ key/key/'` 补救；改完必跑 `mihomo -t` 校验再 restart |
| 给 B 机装新代理/内核类服务必撞端口 | **B 机 OpenClash 进程名是 `clash`**（不是 mihomo），占 :::7890/7891/7892/7893/:::9090；`pidof mihomo` 查不到它 | 装 前 `netstat -lntp` 预检；装 后把默认 7890→7897、9090→9099（sed config），`pidof mihomo` 只能查自装的新内核 |
| mihomo 面板下载与开启（clash-verge-router 实操，2026-09-12） | `external-controller: 0.0.0.0:9099` + `secret` + `external-ui: ui` + `external-ui-name: metacubexd` + `external-ui-url: .../compressed-dist.tgz`，启动时自动下载解压到 `ui/metacubexd/`，HTTP 路由仍是 `/ui/` | 面板地址 `http://192.168.66.1:9099/ui/`，API 带 `Authorization: Bearer <secret>`；配置备份 `config.yaml.bak-dash` |
| opkg 装依赖即使 `--force-depends` 也拒 | unresolved 依赖在候选解析阶段就被拒 | 造 stub 空 ipk 补依赖（唯一干净路径） |
| 商店「打开」按钮不渲染 | route 字段为空 → has_luci=0 | 注册表 route 填非空；填完整 `http://` URL 则前端新窗口打开 |
| **商店「打开」点了是一片空白（本地注册的应用）** | 守护进程 `appcenter` 只给**远程目录**里的应用下发 `luci_module_route`；本地 UCI 注册的条目拿不到这个字段，而且它会把你手写的同名 option **重写丢弃**。所以「已注册 + 显示已安装」都可能都正常，只有「打开」空白 —— 肉眼很难判断是哪一环 | 路由写到守护进程碰不到的 **`/etc/kp_store/routes.list`**（每行 `应用名\|路由`），再在 `controller/nradio_adv/appcenter.lua` **末尾后定义同名函数覆盖** `action_app_list_data()` 去读它（原函数 100+ 行，改函数体必然跟固件升级冲突）。改完必须 `rm -rf /tmp/luci-modulecache /tmp/luci-indexcache` + `/etc/init.d/uhttpd restart`。完整实现见仓库 `h910056902/nros-panel` 的 `kp-store-lib.sh` |
| **非 opkg 安装的应用在商店里永远显示「未安装」** | 商店「已安装」由守护进程实时 `opkg info <子包名>` 判定；1Panel 是官方脚本装的、ocspeed 是拷文件装的，opkg 数据库里查无此包 | 造**空占位 ipk**：`control` 里 `Depends: libc` + `Architecture: $(DISTRIB_ARCH)`，`data` 只放一个 README，打成 debian-binary / control.tar.gz / data.tar.gz 三件套。已装就跳过（`opkg status <pkg> \| grep -q Status:`）。注释务必写清「商店里的卸载只删占位包，真正卸载走 1pctl uninstall」 |
| **跑在独立端口的服务无法作为商店「打开」目标** | 「打开」固定 iframe 加载 `/cgi-bin/luci/<路由>`，而同源限制 + 服务本身不是 LuCI 页面 | 造**同源承载页**：`controller/nradio_adv/<name>.lua` 注册一个 `template()` 路由 + `view/nradio_<name>/panel.htm` 里再套一层 iframe 指向真实地址。地址**动态读**（1Panel 用 `1pctl user-info \| grep -oE 'http://[^ ]*'`）而不是写死，端口/入口改了不用动脚本 |
| 改了 Lua 前端没变化 | LuCI index 缓存 | `rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache` |
| **部署成功后文件"自己变回旧版"（2026-09-19 实测）** | **另一个并发 AI 会话/工具在改 PC 侧源码仓库并推送路由器**（改动后 ~1 分钟内推到设备）。表现为部署 md5 校验通过、几十分钟后文件被整体覆盖回旧版（htm/lua/view 多文件同 mtime）。商店守护进程无下载 URL 时不会自愈还原，cron 也无关 | ① 排查顺序：设备文件 md5 ↔ PC 仓库比对（逐字节一致即实锤）→ 设备多文件同 mtime 时间点 → PC 侧 automation 列表 → 仓库文件 mtime 是否在检查期间变化；② **部署前先和用户确认没有其他会话在动同一批文件**，统一"仓库=唯一真源"后再部署；③ 匹配到仓库旧版时，把新改动重放到仓库最新版之上（锚点断言式替换），别拿旧基线产物硬盖 |
| **行切分 heredoc 分片上传后 md5 对不上** | `text.split("\n")` 若文本以换行结尾会得到末尾空元素 `""`，按行写片后该空元素变成片尾多出的空行 → 整体多一个 `\n` | 切分后 `lines.pop()` 去掉末尾空元素（heredoc 每行自带 `\n`），**上传前先在本地模拟拼装并断言 md5 一致**（可复用 `deploy_v11d.py` 的 `make_parts()`）；本机 BusyBox 无 `base64` applet，b64 传输方案不可用 |
| AGH API 改不了 DNS 端口 | 此版 API 无监听端口字段 | sed `AdGuardHome.yaml` 的 `dns.port` 后 `docker restart` |
| 切 53 端口失败/被占 | dnsmasq 还占着 53 | 先迁 dnsmasq 到 5354，再重启 AGH |
| AGH 加清单后 API 无响应 | 后台下载编译规则 | 等约 10 秒重查 |
| **"内存卡初始化失败"+ 重启后 SSH/OpenClash/AGH/Docker 全消失但 LuCI/DNS 活** | **TF 卡硬件级损坏**（2026-09-15 B 机实测）：内核仍报 `mmc0: new high speed SDHC card` 且无 I/O error，但 /proc/partitions 无分区、fdisk 报无分区表、全卡扇区为高熵乱码、**dd 写入数据读不回（md5 对账 3 轮全失败且每轮读回值不同）** | 定性三板斧：① `dd bs=512 count=1 skip=N \| hexdump -C` 抽 MBR/p1/p2 superblock/尾扇区（本机无 base64/od，只能 hexdump）；② dd 随机 pattern 写尾部 scratch → sync → 读回 md5 对账 ×3；③ 确认 /overlay 丢失（opkg 只剩厂商包、docker/openclash 目录消失）。写读失败即判死，**不要浪费时间重建分区**；换卡（槽支持 1GB-2TB）后用 setup_docker_c2000u.py + phase 脚本重建。前兆：路由器"半死"（部分服务消失、LuCI/DNS 存活） |
| DNS 全断 | 链路某段端口/顺序错 | 按 playbook G 四段排查；回滚备份 `/root/bak-dhcp-*.conf` + `AdGuardHome.yaml.bak-53` |
| 加大清单后设备卡/服务被 OOM | 493MB 内存不足 | 内存 <30MB 可用时只加轻量清单（秋风 902 条 < ADgk 9k < AdRules 19 万） |
| paramiko 通道读超时挂死 | 远端 curl 无限等待 | curl 加 `-m N` |
| 回滚后补丁全丢 | 按字母序取了最老备份 | 按时间戳倒序 + 内容校验选最新完整备份 |
| 网易云解锁失效 | AGH 接管后 UNM 解析被广告链路影响 | AGH 域名定向 `[/music.163.com/]5354` 保活 |
| 外接 USB 盘看不到 /dev/sda | 缺 kmod-usb-storage | `opkg install kmod-usb-storage block-mount`（纯增量不动数据） |
| exFAT U 盘无法挂载 | 内核无 exfat 驱动且源里无 fuse 版 | 免格式无解；NTFS/FAT32 可免格式直挂，ext4 需格式化 |
| 公共 subconverter「No nodes were found」 | 上游订阅 Cloudflare 挡转换器的 UA/IP（本机 curl 默认 UA 403 的源，转换器必拉不到） | 别依赖公共转换器合并订阅；改用 mihomo proxy-providers（可带 `header` 自定义 UA）或直接切换主配置 |
| dropbear exec 超长命令（>~10KB）被 reset | heredoc 内联 60KB 内容触发连接重置 | 分块传输：按 4-6KB 行边界切块，`cat >> file << 'EOF标签'` 逐块追加，末尾 md5sum 校验 |
| 固件无 base64/openssl/xxd 解码工具 | 此精简固件 busybox 未编入 | 传原始文本（YAML 等）走分块 heredoc；PC 侧 hashlib.md5 与路由器 md5sum 对账 |
| **能力测试"假失败"，据此误判设备不支持** | **busybox ash 不支持 `{a,b,c}` 花括号展开**：`mkdir -p /x/{l,u,w,m}` 只建了一个名叫 `{l,u,w,m}` 的目录，随后 `mount` 报 ENOENT，看上去像"内核不支持 overlay" | 设备侧脚本**一律分开写路径参数**，不用花括号；得到否定结论前先自查命令语法（本次 C2000 U 就因此把 overlay 误判为不可用，分开写后 `RC:0`） |
| 设备侧排查工具缺失 | 该精简固件**无 `jq` / `timeout` / `python3` / `od` / `nft`**；`sort` 不支持 `-h`；**`date` 不支持 `%N`**（微秒计时会拿到字面 `%N`） | 用 `lua`、`awk`、`md5sum`、`cut` 替代；十六进制查字节用 `head -c N file \| od -c`（**od 也没有**）→ 改用 PC 侧 Python 读字节；**计时放 PC 侧做**（`time.time()` 包住 exec_command） |
| **paramiko `open_sftp()` 报 `SSHException: EOF during negotiation`** | 官方精简固件**根本没装 sftp-server 子系统**（`/usr/libexec/sftp-server` 不存在），不是权限/配置问题 | **别用 SFTP**。改用 `scripts/rtr_lib.py`：文本走 heredoc + md5 对账、**二进制走 `printf '\\NNN\\NNN...'`**（固件无 base64/openssl/xxd，这是唯一通道；实测 256B/900B 全字节精确）。单条命令 <10KB，超长降级分块 append |
| **大文件（ipk/内核镜像）投递** | printf 八进制通道传 10MB 不可行；设备也拉不到 PC 上的 HTTP（Windows 防火墙拦 LAN 入站） | **SSH 反向端口转发**：`scripts/revtunnel_put.py`（paramiko `request_port_forward` + PC 内置 http.server + 设备 curl 自拉 + md5 对账），实测 10.2MB/1.6s。见 `references/c2000u-openclash.md` §1 |
| **装本地 stub ipk 却报出 stub 里根本没有的依赖** | **opkg 遇到 feed 里同名包时优先解析 feed 候选，忽略你本地文件里的 control**（本次 `btrfs-progs` 报 `cannot find dependency kmod-fs-btrfs`，那是 feed 版的依赖） | **装 stub 前临时移走 feed 索引**：`mv /var/opkg-lists /var/opkg-lists.off` → `opkg install --force-reinstall 本地.ipk` → `rm -rf /var/opkg-lists; mv /var/opkg-lists.off /var/opkg-lists` |
| **写了 `/etc/docker/daemon.json` 却不生效（仍是 vfs、bridge 照旧）** | init 脚本每次启动都 `rm -rf /tmp/dockerd` 后用 UCI 重新生成 daemon.json，dockerd 实际读的是 **`/tmp/dockerd/daemon.json`**；且 **UCI 生成器只支持 data-root / log-level / iptables / bip / registry-mirrors / hosts / dns / ipv6 / ip / fixed-cidr，没有 `storage-driver` 和 `bridge`** | **唯一正路**：`uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json' && uci commit dockerd`。init 见到该项就会 `ln -s` 你的文件到 `/tmp/dockerd/daemon.json`，全文由你掌控 |
| 正则提取 JS 字符串一个都匹配不上 | minified JS 的 `\"` 转义让配对错位并传播到文件末尾（27 处转义毁掉 7 万个串） | 用 `"([^"\\]*(?:\\.[^"\\]*)*)"`；注意空串时 `group(1) or group(2)` 会取到 None |
| 路由器 curl 对部分境外域名间歇 000 | 经 fake-ip 代理链瞬态抖动，verbose 重试即 200 | 重试 2-4 次再下结论；测试脚本内建 for 循环 |
| **「只有境外网站打不开」，国内正常** | 兜底规则 `MATCH,<订阅的代理组>`（本例 `MATCH,宝贝云`）指向的那个组**当前选中了半死节点**。ocspeed 每 30 分钟全量测速，若出现「决赛全部未通过」会**按初赛排名兜底**选一个其实不通的节点 → 全网境外挂。**注意：跟 `GLOBAL` 无关** —— `GLOBAL` 是 mihomo 内核内置组（yaml 里搜不到），规则没引用它，改它没用 | **免 SSH 定位**：mihomo API `http://192.168.66.1:9090`，头 `Authorization: Bearer <dashboard 密码>` → `GET /proxies/宝贝云` 看 `now`；`GET /proxies/<名>/delay?url=http://www.gstatic.com/generate_204&timeout=5000` 现测。**治本**：启用 ocspeed 自带的故障转移 —— `uci set ocspeed.main.failover_enable='1'; uci set ocspeed.main.backup_enable='1'; uci commit ocspeed; /usr/libexec/openclash-helper/speedswitch.sh enable`（**没有 cron 子命令**，必须用 `enable` 才会 `cron_apply`）。见 `references/c2000u-openclash.md` §9 |
| **ocspeed（自动测速）整个消失：`/usr/libexec/openclash-helper/` 没了、crontab 只剩 logrotate** | ocspeed **不是 opkg 包**，是自建插件：helper 脚本 + `/usr/lib/lua/luci/controller/ocspeed.lua` + `view/ocspeed.htm` + `/etc/config/ocspeed` **全部跟着 overlay 走** → 重建 TF 卡 / 换卡 / 扩容（16G 那次实测）后一样不剩，且没有任何包能装回来 | 一行恢复：`SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh`（可加 `OCS_GROUP=宝贝云 OCS_RUN=1`）。源码在 nros-panel 仓库 `ocspeed/` 五件套，设备另有备份 `/mnt/storage/data/ocspeed-backup/`。**上传务必按行分块 heredoc（≤2.5KB/块）** —— 36KB 脚本整块一次会把 SSH 通道撑爆（表现为脚本直接退 1，无报错）。缺的 `view/nodetest.htm` 备份里本来就没有，需照 ocspeed.htm 风格补一个 |
| **`docker run` 容器起不来：`failed to add the host (veth...) <=> sandbox (veth...) pair interfaces: operation not supported`** | **内核没有 veth**（`lsmod \| grep -c '^veth'` = 0，厂商没编译，`kmod-veth` 还是空包）。默认桥接网络一定会走到建 veth pair 这一步然后失败 | **所有容器一律加 `--network host`**（实测 hello-world 加完立刻成功）。这是内核能力缺失，**改 `daemon.json` / UCI 都没用**，别浪费时间调 bridge 配置 |
| **误判「出网是正常的」** | fake-ip + TUN 会本地接管：`ping` 外网 0% 丢包、TCP 连外网 IP **0.00s 就成功**都可能是假象 | 必须发**真 HTTP/HTTPS 请求**看响应码才算数；据此判断"通/断" |
| **git push 报 `Connection was reset` / `Failed to connect to github.com port 443`** | **不是 GitHub 挂了，是本机 DNS 被污染**：`github.com` 解析到 `20.205.243.166`、`ssh.github.com` 到 `20.205.243.160`，这两个 IP 的 443 被阻断；而 `140.82.113.3` / `140.82.114.3` / `140.82.116.3` / `20.27.177.113` / `20.200.245.247` / `4.237.22.38` / `20.248.137.48` / `20.205.243.168` 实测 **200 / 0.5s 全通** | 用 `python scripts/gh_proxy_push.py push <仓库目录>`：起一个只监听 127.0.0.1 的 CONNECT 代理，把 `*.github.com:443` 强制转到可用 IP，git 走它 → **TLS SNI 仍是 github.com，证书正常**。**绝不要用 `url.insteadOf` 换成 IP**（SNI 变 IP 必然证书失败）。自检：`curl --resolve github.com:443:140.82.113.3 https://github.com` |
| **外接 USB 盘看不到 `/dev/sda`（C2000 U 实测）** | ⚠️ 与 A 机不同：C2000 U 的 `opkg status` 里 **`kmod-usb-storage` 是"装了但没内容"** —— `opkg files` 只列出 `/etc/modules-boot.d/usb-storage` + `/etc/modules.d/usb-storage` 两个 modprobe 配置，**`.ko` 根本不存在**（`/lib/modules/5.4.281/` 191 个模块里没有它，`modinfo usb-storage` 空）。所以「已注册」≠「可用」 | 别据此认为 B 机支持外接盘 → **NAS 类插件（ksmbd/aria2/minidlna/NFS）在 C2000 U 上失去前提**。要修得先找到 5.4.281 厂商源的 kmod（官方 21.02.7 源的 vermagic 不匹配，装了也加载不了） |
| **C2000 U 能不能跑 OpenClash 的 TPROXY / TUN** | 实测**都能**：`CONFIG_TUN=m` + `tun.ko` → `modprobe tun` OK、`/dev/net/tun` 在；`CONFIG_NETFILTER_XT_TARGET_TPROXY=m` + `nf_tproxy_ipv4/ipv6.ko` → `modprobe xt_TPROXY` OK；`xt_socket`/`nf_socket_ipv4,6`/`nf_nat`/`xt_MASQUERADE`/`iptable_nat`/`ip_set`/`xt_set` 全已加载 | **别因为"没有 veth"就以为代理也跑不了** —— veth 只影响 Docker 桥接，与 TPROXY/TUN 无关。两条路都可用 |
| **`/lib/modules/<ver>/` 里没有 `modules.dep`** | C2000 U 实测缺 `modules.dep`，但 `modprobe` 仍能按名加载（kernel 自动按 name 找） | 不必紧张；`modinfo <name>` 是判断"模块到底在不在"的最权威手段 |
| **`gh_proxy_push.py` 输出 `MATCH: True` 但远端其实没更新** | **该脚本只做 `git push/pull origin <branch>`，从不 `git add` / `git commit`**。改动没进版本库时，本地 HEAD 与远端自然还是同一个老 commit，于是显示"一致"——看起来像推送成功，实际什么都没上去 | **先 `git add -A && git commit -m "..."` 再调 `gh_proxy_push.py push <目录> <分支>`**；推完用 `git rev-parse HEAD` 对比推之前的哈希，**哈希没变就是没推上去** |
| **新建仓库/直推 GitHub：`git push` 静默 `rc=128` 且 stderr 全空** | `github.com` 解析被污染时，git 自己的连接会直接失败并给出**空错误**（`git ls-remote` 偶发成功、多数时候 128），极难判断。**但用 `gh_proxy_push.py`（本地 CONNECT 代理把 `github.com:443` 指到可用 IP）必定成功**，包括给**全新空仓库**推第一个 commit | 推任何 GitHub 仓库（含新建的）一律走 `gh_proxy_push.py push <目录> <分支>`；只在它失败时才排查别的。核验用 `gh api repos/<owner>/<repo>/commits/main --jq '.sha'` |
| **以为本机没装 `gh`（GitHub CLI）** | **`gh.exe` 在 `C:\tmp\bin\gh.exe`，只是没进 PATH**，而且已登录（`h910056902`，token scope 含 `repo`），并被配成 git 的 github.com credential helper（`git config --global --list` 可见） | 建仓：`C:\tmp\bin\gh.exe repo create <名字> --private --description "..."`（`--confirm` 已废弃，可省略，警告不影响创建）；查远端：`gh api repos/<owner>/<repo>/...`；取 token：`gh auth token` |
| **从路由器往 PC 取文件（设备无 SFTP、无 base64/xxd）** | 拷到 uhttpd 文档根 `/www/<tmpdir>/`，PC 用 `http://192.168.66.1/<tmpdir>/...` 逐个 `urlopen` 拉取，拉完 `rm -rf`。比 `printf '\NNN'` 快几个数量级，目录/二进制都适用 | 文件名可能含空格（如 `signal_small_no service.png`），**必须 `urllib.parse.quote(url, safe=":/?&=%")`**；源站对 PC 直连返回 403 时，改在路由器上 `curl` 下来再走这条通道 |
| **La 源站 `la.2014816.xyz` 对 PC 侧 urllib 返回 403** | 站点挡非路由器 UA/来源；路由器上 `curl -k -sL` 同样是这个域名却 200 | 要抓源站文件：**在路由器上 `curl` 到 `/www/...`，再由 PC 用 HTTP 拉** |
| **`/etc/init.d/firewall reload` 之后 AdGuardHome 被旁路（广告过滤静默失效，但 DNS 照常通）** | OpenClash 的 53 劫持目标 `DNSPORT=$(uci -q get dhcp.@dnsmasq[0].port)`（/etc/init.d/openclash 第 2177 行）。阶段 5 把 dnsmasq 挪到 5354、AGH 接管 53 后，**每次防火墙/openclash 重载都会把劫持重新指向 5354**，于是 LAN 所有 53 流量（含发给 192.168.66.1:53 的）都被 REDIRECT 到 dnsmasq → clash，**AGH 一个查询都收不到**。症状极隐蔽：DNS 正常、上网正常，只是过滤没了 | **用 OpenClash 官方钩子覆盖**：`/etc/openclash/custom/openclash_custom_firewall_rules.sh`（该脚本在 OpenClash 自身规则**之后**执行，注释里写明了）里用 `iptables -t nat -I PREROUTING -p udp --dport 53 -j REDIRECT --to-ports 53` 插到官方规则前面。校验：`iptables -t nat -S PREROUTING \| grep 'dport 53'`，KP 规则行号必须小于 OpenClash 的。改完 `chmod +x` 并 `/etc/init.d/openclash reload "firewall"` |
| **单次 HTTPS 失败就判"境外又不通了"** | URLTest（延迟最低）组在自动换节点的瞬间会有一次 `SSLEOFError / UNEXPECTED_EOF_WHILE_READING`（约 0.3-0.5s 即返回），几秒后自动恢复 | **连测 3 次**再下结论；判定"通"要看 `generate_204` 是否 204、`youtube` 是否 200。真故障会连续失败且 `/connections` 里 chain 是 `DIRECT` |
| **数"多少个节点超时"数错** | 订阅里混着 `无法使用请升级客户端` / `套餐到期：2026-09-15` / `距离下次重置剩余：7 天` 这类**广告/信息条目，被 mihomo 当节点列进 `all`**，它们永远测不通 | 统计节点健康度时先剔除这些非节点条目；看到它们出现在延迟榜里属正常 |
| **误判 git push 失败** | **PowerShell 调用 git 时，git 的正常进度输出（`To https://...`、`x..y main -> main`）走 stderr，PowerShell 渲染成 `NativeCommandError` 红色异常** |  **看 `git ls-remote origin refs/heads/main` 与 `git rev-parse HEAD` 是否一致，或看 `$LASTEXITCODE`；绝不用 stderr 有无内容判断。Bash 工具下 git 输出会被吞（EXIT=0 但日志空），需改用 Python subprocess** |
| **误判「提交信息/文件存成了乱码」** | PowerShell 控制台回显 UTF-8 中文会显示成 `鏂板`/`杩涘害` 之类，**但仓库数据其实是正确的 UTF-8** | 核对编码**只能走字节层**：Python `subprocess` 跑 `git cat-file commit HEAD`，看 hex（`e6 96 b0` = "新"）。**绝不据控制台回显下结论** |
| **往路由器传大文件（几百 KB ~ 几 MB、多文件）走 SSH 分块，慢到不可用** | 无 SFTP、无 base64，SSH 单条命令还有 ~8KB 上限，167 文件 / 2.7MB 要几百条命令、还可能被 reset | **反向 HTTP**：PC 起临时 `http.server`，路由器 `curl -o` 拉。实测 2.86MB 秒传。两个坑：① `SimpleHTTPRequestHandler` **必须传 `directory=`**，否则服务的是进程 CWD 会 404；② 若路由器 curl 拿不到 200，多半是 Windows 防火墙挡入站，加规则 `New-NetFirewallRule -Direction Inbound -LocalPort <port> -Protocol TCP -Action Allow`。可复用实现：`scripts/restore_nrwebui.py`（`--check` 只测连通性） |
| **用 heredoc 往路由器写大文件，SSH 通道直接 EOFError** | **单条 `exec_command` 超过约 8KB 会被 dropbear reset**（实测 10KB 的 api.sh、12KB 的 app.js 必挂；5KB 的 css 没事）。`rtr_lib.put_text_verified` 只在 **md5 不一致**时才降级分块，遇到异常会直接抛出，不会自动降级 | 自己按行切成 **≤3000 字节**的小块，第一块 `cat > f <<'TAG'`，后续 `cat >> f <<'TAG'`。**两个细节**：① body **不要**再补尾换行（命令里的 `\n` 已经补了，否则每块之间多一个空行，md5 永远对不上）；② 校验基准要先把本地文本归一化成"以换行结尾"再算 md5。可复用实现见 `scripts/deploy_kpwebui.py` 的 `_chunk_write()`。**2026-09-19 更新：rtr_lib 已修复**——`put_text_verified` 现在捕获单发阶段的连接重置异常（ConnectionResetError 10054）并自动降级分块，ocspeed v1.0 部署 112KB 文件实测命中此坑 |
| **CGI 里 `printf` 拆成多条，前半段字段全空、后半段重复打印** | POSIX printf 的参数只属于**它那一条**。`printf '{"a":%s,'` 后面没参数 → `%s` 打成空；所有 18 个参数挂在最后一条上 → 格式串被重复使用 | 每个 `printf` 自带它要用到的参数，别图省事把参数统一甩到最后一条 |
| **CGI 拼 JSON 数组时逗号全丢了，输出 `{...}{...}`** | 管道里的 `while` 是**子 shell**，`first=0` 改不回父 shell，每次迭代看到的 `$first` 都是 1 | 子 shell 里把对象**逐行写临时文件**，父 shell 用 `awk 'NF{c++; if(c>1) printf ","; printf "%s", $0}' "$TMPF"` 拼 |
| **busybox awk 报 `Call to undefined function`** | v1.33.2 的 awk 对三元表达式 + 嵌套 for/if 支持不全 | 解析 `ls -la` 别用复杂 awk，改用纯 shell：`ls -la \| while read -r perm lk own grp sz mo d tm name`。busybox `ls -la` 字段固定：1权限 2链接数 3属主 4属组 5大小 6月 7日 8时间或年 9+名称 |
| **`/etc/kp_store/plugins.json` 解析只拿到最后一条** | 它是**跨行 pretty JSON**（每个字段一行），按行 grep 一行只有一个字段，贪婪 `.*` 只会命中最后一个 | 先 `tr -d '\n'` 压平，再 `tr '{' '\n'` 切开，每个对象一行后再逐字段提取。`installed.list` 则是 `\|` 分隔：`id\|name\|pkg\|ver\|time\|route\|source\|des\|url` |
| **iptables `-S` 取 comment 多出引号（`"OpenClash`）** | `-m comment --comment "OpenClash"` 里 comment 值带引号，`s/.*comment \([^ ]*\).*/\1/p` 会把前引号一起抓进来 | 用 `s/.*--comment "\([^"]*\)".*/\1/p` |
| **想在路由器上做任何 WebUI，先排除 uhttpd Lua** | 固件**没有** `uhttpd_lua.so`（`Could not open plugin uhttpd_lua.so`），任何 `uhttpd_*.so` 都不存在；`base64` applet 也没有 | 可行路线：**第二个 uhttpd 实例 + CGI(ash)**，`uhttpd -f -p <lan_ip>:<port> -h <docroot> -x /cgi`。CGI 环境变量 `PATH_INFO`/`QUERY_STRING`/`REQUEST_METHOD`/`CONTENT_LENGTH` 都可用；上传走 stdin 原始字节 `cat > file`。已落地为 kp-webui，见 `references/kpwebui.md` |
| **把自建服务塞进鲲鹏原生商店（出现在厂商 UI 里）** | 商店数据来源两个文件：`/etc/kp_store/plugins.json`（清单，pretty JSON）和 `/etc/kp_store/installed.list`（已装，`\|` 分隔） | 往清单 `plugins` 数组追加条目（字段 `id/name/pkg/route/source/des/open_url`；**外链服务把 URL 同时写进 `route` 和 `open_url`**，照 `dpanel` 那条抄），然后 `kp-store-register <pkg>`（按 `pkg` 在清单里找，找不到报 `pkg not in manifest`）。改完用 `lua -e 'require "cjson"'` 验 JSON 没写坏 |
| 写文件多出 BOM（回显为 `锘`） | Windows PowerShell 5.1 的 `Out-File -Encoding utf8` / `Set-Content -Encoding UTF8` **会写 BOM** | 用 `[System.IO.File]::WriteAllText($p,$t,New-Object System.Text.UTF8Encoding($false))`，或改用 Python `open(p,"w",encoding="utf-8")` |
| **`192.168.66.1:10086` 页面全 404 但 API 正常** | 第三方 WebUI（`nr_webui`）后端活着、前端目录 `/root/webui/` 为空。**根因不是资源源缺货**——`la.2014816.xyz/webui/` 只放 `nradio.sh` 和后端二进制，前端由 `nr_webui` 自己从**另一台明文 HTTP:80 的国内 OTA 服务器**拉（`http://%s/%s?devtype=%s&ver=%d&device_code=%s&ver_s=%s`）。失败只因 `nradio.sh` 里 `./nr_webui downloads` **没有任何错误检查**，下载挂了仍打印"webui全部部署完成" | **直接补跑 `cd /root && ./nr_webui downloads`**（一次成功，实测拉到前端 V2.0.15 / 2.7MB / 167 文件，后端顺带自更新 229840→233944 B）。**不要**去 `la.2014816.xyz` 找 zip（那里 404 是正常的，从来没放过）。判后端存活：`curl /api/islogin` → 200。完整档案见 `references/nr-webui-service.md` |
| **以为 C2000 U 不支持 nr_webui 的短信功能** | 工具打的 `/cgi-bin/luci/nradio/cellular/sms/send` **在 C2000 U 上存在**，只是注册在 `controller/nradio_adv/sms.lua`（挂到 `nradio/cellular/sms/*` 路径下），不是 `controller/nradio/cellular.lua`（该文件确实没有）。配套 `atsd -i cpe/cpe1`、`smsd -i cpe/cpe1` 实测都在跑 | 判断 LuCI 端点存不存在，**要 grep 整个 `controller/` 目录的 `entry({...})`**，不能只看文件名 |
| **单台手机连 WiFi 显示"不可上网"，电脑等其他设备正常** | 链路健康时优先怀疑两个：① **LAN 下发无出口的 ULA IPv6**——WAN 无公网 v6（只有 link-local）时 odhcpd 仍下发 `fd8f::` ULA + RA other-config，Android 部分请求优先走 v6 黑洞 → captive portal 检测失败；Windows 不吃这套所以电脑没事。② 手机检测连接挂死——mihomo `/connections` 里该设备 80 端口连接 dl=0 挂起是标志（443 有流量 = 手机其实有网，只是"不可上网"标志坏了） | 逐环实测：`nslookup` 各端口、路由器本机 `curl -H 'Host: <检测域名>' http://<检测IP>/generate_204` 得 204 说明服务器与路径正常；`ip -6 route` 无 default + WAN 无 GUA 即 v6 黑洞实锤。修复：`uci set dhcp.lan.ra='disable'; uci set dhcp.lan.dhcpv6='disable'; uci commit dhcp; /etc/init.d/odhcpd restart`（先备份 `uci show dhcp`），手机忘网重连/关随机 MAC。实测 B 机 2026-09-11：检测服务器 204 仅 0.025s、DNS 8/8 稳定，纯手机端标志问题 |
| **busybox 巡检误报"全部服务 NOT RUNNING"** | 此固件 busybox **不支持 `pgrep -c`**（也不支持 `-c` 计数语义），命令失败返回 0 → 判活脚本全灭；连 `dockerd` 这种明明在跑的也报"NOT running"（2026-09-13 B 机巡检实测，dropbear/uhttpd/dnsmasq/dockerd/1panel 全误报） | 判活一律用 `pidof <名> >/dev/null && echo ok`（busybox 自带）；复杂场景用 `ps w \| grep '[]名' \| wc -l`。固化版本：`scripts/healthcheck_c2000u.py`（B 机全量只读巡检 13 板块 + `healthcheck_c2000u_r2.py` 6 板块复核） |
| **B 机（C2000 U）DNS 链路实况（2026-09-13 巡检）** | B 机**没有 AGH**（docker 只有 dpanel 容器），53 = dnsmasq 直接监听 → clash:7874，fake-ip 生效；`KP-DNS-Hijack-to-AGH` iptables 规则虽在（都 REDIRECT 到 53），但钩子脚本有守卫（`grep AdGuardHome` 不命中就不插），属无害残留；UCI 无线配置（psk2 的 @NRadio-* SSID）与实际广播（2G_OPEN_0/5G_OPEN_0 明文开放）不一致，MTK 驱动层自管 SSID | 给 B 机做 DNS/无线排查时**别套用 A 机 AGH 架构**；B 机 WiFi 明文开放是厂商驱动层行为，改 UCI wireless 无效，要走厂商 App/nr_webui |
| **1Panel 装应用卡在 `compose up` 无报错（B 机 2026-09-14）** | OpenWrt 源的 `docker-compose` 是 **python 版 1.28.2**，解析不了 1Panel 生成的 compose（`${VAR:+--requirepass "..."}` 这类嵌套引号插值，v2 语法）→ 语法解析直接失败、面板无提示 | 换官方静态二进制 **compose v2**：`wget -O /usr/bin/docker-compose https://github.com/docker/compose/releases/download/v2.32.1/docker-compose-linux-aarch64 && chmod +x`（原版改名 `docker-compose-py1.28`）。**官方 1Panel install.sh 的 `configure_accelerator` 会整体覆盖 daemon.json，别执行** |
| **1Panel 应用装完容器起不来：`failed to add the host (veth) <=> sandbox (veth) pair interfaces`** | 内核无 VETH（见设备档案），而 1Panel 应用的 compose 一律用外部 bridge 网络 `1panel-network`。`docker network create -d host` 也被拒（docker 只允许一个预定义 host 网络），改网络不可行 | 改 compose：删 `networks:`/`ports:` 段 + 每个服务加 `network_mode: host`。幂等脚本 `kp-docker1panel/1panel-hostnet-fix.sh`（bridge→host + Redis 兼容参数注入）。**代价**：host 下端口直接占宿主机，同端口不能复用；手工 up 的容器不出现在面板「已安装应用」，但在「容器」页可见 |
| **Docker 自检「通过」但镜像其实拉不下来** | `docker info` 通只代表守护进程活着；本机直连 `registry-1.docker.io` 实测 15s 无响应（B 机 2026-09-15），加速站也有挂的时候。而 `docker run hello-world` **必须带 `--network host`** —— 默认 bridge 会在建 veth pair 时直接失败（内核无 veth），看起来像"镜像坏了" | 冒烟测试按「`docker pull` → `docker run --rm --network host`」两步做；拉了不动就**逐个加速镜像单独试**（清 `dockerd.globals.registry_mirrors` → `uci add_list` 单个 → `commit` → `restart dockerd` → 再拉），把能用的那个留在 UCI 里。另外 `dockerd` **只认 UCI** `/etc/config/dockerd`（init 渲染到 `/tmp/dockerd/daemon.json`），写 `/etc/docker/daemon.json` 完全没人读。实现见仓库 `h910056902/nros-panel` 的 `docker_smoke()` |
| **自建插件（如 ocspeed）在 overlay 重建后整目录消失，且 opkg 装不回来** | 它不在任何 opkg 源里 —— 代码全在 `/usr/libexec/`、`/usr/lib/lua/luci/`、`/etc/config/` 这些跟 overlay 走的地方。重建 TF 卡 / 换卡 / `REBUILD=1` 扩容后一起没了，`crontab` 里只剩系统的 logrotate，`opkg install` 也查无此包 | ① 把源码收进自己的仓库（`nros-panel/ocspeed/`），恢复流程里显式装一遍；② **同时在数据盘留一份**（`/mnt/storage/data/ocspeed-backup/`）—— 真断网时能原地 `cp` 回来；③ cron 由插件自己的 `enable` 重建，别手工改 `/etc/crontabs/root`（下次 enable 会覆盖）。ocspeed 完整恢复见 `references/one-command-restore.md` |
| **Redis 8.x 容器无限重启（B 机 5.4 内核）** | ARM64-COW-BUG 自检失败直接退出；该检测早于配置文件加载，**写进 redis.conf 无效** | 只能命令行传：`redis-server /etc/redis/redis.conf --ignore-warnings ARM64-COW-BUG`（**必须放在 conf 之后**，该指令是可变参数、会吃掉后面的内容）；另建议 `sysctl -w vm.overcommit_memory=1`。**sed 注入时千万别用 `g`**，否则会污染 volumes 挂载行里的同一路径 |
| **Jellyfin 启动报 `insufficient free space. Available: 1.6GiB, Required: 2GiB`** | Jellyfin 启动自检硬门槛：/config 所在分区可用空间必须 ≥2GiB | 把 config/cache 挂到别的分区绕过（`overlay` 有 3.1G 可用即可）：`-v /overlay/jellyfin/config:/config -v /overlay/jellyfin/cache:/cache`。但 RSS 218MB + Kestrel 线程池饥饿，992MB 机器实用价值低 |
| **filebrowser 容器 `open /database.db: is a directory` / `permission denied`** | ① 把宿主机**目录**挂成了 db 文件路径；② 镜像非 root 运行，宿主机目录权限不够 | 挂目录 + 指定文件：`-v <dir>:/database ... --database /database/filebrowser.db`，并 `chmod -R 777 <dir>`。另外它**默认监听 127.0.0.1**，host 网络下必须加 `--address 0.0.0.0` 才能从 LAN 访问（filebrowser 官方 2026-09-01 已归档停更） |
| **本机技能仓库 `.git` 离奇损坏：refs/ 目录整体消失、新 commit 对象丢失（2026-09-13 实测）** | push 成功创建 commit 后，refs/ 与该 commit 的 objects 在会话进行中被清（疑似 360/火绒对 git 内部文件的实时清除；本机有 .ps1 被静默删除的先例）。症状：`git rev-parse` 报 not a git repository（refs/ 缺失时）或 `invalid object ... for 'xxx'`（index 引用的 blob 丢失）、`git pull` 协商报 bad object | 修复流程（实测 5 分钟内可完成）：① `gh api repos/<o>/<r>/commits/main --jq .sha` 拿远端 sha；② 手写 `refs/heads/main=远端sha` 若引发 fetch 协商 bad object 则**删掉该 ref 文件**；③ 复用 `gh_proxy_push.py` 的 CONNECT 代理 fetch；④ **删除 .git/index 强制 add -A 全量重建 blob**（index 缓存的旧 blob 已丢，add 因"内容没变"不会重写）；⑤ commit → push → ls-remote 校验，不匹配就循环重试（每轮重删 index）。可复用实现：工作区 `git_repair3.py` 模式 |

| **出厂 opkg 源「全部」失效（2026-09-15 实测，纠正旧结论）** | 旧结论「只有 `packages`/`routing` 404、base/core 还能用」**是错的**。6 个源（base / packages / routing / mtk_openwrt_feed / openmptcprouter + core 的 `targets/mediatek/mt7987`）**全返回 `000`** —— 不是 404，是连接建不起来：DNS 解析正常（`downloads.openwrt.org → 146.75.46.132`，Fastly）但 `conn=0.000000s`，v4 / v6 / `--resolve` 固定 IP 全是 000。**后果是连 `bash` 都装不上** | **整体重写 distfeeds**：base/packages/routing 全指向阿里云 `21.02.7`（四个子源实测全 200，含 docker/dockerd/containerd/docker-compose/runc）。`core` 与 target 源**故意不留**（官方没有 mt7987 target，留着只会让 `opkg update` 卡超时），缺 kmod 依赖统一 `--force-depends`。备份 `distfeeds.conf.kp-bak`，只在检测到 `21.02-SNAPSHOT` 时才重写（幂等） |
| **设备上 curl 拉 raw.githubusercontent.com 必失败，wget 却可以** | 同一地址背后是两条不同的网络栈：`curl -fsSL` → **000**，`wget -qO` → **200**。脚本若 curl 优先，就白白浪费一次源切换；重启续跑段更会直接断掉 | 下载函数写成 **curl 失败立刻换 wget 重试同一 URL**，再考虑换镜像源（ghfast / gh-proxy 实测均 200）。别用单一工具的一次失败下结论 |
| **重启后 `/etc/rc.local` 没人执行 / 写了续跑钩子却丢了** | ① 此固件**根本没有 `/etc/init.d/rc.local`**，执行 rc.local 的是 **`/etc/init.d/done`（`/etc/rc.d/S95done`）**，其 `boot()` 里 `[ -f /etc/rc.local ] && sh /etc/rc.local`；② **`S95done` 来自只读的 `/rom`**，所以新 overlay 再空也继承这个钩子；③ 但写在**当前** overlay 里的 rc.local 会随重启一起消失 | 要跨重启续跑，就把 rc.local **预置进新卡 p1 的 overlay upper 层**：`mount p1 → mkdir -p upper/etc work → 写 upper/etc/rc.local → umount`。注意 heredoc `<<EOF`（不带引号）会在**生成时**展开变量：`$RAW` 要展开、运行时循环变量必须写成 `\$u` |

## 完成后的收尾（每次都要）

1. grep/读回验证全部改动
2. 内存复核 `free -k`，对比操作前
3. 向用户报告：改了什么、备份在哪、如何回滚
