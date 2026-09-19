# Docker 移植（缺 kmod 的官方固件）

目标固件内核 5.4.281（mt7987 定制）**缺 veth 及 kmod 系列**，且无匹配源 → 桥接网络不可用。最终方案：host 网络模式 + vfs 存储驱动，实测 Filebrowser/AdGuard Home 容器全链路可用。

## 已知短板（选型前必读）

| 短板 | 影响 | 对策 |
|---|---|---|
| 无桥接，只有 host 网络 | 不能端口映射，端口冲突写死；无容器网络隔离 | 每个容器规划独占端口；信任的轻应用才上容器 |
| vfs 存储驱动 | 层不共享、空间翻倍、启动慢、写放大 | 重 IO 应用（NAS/数据库）改走原生 opkg |
| 493MB 内存 | 再塞一个大容器就 OOM | 容器内存 ≤15MB 级才考虑（AGH +44MB 已是极限） |
| 依赖靠 stub ipk | 固件 OTA 后 stub/dockerd 可能失效需重打 | 升级固件前备份 /opt/docker 与 stub 包 |
| dockerd 20.10.17 偏老 | 新镜像要求新 API/cgroup 特性可能起不来 | 选 alpine 系老标签镜像 |
| 运维手动挡 | rc.local 拉起无守护；日志无轮转 | 可加 log rotate 配置（max-size）+ procd 服务化 |

**结论**：适合 1-2 个轻量常驻容器（DNS、文件管理）；当小 NAS 主力存储/多容器平台不合适——NAS 服务走原生 opkg（见 `nas-upgrade.md`）。

## 镜像选型：只选 Go/Rust 单文件镜像（vfs 硬约束）

vfs 会把镜像展开成完整目录树，**文件数量和镜像体积直接决定能不能用**：

| 类型 | 例子 | 表现 | 结论 |
|---|---|---|---|
| Go/Rust 单文件 | **Portainer CE alpine**（实测 15MiB 内存、拉取 4 分钟）、AGH、Dozzle | 文件少、启动快 | ✅ 推荐 |
| Node 全家桶 | **Dockge**（769MB / node_modules 几万小文件） | 拉取 15 分钟、`docker run` 挂 280 秒不返回 | ❌ 禁用 |
| 同属 Node 的 Yacht | Yacht | 同上 | ❌ 不用 |

- Docker 管理面板首选 **Portainer CE**：`portainer/portainer-ce:alpine`，host 网络，端口 :9000（HTTPS :9443），数据 `/opt/docker/data/portainer`，首次访问在网页设管理员密码
- 参考值（2026 实测）：Dockge 35-60MB 内存、Portainer 60-110MB、Yacht ~45MB、Komodo（Rust，多组件）、Arcane（Go 新秀）——但内存不是唯一指标，**镜像体积/文件数才是 vfs 上的生死线**

## 操作纪律（否则会出现“幽灵容器”）

1. **所有 docker pull / run 必须后台化**：`nohup sh -c 'docker ...' > /tmp/x.log 2>&1 &` 再轮询（前台 180 秒必超时）
2. 超时被断开会留下**名字被占但 `docker ps -a`/`inspect` 查不到**的幽灵容器，`docker rm -f` 也报 No such container → 只能 `/etc/init.d/dockerd restart` 清索引
3. 判断镜像是否拉取成功不要用 `docker images | grep`（会命中表头），看 `docker images` 全量输出
4. dockerd 实际读的是 `/tmp/dockerd/daemon.json`（不是 /etc/docker/daemon.json），改配置前先确认

## 关键决策

| 问题 | 方案 |
|---|---|
| dockerd 依赖 6 个 kmod 无源可装 | 用 Python tarfile 造 **stub 空 ipk** 满足依赖解析（见下） |
| veth 缺失 → 桥接不可用 | daemon.json 设 `bridge=none`，容器一律 `--network=host` |
| overlay2 在 f2fs 上不可用 | 存储驱动 `vfs`（慢但稳） |
| 493MB 内存吃紧 | 1GB swap：`dd` 到 /overlay/.docker-swap + swapon，写入 rc.local 开机生效 |
| 镜像/容器数据持久化 | /opt/docker |

## Stub ipk 的坑（最重要）

1. **opkg 拒绝 unresolved 依赖**，即使 `--force-depends` 也会在候选解析阶段失败 → stub 是唯一干净路径
2. **此固件 opkg 的 ipk 不是 ar 归档**，而是老式 gzip+tar 嵌套：
   - 外层 `data.tar.gz` / `control.tar.gz`（gzip 压缩的 tar）
   - 最外层再 gzip 一层成 `.ipk`
   - Python tarfile 默认 PAX 格式写出的 tar 老式 opkg 不认（报 "Malformed"）→ 必须用 `tarfile.GNU_FORMAT`/USTAR 老格式重建
3. 参考实现见 `scripts/setup_docker.py`（含 stub 造包、dockerd 安装、daemon.json、swap、注册进商店）

## 容器实践

- host 模式下端口直接占宿主端口：Filebrowser :8180、AGH :3000/:53
- 容器内 uid 1000 跑 filebrowser → 挂载目录需 `chmod 777`
- 新版 filebrowser admin 密码随机生成，在容器日志里查
- AGH 免交互初始化：POST `/control/install/configure` API
