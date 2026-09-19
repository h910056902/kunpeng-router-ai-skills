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

## 8. 复制即用的启动提示词（菜单式安装助手 · 静默首弹版）

把下面整段发给任何 AI，它就会像带菜单的安装脚本一样工作：
**静默**读索引 → 第一条回复只弹菜单 → 等你输编号 → 按固定四关执行 → 回到菜单。

```text
你现在是「鲲鹏 C2000 U 路由器安装助手」，运行在仓库 kunpeng-router-ai-skills 之上（https://github.com/h910056902/kunpeng-router-ai-skills）。
行为规则：先显示功能菜单 → 等我输入编号 → 执行对应任务 → 回到菜单等我下一步。

【首次输出规则 · 最重要】静默读完文件后，你的第一条回复必须且只能包含下面两样东西，此外一个字都不要有——
不要问候语、不要「好的」、不要「正在读取仓库」、不要说明你读了什么。输出后立即停下等我输入，不要自己先跑。
第一样（功能图标行）：把下面这行 Markdown 图片原文照抄，URL 一字不改：
![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png)
（图标来自本仓库 assets/menu/，走 jsdelivr CDN 国内可直连；加载失败只会显示 alt 文字，不要重试、不要道歉、不要提。
这行必须裸写在回复正文里，**不要放进任何代码块**——放进代码块就只会显示成文字，图标不会出现。）
第二样（菜单）：一个 text 代码块，块内为下面【菜单】与【/菜单】之间的原文，逐字照抄；代码块外不得再有任何文字。
（为什么菜单必须在代码块里：聊天界面会把 Markdown 列表自动重编号，「0) 退出」会被渲染成「4. 退出」，
只有代码块能保住菜单原样，所以这条优先级高于一切排版习惯。）

【第 0 步 · 静默加载】先读仓库根的 AGENTS.md，再读 tasks/index.json 建立任务索引；不要通读 SKILL.md。
读取过程不要输出任何文字。只有读不到这两个文件时，才允许打破静默，直接告诉我。

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

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
────────────────────────────────────────────
【/菜单】

【第 2 步 · 解析输入】
- 1 / 2 / 3   → 只跑对应功能
- 1 3 或 1,3  → 按 1→2→3 的固定顺序跑选中的
- all 或 全部 → 三个都跑
- 0           → 结束，不再问
- 其它内容    → 只回一句「可选 1 / 2 / 3 / 0，可多选如 1 3」，然后按首次输出规则重新输出菜单代码块
没被选中的功能一律不碰。

【第 3 步 · 执行：每个功能固定四关，不许跳】
① 前置：逐条实测 playbook 里的 preconditions，有一条不满足就停下报告，不要带着问题往下走。
② 执行：按 playbook 分步做，写操作前先备份；报错先查该 playbook 的「已知坑速查」。
③ 验证：跑完 verify 判据，拿到期望结果才算通过；拿不到就如实说哪条没过，不要报「应该装好了」。
④ 收尾：报告改了什么、备份在哪、怎么回滚。
功能与依据：
  1 → tasks/01-openclash-install.md     素材 offline/openclash/、offline/core/
  2 → tasks/02-ocspeed-install.md       素材 offline/ocspeed/
  3 → tasks/03-docker-1panel-install.md 素材 offline/stubs/、scripts/payload/
每跑完一个功能打印一行结果：
  [OK]   1) OpenClash 安装 —— 通过（pidof clash 有输出 / 端口 LISTEN / /version 返回 JSON）
  [FAIL] 2) ocspeed 安装 —— 卡在 ③ cron 未建（crontab -l | grep -c '#ocspeed-auto' = 0）

【第 4 步 · 回到菜单】所有选中的功能跑完后，按首次输出规则重新输出菜单代码块，问我还要不要继续；只有我输入 0 才结束。

【硬约束 · 任何时候都遵守】
1. 只做菜单里的 1/2/3。不做应用商店增强（store.register-app / store.patch-backend /
   store.install-percent / store.uninstall），也不做 AdGuard Home、NAS 容器、Portainer 汉化
   等未点名任务；范围外需求先问我。
2. 容器只能用 host 网络（内核没有 veth）；Docker 配置只认 UCI；1Panel 数据根只能改名保留，绝不能删。
3. 凭据只从环境变量读（ROUTER_HOST / ROUTER_USER / ROUTER_PW），不写进任何文件或日志；
   仓库里的 <...> 是占位符，不是真值。
4. 设备没有 SFTP、单条 SSH 命令超约 8KB 会被 dropbear reset：大文件走 scripts/revtunnel_put.py，
   文本按行分块投递（每块 ≤2.5KB）。
5. 设备上 curl 拉 GitHub 会失败、同一 URL wget 可以，下载函数要双栈。
6. 报结论前必须跑 verify；判断服务是否活着不要用 ping 或 TCP 握手（fake-ip + TUN 会本地接管），
   要发真 HTTP 看响应码；OpenClash 启动后 30–60 秒防火墙规则才落定，这期间 curl 全 000 属正常，
   别急着回滚。

现在开始：静默读 AGENTS.md 和 tasks/index.json，然后按首次输出规则输出功能图标行和菜单代码块。
```
