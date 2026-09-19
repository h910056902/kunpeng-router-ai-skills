# kunpeng-router-ai-skills

> **AI Agent 技能包**：鲲鹏无限 / NRadio 鲲鹏 C2000 Max / C2000 U（MediaTek MT7987 · OpenWrt 21.02.7 · 内核 5.4.281）路由器的深度定制与调优经验。
>
> 全部结论来自**真机实测**，不是文档抄录。每一条都写清了「为什么」和「怎么验证」。

## 这是什么

一个可直接被 AI Agent 加载的 **skill**（技能包）：把路由器改造成「能跑 Docker、能装 1Panel、能全网去广告、能按需分流」的完整打通过程，连同**踩过的每一个坑**，整理成可复用的 playbook。

适配 WorkBuddy / Claude Code 等支持 skills 目录的 Agent（`SKILL.md` + `references/` + `scripts/` 结构）。

**核心价值在「坑」而不在「成功路径」** —— 这台机器遇到的大部分障碍都不是配置错误，而是**内核能力缺失**（没有 veth）、**厂商固件的反直觉行为**（UCI 才是唯一配置入口）、**工具链残缺**（无 SFTP / 无 base64 / busybox 缺 applet）。这类问题在搜索里查不到，只能实测。

## ⚠️ 安全说明（先读）

- 仓库内容**已脱敏**：所有密码、面板入口码、dashboard secret 均为占位符，凭据一律走环境变量（`ROUTER_PW`、`AGH_PASS` 等）。
- 文中保留内网地址 `192.168.66.1`（RFC1918 私有地址）与设备规格，这是技能触发词和判断依据，不是敏感信息。
- 所有操作针对**自有设备**。路由器改装有变砖风险，动手前请自行备份。

## 机型支持

| 机型 | 说明 |
|---|---|
| **C2000 U**（产品名 `C2000-798`，板型 `HC-WT9500`） | 992MB 内存 · TF 卡 7.5G→16G · **Docker 实装成功，`storage-driver = overlay2`** |
| **C2000 Max** | 493MB 内存 · eMMC 27.8G · Docker 可跑但**只能 `vfs`**（overlay-on-overlay 被内核拒） |

两者同 SoC 家族（MT7987 / aarch64 / 内核 5.4.281），**共同硬约束：内核没有 veth → 容器只能用 host 网络，不能端口映射**。

同为 MT798x + OpenWrt 21.x 的机器，方法基本通用。

## 打通了什么

- **在线应用商店增强** —— 不刷机把可选应用从 7 个扩到 147 个，安装显示实时百分比，把 Docker 容器（AdGuard Home 等）注册进商店卡片直接「打开」
- **Docker 落地** —— 官方内核缺模块且源里无匹配包（opkg 在「选候选」阶段就拒，`--force-depends` 无效）→ 用 **stub ipk 闭合依赖链**；C2000 U 拿到 `overlay2`
- **1Panel + 容器** —— 1Panel v1.10 原生装成（端口 10090）；**无 veth 内核上让 1Panel 应用「默认」跑 host 网络**：换掉 `/usr/bin/docker-compose` 为 wrapper，调用前幂等 host 化 compose（真件保留为 `.real`，一条命令可回滚）
- **全网去广告** —— AdGuard Home 接管全屋 DNS(:53) → OpenClash 分流 → 上游；7 个清单 50 万+ 条规则
- **OpenClash 自动测速与故障转移** —— 修掉「功能静默失效」类缺陷（节点属性错位、running 残留、用抖动的延迟排名）
- **TF 卡原地扩容 4G→16G（数据零丢失）** —— 靠「NOR 窗口」绕开 `resize.f2fs` 拒绝对已挂载文件系统操作的限制
- **无 SSH / 卡损坏的救援路径** —— 借 LuCI 当命令通道，TF 卡硬件级损坏的三板斧判死法

## 目录

```
SKILL.md                       ← 主技能：设备档案 + 任务路由表 + 高危禁令 + 踩坑速查表
README.md                      ← 本文件
docs/调优经验总览.md            ← ⭐ 按领域汇总的全部调优经验（12 个板块，含结论与判据）
C2000U-Docker-assessment.md    ← C2000 U Docker 适配评估 + 实装全记录（13 项门槛逐条判定）
references/                    ← 23 篇专题文档（每个领域一篇，含原始证据）
  1panel-hostnet-default.md   ⭐ 1Panel 应用默认 host 网络方案（含真机事故复盘）
  docker-porting.md           Docker：stub ipk 格式细节、vfs、swap
  c2000u-docker.md            C2000 U Docker 实装全记录
  docker-panel.md             自建 Docker 面板：Lua socket.unix 性能修复、du 原子锁
  adguard-setup.md            AGH 部署、DNS 接管顺序、API
  c2000u-openclash.md         OpenClash 分流、自动测速切换、故障转移
  no-ssh-recovery.md          无 SSH 时的救援通道
  tf-partition-resize.md      TF 卡原地扩容（NOR 窗口法）
  one-command-restore.md      一条命令重装三大件
  pc-toolchain-limits.md      PC 侧工具链限制与编码坑
  script-ui.md                busybox 下的终端界面约束
  …（其余见目录）
scripts/                       ← 可直接复用的 PC 侧工具（凭据全走环境变量）
  rtr_lib.py                  ⭐ 路由器远程操作库（无 SFTP 专用：heredoc/printf/断线重连）
  kp-1panel-install-test.py   ⭐ 1Panel 装容器能力测试驱动（8 阶段一条命令跑完）
  kunpeng-toolkit.sh          设备侧工具箱
  gh_proxy_push.py            GitHub DNS 被污染时的推送绕行工具
  revtunnel_put.py            反向隧道投递大文件
  setup_docker_c2000u.py      C2000 U Docker 一键实装
  healthcheck_c2000u.py       全量只读巡检（13 板块）
  payload/                    ⭐ 设备端脚本：host 网络默认化三件套 + compose 转换器 + 回归自测
```

## 怎么用

```bash
# 1) 放进 Agent 的 skills 目录
git clone https://github.com/h910056902/kunpeng-router-ai-skills.git \
  ~/.workbuddy/skills/kunpeng-router-tuning

# 2) 凭据只走环境变量，不落盘
export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<你的SSH密码>
export AGH_USER=<AGH账号> AGH_PASS=<AGH密码>

# 3) 只读巡检（先看清现场再动手）
python scripts/healthcheck_c2000u.py

# 4) 1Panel 装容器能力测试（8 阶段，会先只读探测再要你授权）
python scripts/kp-1panel-install-test.py --stage probe
```

Agent 载入后按 `SKILL.md` 的**任务路由表**分发：描述你的目标（例如「让 1Panel 装的应用能起来」），它会跳到对应 playbook 并带上该领域的历史坑。

## 核心经验 TL;DR

1. **先确认真实约束，再调配置** —— `docker run` 起不来报 `veth pair: operation not supported` 是**内核没有 veth**，改 `daemon.json`/UCI 全都没用，唯一出路是 `--network host`
2. **UCI 是唯一配置入口** —— `dockerd` 每次启动都用 UCI 重新生成 `/tmp/dockerd/daemon.json`，写 `/etc/docker/daemon.json` **没人读**；正路是 `uci set dockerd.globals.alt_config_file`
3. **opkg 拒装依赖时，`--force-depends` 是无效开关**（它只管「装包时」的检查）→ 造只声明 `Provides` 的 **stub ipk** 闭合依赖链
4. **「已注册」≠「可用」** —— `kmod-usb-storage` 在 `opkg status` 里是「装了但没内容」，`.ko` 根本不存在
5. **判断「通不通」必须发真 HTTP 请求** —— fake-ip + TUN 会让 `ping` 和 TCP 握手都变成假象
6. **host 化之后端口以「容器内端口」为准** —— compose 的 `ports:` 被删掉，模板里 `10443:8443` 真正监听的是 **8443**
7. **写死的缩进假设会毁掉转换器** —— 1Panel 面板落盘的 compose 是 4 空格缩进（商店 tarball 是 2 空格），按字面缩进转换会产出「半转换」文件，报 `uses an undefined network`
8. **面板参数填错也能无 UI 修** —— 1Panel 库在 `1panel/db/1Panel.db` 的 `app_installs.env`（JSON），设备有 `python3` 无 `sqlite3`，用标准库在线改即可

详见 [`docs/调优经验总览.md`](docs/调优经验总览.md)。

## 相关仓库

| 仓库 | 可见性 | 内容 |
|---|---|---|
| **kunpeng-router-ai-skills**（本仓库） | public | 脱敏后的技能包：调优经验 + 可复用工具 |
| `h910056902/nros-panel` | public | 三大件一键重装（OpenClash + Docker + 1Panel）+ 自建 Docker 面板 + ocspeed 五件套 |
| `h910056902/kunpeng-istoreos` | public | iStoreOS 化、应用中心极光主题、在线商店增强 |
| `kunpeng-router-tuning` | private | 完整档案：真机日志、设备细节、源码归档 |

## Disclaimer

仅用于自有设备的合法定制与学习。所有操作前请自行备份，变砖风险自负。
