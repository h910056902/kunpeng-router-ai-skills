# NAS 升级路线（C2000 Max）

> 状态：**调研完成，未实施**（2026-09-08 探明硬件与软件可行性）。用户意向：不格式化 U 盘优先。

## 硬件探明结论（实测）

- CPU：双核 ARMv8 Cortex-A53，文件共享够用
- USB 3.0 口正常（xHCI），已识别外接设备：朗科 3466:3301（U 盘/读卡器）
- **缺 `kmod-usb-storage` 驱动** → 外接盘不出现 /dev/sda，装上即现形（纯增量，不动数据）
- 源里无 `kmod-usb-storage-uas`（只配了基础 usb-storage）
- 待机温度 ~62°C，偏热；内存可用 ~68MB

## 文件系统支持矩阵（免格式化关键）

| U 盘格式 | 免格式挂载 | 方式 | 表现 |
|---|---|---|---|
| NTFS | ✅ | ntfs-3g **已装**（FUSE） | ~10-20MB/s，CPU 偏高，读写可用 |
| FAT32 | ✅ | kmod-fs-vfat **已装**（原生） | 快，但单文件 ≤4GB |
| ext4 | ✅ | kmod-fs-ext4（装驱动时顺带） | 最优解，但需格式化才有 |
| exFAT | ❌ | 内核无 exfat，源里无 exfat-fuse（只有 mkfs/fsck 工具） | 只能格式化或换盘 |
| btrfs | 理论可 | kmod-fs-btrfs 在源里 | 未验证，别冒险 |

## 实施计划（分阶段，全部原生 opkg，不进 Docker）

| 阶段 | 内容 | 包 | 内存代价 |
|---|---|---|---|
| 1 挂盘 | 装驱动 → blkid 识别 → 按格式挂载 → fstab 持久化 | kmod-usb-storage, block-mount（+kmod-fs-ext4 备用） | ≈0 |
| 2 共享 | ksmbd 内核级 SMB + LuCI 管理页，`\\192.168.66.1\nas` | ksmbd-server, luci-app-ksmbd, ksmbd-utils(设密码) | ~5MB |
| 3 下载机 | 原生 aria2（BT/HTTP/磁力）；**禁选 qBittorrent 容器**（100MB+ 内存） | aria2 (+luci-app-aria2 可选) | ~20MB |
| 4 媒体 | DLNA 给电视发现片源 | minidlna | ~15MB |
| 5 进阶 | Docker 跑 Alist/WebDAV 聚合网盘（vfs 慢，仅轻应用）；Filebrowser 已覆盖网页文件管理 | — | 视容器 |

## 关键决策原则

1. **NAS 服务全走原生 opkg，不进 Docker**：vfs 存储驱动 + 493MB 内存，容器方案全面吃亏（ksmbd 是内核态，~5MB 就能跑）
2. **免格式化路径**：NTFS/FAT32 直接挂；exFAT 是死路。想上 ext4 必须格式化（用户确认后）
3. **零格式化起步替代**：内置 eMMC 29G f2fs（/tmp/storage/mmcblk0p1，空闲 25.9G）直接 ksmbd 共享出去，立刻可用；缺点是与系统同盘、容量小
4. 性能预期：USB3 + ksmbd 内核态 ≈ 跑满千兆的 6-8 成；NTFS(FUSE) 打对折
5. 7x24 注意事项：温度 62°C 起步要通风；hdparm 设硬盘待机；单盘无冗余，重要数据另备份

## 探测脚本

`scripts/probe_nas.py`：一键体检 CPU/USB/块设备/内核模块/挂载/温度/NAS 软件源/内存。动手前先跑它确认现状。
