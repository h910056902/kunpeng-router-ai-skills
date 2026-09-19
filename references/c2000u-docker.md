# 第二台设备：鲲鹏 C2000 U（C2000-798 / WT9500）Docker 适配与实装

> 状态：**✅ 已安装并全链路实测通过**（2026-09-11 10:13 GMT+8）
> 过程：只读探测 → 零安装二进制试运行 → 换源 → 造 stub → 装包 → 配 daemon.json → 拉镜像 → 跑容器 → 生命周期回归
> **关键成果**：`storage-driver = overlay2`（backing fs **f2fs**），data-root `/mnt/storage/data/docker`，开机自启已开
> 复现脚本：`scripts/setup_docker_c2000u.py`（配 `scripts/rtr_lib.py`）

## ⭐ 实装记录（2026-09-11，全部实测数据）

| 步骤 | 结果 |
|---|---|
| 备份出厂源 | `/etc/opkg/distfeeds.conf.bak-c2000u-20260911_100247`（702B） |
| 换源 | `21.02-SNAPSHOT`（已 404）→ 阿里云 `21.02.7` 的 base/packages/routing；`opkg update` **3.0s**，签名校验通过 |
| 造 stub | 6 个：`kmod-veth` `kmod-br-netfilter` `kmod-ikconfig` `kmod-nf-ipvs` `btrfs-progs` `libdevmapper` |
| 装真包 | `libseccomp 2.5.1-1` `libnetwork` `tini 0.19.0-2` `runc 1.1.2-1` `containerd 1.6.6-1` `dockerd 20.10.17-1` `docker 20.10.17-1` |
| 配置落地 | `uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json'` → init 软链 `/tmp/dockerd/daemon.json` |
| 存储驱动 | **overlay2**，`Backing Filesystem: f2fs`（老 Max 只能 vfs） |
| data-root | `/mnt/storage/data/docker`（首次拉镜像后实占 8.2M，overlay2 子目录 7.8M → **无翻倍放大**） |
| 拉镜像 | `alpine:3.19` 走加速源，**7.73MB**，checksum 通过 |
| 跑容器 | `--network=host` 起 alpine，容器内可见宿主 `eth0 192.168.1.6`，`nslookup mirrors.aliyun.com` 解析成功 |
| 挂载/写盘 | `-v /tmp:/hosttmp` 写入成功，宿主侧 `cat` 回读一致 |
| 生命周期 | `run -d` → `ps` → `stats`（720KiB/992.6MiB）→ `exec` → `stop` → `rm` 全通 |
| 服务重启后 | 配置持久（软链重建、仍为 overlay2） |
| CLI 速度 | PC 侧计时（含 SSH 往返）**0.01–0.07s**（老 Max vfs 时代 4–9s） |
| 内存占用 | dockerd RSS ≈ 59.7MB + containerd ≈ 38.4MB；系统 available 仍 **≈668MB** |
| 开机自启 | `/etc/rc.d/S99dockerd` 已建 |

### 最终生效的 `/etc/docker/daemon.json`

```json
{
  "data-root": "/mnt/storage/data/docker",
  "storage-driver": "overlay2",
  "bridge": "none",
  "iptables": false,
  "log-level": "warn",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" },
  "registry-mirrors": ["https://docker.1ms.run", "https://docker.m.daocloud.io"]
}
```

`docker info` 回读：`Storage Driver: overlay2` / `Backing Filesystem: f2fs` / `Docker Root Dir: /mnt/storage/data/docker` /
`Registry Mirrors: https://docker.1ms.run/ , https://docker.m.daocloud.io/`（**已确认真正生效**，不是只写在文件里）

### 三个决定性机制（别的 AI 必须知道）

1. **配置只能走 `alt_config_file`** —— init 脚本 `/etc/init.d/dockerd` 的 `process_config()` 只会生成
   `data-root / log-level / iptables / bip / registry-mirrors / hosts / dns / ipv6 / ip / fixed-cidr*`，
   **没有 `storage-driver`，也没有 `bridge`**。想要这两项，唯一正路是：
   ```sh
   uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json'
   uci commit dockerd
   ```
   此时 init 会 `rm -rf /tmp/dockerd` 后 `ln -s /etc/docker/daemon.json /tmp/dockerd/daemon.json`，
   dockerd 以 `--config-file=/tmp/dockerd/daemon.json` 启动 → **文件全文完全由你掌控**。
   （直接写 `/etc/docker/daemon.json` 而不设 UCI 是**无效**的，dockerd 读的是 `/tmp/dockerd/daemon.json`）
2. **opkg 会被 feed「同名包截胡」** —— 用 `opkg install /tmp/xxx.ipk` 装本地 stub 时，**若 feed 里存在同名包，
   opkg 会优先解析 feed 候选并忽略你本地文件里的 control**，报出你 stub 里根本没有的依赖
   （本次 `btrfs-progs` 报 `cannot find dependency kmod-fs-btrfs`，正是 feed 版的依赖）。
   解法：**临时把 `/var/opkg-lists` 移走**再装，装完移回：
   ```sh
   mv /var/opkg-lists /var/opkg-lists.off
   opkg install --force-reinstall /tmp/dockerstubs/btrfs-progs_5.11-1_aarch64_cortex-a53.ipk
   rm -rf /var/opkg-lists; mv /var/opkg-lists.off /var/opkg-lists
   ```
3. **本机无 SFTP**（`ls /usr/libexec/sftp-server` 不存在，paramiko `open_sftp()` 报
   `SSHException: EOF during negotiation`）→ 传文件只能靠 `exec_command`：
   - 文本 → heredoc `cat > f << 'TAG'`，末尾 md5sum 对账
   - **二进制 → `printf '\NNN\NNN...' > f`**（3 位八进制转义全字节覆盖，实测 256B/900B 均字节级精确）。
     注意固件**没有 base64/openssl/xxd/python3**，`printf` 是唯一可用通道；单条命令别超 ~10KB。

## 设备档案（设备自报，硬编码事实）

| 项 | 值 |
|---|---|
| 产品名 | `C2000-798`（`uci get oem.board.pname`） |
| 板型 | `HC-WT9500`（`/tmp/sysinfo/model`、`/proc/device-tree/model`） |
| 硬件 ID | `HCMT7987-SNSD` |
| 厂商字段 | `vendor=nradio`、`ptype=rt`、`feature.cpe=2` |
| SoC | MediaTek **MT7987**，4× Cortex-A53（aarch64），Wi-Fi 芯片 MT7992 |
| 内存 | **1016432 kB ≈ 992MB**，无 swap |
| 存储 | `mmcblk0` **7.5 GiB**（**TF/SD 卡**，非 eMMC）：p1 4.0G=f2fs `/overlay`(3.7G 可用)、p2 3.5G=f2fs `/mnt/storage/data`(3.2G 可用) |
| 系统 | OpenWrt **21.02-SNAPSHOT**，rev `2.3.0.n0.c1`，sdk `f3dad89b`，target `mediatek/mt7987` |
| 内核 | **5.4.281**（与老 Max 完全一致） |
| LuCI | **git-26.253.32058-228b00a**（比老 Max 的 git-26.224 更新，**同样禁装旧 luci-compat**） |
| 商店 | `/etc/init.d/appcenter` + `/usr/sbin/appcenter` 在，**但 `/etc/kp_store` 目录不存在**（无 installed.list / plugins.json） |
| 蜂窝 | IMEI/ICCID 已写入，`/dev/ttyUSB0-3`，cellular_* 系列 init 脚本齐全；当前走有线 WAN |
| 网络 | WAN=eth0（DHCP 到 192.168.1.6，上级 192.168.1.1）；LAN=br-lan 192.168.66.1；eth1/eth2 在 br-lan；ra0/rai0 无线 |

## 结论：✅ 可以适配，条件优于老 Max

**决定性证据**（零安装，直接解包跑二进制）：

```
Docker version 20.10.17, build a89b842
RC:0
```

## 硬门槛实测（13 项：11 通过 / 1 受限 / 1 需绕行）

| 门槛 | 结果 | 证据 |
|---|---|---|
| CPU 架构 | ✅ | `aarch64_cortex-a53`，与老 Max 同源，包可直接复用 |
| 内存 | ✅ | `MemTotal 1016432 kB`，`MemAvailable` 约 690MB |
| 存储 | ✅ | overlay 3.7G + data 3.2G ≈ 6.9G |
| dockerd 可得 | ✅ | 21.02.7 源有 dockerd 20.10.17 / containerd 1.6.6 / runc 1.1.2 / libnetwork / tini / libseccomp；阿里云镜像 200 / 0.85s |
| 二进制可跑 | ✅ | 实测 `dockerd --version` 通过 |
| cgroup | ✅ | **cgroup v2** 挂 `/sys/fs/cgroup`，`cpuset cpu io memory pids rdma` 全在（无 v1 层级） |
| Namespace | ✅ | UTS / IPC / USER / PID / NET 全在 `/proc/self/ns` |
| overlayfs | ✅ | `CONFIG_OVERLAY_FS=y`；**实体挂载 RC:0** |
| seccomp | ✅ | `CONFIG_SECCOMP` + `SECCOMP_FILTER=y`（需装 `libseccomp`） |
| 转发/iptables | ✅ | `net.ipv4.ip_forward=1`、`CONFIG_BRIDGE=y`、`BRIDGE_NETFILTER=y`、`nf_nat`/`iptable_nat` 在 |
| **veth（桥接）** | ❌ | `CONFIG_VETH is not set`；实测 `ip link add veth...` → `RTNETLINK answers: Not supported` |
| dockerd kmod 依赖 | ⚠️ | 依赖 `kmod-veth` `kmod-br-netfilter` `kmod-ikconfig` `kmod-nf-ipvs` `kmod-nf-nat` `kmod-nf-conntrack-netlink` + `btrfs-progs` `libdevmapper`，本机没有 → 需 stub 空 ipk |
| 出厂软件源 | ⚠️ | `distfeeds.conf` 全指向 21.02-SNAPSHOT → **404 已失效**，一个包都装不上 |

## 与老 C2000 Max 的关键差异

| 维度 | 老 Max | C2000 U | 影响 |
|---|---|---|---|
| 内存 | 493MB | **992MB** | 不再频繁 OOM / swap 抖动 |
| 存储驱动 | vfs（overlay2 不可用） | **overlay2 很可能可用** | 老 Max 最大痛点是 vfs：体积翻倍、Dockge 拉 15 分钟 |
| overlay 挂载 | 失败 | **`/mnt/storage/data` 上 RC:0** | 因为该分区是**裸 f2fs 挂载**，不在 overlayfs 之上（Docker 拒绝 overlay-on-overlay） |
| 根分区空间 | 27.8G 空闲 | 3.7G + 3.2G | 空间小很多但够用 |
| USB 存储驱动 | **未装** usb-storage | **`usb-storage` 已注册** | 外接盘可行 |
| swap | 1GB | 无 | 建议补 swapfile（`CONFIG_SWAP=y`） |
| veth | ❌ | ❌ | 唯一没改善的短板 |
| 内核 | 5.4.281 | 5.4.281（相同） | 现有 stub 造包脚本、部署脚本几乎可原样复用 |

## ⭐ 零安装验证法（最值得复用的一招）

判断"某个 ipk 能不能在这台设备上跑"，**不需要安装**，解包跑一下二进制即可：

```sh
# 1) 下载 ipk（本例取自阿里云镜像）
curl -sL -o /tmp/dv/dockerd.ipk \
  https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages/dockerd_20.10.17-1_aarch64_cortex-a53.ipk
# 2) 解开外层（老式 gzip+tar 嵌套，不是 ar 归档）
mkdir -p /tmp/dv/x && tar xzf /tmp/dv/dockerd.ipk -C /tmp/dv/x
# 3) 解开内层
tar xzf /tmp/dv/x/data.tar.gz -C /tmp/dv/x
# 4) 直接跑
/tmp/dv/x/usr/bin/dockerd --version      # => Docker version 20.10.17, build a89b842
```

要点：
- `dockerd` 是**静态链接的 Go 二进制**（`ldd` 报 `Not a valid dynamic program`），所以**不受 libc 版本差异影响**
- 这套方法对任何 ipk 都适用，是最廉价的目标架构体检手段
- 事后务必 `rm -rf` 清理，别留在 `/tmp`

## 落地路线（**已按此执行完毕，见上方实装记录**）

1. **换源**（低风险，先备份 `distfeeds.conf`）：`21.02-SNAPSHOT` → `21.02.7` 或阿里云镜像。注意本机 `libc` 报 `1.2.3-3`（比 21.02.7 的 musl 1.1.24 新），musl ABI 向前兼容，实测二进制已跑通；万一不行改用 22.03 源
2. **造 stub ipk + 装 dockerd**：6 个 kmod + `btrfs-progs` + `libdevmapper` 用 stub 满足依赖解析（**老式 gzip+tar 嵌套、`tarfile.GNU_FORMAT`，不能用 PAX**）；再正常装 dockerd / containerd / runc / libnetwork / tini / libseccomp / docker CLI。压缩包约 65MiB，安装后约 150-200MB
3. **data-root 落点取舍**：
   - 方案 A（推荐）`/mnt/storage/data/docker` + **overlay2** —— 省空间、快；风险：厂商数据分区，**恢复出厂可能被清空**
   - 方案 B（保守）`/opt/docker` + vfs —— 与老 Max 同路径、已知可用，但慢
   - 先试 A，用 `dockerd --data-root=... --storage-driver=overlay2` 起一次看结果，失败自动退 B
4. **（可选）移植 Docker 面板**：老 Max 的 `dpctl` + `dpapi.lua`（Lua `socket.unix` 直连 docker.sock）+ htm，架构相同、LuCI 同代，理论上可直接移植；但本机 `/etc/kp_store` 不存在，商店注册要另补

## 风险与注意

1. **老 Max 已不在链路里**：PC 现在的网关是这台 U，U 自己往上走 192.168.1.1。老 Max 的 OpenClash / AGH / Docker 面板都不在当前路径上
2. **`192.168.66.0/24` 网段冲突**：老 Max 与本机 LAN 默认都是 `192.168.66.1`，两台同时上电会撞车
3. **LuCI git-26.253 —— 绝对不能装 21.02.7 的旧版 luci-compat（git-22.046）**，会污染 luci-base，卸载时删走 `cbi.lua` / `model/network.lua` / `view/cbi/*` → 整个 LuCI 502
4. **存储是可插拔介质**：`dmesg` 写的是 `mmc0: new high speed SDHC card ... mmcblk0: mmc0:0001 SD 7.50 GiB`，**不是 eMMC**。好处是大概率能换更大容量的 TF 卡（C2000 MAX 手册称 TF 槽支持 1GB-2TB）；坏处是写入寿命不如 eMMC，重 IO 应用别长期压在上面
5. **`/mnt/storage/data` 是厂商数据分区，而 Docker data-root 就在它上面**（`/mnt/storage/data/docker`）：
   - `zeroclaw` 用 `/mnt/storage/data/nradio/`，`/lib/preinit/82_mount_storage_data` 会建 `NROS/` 目录
   - ⚠️ **恢复出厂设置有可能清空该分区 → 镜像/容器/卷全丢**。重要数据务必挂载到别处或另做备份
   - 该分区是 **TF 卡**（非 eMMC），重 IO 的容器（数据库）长期压在上面会加速损耗
   - **备选（保守）**：把 data-root 改回 `/opt/docker`（在 overlayfs 根分区上）—— 但那时 Docker 只认 **vfs**，
     空间放大、启动变慢。**overlay2 与 `/mnt/storage/data` 是绑定的，二选一**
   - 回退办法：改 `/etc/docker/daemon.json` 的 `data-root` 为 `/opt/docker` 并删掉 `storage-driver`（自动落 vfs），
     再 `/etc/init.d/dockerd restart`
6. **厂商常驻服务很多**：180 个进程、已用 260MB（`msad` `cloudd` `mqttagent` `zeroclaw` `kpsh` `smsd` `cellular_*` `wifidogx` `miniupnpd` `telnetd` `xl2tpd` `igmpproxy` `mosquitto` …）。Docker 上线后可照老 Max 的办法精简，但**绝不能停** network / firewall / dnsmasq / uhttpd / dropbear

## 本机精简固件的工具缺口（探测时踩到）

- 缺：`jq`、`timeout`、`python3`、`od`、`nft`
- `sort` **不支持 `-h`**（busybox），`sort -rn` 可用
- **busybox ash 不支持 `{a,b,c}` 花括号展开** —— 本次探测中 `mkdir -p /x/{l,u,w,m}` 只建了一个名叫 `{l,u,w,m}` 的目录，导致 overlay 挂载测试**假失败**，换成分开写就 `RC:0`。**下结论前先怀疑自己的命令语法**
- 有：`curl` `wget` `md5sum` `lua` `opkg` `brctl` `iptables`(legacy 1.8.7) `iproute2 6.4.0`
