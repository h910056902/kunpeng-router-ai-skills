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
| 所有容器（含停止的 Exited 容器） | **dockerd 进程与配置**（`data_root` / 加速源 / `alt_config_file` 保持） |
| 所有镜像（拉回来要重新下，本机走加速源；**清空前必须实测能 pull 回来**） | **data-root 目录本身**（只清内容；`--data-root` 才会动） |
| 所有数据卷（业务数据一并消失——**加 `--backup-vols` 可先打包**） | **OpenClash / Mihomo**（原生 UCI 服务，与 Docker 无关，网络不会断） |
| 自定义 docker 网络（host / none / bridge 保留） | **host 网络默认化 wrapper**（`/usr/bin/docker-compose`，在 overlay 上，不受影响） |
| （加 `--panel-reset`）1Panel 面板程序 + 数据根 → **改名/移入备份**，可还原 | 1Panel 数据**内容**（改名归档，不是删除） |

> ⚠️ **卷是最危险的一环，必须逐个查归属**：`docker volume ls` 出来的卷名是 64 位哈希，看不出属于谁，
> 而**正在运行的容器也可能挂在卷上**（实测见过 `1Panel-ai-gateway` 就挂着一个匿名卷）。
> 查法：
> ```sh
> docker ps -a --format '{{.Names}}' | while read c; do
>   echo "--- $c"; docker inspect -f '{{range .Mounts}}{{.Type}}:{{.Source}}->{{.Destination}} {{end}}' $c
> done
> ```
> 有主的卷 → 要么 `--backup-vols` 打包后再删，要么 `KEEP_VOL="<卷名>"` 保留（**但与 `--data-root` 互斥**，
> 因为 data-root 整体清空时卷目录也在里面）。
>
> 💡 **镜像能不能重拉，清空前一定要实测**：`docker pull busybox`（1.4MB，无害）。
> `uci show dockerd | grep registry_mirrors` 里的加速源只要有一个活着就不慌；全挂了就别清镜像。

### 想连 1Panel 环境一起清（从零重装演练）

加 `--panel-reset`，它会：

1. `1paneld stop`（**先停面板**，否则它会边删边重建容器、边重写数据根）
2. 数据根 `/mnt/storage/data/1panel` → **改名** `1panel.bak-<时间戳>`（铁律：只改名，绝不删）
3. `/usr/local/bin/1panel`、`/usr/local/bin/1pctl`、`/etc/init.d/1paneld` → **移入备份** `$BK/panel-bin/`（可原样搬回）
4. 删 `/etc/rc.d/K151paneld`、`S951paneld` 两个软链（留着会指向不存在的 init 脚本报错；重装会重建）

**一条命令全量**（docker 环境 + 1Panel 环境）：

```sh
sh /tmp/kp-docker-purge.sh --apply --yes --backup-vols --data-root --panel-reset
```

重装回到 [`tasks/03-docker-1panel-install.md`](03-docker-1panel-install.md)，
或用 `offline/panel/kp-install.sh` 一把梭：`SKIP=oc sh kp-install.sh`（跳过 OpenClash 阶段，不动外网）。

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

| 文件/目录 | 内容 | 用途 |
|---|---|---|
| `containers.txt` | `docker ps -a` 全量 | 复原容器名/镜像/端口/命令的记忆 |
| `images.txt` | `docker images` 全量 | 知道要重新拉哪些镜像 |
| `volumes.txt` | `docker volume ls` | 卷名清单 |
| `volumes/<卷名>.tar.gz` | **卷内容打包**（`--backup-vols` 时生成） | 卷被删后唯一的数据救回途径 |
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
# ② 确认后真删（清容器 + 卷 + 镜像 + 自定义网络；--backup-vols 先打包卷内容）
KEEP="alist" sh /tmp/kp-docker-purge.sh --apply --yes --backup-vols
# ③ 可选：连 data-root 里的镜像层一起清（停 dockerd → 清目录 → 重启）
sh /tmp/kp-docker-purge.sh --apply --yes --backup-vols --data-root
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
| `pidof clash` 有输出、`10090` 计数 = 1 | 证明这刀没砍到 OpenClash（`10090` 在用 `--panel-reset` 时应当为 0，因为面板已停） |
| 备份目录含 ≥8 个文件 + `panel-bin/` | 少于这个数说明备份不完整，**回滚会缺依据** |
| `--backup-vols` 时 `volumes/<卷名>.tar.gz` 存在 | 这是卷数据唯一救回途径 |
| `--panel-reset` 后 `ls -d /mnt/storage/data/1panel.bak-*` 有输出 | 数据根是**改名**不是删除，必须能看到归档目录 |

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 容器 | 按 `$BK/containers.txt` 的 `IMAGE COMMAND PORTS` 重新 `docker run`（脚本不保存容器可写层，任何容器内改动都不可恢复——这是 destructive 的本义） |
| 镜像 | 按 `$BK/images.txt` 逐个 `docker pull`（走 UCI 里的加速源） |
| 数据卷 | 有 `--backup-vols` 时：`docker volume create <卷名>` → `tar -xzf $BK/volumes/<卷名>.tar.gz -C $(docker volume inspect -f '{{.Mountpoint}}' <卷名>)`。没打包过则**不可恢复** |
| dockerd UCI | `uci import dockerd < $BK/uci-dockerd.txt && uci commit dockerd && /etc/init.d/dockerd restart` |
| alt_config_file | `cp $BK/daemon.json /etc/docker/daemon.json` 并确认 `uci get dockerd.globals.alt_config_file` 指向它 |
| 1Panel apps 目录 | `mv /mnt/storage/data/1panel/apps.bak-<ts> /mnt/storage/data/1panel/apps` |
| **1Panel 整个环境** | `mv /mnt/storage/data/1panel.bak-<ts> /mnt/storage/data/1panel` → `cp $BK/panel-bin/1panel $BK/panel-bin/1pctl /usr/local/bin/` → `cp $BK/panel-bin/1paneld /etc/init.d/` → `/etc/init.d/1paneld enable && /etc/init.d/1paneld start` |
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
- 若紧接着做 1Panel 重装演练：进入 `tasks/03-docker-1panel-install.md`，从 §3「装 1Panel」开始（Docker 本体已在），
  或直接 `SKIP=oc sh kp-install.sh`（幂等、跳过 OpenClash 阶段）
- 演练结论回写 `memory/YYYY-MM-DD.md`（设备上真实发生了什么、耗时、踩到的坑）

---

## 9. 实战记录（2026-09-19 真机演练，C2000 U）

命令：`sh /tmp/kp-docker-purge.sh --apply --yes --backup-vols --data-root --panel-reset`

| 阶段 | 实测结果 |
|---|---|
| 清前现状 | 容器 2（`1Panel-ai-gateway-GR7n` **正在运行 healthy**、`1Panel-deepseek-harness-zd4d` Exited）· 镜像 6（合计 1.1 G）· 卷 1 · 网络 4 |
| 卷归属排查 | 唯一那个匿名卷 `084dafc1…` 属于**正在运行的 ai-gateway**（挂 `/opt/ai-gateway`）——只删不查就会带走它的数据 |
| 卷打包 | 11 KB 原始 → `volumes/084dafc1….tar.gz`（tar 后几乎不占空间） |
| 清理 | 容器 2→0、镜像 6→0、卷 1→0、网络 4→3（`1panel-network` 删除） |
| data-root | 1.1 G → 296 K（12 个子目录清空）· dockerd 重启后 pid 31586 |
| 1Panel 复位 | 数据根 → `1panel.bak-20260919_203034`；`1panel`/`1pctl`/`1paneld` → `$BK/panel-bin/` |
| 未受影响 | **clash pid 16659 全程在**（网络没断）· compose wrapper 完好 · dockerd UCI 加速源完好 |
| 空间回收 | `/mnt/storage/data` 已用 1.87 G → 752 M（**回收约 1.1 G**） |
| 清后冒烟 | `docker pull hello-world` + `docker run --rm --network host hello-world` 一次通过，`overlay2 / f2fs / /mnt/storage/data/docker` 全部正确 |

**三条实测教训**（已写进上面的表格与脚本）：

1. **匿名卷可能属于正在运行的容器** —— 删前必须 `docker inspect` 查归属，否则静默带走数据。
2. **`--data-root` 与 `KEEP_VOL` 互斥**（卷目录就在 data-root 里）—— 要保数据只能 `--backup-vols` 先打包。
3. **`--panel-reset` 必须先停 `1paneld`** —— 面板活着时删容器，它可能边删边重建。

### 清空后的重装（同一晚实测，闭环验证）

```sh
# 上传 offline/panel/*.sh 到 /tmp/kp1pt，然后：
cd /tmp/kp1pt && SKIP=oc sh kp-install.sh
```

| 阶段 | 实测结果 |
|---|---|
| [1/4] 预检换源 | ✓ opkg 源已就绪（幂等，没重复改源）· 5 s |
| [2/4] OpenClash | 按 `SKIP=oc` 跳过 —— **clash pid 全程不变，网络没断** |
| [3/4] Docker | ✓ 回读 `overlay2 / /mnt/storage/data/docker`；host 网络冒烟通过 · 1 s |
| [4/4] 1Panel | ✓ 安装包 SHA256 校验 → 文件就位 → 凭据播种 → **HTTP 200** · 38 s |
| 面板 | 新入口 `http://192.168.66.1:10090/<随机路径>`，凭据写入 `/root/1panel-credentials.txt`，`S951paneld` 自启链接重建 |
| 总用时 | **44 s**（docker 环境已清空的前提下一把装回） |

> ⚠️ **重装会覆盖 `/root/1panel-credentials.txt`**：旧面板的入口路径与密码就此丢失（旧数据仍在 `1panel.bak-*` 里，
> 想回旧环境要按 §6 那行搬回去，但镜像已被删，各应用首次启动需重新拉取）。
>
> ⚠️ **busybox 没有 `setsid`**：想在设备上后台跑长任务，用 `nohup ... &`（`nohup` 本机实测存在），
> 别照搬 PC 侧的习惯。
