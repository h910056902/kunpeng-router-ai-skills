# 任务 04 · 清空 Docker 环境与容器（重装演练的前置动作）

> `id: docker.purge` · `risk: **destructive**`（不可逆；唯一救赎是动手前的备份快照）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，内核 5.4.281，OpenWrt 21.02，TF 卡存储）
> 目标：把设备上的 **容器 / 镜像 / 数据卷 / 自定义网络** 清干净，让 Docker 回到「刚装完、能跑 hello-world」的裸状态，
> 用于 1Panel 重装演练、镜像层损坏排障、TF 卡空间回收。
> 一键脚本：[`scripts/payload/kp-docker-purge.sh`](../scripts/payload/kp-docker-purge.sh)（默认 dry-run，双开关才真删）
> 复装走：[`tasks/03-docker-1panel-install.md`](03-docker-1panel-install.md)

---

## ⚠️ 0. 先看清楚：这一刀会砍掉什么

| 会被清掉 | 不会被清掉（除非你显式加开关） |
|---|---|
| 所有容器（含停止的 Exited 容器） | **1Panel 面板本身**（它是原生进程 + `/etc/init.d/1paneld`，不是容器） |
| 所有镜像（拉回来要重新下，本机走加速源） | **1Panel 数据根** `/mnt/storage/data/1panel`（只改名归档，铁律） |
| 所有数据卷（卷里的业务数据一并消失） | **dockerd UCI 配置**（`data_root` / 加速源 / `alt_config_file` 保持） |
| 自定义 docker 网络（host / none / bridge 保留） | **data-root 里的镜像层**（要 `--data-root` 显式开关才动） |
| — | **OpenClash / Mihomo**（原生 UCI 服务，与 Docker 无关，网络不会断） |

**开始前必须让用户逐条确认的三件事**（缺一条就别动手）：

1. 待删容器清单（脚本 dry-run 会打印），里面**有没有还要用的**？要保留的写进 `KEEP="alist foo"`。
2. 有没有容器**存着唯一一份数据**（卷里 / 挂载目录里）？有就必须先单独归档。
3. 清空后是否立刻复装（走任务 03）？还是保持空环境给别的事情用。

> 🔴 **AI 助手请注意**：这是 `destructive` 任务。**必须先跑 dry-run 把清单展示给用户、拿到明确同意，才能加 `--apply --yes`**。
> 用户说「随便清」「你看着办」都不算确认——要具体到「清单里这 3 个容器可以删」。

---

## 1. 前置检查

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| 1 | SSH 可达 | `echo ok` | `ok` | 见 `references/no-ssh-recovery.md` |
| 2 | 存储就绪 | `awk '$2=="/overlay"{print $1}' /proc/mounts` | `/dev/mmcblk0p1` | `mtdblock8` → overlay 丢了，先 `restore.all` |
| 3 | 数据分区已挂 | `df -k /mnt/storage/data \| tail -1` | 有可用空间 | 见 `references/one-command-restore.md` 的 `ensure_data()` |
| 4 | Docker 可用 | `docker ps -a` | 能列出（含空） | dockerd 没起来就先 `/etc/init.d/dockerd start` |
| 5 | 备份目录可写 | `mkdir -p /mnt/storage/data/kpbackup && touch /mnt/storage/data/kpbackup/.w` | 成功 | 清理 TF 卡空间 |
| 6 | **已拿到用户对清单的确认** | — | 明确同意 | **停下，回到 §0 逐条问** |

```sh
# 一次性跑完（设备侧，只读）
echo "--- 1 ssh"; ok
echo "--- 2 ovl"; awk '$2=="/overlay"{print $1}' /proc/mounts
echo "--- 3 data"; df -k /mnt/storage/data | tail -1
echo "--- 4 docker"; docker ps -a 2>&1 | head -20
echo "--- 5 bakdir"; mkdir -p /mnt/storage/data/kpbackup && echo writable
```

---

## 2. 备份快照（真删前必做，脚本自动完成）

脚本在 `--apply` 时会先建 `$BK = /mnt/storage/data/kpbackup/docker-purge-<时间戳>/`，写入：

| 文件 | 内容 | 用途 |
|---|---|---|
| `containers.txt` | `docker ps -a` 全量 | 复原容器名/镜像/端口/命令的记忆 |
| `images.txt` | `docker images` 全量 | 知道要重新拉哪些镜像 |
| `volumes.txt` | `docker volume ls` | 卷名清单 |
| `networks.txt` | `docker network ls` | 自定义网络清单 |
| `docker-info.txt` | `docker info` | 驱动 / data-root / 加速源当时的真实值 |
| `uci-dockerd.txt` | `uci export dockerd` | **UCI 回滚依据**（配合 `--reset-uci` 用） |
| `daemon.json` | `/etc/docker/daemon.json` 副本（存在时） | alt_config_file 内容 |
| `1Panel.db` | 1Panel 面板数据库副本 | 面板账号/应用记录（配合 `--panel-apps` 用） |
| `df.txt` / `data-root-ls.txt` | 磁盘与 data-root 现状 | 事后对比空间回收效果 |

> **镜像能不能救回来？** 不能「还原」，但可以「重拉」：`images.txt` 里有完整 `REPOSITORY:TAG` 列表，
> 复装时按它 `docker pull` 即可。**别指望 `docker save`** —— aarch64 + overlay2 下导出 tar 会吃掉 TF 卡几倍空间，得不偿失。

---

## 3. 执行（脚本一键，五步）

```sh
# ① 先预览，把清单贴给用户确认（安全，不删任何东西）
sh /tmp/kp-docker-purge.sh
# ② 确认后真删（清容器 + 卷 + 镜像 + 自定义网络）
KEEP="alist" sh /tmp/kp-docker-purge.sh --apply --yes
# ③ 可选：连 data-root 里的镜像层一起清（停 dockerd → 清目录 → 重启）
sh /tmp/kp-docker-purge.sh --apply --yes --data-root
# ④ 可选：1Panel 应用工作目录改名归档（**只改名不删**）
sh /tmp/kp-docker-purge.sh --apply --yes --panel-apps
# ⑤ 可选：复位 dockerd UCI（会丢 overlay2/加速源配置，慎用）
sh /tmp/kp-docker-purge.sh --apply --yes --reset-uci
```

脚本内部顺序（也是手工执行的正确顺序）：

1. **盘点** → 列出待删清单
2. **备份快照** → `$BK/`（失败即 `exit 2`，不进入删除）
3. **停容器** → `docker stop -t 10`（优雅停，超时强杀在后面）
4. **删容器 → 删卷 → 删镜像 → 删自定义网络**（顺序不能反：镜像被容器占用时删不掉）
5. **按开关处理 data-root / 1Panel apps / UCI**，最后验证

> **为什么不是 `docker system prune -a`？**
> prune 不带备份、不打印待删清单、`--volumes` 会静默吞掉数据卷，且在本机这种「镜像本来就少」的场景省不了多少事。
> 显式逐项删 + 先备份，才配得上 `destructive` 这个风险等级。

---

## 4. 清空后复装（闭环）

```sh
# Docker 本体没被卸，此时应能直接拉起
docker run --rm --network host hello-world      # 再拉一次 hello-world
# 若镜像层被清（用了 --data-root），driver 仍应是 overlay2：
docker info | grep -E 'Storage Driver|Docker Root Dir'
# 1Panel 面板若也要重装 / 恢复应用
sh /tmp/kp1pt/kp-install.sh                     # 见 tasks/03 §3
sh /tmp/kp-docker-purge.sh --help               # 随时回看开关
```

再装任意 1Panel 应用前，**先确认 host 默认化装置还在**（它是装应用不报 veth 错的前提）：

```sh
ls -l /usr/bin/docker-compose /usr/bin/docker-compose.real
```

---

## 5. 验证判据

```sh
# ① 四清（数字必须是 0）
echo "容器=$(docker ps -aq | grep -c .)  镜像=$(docker images -q | grep -c .)  卷=$(docker volume ls -q | grep -c .)"
# ② 网络只剩默认三个
docker network ls --format '{{.Name}}' | sort | tr '\n' ' '
#    期望：bridge host none
# ③ dockerd 还活着
pidof dockerd
# ④ 属主服务没被误伤（这俩跟 docker 无关，必须还活着）
pidof clash ; netstat -ltn | grep -cE ':10090\b'
# ⑤ 备份在位且非空
ls -la /mnt/storage/data/kpbackup/docker-purge-*/ | head -20
# ⑥ 空间回收（和 $BK/df.txt 对比）
df -k /mnt/storage/data | tail -1
```

| 期望 | 说明 |
|---|---|
| 容器/镜像/卷 = 0 | 任一不为 0 → 有容器在自动重启（查 `/etc/init.d/` 与 watchtower 类守护） |
| 网络 = 3（bridge/host/none） | 少一个说明删过头（`bridge` 虽不可用但别删，dockerd 启动依赖它的默认定义） |
| `pidof dockerd` 有输出 | 没输出 → `/etc/init.d/dockerd start` 并把报错原文抄给用户 |
| `pidof clash` 有输出、`10090` 计数 = 1 | 证明这刀没砍到 OpenClash / 1Panel 面板 |
| 备份目录含 ≥8 个文件 | 少于这个数说明备份不完整，**回滚会缺依据** |

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 容器 | 按 `$BK/containers.txt` 的 `IMAGE COMMAND PORTS` 重新 `docker run`（脚本不保存容器可写层，任何容器内改动都不可恢复——这是 destructive 的本义） |
| 镜像 | 按 `$BK/images.txt` 逐个 `docker pull`（走 UCI 里的加速源） |
| 数据卷 | **不可恢复**（除非事先单独归档过卷内容）。事后靠 1Panel 应用重装重建 |
| dockerd UCI | `uci import dockerd < $BK/uci-dockerd.txt && uci commit dockerd && /etc/init.d/dockerd restart` |
| alt_config_file | `cp $BK/daemon.json /etc/docker/daemon.json` 并确认 `uci get dockerd.globals.alt_config_file` 指向它 |
| 1Panel apps 目录 | `mv /mnt/storage/data/1panel/apps.bak-<ts> /mnt/storage/data/1panel/apps` |
| 1Panel 数据库 | 停 `1paneld` → `cp $BK/1Panel.db /mnt/storage/data/1panel/db/1Panel.db` → 起 |
| 整机兜底 | `restore.all`（`tasks/03 §5` 的一条命令全装） |

---

## 7. 已知坑速查（本任务相关）

| 症状 | 原因 | 修法 |
|---|---|---|
| `docker rm` 报 `container is running` | 没用 `-f`，或 stop 超时被忽略 | 脚本用 `docker rm -f`；手工时先 `docker stop -t 10` |
| 镜像删不掉 `image is being used by ...` | 还有容器（含 Exited）引用它 | 先删容器，再删镜像（脚本顺序已固定） |
| 删完过一会儿又冒出来 | 有守护/自启在拉（1Panel 应用计划任务、`/etc/init.d/S99*`） | 先停对应守护；1Panel 侧先在面板停应用 |
| 清空后 dockerd 起不来 | `--data-root` 清空时把目录本身删了，或 UCI 指向不存在的路径 | `mkdir -p /mnt/storage/data/docker` 后 `/etc/init.d/dockerd start` |
| 网络删过头，dockerd 报 `bridge not found` | 误删了默认 `bridge` | `docker network create bridge` 或重启 dockerd 让其重建；`docker network prune` 别乱跑 |
| 面板 10090 打不开 | 把 1Panel 数据根整个删了 | 铁律：**只能改名**。改名回来的命令见 §6 |
| `docker ps` 卡住不返回 | TF 卡 IO 慢 / data-root 在坏块上 | 等 30 s；仍卡则 `stop dockerd`，查 `dmesg | tail` 有无 f2fs 报错 |

---

## 8. 完成后

- 向用户报告：**删了什么**（容器/镜像/卷/网络各自数量）、**备份在哪**（`$BK` 绝对路径）、**怎么回滚**（指向 §6 对应行）
- 若紧接着做 1Panel 重装演练：进入 `tasks/03-docker-1panel-install.md`，从 §3「装 1Panel」开始（Docker 本体已在）
- 演练结论回写 `memory/YYYY-MM-DD.md`（设备上真实发生了什么、耗时、踩到的坑）
