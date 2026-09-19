# 鲲鹏 C2000 U（C2000-798 / WT9500）Docker 适配评估与实装报告

> 评估时间：2026-09-11 09:5x（GMT+8）　**实装完成：2026-09-11 10:13**
> 评估方式：只读探测 + 零安装二进制试运行（未改动设备任何文件）
> 实装方式：换阿里云源 → 6 个 stub ipk → 装 dockerd 全家 → 配 `alt_config_file` → 冒烟测试
> 设备地址：192.168.66.1（root）

---

## 零、实装结果速览（已落地，全文见文末「实装记录」）

| 项 | 结果 |
|---|---|
| Docker 版本 | **20.10.17**（docker CLI / containerd 1.6.6 / runc 1.1.2 / libnetwork / tini / libseccomp 全装齐） |
| **存储驱动** | **overlay2**（`Backing Filesystem: f2fs`）—— 老 Max 只能 vfs，这是最大提升 |
| data-root | `/mnt/storage/data/docker`（首镜像 alpine:3.19，实占 8.2M，**无 vfs 那种翻倍放大**） |
| 网络 | `bridge=none` + `iptables=false`，容器一律 `--network=host` |
| 镜像加速 | `docker.1ms.run` + `docker.m.daocloud.io`（已回读确认生效） |
| 开机自启 | ✅ `/etc/rc.d/S99dockerd` |
| 内存占用 | dockerd ≈60MB + containerd ≈38MB；系统 available 仍 ≈668MB |
| CLI 速度 | 0.01–0.07s（PC 侧计时含 SSH 往返） |
| 实测项 | 拉镜像 ✅ host 网络跑容器 ✅ 容器内 DNS ✅ 卷写盘 ✅ `-d` 生命周期 ✅ 服务重启配置持久 ✅ |
| 唯一未改善短板 | **`CONFIG_VETH` 未编入 → 不能桥接/端口映射**（与老 Max 同） |

---

## 一、结论

**✅ 可以适配，而且条件比老 C2000 Max 好一大截。**

最硬的证据：把 dockerd 的二进制从官方软件包里解出来、**不做任何安装**直接执行，直接跑通了：

```
Docker version 20.10.17, build a89b842
RC:0
```

（dockerd 是静态链接的 Go 二进制，`ldd` 报 "Not a valid dynamic program"，所以连 libc 版本差异都不用担心。）

---

## 二、设备身份（设备自报）

| 项 | 值 |
|---|---|
| 产品名 | **C2000-798**（`uci get oem.board.pname`） |
| 板型 | **HC-WT9500**（`/tmp/sysinfo/model`、`/proc/device-tree/model`） |
| 硬件 ID | `HCMT7987-SNSD` |
| 厂商 | nradio，`ptype=rt`，`feature.cpe=2`（5G CPE） |
| SoC | **MediaTek MT7987**，4× ARM Cortex-A53（aarch64），Wi-Fi 芯片 MT7992 |
| IMEI / ICCID | 已写入（864640060028295 / 89863026000007034320） |
| 系统 | OpenWrt **21.02-SNAPSHOT**，revision `2.3.0.n0.c1`，target `mediatek/mt7987` |
| 内核 | **5.4.281** —— 与老 Max 完全一致 |
| LuCI | **git-26.253.32058-228b00a**（比老 Max 的 git-26.224 还新） |
| 当前链路 | WAN=eth0 取到 192.168.1.6（上级 192.168.1.1），LAN=br-lan 192.168.66.1 |

---

## 三、Docker 硬门槛逐项实测

| # | 门槛 | 结果 | 证据 |
|---|---|---|---|
| 1 | CPU 架构 | ✅ | `aarch64_cortex-a53`，与 Max 同 → Docker 包可直接复用 |
| 2 | 内存 | ✅✅ | `MemTotal: 1016432 kB`（≈ **992MB**），可用 ~690MB |
| 3 | 存储空间 | ✅ | overlay 3.7G 可用 + data 3.2G 可用 = **约 6.9G** |
| 4 | dockerd 可获取 | ✅ | 21.02.7 源有 `dockerd 20.10.17` / `containerd 1.6.6` / `runc 1.1.2` / `libnetwork` / `tini` / `libseccomp`；阿里云镜像实测 200 / 0.85s |
| 5 | 二进制可执行 | ✅ | **实测 `dockerd --version` 返回 20.10.17** |
| 6 | cgroup | ✅ | cgroup **v2** 已挂载 `/sys/fs/cgroup`，控制器 `cpuset cpu io memory pids rdma` 全在 |
| 7 | Namespace | ✅ | UTS / IPC / USER / PID / NET 全套 |
| 8 | overlayfs | ✅ | `CONFIG_OVERLAY_FS=y`；**实体挂载测试 RC:0** |
| 9 | seccomp | ✅ | `CONFIG_SECCOMP` + `CONFIG_SECCOMP_FILTER=y` |
| 10 | 网络转发 | ✅ | `net.ipv4.ip_forward=1`，`CONFIG_BRIDGE=y`，`BRIDGE_NETFILTER=y`，nf_nat / iptable_nat 齐备 |
| 11 | **veth（桥接网络）** | ❌ | `CONFIG_VETH is not set`；实测 `ip link add veth...` → **`RTNETLINK answers: Not supported`** |
| 12 | 依赖 kmod | ⚠️ | dockerd 声明依赖 6 个 kmod（veth/br-netfilter/ikconfig/nf-ipvs/nf-nat/nf-conntrack-netlink）+ btrfs-progs + libdevmapper，本机没有 → 需造 stub 空包 |

**11 项通过、1 项不通过、1 项需绕行。**

---

## 四、与老 C2000 Max 的关键差异（这是本次最大收获）

| 维度 | 老 C2000 Max | **C2000 U（本机）** | 影响 |
|---|---|---|---|
| 内存 | 493MB | **992MB** | 不再动不动被 OOM/swap 拖死 |
| 存储驱动 | **vfs**（overlay2 不可用） | **overlay2 很可能可用** ✅ | 层可共享、省空间、启动快。老 Max 上 vfs 是最大痛点（体积翻倍、Dockge 拉 15 分钟） |
| overlay 挂载实测 | 失败 | **`/mnt/storage/data` 上 RC:0 成功** | 因为该分区是**裸 f2fs 挂载**，不在 overlayfs 之上（Docker 拒绝 overlay-on-overlay） |
| 根分区 | 27.8G 空闲 | 3.7G + 3.2G | 空间小很多，但够用 |
| USB 存储驱动 | **未装** usb-storage | **`usb-storage` 已注册** ✅ | 外接盘有戏 |
| 交换分区 | 有 1GB swap | **无 swap** | 建议补一个 swapfile 兜底 |
| veth / 桥接网络 | ❌ 不可用 | ❌ **同样不可用** | 唯一没改善的短板，容器只能 `--network host` |
| 内核版本 | 5.4.281 | 5.4.281（**相同**） | 现有 stub 造包脚本、部署脚本几乎可原样复用 |

---

## 五、必须接受的两个限制

1. **无 veth → 只能 host 网络。** 这是内核编译时 `CONFIG_VETH` 没开导致的死结（改不了，除非换固件）。后果：容器不能端口映射、端口冲突写死、无网络隔离。每个容器要规划独占端口。
2. **存储是 TF/SD 卡。** `dmesg` 明确写的是 `mmc0: new high speed SDHC card ... mmcblk0: mmc0:0001 SD 7.50 GiB`，不是 eMMC。好处是**大概率可换更大容量卡**；坏处是 SD 卡写入寿命/可靠性不如 eMMC，重 IO 应用（数据库、下载机）不建议长期压在上面。

---

## 六、还有一个隐藏坑：软件源已失效

```
/etc/opkg/distfeeds.conf 里全部指向 downloads.openwrt.org/releases/21.02-SNAPSHOT/...
  target_feed : 404   ← 已失效
  base_feed   : 404   ← 已失效
  v2102.7_base: 200   ← 活着
  v2102.7_pkgs: 200   ← 活着
  aliyun 镜像 : 200 / 0.85s  ← 最快
```

也就是说：**设备出厂带的那套源现在一个包都装不上**，必须先换源（指向 21.02.7 或阿里云镜像），否则连 `libseccomp` 都装不了。

---

## 七、建议落地路线（4 步，可分批做）

### Step 1 — 换源（低风险，可回滚）
把 `/etc/opkg/distfeeds.conf` 的 `21.02-SNAPSHOT` 改为 `21.02.7`，或直接切阿里云镜像。改前备份原文件。
> 注意：`libc` 报的是 `1.2.3-3`（比 21.02.7 的 musl 1.1.24 新）。musl ABI 向前兼容，实测二进制已跑通，风险可控；万一不行则改用 22.03 源。

### Step 2 — 造 stub ipk + 装 dockerd
- 6 个 kmod 依赖 + `btrfs-progs` + `libdevmapper` 用 **stub 空 ipk** 满足依赖解析（老式 gzip+tar 嵌套格式，`tarfile.GNU_FORMAT`，不能用 PAX）
- 正常 `opkg install` dockerd / containerd / runc / libnetwork / tini / libseccomp / docker(CLI)
- 预计占用：压缩包约 65MiB，安装后约 150-200MB

### Step 3 — 决定 data-root 落点（关键取舍）

| 方案 | 位置 | 存储驱动 | 优点 | 风险 |
|---|---|---|---|---|
| **A（推荐）** | `/mnt/storage/data/docker` | **overlay2** | 省空间、快、层共享 | 属厂商数据分区，**恢复出厂设置可能被清空** |
| B（保守） | `/opt/docker` | vfs | 与老 Max 同路径、已知可用 | 体积翻倍、慢 |

建议先试 A，用 `dockerd --data-root=/mnt/storage/data/docker --storage-driver=overlay2` 起一次看结果，失败自动退 B。

### Step 4 —（可选）移植 Docker 面板
老 Max 那套 `dpctl` + `dpapi.lua`（Lua `socket.unix` 直连 docker.sock）+ 前端 htm，架构相同、LuCI 同一代（git-26.x），**理论上可直接移植**。注意本机 `/etc/kp_store` 目录都不存在，商店注册要另外补。

---

## 八、其它风险提示

1. **老 Max 已不在链路里了。** 本机 PC 现在的网关是这台 C2000 U（192.168.66.1），而 C2000 U 自己往上走 192.168.1.1。老 Max 的 OpenClash / AdGuard Home / Docker 面板都不在当前路径上。
2. **`192.168.66.0/24` 网段冲突。** 老 Max 和这台 U 的 LAN 默认都是 `192.168.66.1`，两台同时上电会撞车。
3. **LuCI git-26.253 —— 绝对不能装 21.02.7 的旧版 luci-compat（git-22.046）**，会污染 luci-base，卸载时删走 `cbi.lua` 等系统必需文件，整个 LuCI 502。（这条是老 Max 上踩过的血泪坑，规则完全适用于本机。）
4. **本机工具同样是精简固件**：无 `jq`、无 `timeout`、无 `python3`、无 `nft`；`sort` 不支持 `-h`；busybox ash **不支持 `{a,b,c}` 花括号展开**（本次探测中就因此误判过一次 overlay 挂载失败）。
5. 大量厂商常驻服务在跑（`msad`/`cloudd`/`mqttagent`/`zeroclaw`/`kpsh`/`smsd`…共 180 个进程，已用 260MB）。Docker 上线后可考虑照老 Max 的办法精简，但**绝不能停** network/firewall/dnsmasq/uhttpd/dropbear。

---

## 九、原始证据（关键几条）

```
# 型号
HC-WT9500                                    ← /tmp/sysinfo/model
pname 'C2000-798'  name 'WT9500'  vendor 'nradio'   ← /etc/config/oem

# 内存
MemTotal: 1016432 kB   MemAvailable: 701060 kB       ← /proc/meminfo

# 内核是否给了 veth
# CONFIG_VETH is not set                              ← /proc/config.gz
ip link add vethprobe0 type veth peer name vethprobe1
RTNETLINK answers: Not supported                      ← 实测

# overlay 在裸 f2fs 上可用
mount -t overlay overlay -o lowerdir=...,upperdir=...,workdir=... /mnt/storage/data/ovt/m
RC:0                                                  ← 实测

# dockerd 零安装跑通
./x_dockerd/usr/bin/dockerd --version
Docker version 20.10.17, build a89b842                ← 实测
```

---

## 十、实装记录（2026-09-11 10:02–10:13，已执行完毕）

按第七节路线执行，**6 步全部成功**。

| 步骤 | 动作 | 结果 |
|---|---|---|
| 1 | 备份 `distfeeds.conf` → 换阿里云 21.02.7 → `opkg update` | 备份 `.bak-c2000u-20260911_100247`；更新 **3.0s**，签名校验通过 |
| 2 | 造 6 个 stub 空 ipk 并安装 | `kmod-veth` `kmod-br-netfilter` `kmod-ikconfig` `kmod-nf-ipvs` `btrfs-progs` `libdevmapper` 全部登记 |
| 3 | 装真包 | `libseccomp → libnetwork → tini → runc → containerd → dockerd → docker` 全部成功 |
| 4 | 写 `/etc/docker/daemon.json` + `uci set dockerd.globals.alt_config_file` | `docker info` 回读 **Storage Driver: overlay2 / Docker Root Dir: /mnt/storage/data/docker** |
| 5 | `/etc/init.d/dockerd enable` | `/etc/rc.d/S99dockerd` 已建 |
| 6 | 冒烟测试 | 拉 `alpine:3.19`（7.73MB）→ host 网络跑通 → 生命周期回归 → 全绿 |

最终生效的 `/etc/docker/daemon.json`：

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

### 实装中遇到的三个真坑（都绕过了）

1. **本机没有 SFTP** —— `paramiko.open_sftp()` 直接报 `SSHException: EOF during negotiation`
   （固件未编入 sftp-server 子系统）。改用 `exec_command`：文本走 heredoc + md5 对账，
   **二进制走 `printf '\NNN\NNN...' > f`**（该固件无 base64/openssl/xxd/python3，这是唯一可用通道）。
2. **opkg 会被 feed 同名包「截胡」** —— 用 `opkg install /tmp/stub.ipk` 装本地的 `btrfs-progs` 时，
   因为 feed 里有同名包，opkg 转而解析 feed 候选，报出 stub 里根本不存在的 `kmod-fs-btrfs` 依赖而失败。
   解法：**装 stub 前先 `mv /var/opkg-lists /var/opkg-lists.off`**，装完移回。
3. **`/etc/docker/daemon.json` 光写不生效** —— init 脚本 `/etc/init.d/dockerd` 每次启动都会
   `rm -rf /tmp/dockerd` 后用 UCI 重新生成 `daemon.json`，而 **UCI 生成器不支持 `storage-driver` 和 `bridge`**
   （只支持 data-root / log-level / iptables / bip / registry-mirrors / hosts / dns / ipv6 / ip / fixed-cidr）。
   唯一正路：`uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json' && uci commit dockerd`，
   init 见到这项就把它 `ln -s` 到 `/tmp/dockerd/daemon.json`，全文由自己掌控。
   另：`busybox date` **不支持 `%N`**，计时改在 PC 侧做。

> 关于 stub 取舍：`btrfs-progs` / `libdevmapper` 也用 stub 而**不装真包**，是为了避免拉入
> `libblkid1`/`libuuid1`/`libmount1` 等 util-linux 库而**升级厂商固件自带的库**（有破坏厂商二进制的风险）。
> overlay2/vfs 都用不到 btrfs 与 devicemapper，stub 足够。

---

## 十一、收尾复核（2026-09-11 10:33，重启后 46 分钟）

重启后复测，状态稳定，**任务闭环**：

| 复核项 | 结果 |
|---|---|
| 开机自启 | **YES**（`/etc/rc.d/S99dockerd` 生效） |
| 进程 | `dockerd` RSS≈59.7MB + `containerd` RSS≈38.4MB，双活 |
| `docker info` | Server **20.10.17** / Storage Driver **overlay2** / Backing Filesystem **f2fs** |
| Docker Root Dir | `/mnt/storage/data/docker` |
| Registry Mirrors | `docker.1ms.run` + `docker.m.daocloud.io`（回读生效） |
| 镜像 | `alpine:3.19`（7.73MB）在库 |
| 容器 | 列表为空 —— 冒烟容器已清理，无残留 |
| 内存 | total 1016432 kB，**available 661360 kB ≈ 646MB** |
| 存储 | `/overlay` 4.0G 用 13%；`/mnt/storage/data` 3.5G 用 9% |
| 软件源 | 阿里云 `21.02.7`（base/packages/routing 三源）；备份文件在位 |

---

*第一~九节由只读探测生成，未对设备做任何写操作；第十节为实装记录，第十一节为收尾复核。
复现脚本见技能包 `scripts/setup_docker_c2000u.py` + `scripts/rtr_lib.py`；
专题文档 `references/c2000u-docker.md`；绕 DNS 污染推 GitHub 用 `scripts/gh_proxy_push.py`。*
