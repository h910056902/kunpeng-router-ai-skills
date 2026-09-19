# C2000 U（B 机）· NAS 影视墙容器实测档案（2026-09-14）

> 前提：**内核无 VETH（`CONFIG_VETH/MACVLAN/IPVLAN` 全 not set，厂商 `kmod-veth` 是空包）**
> → Docker 桥接网络不可用，**所有容器必须 `--network host`**，端口直接占宿主机。
> 数据根目录约定：`/mnt/storage/data/media/`（**TF 卡** p2 f2fs，3.5G，装完镜像后余量紧张）。

## 一、实测结果总表

| 应用 | 镜像 | 镜像大小 | 拉取耗时 | 端口 | 结果 |
|---|---|---|---|---|---|
| **Alist** | `xhofe/alist:latest` | 129MB | 33s | 5244 | ✅ HTTP 200。初始密码在 `docker logs alist`（`Successfully created the admin user ...`） |
| **Navidrome** | `deluan/navidrome:latest` | 232MB | 45s | 4533 | ✅ 302（跳登录，正常）。音乐墙，Go 单文件，内存仅 ~19MB |
| **FileBrowser** | `filebrowser/filebrowser:latest` | 36.5MB | 20s | 8082 | ✅ 200。⚠️ 官方 2026-09-01 已归档停更 |
| **Jellyfin** | `jellyfin/jellyfin:latest` | **867MB** | 6m32s（多层重试） | 8096 | ⚠️ 拉取 OK，启动看磁盘；RSS **218MB**，992MB 内存机器上吃紧 |

## 二、可直接复用的启动命令（host 网络）

```sh
D=/mnt/storage/data/media
mkdir -p $D/{alist,navidrome,filebrowser,movies,music}

# Alist —— 网盘/本地聚合，可对外提供 WebDAV 给影视墙
docker run -d --name alist --network host --restart unless-stopped \
  -v $D/alist:/opt/alist/data -e PUID=0 -e PGID=0 -e UMASK=022 xhofe/alist:latest

# Navidrome —— 音乐墙
docker run -d --name navidrome --network host --restart unless-stopped \
  -v $D/music:/music:ro -v $D/navidrome:/data -e ND_PORT=4533 deluan/navidrome:latest

# FileBrowser —— 轻量文件/影视目录浏览
chmod -R 777 $D/filebrowser
docker run -d --name filebrowser --network host --restart unless-stopped \
  -v $D:/srv -v $D/filebrowser:/database \
  filebrowser/filebrowser:latest --port 8082 --address 0.0.0.0 --database /database/filebrowser.db

# Jellyfin —— 影视墙（仅当 config 分区可用空间 ≥2GiB 时才可能启动）
docker run -d --name jellyfin --network host --restart unless-stopped \
  -v /overlay/jellyfin/config:/config -v /overlay/jellyfin/cache:/cache \
  -v $D/movies:/media jellyfin/jellyfin:latest
```

访问：`http://192.168.66.1:<端口>`（host 网络无需端口映射）。

## 三、坑清单

1. **filebrowser 挂载**：`-v 目录:/database.db`（当文件挂）→ `is a directory`；非 root 运行需 `chmod -R 777`；
   默认只听 127.0.0.1，LAN 访问要 `--address 0.0.0.0`。
2. **Jellyfin 启动自检**：硬要求 `/config` 所在分区可用空间 ≥2GiB（`Available: 1.6GiB, Required: 2GiB`）。
   数据分区装完 867MB 镜像后必然不满足 → 把 config/cache 挂到 `/overlay`（3.1G 可用）绕过。
   即便启动成功，Kestrel 会报 thread pool starvation（CPU 弱），RSS 218MB。
3. **alist 初始化告警无害**：qBittorrent/Transmission/aria2 连不上只是它试图探测本机下载器。
4. **空间预算**：eMMC 数据分区 3.5G，Redis(166MB)+alist+navidrome+filebrowser+jellyfin ≈ 1.4G，
   加 dockerd 元数据后余量很小 → **影视墙真心要用请外接存储或按需只留 1-2 个镜像**。

## 四、内存账本（2026-09-14 实测，992MB 总内存）

清理前可用 **280MB** → 清理后 **434MB**（删 3 个 Exited 测试容器 + 停 jellyfin）。

| 进程 / 容器 | RSS |
|---|---|
| jellyfin（已停） | 218MB |
| 1panel | 70MB |
| clash（**openclash，用户要求保留**） | 65MB |
| dockerd | 40MB |
| alist | 33MB |
| containerd | 23MB |
| navidrome | 19MB |
| zeroclaw | 14MB |
| filebrowser | 13MB |
| quickstart | 12MB |
| mihomo（**clash-verge-router，与 openclash 重复的第二套代理**） | 11MB |

后续可腾挪项（按收益排序）：jellyfin 容器（若再开）/ 1Panel 面板（用时再开 `/etc/init.d/1paneld start`）
/ 停 clash-verge-router（重复代理，先确认流量不走它）/ 停 `telnetd`（明文服务，安全收益 > 内存收益）。

巡检脚本：`kp-docker1panel/mem-report.sh`（进程 RSS Top 25 + 自启服务列表 + 容器状态）。
拉取脚本：`kp-docker1panel/media-pull-test.sh`（支持 `light` 只拉轻量三件套、`ONLY=<name>` 拉单个）。
