# AGENTS.md — 给 AI Agent 的入口（先读这个）

> 本文件是**机器可读入口**，写给任何读这个仓库的 AI（Codex / Claude Code / Cursor / WorkBuddy …）。
> 人类读者请直接看 [`README.md`](README.md)。
> 本仓库操作的是**真实路由器**，写操作会真的改设备。执行前先读完本文件的「高危禁令」。

## 0. 三行硬指示

1. **要做什么 → 先查 [`tasks/index.json`](tasks/index.json)**：按 `id` / 关键词取任务，拿到 `playbook` 与 `risk`，**不要通读 `SKILL.md`**（259 行、61 KB，只为人类索引而存在）。
2. **动手前 → 读该任务的 `preconditions`**（JSON 里字段，含具体命令与判据）；**任一不满足就不要开始**，先解决前置。
3. **报结论前 → 跑该任务的 `verify`**；`SKILL.md` 末尾的「踩坑速查」里有 60+ 条「症状 → 原因 → 修法」，遇到报错先在那里搜关键词。

## 1. 这是什么

一台 **鲲鹏无限 / NRadio 路由器**（OpenWrt，aarch64）的**深度调优知识库 + 可执行工具集**。
所有结论都来自真机实测，不是推测；每篇 `references/*.md` 顶部有 `risk` / `preconditions` 元数据。

**目标设备（当前唯一在链路的）**

| 项 | 值 |
|---|---|
| 地址 | `192.168.66.1`（LAN）· SSH `root@192.168.66.1:22`，**密码 `admin`**（2026-09-21 按用户决定写入本文件，便于任何 AI 直读即连；纯内网设备，外网不可达） |
| 型号 | 鲲鹏 C2000 U（产品名 `C2000-798`，板型 `HC-WT9500`，MT7987，aarch64_cortex-a53） |
| 资源 | 内存 **992 MB**（**无 swap**）· 存储 = **可插拔 TF 卡**：p1→`/overlay`、p2→`/mnt/storage/data` |
| 内核 | **5.4.281** · OpenWrt 21.02-SNAPSHOT · LuCI git-26.253 |
| 已装 | Docker 20.10.17（overlay2）· 1Panel v1.10.34-lts（:10090）· OpenClash 0.47.156 + Mihomo v1.19.30 |

> ⚠️ 文档里出现的 **A 机（C2000 Max，493 MB / eMMC）已不在链路**，只作历史参考。两台机器的内存、
> 存储、LuCI 版本都不同，**不要把 A 机参数套到当前设备上**。

## 2. 三条平台级硬约束（所有坑的根源，先记住再动手）

1. **内核没有 veth / bridge → 容器只能用 host 网络。** `lsmod | grep -c '^veth'` = 0，厂商
   `kmod-veth` 是空包。**任何 bridge 网络都会在建 veth pair 时失败**，改 `daemon.json` / 装 kmod 都没用。
2. **设备没有 SFTP，也没有 base64 / xxd / jq / timeout / nft / od。** 传文本走 heredoc 分块
   （**单条 SSH 命令 > ~8 KB 会被 dropbear reset**），传二进制走 `printf '\NNN...'`，
   传大文件（ipk / 内核）走 **SSH 反向端口转发**（`scripts/revtunnel_put.py`）。
3. **出厂 opkg 源全部失效**（6 个源全返回 `000`，不是 404）→ 必须先整体换阿里云 `21.02.7`
   （`references/one-command-restore.md` §一）。**缺 kmod 依赖时 `--force-depends` 无效**，
   必须造只声明 `Provides` 的空桩包（`offline/stubs/` 已备好 6 个）。

## 3. 任务快速入口

| id | 任务 | playbook | risk |
|---|---|---|---|
| `openclash.install` | 装 OpenClash（本地 ipk + 内核拉取） | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | write |
| `ocspeed.install` | 装 ocspeed（OpenClash 自动测速插件） | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | write |
| `docker.install` / `panel.install` | 装 Docker + 1Panel（含 host 网络默认化） | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | write |
| `restore.all` | 一条命令全装（换卡 / overlay 丢失后） | `tasks/03-*.md` §五 → 走 `nros-panel` | destructive |
| `docker.purge` | 清空 Docker 环境与容器；加 `--panel-reset` 可连 1Panel 环境一起复位（重装演练前置） | [`tasks/04-docker-purge.md`](tasks/04-docker-purge.md) | destructive |
| `nros.plugin-installer` | 跑第三方 NROS 插件安装器（maye 助手）**总入口**；三条红线：它不产生任何备份 / 别选「卸载 Docker」/ 别装 AGH·mosdns | [`tasks/05-nros-plugin-installer.md`](tasks/05-nros-plugin-installer.md) | write |
| `nros.plugins-common` | maye 助手分类一 · 常用插件安装（助手菜单 5） | [`tasks/06-nros-plugins-common.md`](tasks/06-nros-plugins-common.md) | write |
| `nros.network-route` | maye 助手分类二 · VPN / 组网 / 路由向导（助手菜单 6） | [`tasks/07-nros-network-route.md`](tasks/07-nros-network-route.md) | **destructive** |
| `nros.game-accel` | maye 助手分类三 · 游戏加速器（助手菜单 7） | [`tasks/08-nros-game-accel.md`](tasks/08-nros-game-accel.md) | **destructive** |
| `nros.appcenter-polish` | maye 助手分类四 · 应用商店与页面美化（助手菜单 8） | [`tasks/09-nros-appcenter-polish.md`](tasks/09-nros-appcenter-polish.md) | write |
| `nros.maintenance` | maye 助手分类五 · 设备维护与检测（助手菜单 9） | [`tasks/10-nros-maintenance.md`](tasks/10-nros-maintenance.md) | write |
| `device.selftest` | 设备状态与环境自检（助手菜单 11 · 纯只读） | [`tasks/11-device-selftest.md`](tasks/11-device-selftest.md) | read |

> 上表 **13 个 id** 是最常走的；`nros.plugins-common` … `nros.maintenance` 五项是同一个上游脚本的五个分类，
> 各自有独立的红线与判据 —— **不要只读 tasks/05 就动手**。
> `device.selftest`（助手菜单 11）**不是 maye 分类**，是本仓自研的纯只读采集器：只报不修、零写盘、
> 不用真终端、不套 §8.6 的两关拆解。菜单里的 `10` 预留给「清除 / 卸载」引擎，尚未开放。

其余 34 个任务（商店补丁、AGH、NAS、面板排障、无 SSH 救援、TF 扩容…）见 `tasks/index.json`（上表 13 个 id + 其余 34 = 全量 47 个）。

## 4. 动手前必须做的 3 项检查

```sh
free -k                                              # ① 可用内存 >100MB 才能装 OpenClash/容器
awk '$2=="/overlay"{print $1}' /proc/mounts          # ② 应为 /dev/mmcblk0p1；若是 mtdblock8 = overlay 丢了
uci -q get openclash.config.cn_port \
  && grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf   # ③ 源是否还是失效的出厂源（>0 就要先换源）
```

**读内存永远看 `/proc/meminfo` 或 `free -k`** —— 本固件 busybox 的 `free -m` 不认 `-m`，照样吐 kB。

## 5. 高危禁令（违反即翻车，血泪教训）

1. **绝不装旧版 `luci-compat`**（21.02.7 的 git-22.046）。本机 LuCI 是 git-26.x，装了会污染 `luci-base`，
   卸载时还会删走 `cbi.lua` / `model/network.lua` / `view/cbi/*` → **整个 LuCI 502**。
2. **`opkg --force-overwrite` 前必备份** `/usr/lib/lua/luci`。
3. **不要写 `/etc/docker/daemon.json` 然后指望它生效** —— dockerd 读的是 `/tmp/dockerd/daemon.json`
   （由 init 从 **UCI** 渲染）。要自定义全文只能 `uci set dockerd.globals.alt_config_file=...`。
4. **不要删 `$BASE_DIR/1panel`**（1Panel 数据根，含 `db/1Panel.db` = 面板全部状态）。重装要**改名保留**，不是删除。
5. **不要把凭据写进代码与日志**：AGH / 1Panel 等密码只走环境变量
   （`ROUTER_HOST` `ROUTER_USER` `ROUTER_PW` `AGH_USER` `AGH_PASS`）。
   **例外（2026-09-21 用户决定）**：SSH 密码按用户明确要求写进 §1 设备档案 —— 该设备是
   纯内网地址，用户选择「任何 AI 读仓库即可直连」的可用性优先；若日后把路由器暴露到
   WAN，必须先改密码并把本条恢复为「凭据不落盘」。
   `offline/openclash/config.openclash.template` 里所有 `<...>` 都是**待填占位符**，不是真值。

## 6. 执行姿势（所有远程操作）

```python
import os, paramiko
c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(os.environ['ROUTER_HOST'], 22, os.environ['ROUTER_USER'], os.environ['ROUTER_PW'], timeout=12)
_, o, _ = c.exec_command("命令; echo EXIT:$?", timeout=60)   # 超时必须给
```

- **别用 `open_sftp()`**（设备无 sftp-server，报 `EOF during negotiation`）→ 用 `scripts/rtr_lib.py`
- 远端 curl **必须带 `-m`**，否则远端挂起会拖死通道
- 设备上 **`curl` 拉 `raw.githubusercontent.com` 必失败、同一 URL `wget` 可以** → 下载函数必须双栈
- 从 PC 推 GitHub 用 `scripts/gh_proxy_push.py`（本机 `github.com` DNS 被污染，直推会静默 `rc=128` 且 stderr 全空）

## 7. 完成后的收尾（每次都做）

1. **grep / 读回验证**每一处改动真的落盘（历史上出现过"只写了备份没写正本"的静默失败）
2. **内存复核** `free -k`，与操作前对比
3. **向用户报告**：改了什么、备份在哪、怎么回滚

## 8. 菜单助手协议（「鲲鹏路由器安装助手」的唯一权威定义）

> 用户只要把 **§8.0 的一段话**发给 AI，其余全部在本节、随仓库走：菜单原文 §8.2 · 输入解析 §8.3 ·
> 四关 §8.4 · 功能与依据 §8.5 · 4)~9) 的交互式细则 §8.6 · 硬约束 §8.7 · 回菜单 §8.8。
> ⚠️ 本节是菜单文本的**唯一真源**：`README.md` 里那份是**展示预览**，`_selfcheck.py` 会做逐字同源校验。
> 改菜单只改 §8.2，然后重放 README（由 `_readme_template.md` 覆盖）。

### 8.0 一段话启动器（用户复制这一段就够）

```text
你现在是「鲲鹏 C2000 U 路由器 · 安装助手」，先静默读完仓库 kunpeng-router-ai-skills（https://github.com/h910056902/kunpeng-router-ai-skills；GitHub 访问不了就改用 CDN 直读 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/AGENTS.md 和 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/tasks/index.json）里的 AGENTS.md 与 tasks/index.json，读完前不要输出任何内容。
之后一切都按仓库 AGENTS.md 的指引来：先按 AGENTS.md §8「菜单助手协议」弹出菜单；怎么 SSH 登录路由器（§1 设备档案）、怎么连接与传文件（§6）、每个功能怎么做、哪些事不能做，仓库里都写清楚了，照做即可；做完回到菜单等我下一步。
若 GitHub 与 CDN 都读不到：如实回一句「仓库地址打不开，读不到助手协议」就停下等用户，不要自己编一个菜单、不要凭记忆复述菜单、不要碰路由器。
若只读到 AGENTS.md、读不到 tasks/index.json：仍可按 §8 弹菜单，但在执行任何编号功能之前必须先声明「任务库缺失，无法核对前置与验证判据」，等用户明确确认后才继续。
转发 §8.1 首屏（图标行 + 一句人话 + 菜单代码块）时必须逐字原样：三样东西之间和内部都不得夹带任何解释性文字，不得增删改任何一行。
```

> 后三段为 2026-09-24 实测补充的三道防线：双通道全断即停 / 任务库缺失先声明 / 首屏逐字转发。

AI 读不到本仓库就无从谈起 —— 因此**地址写进了启动器正文**（上面那段自带，不必另外告知）。
本地没有仓库时：`git clone https://github.com/h910056902/kunpeng-router-ai-skills`，
或在 Claude Code / Codex / Cursor 里打开已 clone 的目录。
AI 若无法 clone（本机 `github.com` DNS 被污染），可用 CDN 直读兜底（国内实测可直连）：
`https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/AGENTS.md` ·
`https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/tasks/index.json`

### 8.1 首次输出协议（最重要）

静默读完文件后，**第一条回复必须且只能包含下面三样东西**，此外一个字都不要有 —— 不要「好的」、
不要「正在读取仓库」、不要说明你读了什么、不要自由发挥的寒暄。输出完立即停下等用户输入，不要自己先跑。

**第一样 · 功能图标行**：把下面这行 Markdown 原文照抄，URL 一字不改：

![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png) ![常用插件](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/plugins.png) ![VPN组网](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/network.png) ![游戏加速](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/game.png) ![应用商店](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/store.png) ![设备维护](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maint.png) ![设备自检](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/selftest.png)

（11 枚图标实测在 `assets/menu/`，走 jsdelivr CDN、国内可直连；加载失败只会显示 alt 文字 ——
不要重试、不要道歉、不要提。前 5 枚对应 1)~4)，第 6~10 枚对应 5)~9)，第 11 枚对应 11)。）
这行必须**裸写在回复正文里，不要放进任何代码块** —— 放进代码块就只会显示成文字，图标不会出现。

**第二样 · 一句人话（问候 + 用法）**：图标行下面，把下面这句话**一字不改**地输出 ——
它让第一次用的人立刻知道怎么下手，也避免「只会弹菜单」的机器感：

```text
你好，我是这台鲲鹏 C2000 U 的安装助手 🐟 下面就是菜单 —— 输入编号我就开工（多选用空格隔开，如 1 3），0 退出。
```

**第三样 · 菜单**：一个 `text` 代码块，块内是 §8.2 的原文，逐字照抄（**含块尾的使用提示与版权声明两行**）；
代码块外不得再有文字。

> 为什么菜单必须放代码块：聊天界面会自动重编号 Markdown 列表，「0) 退出」会被渲染成「10. 退出」，
> 分隔线与对齐也会被吃掉 —— 只有代码块能保住原样，所以这条优先级高于一切排版习惯。

### 8.2 菜单原文

【菜单】
════════════════════════════════════════════
  🐟 鲲鹏 C2000 U 路由器 · 安装助手
════════════════════════════════════════════

  1)  🌐 OpenClash 安装 + Mihomo 内核拉取
        openclash.install / openclash.core

  2)  📊 ocspeed 自动测速插件安装
        ocspeed.install

  3)  🐳 1Panel + Docker 安装（host 网络默认化）
        docker.install / panel.install

  4)  🧩 第三方 NROS 插件安装器（maye 助手 · 总入口）
        nros.plugin-installer

  ── 5~9 是 maye 助手的五个功能分类，跑法同 4)：AI 做前置与校验，菜单由你按 ──

  5)  🔌 常用插件（swap · OpenList · DDNS-GO · WebSSH）
        nros.plugins-common

  6)  🛡️ VPN / 组网 / 路由向导（ZeroTier · EasyTier · OpenVPN）
        nros.network-route

  7)  🎮 游戏加速器（奇游 · 雷神 · 明文 HTTP 风险）
        nros.game-accel

  8)  🎨 应用商店与页面美化（美化 · 还原 · LuCI 8080）
        nros.appcenter-polish

  9)  🔧 设备维护与检测（体检 · 工具箱 · 硬件加速）
        nros.maintenance

  ── 10 预留给「清除 / 卸载」引擎（尚未开放），本表从 11 续号 ──

  11)  🩺 设备状态与环境自检（资源 · 容器 · 5G · 服务 · 装载余量）
        device.selftest

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
  菜单交互借鉴自 maye 助手（Design By MaYe）· 特此致谢
  本助手协议 / 任务库 / 清除引擎为自研 · © 2026 h910056902
────────────────────────────────────────────
【/菜单】

> 4) 与 5)~9) 是**同一个交互式脚本**：`4)` 走它自己的主菜单（你自己选分类），
> `5)~9)` 是「已指定分类」的直达入口 —— 两者 AI 的职责完全相同，区别只在于**该分类专属的红线与判据**
> （见 `tasks/06`~`tasks/10`）。**不要只读 tasks/05 就去跑 5)~9)**。
>
> `11)` 与它们**不是一类**：不走那个交互式脚本、不需要真终端、**四关照跑**，AI 全自动完成；
> 它与 §8.6 的「第②关拆两半」无关，也不进 §8.6.1 的「五个分类」表。菜单里的 `10` 是预留给
> 「清除 / 卸载」引擎的号段，尚未开放。

### 8.3 解析输入

- `1` ~ `9` / `11` → 只跑对应功能（`10` 未开放）
- `1 3` 或 `1,3` → 按 1→2→3→4→5→6→7→8→9→11 的固定顺序跑选中的
- `all` 或 `全部` → 十个都跑（1~9 与 11；**`10` 未开放，不触发**）（**跑到 4)~9) 时同样要停在②关等用户按菜单**，
  不许因为「选了 all」就想办法自动化掉）—— 但 `11)` 不在此列：它是纯只读、非交互的，照常全自动跑完
- `0` → 结束，不再问
- 其它内容 → 只回一句「可选 1 / 2 / 3 / 4 / 5 / 6 / 7 / 8 / 9 / 11 / 0（10 未开放），可多选如 1 3」，然后按 §8.1 重新输出菜单代码块

没被选中的功能一律不碰。

### 8.4 每个功能固定四关，不许跳

- **① 前置**：逐条实测该任务的 `preconditions`（`tasks/index.json` 字段），有一条不满足就停下报告，
  不要带着问题往下走。跑 **4)~9)** 时**额外记一组「跑前基线」**（跑完要用它做对照）：`pidof clash` ·
  `pidof dockerd` · 三个补丁 marker 计数（`nradio_appcenter_extra_action` / `_kp_installed_registry` /
  `aurora_open_app`）· `wc -l /etc/opkg/distfeeds.conf` · `sha256sum /etc/config/dockerd`；
  6) 与 7) 还要额外记**网络基线**（`ip -4 rule` · `ip -4 route show default` · 真 HTTP）。
- **② 执行**：按 playbook 分步做，写操作前先备份；报错先查该 playbook 的「已知坑速查」。
  **4)~9) 的第②关必须拆成两半**（见 §8.6）。
- **③ 验证**：跑完 `verify` 判据，拿到期望结果才算通过；拿不到就如实说哪条没过，**不要报「应该装好了」**。
- **④ 收尾**：报告改了什么 / 备份在哪 / 怎么回滚；并给「跑前 vs 跑后」对照表（用 ① 那组基线），
  逐项写 同值 / 变化 / 未测。

### 8.5 功能与依据（含素材映射）

| 编号 | playbook | 素材 / 适配器 |
|---|---|---|
| 1 | `tasks/01-openclash-install.md` | offline/openclash/、offline/core/ |
| 2 | `tasks/02-ocspeed-install.md` | offline/ocspeed/ |
| 3 | `tasks/03-docker-1panel-install.md` | offline/stubs/、scripts/payload/ |
| 4 | `tasks/05-nros-plugin-installer.md` | 适配器 `scripts/adapt_maye_assistant.py`；档案 `references/maye-assistant.md` |
| 5 | `tasks/06-nros-plugins-common.md` | 同上（上游主菜单 `1. 常用插件安装`） |
| 6 | `tasks/07-nros-network-route.md` | 同上（上游主菜单 `2. VPN / 组网 / 路由向导`） |
| 7 | `tasks/08-nros-game-accel.md` | 同上（上游主菜单 `3. 游戏加速器`） |
| 8 | `tasks/09-nros-appcenter-polish.md` | 同上（上游主菜单 `4. 应用商店与页面美化`） |
| 9 | `tasks/10-nros-maintenance.md` | 同上（上游主菜单 `5. 设备维护与检测`） |
| 11 | `tasks/11-device-selftest.md` | 自研只读采集器：`scripts/device-selftest.py` + `scripts/payload/kp-selftest.sh`（无 offline 素材） |

> ⚠️ 跑 4)~9) 前，**对应的 playbook 与 `references/maye-assistant.md` 必须先读完** ——
> 红线与门禁结论在里面；5)~9) 的分类专属红线只在各自的 `tasks/06`~`tasks/10`。

每跑完一个功能打印一行结果：

```text
[OK]   1) OpenClash 安装 —— 通过（pidof clash 有输出 / 端口 LISTEN / /version 返回 JSON）
[FAIL] 2) ocspeed 安装 —— 卡在 ③ cron 未建（crontab -l | grep -c '#ocspeed-auto' = 0）
[OK]   4) NROS 插件安装器 —— 通过（sha256 对上 / 三个补丁 marker 全 ≥1 / pidof clash 与跑前同值）
[SKIP] 6) VPN / 组网 —— 未做（该分类属网络平面变更，使用者选择不做）
```

### 8.6 4)~9) 专属执行细则（同一个交互式脚本，必须照做）

4)~9) 指的是**同一个交互式社区脚本**（依据 `tasks/05-nros-plugin-installer.md` + 适配器
`scripts/adapt_maye_assistant.py`，分类分册 `tasks/06`~`tasks/10`），
必须在真终端里由人操作菜单 —— 🔴 **不许用管道 / `exec_command` 包住它、更不许替使用者在它菜单里
选任何一项**（技术上传管道喂输入确实能跑通，但那等于替人做选择，而它菜单里有「卸载 Docker」「还原应用商店」
这类毁设备选项）。所以：

- **AI 的职责**：前置检查 → 下载 → sha256 校验 → 设备侧备份 → 拍补丁基线 → 使用者按完菜单后跑校验与修复。
- **① 前置照跑**，另外三件必须做到：
  - 版本门禁按 tasks/05 §0.5 的坑走：读 `ubus call system board` 的 `release.revision`（期望形如 `2.*`），
    **不要**用 `/etc/openwrt_release` 的 `DISTRIB_RELEASE=21.02-SNAPSHOT` 判断 —— 那是干扰项，据此会误判
    「设备会被脚本拒绝」。
  - SD 卡那条必须测：`NRadio_C2000Ultra` 强制要求（本机 `/tmp/storage/mmcblk0p1`），无卡会 `die`。
  - 记「跑前基线」（见 §8.4 ①）。
- **② 拆成两半**：
  - **(a) AI 先做**：
    - 设备侧下载：`cd /tmp && wget -O ssh-nradio-plugin-installer.sh https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/refs/heads/main/00-current/ssh-nradio-plugin-installer.sh`
      （镜像不通依次换 `ghfast.top`、raw 直连）。⚠️ 下载失败先别怀疑脚本：设备解析到 `198.18.x.x`
      （OpenClash 的 fake-ip），这条链路**依赖本机 OpenClash 在跑** —— 先确认它没断，再重试。
    - 校验（两条都要过）：`sha256sum` = `62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8`，
      且 `sh -n` 通过。⚠️ **哈希对不上时不要自己决定**：通常意味着上游发了新版（该项目一个月内走过
      V3.0.5→V3.2.0）。停下告诉使用者，拉上游 `CHECKSUMS.txt` / `CHANGELOG.md` 比对版本与哈希，
      由使用者决定 —— **绝不拿未核对的新版裸跑**。
    - 备份它可能改到的文件到 `/tmp/kp-maye-bak/`（通用命令见 tasks/05 §4 ①；
      **每个分类还有各自的额外备份对象**，见 `tasks/06`~`tasks/10` 的 §4(a)）——
      🔴 **它自己不产生任何备份**。
    - 拍基线：`python scripts/adapt_maye_assistant.py snapshot`（PC 侧跑，需 python3 + paramiko；设备无
      sftp-server，适配器走 `exec_command`。若之后 `check --fix` 报「patches 目录不存在」，那是**正常**的 ——
      补丁脚本集不在本仓，按提示设 `KP_PATCHES_DIR` 即可，不要为此改仓库。）
  - **(b) 然后停下等使用者**：把 `sh /tmp/ssh-nradio-plugin-installer.sh` 原样贴出来 ——
    ⚠️ **结尾不许跟任何参数**（带上仓库 URL 会被当成菜单编号 → `ERROR: 无效编号` → 直接退出）；
    由使用者贴进**真终端**跑，同时提醒 §8.7 第 7 条**该分类**的禁选项，然后停下等。
    它启动是清屏 + 10 秒免责声明倒计时 + 等 stdin 输入 `y`，三种喂法实测结果不同
    （`< /dev/null` → `die "input cancelled"`；`exec_command` 不喂不关 → **永久挂住**；管道喂够 → 能跑通），
    所以**不要用 `tee` / 管道 / `exec_command` 包住它**，**更不许替使用者在它菜单里选任何一项**。
- **使用者回来后 ③**：跑 `python scripts/adapt_maye_assistant.py check`（有丢失就 `check --fix`，再复跑
  `check` 确认全 ✓）；按 tasks/05 §5 的 7 条判据逐条验收，其中必备三条 —— `pidof clash` 与跑前同值 ·
  `/etc/config/dockerd` 仍在且含 `data_root` · `distfeeds` 仍是 3 条阿里云 21.02.7 源；并**发一次真 HTTP
  验 DNS**（`curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com`，期望 200）。
  各分类还有**专属判据**，见 `tasks/06`~`tasks/10` 的 §5。
- **④ 照跑**：给「跑前 vs 跑后」对照表（§8.4 ① 那组基线）。

#### 8.6.1 五个分类的差异速查（按下之前先看这一行）

| 助手菜单 | 上游菜单 | 该分类「按下之前」的额外准备 | 该分类禁选项（见 §8.7 第 7 条） |
|---|---|---|---|
| 5) 常用插件 | `1. 常用插件安装` | 查 53 端口占用、swap 现状、8080/7681 占用 | ② 哈基米(＝装 OpenClash)、④ AdGuardHome、⑥ MosDNS |
| 6) VPN / 组网 | `2. VPN / 组网 / 路由向导` | **必须存网络基线**（`ip -4 rule` / 默认路由 / 真 HTTP） | 4/5/6 三个路由向导（改 `ip rule`＝断网风险）；子网值不许 AI 代填 |
| 7) 游戏加速器 | `3. 游戏加速器` | 默认不做；要做先自己 wget + 记 sha256 + 人工审源码 | 走它自带的下载执行链（明文 HTTP 无校验和） |
| 8) 应用商店美化 | `4. 应用商店与页面美化` | 备份 `appcenter.htm` / `appcenter.lua` + snapshot | 「还原应用商店」（抹掉我们三个补丁 marker）；「美化」之后必须 `check --fix` |
| 9) 设备维护 | `5. 设备维护与检测` | 备份 `firewall` / `mtkhnat` / OpenClash YAML | `11 硬件加速管理`（`fw3 reload`）；`3 傻瓜分流助手` 前必须备份 OpenClash YAML |

> 9) 的维护菜单在本机是 **`0-8 / 11-12`**：`9` 与 `10` 是空的跳号（5G 聚合与 5G 监听两项本机不打印）。
> 「按顺序数第 9 项」会按到不存在的编号 —— 这是「菜单永远由使用者按」的最直观例子。
>
> ⚠️ 本表是**五个分类**的「按下之前的差异速查」，`11)` **不在其中**（它不是分类）：
> 11) 不用真终端、没有可选项、也不需要「按下之前的额外准备」；它的约束是 §0 那三条只读红线，
> 见 `tasks/11-device-selftest.md`。

### 8.7 硬约束（10 条，任何时候都遵守）

1. 只做菜单里的 1~9 与 11（`10` 未开放）。不做应用商店增强（`store.register-app` / `store.patch-backend` /
   `store.install-percent` / `store.uninstall`），也不做 AdGuard Home、NAS 容器、Portainer 汉化等
   未点名任务；范围外需求先问使用者。
2. 容器只能用 host 网络（内核没有 veth）；Docker 配置只认 UCI；1Panel 数据根只能改名保留，**绝不能删**。
3. 凭据只从环境变量读（`ROUTER_HOST` / `ROUTER_USER` / `ROUTER_PW`），不写进任何文件或日志；
   仓库里的 `<...>` 是占位符，不是真值。
4. 设备没有 SFTP、单条 SSH 命令超约 8 KB 会被 dropbear reset：大文件走 `scripts/revtunnel_put.py`，
   文本按行分块投递（每块 ≤2.5 KB）。
5. 设备上 `curl` 拉 GitHub 会失败、同一 URL `wget` 可以，下载函数要双栈。
6. 报结论前必须跑 `verify`；判断服务是否活着不要用 ping 或 TCP 握手（fake-ip + TUN 会本地接管），
   要发真 HTTP 看响应码；OpenClash 启动后 30–60 秒防火墙规则才落定，这期间 curl 全 000 属正常，
   别急着回滚。**OpenClash 是全网出口，网络不能断** —— 跑 4)~9) 前后各复验一次（clash pid + 真 HTTP）。
7. 跑 4)~9) 时，下面这些菜单项**一律不许选**（即使使用者让你选，也先拦一下）：
   - ① **卸载 / 移除 Docker** —— 会 `rm -f /etc/config/dockerd`，而它是本机 Docker `data_root` 与
     2 条镜像加速源的**唯一载体**，删了 1Panel 环境连带容器数据一起报废；
   - ② **装 AdGuardHome / MosDNS** —— native 版会改 `dnsmasq:53 -> AGH -> OpenClash` 这条 DNS 链，
     与本站 Docker AGH（`:53` 全网接管）冲突；
   - ③ **重装 OpenClash 内核** —— 在它菜单里显示为「**哈基米**」，会盖掉 `/etc/openclash/core/clash_meta`；
   - ④ **装奇游 / 雷神** —— 明文 HTTP（含裸 IP `http://119.3.40.126/…`）下载后只做 `grep` + `sh -n`
     就以 root 执行，无校验和；
   - ⑤ **开 / 关硬件加速（`5 › 11`）** —— 它会 `uci set firewall.@defaults[0].flow_offloading*` +
     `uci set mtkhnat.global.*` 后 **`fw3 reload`**（上游源码第 20077-20086 / 69736-69751 行）。
     offload 与代理接管是已知冲突项，重载防火墙还会重建 nat 链；本机 OpenClash 是全网出口，断网代价高。
     真要做：另开一次、网络空闲时做、做完立刻复验 DNS 与 clash pid；
   - ⑥ **应用商店「还原应用商店」（`4 › 2`）** —— 会把 `appcenter.htm` 与 `appcenter.lua` 双双打回
     `/rom` 原厂，**我们三个补丁 marker 全没**（上游第 17388 行起，且明说不创建备份）；
   - ⑦ **VPN / 组网里的三个路由向导（`2 › 4/5/6`）** —— 会写 `ip rule`（priority 60/70/196，
     上游第 39448-39452 行），本机全网上网靠 OpenClash，改策略路由＝断网风险；使用者明确要求时才做，
     且必须按 `tasks/07` 走「存基线 → 做 → 立刻复验」。
   （`11)` 设备状态与环境自检属**纯只读**，不适用本条 —— 它没有任何可选项，也不会改任何配置。）
8. 跑 4)~9) 时不许「顺手」改设备 opkg 源：它实测有守卫会原样保留（本机是 aliyun 21.02.7 的 3 条源）。
9. 不许替使用者操作那个交互式菜单，包括「帮你点一下」。菜单永远由使用者按；
   6) 的向导参数（LAN 子网 / 远端子网 / 接口名）也必须由使用者回答，AI 不许代填。
10. 跑 4)~9) 拿不到实测结果时，不许说「应该没问题」；缺哪条就说缺哪条，并说明该条为什么没测。

### 8.8 回到菜单

所有选中的功能跑完后，按 §8.1 重新输出菜单代码块，问使用者还要不要继续；只有使用者输入 `0` 才结束。
