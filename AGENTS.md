# AGENTS.md — 给 AI Agent 的入口（先读这个）

> 本文件是**机器可读入口**，写给任何读这个仓库的 AI（Codex / Claude Code / Cursor / WorkBuddy …）。
> 人类读者请直接看 [`README.md`](README.md)。
> 本仓库操作的是**真实路由器**，写操作会真的改设备。执行前先读完本文件的「高危禁令」。

## 0. 三行硬指示

1. **要做什么 → 先查 [`tasks/index.json`](tasks/index.json)**：按 `id` / 关键词取任务，拿到 `playbook` 与 `risk`，**不要通读 `SKILL.md`**（248 行、61 KB，只为人类索引而存在）。
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

其余 ~30 个任务（商店补丁、AGH、NAS、面板排障、无 SSH 救援、TF 扩容…）见 `tasks/index.json`。

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

## 8. 复制即用的启动提示词

```text
你正在操作一台真实的鲲鹏 C2000 U 路由器（192.168.66.1，OpenWrt，992MB 内存，
内核 5.4.281，Docker/1Panel/OpenClash 已装）。请遵守以下约定：

1. 先读仓库根的 AGENTS.md，再读 tasks/index.json，按 id 定位任务；不要通读 SKILL.md。
2. 执行任何写操作前：读该任务的 preconditions 并逐条实测确认；不满足就先停下说明。
3. 三条硬约束：容器只能 host 网络（内核无 veth）；设备无 SFTP 且单条 SSH 命令
   超 ~8KB 会被 reset；opkg 出厂源全失效，必须先换阿里云 21.02.7。
4. 凭据只从环境变量读（ROUTER_HOST / ROUTER_USER / ROUTER_PW），不要写进文件或日志。
5. 每次改动后 grep 读回验证、复核 free -k、并告诉我改了什么/备份在哪/怎么回滚。

我的目标：______（例如「装 OpenClash 并拉好 Mihomo 内核」）
```
