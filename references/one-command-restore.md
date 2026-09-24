---
id: REF-one-command-restore
title: "一条命令恢复（nros-panel）"
tags: [restore, nros-panel, partition, overlay, reboot]
risk: high
preconditions:
  - "换卡/卡被重置/overlay 丢失后使用"
  - "明确会分区并自动重启"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# 一条命令恢复（nros-panel）

> 2026-09-15 建立。适用 B 机（C2000 U，TF 卡存储）。
> 场景：卡被重置 / 换卡 / overlay 丢了，要把 **外网(OpenClash) + Docker + 1Panel** 装回来。

## 仓库与入口命令

- 仓库：**https://github.com/h910056902/nros-panel**（public，脱敏，无凭据）
- 入口（唯一需要记住的命令）：

```sh
wget -qO /tmp/kp.sh https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh && sh /tmp/kp.sh
```

| 文件 | 作用 |
|---|---|
| `install.sh` | 入口：判断存储状态 → 决定「直接装」还是「分区+重启+续跑」 |
| `kp-install.sh` | 主脚本，四阶段：预检换源 → OpenClash → Docker → 1Panel |
| `kp-storage-init.sh` | TF 卡双分区（p1 16G→/overlay，p2 剩余→/mnt/storage/data）+ f2fs + fstab |
| `kp-ui.sh` | 终端界面库（写法约束见 `script-ui.md`） |
| `kp-ui-preview.sh` | 界面本地预览 |
| `kp-store-lib.sh` | **商店注册共享库**（`kp-install.sh` / `kp-ocspeed.sh` 都 source 它） |
| `kp-store-check.sh` | **注册体检**，只读；`SCRIPT=kp-store-check.sh sh /tmp/kp.sh` |
| `kp-ocspeed.sh` + `ocspeed/` | OpenClash 自动测速插件（自建，opkg 里没有） |

## 一、出厂 opkg 源**全部**失效（纠正旧结论）

⚠️ 旧结论「只有 `packages`/`routing` 404，base/core 还能用」**是错的**。

2026-09-15 逐源实测（设备视角 curl）：

| 源 | 结果 |
|---|---|
| `21.02-SNAPSHOT/packages/aarch64_cortex-a53/{base,packages,routing,mtk_openwrt_feed,openmptcprouter}` | **全 000** |
| `21.02-SNAPSHOT/targets/mediatek/mt7987/packages` | **000** |
| 阿里云 `21.02.7/.../{base,packages,routing,luci}` | **全 200** |

`000` 不是 404 —— 是**连接根本建不起来**：DNS 能解析（`downloads.openwrt.org → 146.75.46.132`，
Fastly），但 `conn=0.000000s`，v4 / v6 / `--resolve` 固定 IP 三种方式全是 000。

**后果**：连 `bash` 都装不上（bash 在 packages feed）。所以必须**整体换源**：

```
src/gz openwrt_base     https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/base
src/gz openwrt_packages https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages
src/gz openwrt_routing  https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/routing
```

- 原文件备份 `distfeeds.conf.kp-bak`（脚本只在检测到 `21.02-SNAPSHOT` 时整体重写，幂等且尊重后续手工修改）
- **`core` 与 target 源故意不保留**：官方没有 mt7987 这个 target，留着只会让 `opkg update` 卡在超时上
- 阿里云 packages feed 实测有 `docker / dockerd / containerd / docker-compose / runc`，也有 `bash`
- 缺 kmod 依赖时**造桩包**，不能用 `--force-depends`（实测无效，理由见下）

## 二、kmod 依赖缺失：必须造桩包，`--force-depends` 无效

本机内核**没编 veth / br_netfilter**，且 `kmod-tun`、`iptables` 这类包在 opkg 数据库里显示"未安装"，
**但模块和命令其实都在**（固件自带）。实测：

```
modprobe tun        rc=0   （tun.ko 在 /lib/modules/5.4.281/）
/proc/filesystems   → overlay（内建）、f2fs
lsmod               → ip_tables / nf_nat / nf_conntrack / ip_set 全部在跑
modprobe veth       rc=255 （确实没有）
```

### ⚠️ `--force-depends` 救不了 `dockerd`（2026-09-15 实测推翻旧结论）

`dockerd` 的依赖链里有 **6 个厂商内核里根本不存在的 kmod**：
`kmod-veth`/`kmod-dm`/`kmod-fs-btrfs`/`kmod-br-netfilter`/`kmod-ikconfig`/`kmod-nf-ipvs`。

报错形如：

```
Unknown package 'dockerd'.
Package dockerd wants to install 'kmod-veth', but that file is already provided by package ...
```

关键：opkg **在"选候选包"阶段就失败**，根本走不到依赖检查 —— 所以
`opkg install --force-depends dockerd` **完全无效**（实测加了也报同样的 `Unknown package`）。

**正解：造只声明 `Provides` 的空桩包**，让依赖图闭合：

```sh
# 每个缺失 kmod 造一个空 ipk，只写 Provides（不装任何文件）
# 依赖图闭链后，opkg 才会真正去下载 containerd / runc / libdevmapper 等真依赖
```

桩包做好后 `opkg install dockerd` 正常下载全套真依赖（实测 dockerd 20.10.17 装好、
containerd / runc / libdevmapper / btrfs-progs 全部到位、服务 running）。

### 其余场景

- **Docker** 走 `host` 网络 + `bridge: none` + `iptables: false`，用不到 veth/bridge
- **OpenClash** TUN 可用（`tun.ko` 在）；ipk 依赖里的 `luci-compat` 等固件自带
- 其他个别包确实只差依赖时，`--force-depends` 仍可用；但**先确认不是"选候选包"阶段失败**

## 三、curl 与 wget 是两条不同的网络栈（重要）

同一地址 `https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh`：

| 工具 | 结果 |
|---|---|
| `curl -fsSL` | **000（失败）** |
| `wget -qO` | **200，5965 bytes（成功）** |

→ 下载函数必须 **curl 失败立刻换 wget 重试同一个 URL**，再考虑切换镜像源。
另外 ghfast.top / gh-proxy.com 实测都是 200，可作回退。

```sh
get() {
  HAS_DL=0
  if command -v curl >/dev/null 2>&1; then HAS_DL=1; curl -fsSL -m 180 -o "$2" "$1" && return 0; fi
  if command -v wget >/dev/null 2>&1; then HAS_DL=1; wget -q -T 180 -O "$2" "$1" && return 0; fi
  [ "$HAS_DL" = 1 ] || { echo "no curl/wget" >&2; exit 1; }
  return 1
}
```

## 四、跨重启续跑机制（本方案的技术核心）

### 为什么必须重启

分区后 `/overlay` 要从 NOR 的 mtdblock8（2MB）换成卡上 p1（默认 16G）。
overlay 的切换只在**开机早期**由 `mount_root` 完成，**没法在线换**。
（2MB 装不下 OpenClash 的 46MB 内核，所以必须换。）

### 难点：重启会丢掉当前系统写的一切

写在当前 overlay 里的任何"开机后继续"钩子，重启后随旧 overlay 一起消失。

### 解法：预置到新卡 p1 的 upper 层

**关键情报**：执行 `/etc/rc.local` 的**不是 rc.local 服务** ——
固件里**根本没有 `/etc/init.d/rc.local`**。真正执行它的是：

```
/etc/rc.d/S95done -> ../init.d/done
/etc/init.d/done 的 boot() 里：  [ -f /etc/rc.local ] && sh /etc/rc.local
```

而 **`S95done` 来自只读的 `/rom`**，所以新 overlay 哪怕是空的，这个钩子照样会被执行。

→ 于是把 overlay 的 upper 层**直接预置进 p1**：

```
<新卡 p1>/
├── upper/etc/rc.local   ← 续跑代码（overlayfs 上层优先于 /rom）
└── work/
```

`kp-install.sh` 之外的 `install.sh` 里 `arm_auto()` 负责：

```sh
mount -t f2fs ${DISK}p1 /mnt/kp-prep
mkdir -p /mnt/kp-prep/upper/etc /mnt/kp-prep/work
cat > /mnt/kp-prep/upper/etc/rc.local <<EOF
...三源 + curl/wget 双栈拉 install.sh，重跑...
EOF
chmod 755 ...; sync; umount
```

重启后：`S95done` → `sh /etc/rc.local` → 拉 `install.sh` 重跑 →
此时 `/overlay` 已落在 `${DISK}p1` 上 → 直接进安装 →
装完 `sed -i '/kp-auto/d' /etc/rc.local` 自删，不会重复执行。

**就绪判据必须看 `/overlay` 而不是 `/mnt/storage/data`**：

```sh
[ "$(awk '$2=="/overlay"{print $1}' /proc/mounts)" = "${DISK}p1" ]   # 正确
grep -q " /mnt/storage/data " /proc/mounts                            # 错误（会误判）
```

原因：数据分区 p2 因固件热插拔 bug 可能挂不上（见下），
若拿它当判据会误判成"存储没就绪"→ 又去分区 → 白白清一遍卡。

### p2 挂不上是固件 bug，需要自己兜底

固件热插拔脚本 `/etc/hotplug.d/block/00-mount` 会把新分区先挂到 `/tmp/storage/<设备名>`，
只有 `ID_FS_PARTLABEL=nradio_user_data` 才改挂到 `/mnt/storage/data`。
**而 MBR 分区表根本没有 PARTLABEL**（`blkid -o udev` 只给出 `ID_FS_LABEL`）→ 该判据永远不成立
→ 分区停在 `/tmp/storage/mmcblk0p2`。随后 `/etc/init.d/fstab` 的 `block mount`
看到"设备已被挂载"就跳过，**返回 0 但 `/mnt/storage/data` 始终是空的**。

兜底方案（`kp-install.sh` 的 `ensure_data()` + `install_data_service()`）：
1. 卸掉 `/tmp/storage/<dev>` 那处挂载
2. 自己挂到 `/mnt/storage/data`
3. 生成 `/etc/init.d/kp-storage`（`START=41`，排在 `fstab` 的 S40 之后）保证每次开机都挂

### heredoc 变量展开的坑

`<<EOF`（不带引号）会在**生成时**展开所有 `$变量`。所以：
- `$RAW` **要**展开（写成 `$RAW`）
- 运行时的循环变量**必须转义**（写成 `\$u`）

已用 mock `mount`/`umount` 隔离验证过生成结果：`$RAW` 正确展开、`$u` 保留、
三源齐全、`sh -n` 通过、`upper/`+`work/` 结构正确。

## 五、⚠️ `set -e` 会静默退出：本方案踩过两次的坑

四个主流程脚本（`install.sh` / `kp-install.sh` / `kp-storage-init.sh` / `kp-ocspeed.sh`）
都开了 `set -eu`。`set -e` 下**命令返回非 0 就可能让脚本无声退出**（一行报错都没有）。

> 脚本清单别记错（2026-09-16 复核）：开 `set -eu` 的一共 **5** 个 —— 上面 4 个加上
> 开发用的 `kp-ui-preview.sh`（它**没有** trap）；`kp-store-check.sh` **刻意只开 `set -u`**
> （诊断工具不该因为某个查询返回非 0 就自己退出）；`kp-ui.sh` / `kp-store-lib.sh` /
> `ocspeed/speedswitch.sh` 自己不设标志，被 `source`/调用时**继承调用方的 `-e`**
> —— 所以后三个文件里的函数同样受 `set -e` 约束，别因为"文件里没写 set -e"就放松。

> **2026-09-16 修正（真机实测）**：这一节原先写的是"任何非 0 都退出 / 禁用
> `cmd && break` 与 `[ x ] && {...}`"。在设备上的 busybox ash 里拿 12 个用例逐条跑过之后，
> 结论是**那两种写法本身是安全的**（ash 遵循 POSIX 的 AND-OR 豁免规则，实测 11 种形态全都不退出）。
> 真正会退出的是下面三类 —— 别再去改那些本来安全的写法，白添改动风险。

### 实测过的三条规则

1. **`[ x ] && y` / `cmd && break` 安全，不用改。**
   **唯一例外**：当它是**函数的最后一条语句**、且该函数被**裸调用**时，函数返回 1 会让调用点触发
   `set -e`（`f() { [ -n "" ] && Y=1; }; f` 实测直接退出）→ 函数末句要放必然返回 0 的命令。
2. **每个 `X=$(cmd)` 后面都跟 `|| X=""`** —— 纯赋值语句的退出码 = 命令替换的退出码。
   **这才是真正踩过两次的凶手**（见坑 B）。
3. **可能失败的裸命令要兜底** —— `uci -q delete <不存在的键>`、`cp <不存在的文件>`、
   `/etc/init.d/xxx enable` 都返回非 0，而它们不在 `&&` / `||` 列表里，会直接结束脚本。
   写 `|| :` 或 `|| ui_warn "..."`。

### 踩坑记录

| 坑 | 现象 | 根因 | 正确写法 |
|---|---|---|---|
| A | 续跑时"存储未就绪"误判后清卡 | **不是** `cmd && break`（实测该写法安全）；同一函数里还有没兜底的 `X=$(cmd)` 赋值 | `X=$(cmd) \|\| X=""` |
| B | [2/4] 阶段无任何报错直接中断 | `OC_CONF=$(uci -q get openclash.config.config_path)` —— **纯赋值语句的退出码 = 命令替换的退出码**，`uci get` 对未设置的键返回 1 | `OC_CONF=$(uci -q get ...) \|\| OC_CONF=""` |

### 必装防线：EXIT 陷阱（**不是 ERR**）

⚠️ **busybox 的 ash 不认 `ERR` 信号**：`trap ... ERR` 直接报
`trap: ERR: invalid signal specification`（2026-09-15 实测），那道防线等于没装 ——
脚本照样静默退出。只能用 `EXIT`：

```sh
trap 'rc=$?; [ "$rc" = 0 ] || echo "  ✗ 脚本中断（rc=$rc）—— 上面最后一行输出就是线索" >&2' EXIT
```

三个细节：
- **不要在陷阱里用 `$LINENO`** —— busybox ash **没有这个变量**，会打印空值；只能靠
  "倒数第二行输出"来定位中断点（早期文档里写过 `在第 $LINENO 行中断`，是错的）。
- **`|| :` 或 `[ ... ] ||` 的兜底不能省** —— 否则陷阱自身返回非 0 会再次触发。
- **不能在陷阱里裸写 `echo`** —— `EXIT` 陷阱正常退出时也会执行，裸 `echo` 会让每次成功
  运行都多打一行，看起来像失败。必须先判 `[ "$rc" = 0 ] ||`。

## 六、端到端验证清单（改完脚本照这个走一遍）

1. **语法**：**全部** `.sh` 递归走 `bash -n`（当前 9 个，别漏 `ocspeed/speedswitch.sh`、
   `kp-store-lib.sh`；用 node `execFileSync` 调 PortableGit 的 bash，
   `export PATH=/usr/bin:/bin`，输出由 node 自己写文件 —— 走 PowerShell 中转会把中文和 ESC 毁掉）
2. **三源可达**：设备上 `curl` / `wget` 分别测 raw、ghfast、gh-proxy
3. **换行**：推送前统一 CRLF→LF（CRLF 会让设备上的 sh 报错）
4. **续跑脚本生成**：mock mount/umount 跑 `arm_auto`，检查 `$RAW` 展开与 `$u` 保留
5. **⚠️ 等 CDN 缓存过期**：`raw.githubusercontent.com` 有 **约 5 分钟**缓存，
   刚 push 完就跑会拿到旧脚本，验证结果毫无意义。先用特征串探测远端版本再跑：
   ```sh
   wget -qO /tmp/_p.sh <raw>/kp-install.sh && grep -cF 'ERR || :' /tmp/_p.sh
   ```
6. **"远端是不是最新版"只能靠 git tree 比 blob sha**：`GET /git/trees/<sha>?recursive=1`
   拿每个文件的 blob sha，本地按 `blob <size>\0<content>` 重算 SHA1 逐个比对 —— 不经过 CDN、
   不受缓存影响。**只比 raw 的 md5 是不够的**：入口文件之外的 `docs/`、`ocspeed/` 覆盖不到，
   会得出"已同步"的假结论。

### 静态扫描找 bug：**先证伪，再报bug**（2026-09-16 第三轮审计的教训）

写一个"按踩过的坑逐类扫描"的脚本很有用，但**它的价值完全取决于证伪率**：不逐条回读源码就报
"发现 89 个问题"，那是噪声，还会把本来安全的代码改坏。两个必踩的扫描器陷阱：

- ⚠️ **`set -e\b` 匹配不到 `set -eu`** —— `e` 与 `u` 之间没有词边界，正则失配。结果：
  5 个明明开了 `set -e` 的脚本全被判成"没开"，于是所有"`X=$(cmd)` 缺兜底"的结论全是错的。
  正解是**解析真实的标志串**：`/^\s*set\s+(-[a-zA-Z]+)\s*$/` 逐行拼起来再判断含不含 `e`。
- ⚠️ **"函数在定义前被调用"必须带大括号深度，只报顶层（depth=0）** —— 函数体内的调用
  在源码里写在哪都无所谓（运行期一定已定义），不带深度就会把这些全报成 bug：
  `uci -q get`、`https://mirrors.aliyun.com`、`command -v ui_ok`、`/var/log/xxx.log`
  里的 `get` / `mirrors` / `log` 都会被当成函数名命中。
- 另外两类高频误报：`i=$((i+1))`（算术赋值不会失败）、`X=$(cmd1 | cmd2)`
  （**退出码只看最后一段**，`head`/`cut`/`tr`/`wc` 读 stdin 基本不会失败）。
  真正要盯的是**末段为 `sed`/`awk`/`grep`/`opkg` 且读实体文件、又没 `2>/dev/null`** 的那种。

**结论**：扫描出来的每一项都要回读源码给出"真 / 假"的判定；假阳性要能说出为什么安全
（例如 `[ -n "$size" ] || size=0` 之后才 `total=$((total+size))`、`awk 'END{print s+0}'`
保证算术永不为空）—— 说不出原因的，就还没查完。

## 七、推送：空仓库不能用 Git Data API

`POST /git/blobs` 在空仓库上返回 **409 `Git Repository is empty`** —— 必须先有一个 commit。

流程：

1. Contents API `PUT /contents/README.md` → 建初始提交（自动创建 main 分支）
2. `GET /git/ref/heads/main` → 拿 base commit / tree
3. `POST /git/blobs`（每个文件一个）
4. `POST /git/trees`（带 `base_tree`，`.sh` 用 mode `100755`）
5. `POST /git/commits`（带 `parents`）
6. `PATCH /git/refs/heads/main`

token：`C:\tmp\bin\gh.exe auth token`（用完即弃，不落盘）。
本机 `git push` 被安全软件静默拦截（rc=128、stderr 全空），这条 API 路是唯一可靠通道。

## 八、真机端到端结果（2026-09-15 已验证）

| 项 | 结果 |
|---|---|
| 一键命令全流程 | ✅ 首跑 1m41s、二跑幂等（1Panel 走"已安装回读凭据"0 秒分支） |
| 换源 | ✅ 出厂 6 源全失效（`000`）→ 阿里云 21.02.7 base/packages/routing |
| OpenClash | ✅ 包 + 46MB 内核（`Meta alpha-ge183c58 with_gvisor`）；7890 未监听属预期（无订阅） |
| Docker | ✅ dockerd 20.10.17 + overlay2，数据根 `$PANEL_DIR/docker` 真落在 p2 |
| 1Panel | ✅ HTTP 200；`1pctl` 先写再启动（DB 由首启播种） |
| 自启链 | ✅ `S41kp-storage` / `S99dockerd` / `S99openclash` 齐全 |
| 扩容 | ✅ `/` 16.0G（可用 15.1G）+ 数据 13.1G（可用 12.6G） |

### 仍然存在的硬边界

- **容器只能 host 网络**：`lsmod | grep -c veth` = 0，`docker0` 能建但容器接不上
  （`failed to add the host <=> sandbox (veth...) pair interfaces`）
- **OpenClash 需订阅才能真正跑起来**：内核与包都就绪，填了订阅即可
- **扩容只能在"NOR 窗口"做**：`resize.f2fs` 拒绝已挂载 fs，详见 `tf-partition-resize.md`
上面 1-5 项是静态/隔离验证。首次真机执行时重点盯：

- 重启后 `/etc/rc.local` 是否真被 `S95done` 执行（看 `/tmp/kp-auto.log` 是否生成）
- `mdev -s` 后 `${DISK}p1` / `p2` 节点是否出现（不出现则需手动 reboot 重跑）
- 阿里云源下 `dockerd` 的 `--force-depends` 是否顺利（depends 缺失但功能可用）

## 九、注册进鲲鹏商店（2026-09-16 全流程打通）

三个应用都注册进去：**1Panel / OpenClash / ocspeed**。实现全在 `kp-store-lib.sh`。

| 环节 | 真机制 | 坑 |
|---|---|---|
| 应用目录 | UCI `/etc/config/appcenter` 的 `config package` + `config package_list`，出 `ubus call appcenter list` | 写完要 `uci commit appcenter` + `/etc/init.d/appcenter restart` 才生效 |
| 子包 vs 主包 | 一条主 `package`（卡片：name/icon/des/version/size）+ N 条 `package_list`（`parent` 指向主条目） | 删旧条目要**边删边判**（删除会让索引左移，不能 for 到底） |
| 「已安装」 | 守护进程对每个子包名实时跑 `opkg info` | 非 opkg 安装的应用（1Panel / ocspeed）**必须造空占位 ipk**（`app-1panel` / `app-ocspeed`），否则永远显示未安装 |
| 「打开」 | iframe 加载 `luci_module_route` | 守护进程**只给远程目录里的应用下发这个字段**，UCI 里手写会被重写丢弃 → 路由写 `/etc/kp_store/routes.list`（`应用名\|路由`），由 `appcenter.lua` **末尾后定义同名函数覆盖** `action_app_list_data()` 注入 |
| 改完生效 | — | `rm -rf /tmp/luci-modulecache /tmp/luci-indexcache` + `/etc/init.d/uhttpd restart` |
| 页面判活 | `curl -o /dev/null -w '%{http_code}'` | **未登录 403 = 页面存在**（LuCI 保护），404 才是真没有 —— 不用拿密码也能体检 |

**跑在独立端口的服务**（1Panel 在 :10090）不能直接当「打开」目标 → 造**同源承载页**：
`controller/nradio_adv/kp1panel.lua`（注册 `template()` 路由）+ `view/nradio_kp1panel/panel.htm`
（里面再套一层 iframe）。面板地址**动态读** `1pctl user-info | grep -oE 'http://[^ ]*'`，别写死。

体检：`SCRIPT=kp-store-check.sh sh /tmp/kp.sh`（只读，输出逐项 ✓ / !）。

## 十、Docker 冒烟：必须 `--network host`

- `docker info` 通**不代表**能拉镜像（本机直连 `registry-1.docker.io` 15s 无响应）
- **`docker run` 默认桥接必失败**：`failed to add the host (veth...) <=> sandbox (veth...) pair interfaces: operation not supported`
  → 冒烟一律 `docker run --rm --network host hello-world`
- 拉不动就**逐个加速镜像单独试**：清 `dockerd.globals.registry_mirrors` → `uci add_list` 单个 →
  `commit` → `restart dockerd` → 再拉；把能用的那个留在 UCI 里
- 配置**只认 UCI** `/etc/config/dockerd`（init 渲染到 `/tmp/dockerd/daemon.json`）；
  写 `/etc/docker/daemon.json` 完全没人读（实测那样跑出来还是 `vfs` + `/opt/docker`）
- 自启要**无条件** `enable`（只判 `docker info` 会漏掉"在跑但没开自启"）

## 十一、ocspeed 丢失与恢复（自建插件的通病）

ocspeed **不在任何 opkg 源里**：代码全在 `/usr/libexec/openclash-helper/`、
`/usr/lib/lua/luci/{controller,view}/`、`/etc/config/ocspeed`，跟 overlay 走。
重建 TF 卡 / 换卡 / `REBUILD=1` 扩容之后整个目录消失，`crontab` 里只剩系统 logrotate，
`opkg install` 查无此包 —— **2026-09-16 实测踩过**（16G 扩容重建后全丢）。

- 单独恢复：`SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh`（可加 `OCS_GROUP=宝贝云 OCS_RUN=1`）
- 源码五件套在仓库 `ocspeed/`；数据盘另留一份 `/mnt/storage/data/ocspeed-backup/`
  （断网时能原地 `cp` 回来）
- cron 由插件自己的 `enable` / `disable` 重建 3 条（自动测速 / 故障切换 / 备用预选），
  **别手工改 `/etc/crontabs/root`**，下次 enable 会覆盖
- 上传大文件（88KB 的 htm）**必须按行分块**：单条 `exec_command` 超约 8KB 会被 dropbear reset
- 目录约定：`$DATA=/etc/openclash-helper`（产物 `nodes.json` / `status.json` / `sites.json` /
  `history.log` / `last_run`），`$DIR=/tmp/ocspeed`（测速工作目录）
- **`speedswitch.sh run` 的日志走 `/var/log/ocspeed.log`，stdout 是空的**。
  RC=0 且一行输出都没有是**正常的**，不是空转；要看结果去 tail 那个日志文件，
  或者 `sh -x … run` 开 trace。

## 十二、两个"重跑也不生效"的陷阱（2026-09-19 端到端回归实测）

### 1. `kp-ocspeed.sh` 曾复用 tmpfs 缓存 —— 修了

`fetch_oc()` 原来是「`$OC/$1` 存在就 `return 0`」，而 `$OC=/tmp/kp-nros/ocspeed`
在 **tmpfs，开机内一直保留**。后果：同一次开机里第二次跑（含 overlay 重建后"重跑恢复"
这个最典型场景）装的永远是第一次下载的那份，脚本还照样打印 `✓ 文件已就位`。

现在改成：每次下到 `.new`、成功才 `mv`；三源全挂才退回缓存，**并明确打印"沿用旧版"**。

> 排错提示：重跑后文件字节数没变 → 先看 `/tmp/kp-nros/ocspeed/` 里的缓存，
> 再看 CDN 边缘有没有分发延迟（`install.sh` 的 `get()` 先走 curl，和你手工 wget
> 可能命中不同边缘节点，拿到不同版本）。

### 2. `ocspeed.lua` 曾写死控制端口/密钥 —— 修了

旧代码 `curl … -H "Authorization: Bearer 7LHZ3l74" http://127.0.0.1:9090/…`。
`speedswitch.sh` 一直是从 `uci openclash.config.{cn_port,dashboard_password}` 取，
两处不一致时 lua 那条查询 401；而下面有 `if cur == "" then cur = st.now end` 兜底，
页面静默显示 `status.json` 的**陈旧值**，肉眼看不出来。现在两处取同一套 UCI。

## 十三、静态/动态扫描：先证伪探针，再报 bug

2026-09-19 一轮里，9 个可疑点中有 3 个是**探针自己错了**：

| 假象 | 真相 |
|---|---|
| `opkg status a b c d \| grep -c '^Status:'` = 1，以为漏包 | **`opkg status` 多参数只返回 1 条**。逐包判才准（仓库里 4 处调用全是单包） |
| `/tmp/ocspeed/*.json` 报"非法" | 取的是 `jsonfilter -e '$.ts'`，而 `progress.json` 只有 `phase/msg/pct`。用 `-e '$'` 判合法性 |
| 二进制里搜不到 `Tuic`/`TUIC` → 以为白名单错 | **BusyBox grep 不支持 `-a`**，错误又被 `2>/dev/null` 吞了；连 `mihomo`、`proxy` 都零命中 |
| `/tmp/ocspeed/nodes.json` 报"非法"→ 推出"run 并发把 JSON 写坏了" | **JSON 根本不放在那儿**。`DIR=/tmp/ocspeed` 只放临时文件/锁 `lock/`/`progress.json`；`DATA=/etc/openclash-helper` 才放 `nodes.json` / `status.json` / `sites.json` / `backup.json`。路径写错 → 三项校验齐刷刷 FAIL |

规则：**报 bug 之前先让探针在一个必然为真的输入上通过。**

规则二：**探针里的路径要从脚本的变量定义里抄**（`grep -n '^DIR=\|^DATA=' speedswitch.sh`），
不要凭记忆写。路径错产生的"全 FAIL"看起来和"文件被写坏"一模一样。

## 十四、JSON 原子写入 + 「隔离副本 + 放大输入」的 A/B 方法（2026-09-19）

### 成因

`nodes.json` / `status.json` 是**几十次 `printf` 追加**写出来的，而 run 进行中
页面会通过 `speedswitch.sh status|nodes` 实时 `cat` 它们 → 读到半截 JSON，
`jsonfilter` 直接报错、页面偶发空白，刷新又好了。`sites.json` 早就是
`{...} > .tmp; mv`，这两个一直没补。现在三个文件统一 tmp+mv。

### 怎么证明的（关键方法，可复用）

线上 72 节点的写窗口只有几毫秒，靠"跑一次碰运气"测不出来。做法是**隔离 + 放大**：

1. 把脚本里 `DATA`/`DIR` 两行 `sed` 改道到 `/tmp/race/*` → **完全不碰线上文件**；
2. 用 `sed -n` 只抽出要测的**真实函数** `build_nodes_json`，连同它依赖的变量段
   和 `json_esc` / `get` / `is_fake`，末尾追加一行 `build_nodes_json` 当驱动；
3. 把 `allnodes.txt` 放大到 4000 行 → 写窗口从毫秒变成秒级；
4. 同进程内 `sh harness & wp=$!` + `while kill -0 $wp` 循环里密集
   `jsonfilter -i … -e '@'`，统计合法读 / 撕裂读。

结果（三轮）：直写 `>` + `>>` → 撕裂 **3413~4351** 次、合法仅 5~10 次；
`tmp+mv` → 撕裂 **0** 次、合法 2.4~2.6 万次。两版产物字节数完全相同。

> harness 抽函数时注意：`json_esc` / `get` 是**单行函数**，
> `sed -n '/^name()/,/^}/p'` 会一路吃到后面第一个独占一行的 `}`，把无关函数拖进来；
> 单行的要用 `/^name() {/p`。漏抽 `get` 的表现是每个节点刷一行 `get: not found`
> —— **带报错跑出来的数据不算证据**，必须重跑到 stderr 为空。

### 顺带修掉的：节点类型白名单大小写

mihomo 的 `type` 是 Go 常量（`Tuic` / `ShadowTLS` / `AnyTLS` / `Mieru` / `SSH`），
版本间还变过；而 ash 的 `case` 区分大小写 —— 原名单写的是 `TUIC|Shadowtls`，
拼法对不上就**整类节点静默不参与测速**（现象是"机场明明 60 个节点，测速只认 44 个"，
日志毫无线索）。现在统一小写归一后比对（`NODE_TYPES` + `tr 'A-Z' 'a-z'`）。
已核对策略组类型（Selector / URLTest / Fallback / LoadBalance / Relay / Direct /
Reject / Compatible / Pass / Dns）小写后与名单无任何重合，不会误收组名。

验证方法（真机订阅里没有这几类节点，只能合成）：把两版各自的 `while` 循环**按行号
`sed` 出来**，喂同一份合成 `nt.tsv`（`Tuic`/`ShadowTLS`/`AnyTLS`/`Mieru`/`TUIC`/
`Shadowtls`/`Vless` + 三个组类型）→ 旧版收 5 个（含写死的 `TUIC`/`Shadowtls`），
新版收 7 个（多收 `Tuic`/`ShadowTLS`），策略组两版都排除。

