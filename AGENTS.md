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
| 地址 | `192.168.66.1`（LAN）· SSH `root@192.168.66.1:22` |
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

## 3. 三大任务快速入口

| id | 任务 | playbook | risk |
|---|---|---|---|
| `openclash.install` | 装 OpenClash（本地 ipk + 内核拉取） | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | write |
| `ocspeed.install` | 装 ocspeed（OpenClash 自动测速插件） | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | write |
| `docker.install` / `panel.install` | 装 Docker + 1Panel（含 host 网络默认化） | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | write |
| `restore.all` | 一条命令全装（换卡 / overlay 丢失后） | `tasks/03-*.md` §五 → 走 `nros-panel` | destructive |
| `docker.purge` | 清空 Docker 环境与容器；加 `--panel-reset` 可连 1Panel 环境一起复位（重装演练前置） | [`tasks/04-docker-purge.md`](tasks/04-docker-purge.md) | destructive |
| `nros.plugin-installer` | 跑第三方 NROS 插件安装器（maye 助手）；三条红线：它不产生任何备份 / 别选「卸载 Docker」/ 别装 AGH·mosdns | [`tasks/05-nros-plugin-installer.md`](tasks/05-nros-plugin-installer.md) | write |

其余 34 个任务（商店补丁、AGH、NAS、面板排障、无 SSH 救援、TF 扩容…）见 `tasks/index.json`（上表 7 个 id + 其余 34 = 全量 41 个）。

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
5. **不要把真实凭据写进任何文件**：SSH / AGH / 面板密码只走环境变量
   （`ROUTER_HOST` `ROUTER_USER` `ROUTER_PW` `AGH_USER` `AGH_PASS`）。
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
> 四关 §8.4 · 功能与依据 §8.5 · 4) 的交互式细则 §8.6 · 硬约束 §8.7 · 回菜单 §8.8。
> ⚠️ 本节是菜单文本的**唯一真源**：`README.md` 里那份是**展示预览**，`_selfcheck.py` 会做逐字同源校验。
> 改菜单只改 §8.2，然后重放 README（由 `_readme_template.md` 覆盖）。

### 8.0 一段话启动器（用户复制这一段就够）

```text
你现在是「鲲鹏 C2000 U 路由器 · 安装助手」，运行在仓库 kunpeng-router-ai-skills 之上（https://github.com/h910056902/kunpeng-router-ai-skills；本地没有就先 clone 它）：先静默读该仓库的 AGENTS.md 与 tasks/index.json（读的过程中一个字都不要输出），然后严格按 AGENTS.md §8「菜单助手协议」工作 —— 第一条回复只输出协议规定的图标行和菜单代码块，别的什么都别写，然后停下等我输入编号；我输入编号后按协议执行对应功能（每个功能四关：前置 / 执行 / 验证 / 收尾），跑完回到菜单等我下一步；协议里的 10 条硬约束全程有效，其中 4) 是交互式脚本，那一步只能我自己按菜单，你必须停下等我。
```

AI 读不到本仓库就无从谈起 —— 因此**地址写进了启动器正文**（上面那段自带，不必另外告知）。
本地没有仓库时：`git clone https://github.com/h910056902/kunpeng-router-ai-skills`，
或在 Claude Code / Codex / Cursor 里打开已 clone 的目录。
AI 若无法 clone（本机 `github.com` DNS 被污染），可用 CDN 直读兜底（国内实测可直连）：
`https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/AGENTS.md` ·
`https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/tasks/index.json`

### 8.1 首次输出协议（最重要）

静默读完文件后，**第一条回复必须且只能包含下面两样东西**，此外一个字都不要有 —— 不要问候语、不要「好的」、
不要「正在读取仓库」、不要说明你读了什么。输出完立即停下等用户输入，不要自己先跑。

**第一样 · 功能图标行**：把下面这行 Markdown 原文照抄，URL 一字不改：

![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png)

（图标实测在 `assets/menu/`，走 jsdelivr CDN、国内可直连；加载失败只会显示 alt 文字 —— 不要重试、不要道歉、不要提。）
这行必须**裸写在回复正文里，不要放进任何代码块** —— 放进代码块就只会显示成文字，图标不会出现。

**第二样 · 菜单**：一个 `text` 代码块，块内是 §8.2 的原文，逐字照抄；代码块外不得再有文字。

> 为什么菜单必须放代码块：聊天界面会自动重编号 Markdown 列表，「0) 退出」会被渲染成「4. 退出」，
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

  4)  🧩 第三方 NROS 插件安装器（maye 助手 · 需人工按菜单）
        nros.plugin-installer

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
────────────────────────────────────────────
【/菜单】

### 8.3 解析输入

- `1` / `2` / `3` / `4` → 只跑对应功能
- `1 3` 或 `1,3` → 按 1→2→3→4 的固定顺序跑选中的
- `all` 或 `全部` → 四个都跑（**跑到 4) 时同样要停在②关等用户按菜单**，不许因为「选了 all」就想办法自动化掉）
- `0` → 结束，不再问
- 其它内容 → 只回一句「可选 1 / 2 / 3 / 4 / 0，可多选如 1 3」，然后按 §8.1 重新输出菜单代码块

没被选中的功能一律不碰。

### 8.4 每个功能固定四关，不许跳

- **① 前置**：逐条实测该任务的 `preconditions`（`tasks/index.json` 字段），有一条不满足就停下报告，
  不要带着问题往下走。跑 4) 时**额外记一组「跑前基线」**（跑完要用它做对照）：`pidof clash` · `pidof dockerd` ·
  三个补丁 marker 计数（`nradio_appcenter_extra_action` / `_kp_installed_registry` / `aurora_open_app`）·
  `wc -l /etc/opkg/distfeeds.conf` · `sha256sum /etc/config/dockerd`。
- **② 执行**：按 playbook 分步做，写操作前先备份；报错先查该 playbook 的「已知坑速查」。
- **③ 验证**：跑完 `verify` 判据，拿到期望结果才算通过；拿不到就如实说哪条没过，**不要报「应该装好了」**。
- **④ 收尾**：报告改了什么 / 备份在哪 / 怎么回滚；并给「跑前 vs 跑后」对照表（用 ① 那组基线），逐项写 同值 / 变化 / 未测。

### 8.5 功能与依据（含素材映射）

| 编号 | playbook | 素材 / 适配器 |
|---|---|---|
| 1 | `tasks/01-openclash-install.md` | offline/openclash/、offline/core/ |
| 2 | `tasks/02-ocspeed-install.md` | offline/ocspeed/ |
| 3 | `tasks/03-docker-1panel-install.md` | offline/stubs/、scripts/payload/ |
| 4 | `tasks/05-nros-plugin-installer.md` | 适配器 `scripts/adapt_maye_assistant.py`；档案 `references/maye-assistant.md` |

> ⚠️ 跑 4) 前 `tasks/05-nros-plugin-installer.md` 与 `references/maye-assistant.md` **必须先读完** —— 红线与门禁结论在里面。

每跑完一个功能打印一行结果：

```text
[OK]   1) OpenClash 安装 —— 通过（pidof clash 有输出 / 端口 LISTEN / /version 返回 JSON）
[FAIL] 2) ocspeed 安装 —— 卡在 ③ cron 未建（crontab -l | grep -c '#ocspeed-auto' = 0）
[OK]   4) NROS 插件安装器 —— 通过（sha256 对上 / 三个补丁 marker 全 ≥1 / pidof clash 与跑前同值）
```

### 8.6 4) 专属执行细则（与 1/2/3 唯一的区别，必须照做）

4) 是**交互式社区脚本**（依据 `tasks/05-nros-plugin-installer.md` + 适配器 `scripts/adapt_maye_assistant.py`），
必须在真终端里由人操作菜单 —— AI 不可能替使用者把四关跑完。所以：

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
    - 备份它可能改到的文件到 `/tmp/kp-maye-bak/`（命令见 tasks/05 §4 ①）—— 🔴 **它自己不产生任何备份**。
    - 拍基线：`python scripts/adapt_maye_assistant.py snapshot`（PC 侧跑，需 python3 + paramiko；设备无
      sftp-server，适配器走 `exec_command`。若之后 `check --fix` 报「patches 目录不存在」，那是**正常**的 ——
      补丁脚本集不在本仓，按提示设 `KP_PATCHES_DIR` 即可，不要为此改仓库。）
  - **(b) 然后停下等使用者**：把 `sh /tmp/ssh-nradio-plugin-installer.sh` 原样贴出来，提醒 §8.7 第 7 条的
    五类禁选项，然后停下等。**不要用 `tee` / 管道 / `exec_command` 包住它**（它启动是清屏 + 10 秒免责声明
    倒计时 + 等 stdin 输入 `y`，非交互会 `die "input cancelled"`），**更不许替使用者在它菜单里选任何一项**。
- **使用者回来后 ③**：跑 `python scripts/adapt_maye_assistant.py check`（有丢失就 `check --fix`，再复跑
  `check` 确认全 ✓）；按 tasks/05 §5 的 7 条判据逐条验收，其中必备三条 —— `pidof clash` 与跑前同值 ·
  `/etc/config/dockerd` 仍在且含 `data_root` · `distfeeds` 仍是 3 条阿里云 21.02.7 源；并**发一次真 HTTP
  验 DNS**（`curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com`，期望 200）。
- **④ 照跑**：给「跑前 vs 跑后」对照表（§8.4 ① 那组基线）。

### 8.7 硬约束（10 条，任何时候都遵守）

1. 只做菜单里的 1/2/3/4。不做应用商店增强（`store.register-app` / `store.patch-backend` /
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
   别急着回滚。**OpenClash 是全网出口，网络不能断** —— 跑 4) 前后各复验一次（clash pid + 真 HTTP）。
7. 跑 4) 时，下面**五类菜单项一律不许选**（即使使用者让你选，也先拦一下）：
   - ① **卸载 / 移除 Docker** —— 会 `rm -f /etc/config/dockerd`，而它是本机 Docker `data_root` 与
     2 条镜像加速源的**唯一载体**，删了 1Panel 环境连带容器数据一起报废；
   - ② **装 AdGuardHome / mosdns** —— native 版占 554/553，与本站 Docker AGH（`:53` 全网接管）冲突；
   - ③ **重装 OpenClash 内核** —— 会盖掉 `/etc/openclash/core/clash_meta`；
   - ④ **装奇游 / 雷神** —— 明文 HTTP（含裸 IP `http://119.3.40.126/…`）下载后只做 `sh -n` 就以 root 执行，无校验和；
   - ⑤ **开 / 关硬件加速（`5 › 11`）** —— 它会 `uci set firewall.@defaults[0].flow_offloading*` 后 `fw3 reload`
     （上游源码第 20077-20086 / 69742-69749 行）。offload 与代理接管是已知冲突项，重载防火墙还会重建 nat 链；
     本机 OpenClash 是全网出口，断网代价高。真要做：另开一次、网络空闲时做、做完立刻复验 DNS 与 clash pid。
8. 跑 4) 时不许「顺手」改设备 opkg 源：它实测有守卫会原样保留（本机是 aliyun 21.02.7 的 3 条源）。
9. 不许替使用者操作那个交互式菜单，包括「帮你点一下」。菜单永远由使用者按。
10. 跑 4) 拿不到实测结果时，不许说「应该没问题」；缺哪条就说缺哪条，并说明该条为什么没测。

### 8.8 回到菜单

所有选中的功能跑完后，按 §8.1 重新输出菜单代码块，问使用者还要不要继续；只有使用者输入 `0` 才结束。
