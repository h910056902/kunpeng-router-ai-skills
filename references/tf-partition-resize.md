# TF 卡分区扩容（系统分区装不开时）

> 适用：鲲鹏 NRadio C2000 Max / C2000 U，OpenWrt 21.02-SNAPSHOT，kernel 5.4.281
> 场景：`/overlay`（就是 `/`）只有 4G，装几个包就告急，想把系统分区撑大
> 实测状态：**已在 C2000 Max 上跑通，卡上数据零丢失，4G → 16G**

---

## 一、为什么不能在线扩容（三条硬约束）

| 约束 | 证据 | 后果 |
|---|---|---|
| `resize.f2fs` **拒绝已挂载的 fs** | 二进制里有硬错误串 `Error: Not available on mounted device!` | `/overlay` 就是 `/`，永远挂着 → 在线扩容不可能 |
| overlay 只能落在 p1 | `/lib/preinit/80_mount_root` 里 `pivot_tf_overlay()` **硬编码 `/dev/mmcblk0p1`** | 不能"把 overlay 挪到 p2、把 p2 改大" |
| 改 fstab 也来不及 | `/etc/config/fstab` 只在 preinit 读一次 | 运行时改对当次启动无效 |

**唯一的窗口**：开机瞬间系统临时落在 **NOR 的 `rootfs_data`（`/dev/mtdblock8`，2MB jffs2）**
上，此时 TF 卡尚未被挂载 —— 这就是"NOR 窗口"。

关键情报（决定了整个方案能不能成）：

- **`/mnt/mtdblock8/upper/etc/config/fstab` 就是开机权威配置**。
  fstools 先把 `mtdblock8` 挂成 `/overlay`，再读它里面的 fstab 决定是否切到卡上。
  改这里 = 改开机行为。
- 同一个 `upper` 也是**卡失联时的备用根**，里面的 `etc/shadow` / `dropbear/` /
  `network` / `firewall` 都在（LAN 仍是 `192.168.66.1`，`lan:22` 是 ACCEPT）
  → 窗口期还能 SSH 进来兜底。
- `resize.f2fs` / `mkfs.f2fs` / `fdisk` 在 **squashfs 里也各有一份**
  → 卡没挂载时这些工具照样可用，不用额外搬。

---

## 二、四步流程（在线 → 重启 → 自动完成 → 自动重启）

### 第 1 步（在线）：改分区表

```sh
# 先卸掉数据分区（p2 在 p1 后面，必须重排）
umount /mnt/storage/data 2>/dev/null
for mp in $(grep '^/dev/mmcblk0p2 ' /proc/mounts | cut -d' ' -f2); do umount "$mp"; done

# 备份 MBR（500 字节就够，出事能 dd 回去）
dd if=/dev/mmcblk0 of=/overlay/kp-mbr.bak bs=512 count=1

# p1 起始扇区必须保持 16 不变（否则 overlay 数据全废）
printf 'd\n2\nd\nn\np\n1\n16\n+16G\nn\np\n2\n\n\np\nw\n' | fdisk /dev/mmcblk0
sync
```

干跑核对（务必做）：

```
Device       Boot StartCHS  EndCHS      StartLBA     EndLBA    Sectors  Size Id Type
/dev/mmcblk0p1    0,1,1     1023,3,16         16   33554447   33554432 16.0G 83 Linux
/dev/mmcblk0p2    1023,3,16 1023,3,16   33554448   61067263   27512816 13.1G 83 Linux
```

- `StartLBA` 必须是 **16**（p1 的）
- 改完会看到 `kernel still uses old table` —— **正常**，p1 还挂着，内核不重读分区表
- 29G 卡：系统 16G + 数据 13.1G 是实测值

### 第 2 步（在线）：预置一次性任务 + 关掉 fstab 的 /overlay

在 NOR 的 upper 里写两样东西（`$U=/mnt/mtdblock8/upper`）：

1. `$U/etc/kp-resize.sh` —— 任务本体，核心顺序**不能变**：

```sh
# ① 安全前提：/overlay 绝不能就在卡上
cur=$(awk '$2=="/overlay"{print $1}' /proc/mounts)
[ "$cur" = "/dev/mmcblk0p1" ] && exit 1        # 不在窗口里，什么都不做

# ② 摘掉热插拔挂上去的 p1 ← 最容易漏的一步！
for mp in $(grep '^/dev/mmcblk0p1 ' /proc/mounts | cut -d' ' -f2); do
	umount "$mp" 2>/dev/null || umount -l "$mp" 2>/dev/null
done
grep -q '^/dev/mmcblk0p1 ' /proc/mounts && exit 1   # 还挂着就放弃，别硬来

# ③ 扩容（此时 p1 未挂载，resize.f2fs 才肯动）
resize.f2fs /dev/mmcblk0p1

# ④ 重建 p2（分区表已重排，旧文件系统不认了）
mkfs.f2fs -f -l nradio_user_data /dev/mmcblk0p2

# ⑤ 恢复 fstab，然后重启
uci -c /etc/config set fstab.@mount[0].device='/dev/mmcblk0p1'
uci -c /etc/config set fstab.@mount[0].target='/overlay'
uci -c /etc/config set fstab.@mount[0].enabled='1'
uci -c /etc/config set fstab.@mount[1].device='/dev/mmcblk0p2'
uci -c /etc/config set fstab.@mount[1].target='/mnt/storage/data'
uci -c /etc/config set fstab.@mount[1].enabled='1'
uci -c /etc/config commit fstab
touch /kp-resize.done && reboot
```

2. `$U/etc/rc.local` —— 由它调用任务。**执行 rc.local 的是 `/etc/init.d/done`（`S95done`）**，
   而 `S95done` 来自只读的 `/rom`，新 overlay 空着也能继承：

```sh
# Put your custom commands here that should be executed once
# the system init finished. By default this file does nothing.
if grep -qE MT798 /tmp/sysinfo/board_name; then
	echo 3 > /proc/sys/vm/drop_caches
fi
[ -x /etc/kp-resize.sh ] && /etc/kp-resize.sh
exit 0
```

3. 顺手把当前身份/网络配置复制进备用根（窗口期兜底）：

```sh
mkdir -p $U/etc/config $U/etc/dropbear
cp -f /etc/shadow /etc/passwd /etc/group $U/etc/
cp -f /etc/dropbear/* $U/etc/dropbear/
for c in firewall network dropbear dhcp system; do cp -f /etc/config/$c $U/etc/config/$c; done
```

4. **制造窗口**：把备用根里 `/overlay` 那条 fstab 关掉

```sh
uci -c $U/etc/config set fstab.@mount[0].enabled='0'
uci -c $U/etc/config commit fstab
```

> 这一步是整套方案的关键：`enabled=0` → 开机时 fstools 不会把 p1 挂成 `/overlay`
> → 系统停在 NOR 上 → 卡空着 → 扩容窗口出现。

### 第 3 步：`reboot`

启动流程变成：

```
NOR 备用根启动（/overlay = /dev/mtdblock8）
   └─ S95done → /etc/rc.local → /etc/kp-resize.sh
          ├─ 摘掉 /tmp/storage/mmcblk0p1
          ├─ resize.f2fs 撑满 p1
          ├─ mkfs.f2fs p2
          ├─ 恢复 fstab（/overlay → p1，enabled=1）
          └─ reboot
```

### 第 4 步：自动回来后核对

```sh
awk '$2=="/overlay" || $2=="/mnt/storage/data"' /proc/mounts
df -h / /mnt/storage/data
cat /mnt/mtdblock8/upper/kp-resize.log     # 任务日志落在 NOR 里
ls -la /mnt/mtdblock8/upper/kp-resize.done
```

实测结果：

```
overlayfs:/overlay       16.0G    913.6M     15.1G   6% /
/dev/mmcblk0p1           16.0G    913.6M     15.1G   6% /overlay
/dev/mmcblk0p2           13.1G    570.3M     12.6G   4% /mnt/storage/data
```

---

## 三、踩过的坑

| 坑 | 现象 | 处理 |
|---|---|---|
| **热插拔先挂了 p1** | `resize.f2fs` 报 `Not available on mounted device!` | 扩容前**必须 umount** `/tmp/storage/mmcblk0p1`，见第 2 步 ② |
| **resize.f2fs 输出巨量** | 每迁移一个块打一行，实测 **1.9MB / 36966 行** | 别往小 tmpfs 写；日志直接落 NOR，或 `>/dev/null` |
| **忘了 `-f`** | `mkfs.f2fs` 对已有文件系统会交互确认，非交互下直接失败 | 用 `mkfs.f2fs -f -l nradio_user_data` |
| **`-l` 卷标名随便起** | 厂商 `sd.lua` 按名字认分区 | 照抄官方值：p1 `nradio_tf_overlay`、p2 `nradio_user_data` |
| 改完没重启就验容量 | 仍显示旧的 4G | 内核要重读分区表 + f2fs 要重新挂载，**必须重启** |
| p1 起始扇区改了 | overlay 数据全废 | `fdisk` 里 `n` 之后**第一个扇区一定填 16** |

**回滚**：MBR 已备份在 `/overlay/kp-mbr.bak`（512B），
`dd if=/overlay/kp-mbr.bak of=/dev/mmcblk0 bs=512 count=1` 即可还原分区表；
fstab 改回 `enabled=1` 重启就回到原状。

---

## 四、不想手工做？用一键脚本

仓库 `h910056902/nros-panel` 提供重建路径（**会清空卡**，先备份要留的数据）：

```sh
OVERLAY_SIZE=16G REBUILD=1 sh /tmp/kp.sh
```

`REBUILD=1` 会强制走「重建 TF 卡 → 重启 → 自动续跑安装」，自动蕴含 `FORCE=1`；
已装的 opkg 包随 overlay 迁移保留（`arm_auto()` 会 `cp -a` 整个 upper/work）。

> 区别：一键脚本是**重新格式化**（数据没了），本文这套是**原地扩容**（数据保留）。
> 目标是把现有系统盘撑大、又不想重装 → 用本文流程。

---

## 五、相关事实速查

- 全机只有 `mmcblk0` 一个 mmc 节点；介质是 **SD 卡**不是 eMMC
  （设备树有 `no-mmc` + `broken-cd`），卡可拔出，数据能拿到 PC 上读
- 分区表是 **MBR**（无 PARTLABEL）→ 固件热插拔脚本 `/etc/hotplug.d/block/00-mount`
  的 `ID_FS_PARTLABEL=nradio_user_data` 判据永远不成立，
  所以 `/mnt/storage/data` 常挂不上（固件自身缺陷，脚本里要 `ensure_data()` 兜底）
- `/overlay` 所在设备被拔出时固件会**自动重启**，属正常保护行为
