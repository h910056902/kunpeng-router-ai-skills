# 任务 03 · 装 Docker + 1Panel（含 host 网络默认化）

> `id: docker.install` / `panel.install` / `panel.hostnet` / `restore.all` · `risk: write`（`restore.all` 为 `destructive`）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，内核 **5.4.281**，OpenWrt 21.02，TF 卡存储）
> 目标：dockerd 起来且 storage-driver = **overlay2**；1Panel 面板起来且能登录；
> 1Panel 装应用不再报 veth 错。
> 参考档案：[`references/c2000u-docker.md`](../references/c2000u-docker.md)、
> [`references/c2000u-1panel.md`](../references/c2000u-1panel.md)、
> [`references/one-command-restore.md`](../references/one-command-restore.md)、
> [`references/1panel-hostnet-default.md`](../references/1panel-hostnet-default.md)。

---

## 0. 三条决定性事实（先读，否则必踩）

1. **dockerd 的配置只认 UCI。**
   `/etc/init.d/dockerd` 每次启动都 `rm -rf /tmp/dockerd` 后把 **UCI** 渲染成
   `/tmp/dockerd/daemon.json`，再用 `--config-file=/tmp/dockerd/daemon.json` 加载。
   → **写 `/etc/docker/daemon.json` 完全没人读。** 想要 `storage-driver` / `bridge` 这类
   UCI 生成器不支持的字段，唯一正路是：
   ```sh
   uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json'
   uci commit dockerd
   ```
   init 见到该项就会 `ln -s` 你的文件到 `/tmp/dockerd/daemon.json`，全文由你掌控。

2. **`--force-depends` 救不了 `dockerd`。**
   依赖链里有 **6 个厂商内核根本不存在的 kmod**：`kmod-veth` / `kmod-dm` / `kmod-fs-btrfs` /
   `kmod-br-netfilter` / `kmod-ikconfig` / `kmod-nf-ipvs`。opkg **在「选候选包」阶段就失败**，
   根本走不到依赖检查，所以 `--force-depends` 加了也报同样的错。
   → **必须造只声明 `Provides` 的空桩包**（`offline/stubs/` 已备好 6 个，恰好完整、不多不少）。

3. **容器只能用 host 网络。** `lsmod | grep -c '^veth'` = 0，`CONFIG_VETH is not set`。
   所以 daemon.json 里锁死 `"bridge":"none"` + `"iptables":false`，
   冒烟测试**必须** `docker run --rm --network host`；1Panel 装应用必须做 §4 的 host 默认化。

---

## 1. 前置检查

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| 1 | 架构 | `uname -m` | `aarch64` | 不匹配就别继续 |
| 2 | 可用内存 | `free -k \| awk '/MemAvailable/{print $2}'` | **> 250000**（dockerd ~60MB + containerd ~38MB + 1Panel ~100MB） | 先停重容器；先删 Exited 死容器 |
| 3 | 存储就绪 | `awk '$2=="/overlay"{print $1}' /proc/mounts` | `/dev/mmcblk0p1` | 若是 `mtdblock8` → overlay 丢了，走 `restore.all` |
| 4 | 数据分区已挂 | `df -k /mnt/storage/data \| tail -1` | 有可用空间 | 见 `references/one-command-restore.md` 的 `ensure_data()` 兜底 |
| 5 | 数据分区是**裸 f2fs** | `awk '$2=="/mnt/storage/data"{print $3}' /proc/mounts` | `f2fs` | 非 f2fs / 挂在 overlayfs 之上 → overlay2 用不了，会退化成 vfs |
| 6 | opkg 源可用 | `grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf` | **`0`** | 先换源（见任务 01 §2） |
| 7 | 端口占用 | `netstat -ltn \| grep -cE ':10090\b'` | `0`（要装 1Panel 时） | 换端口（`PANEL_PORT`） |

```sh
# 一次性跑完（设备侧，只读）
echo "--- 1 arch";  uname -m
echo "--- 2 mem";   free -k | awk '/MemAvailable/{print $2}'
echo "--- 3 ovl";   awk '$2=="/overlay"{print $1}' /proc/mounts
echo "--- 4 data";  df -k /mnt/storage/data | tail -1
echo "--- 5 bare";  awk '$2=="/mnt/storage/data"{print $3}' /proc/mounts
echo "--- 6 src";   grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf
echo "--- 7 port";  netstat -ltn | grep -cE ':10090\b'
```

> **overlay2 与 `/mnt/storage/data` 是绑定的**：那个分区是**裸 f2fs 挂载**（不在 overlayfs 之上），
> Docker 才肯用 overlay2。放到 `/opt/docker`（在 overlayfs 根分区上）只能退化成 **vfs** ——
> 空间放大、启动变慢。**二选一，不能都要。**

---

## 2. 装 Docker（六步）

```sh
# ① 备份出厂源
cp -a /etc/opkg/distfeeds.conf /etc/opkg/distfeeds.conf.kp-bak-$(date +%Y%m%d_%H%M%S)

# ② 换源到阿里云 21.02.7（内容同任务 01 §2）→ opkg update
#    （阿里云 packages feed 实测有 docker / dockerd / containerd / docker-compose / runc）

# ③ 造/装 6 个 kmod 空桩包
#    ⚠️ 装桩包前必须移走 feed 索引，否则被同名包截胡、报出桩包里没有的依赖
mv /var/opkg-lists /var/opkg-lists.off
for f in kmod-veth kmod-dm kmod-fs-btrfs kmod-br-netfilter kmod-ikconfig kmod-nf-ipvs; do
  opkg install --force-reinstall /tmp/stubs/${f}_5.4.281-1_aarch64_cortex-a53.ipk
done
rm -rf /var/opkg-lists; mv /var/opkg-lists.off /var/opkg-lists

# ④ 装 dockerd（依赖链闭合后会自动带出全部真依赖）
opkg install dockerd
#    期望带出：containerd 1.6.6 / runc 1.1.2 / libnetwork / tini 0.19.0 / libseccomp 2.5.1
#              btrfs-progs / libdevmapper / docker CLI

# ⑤ 写 daemon.json 并让 init 读它（不是直接写 /etc/docker/daemon.json 就完事！）
mkdir -p /etc/docker
cat > /etc/docker/daemon.json <<'EOF'
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
EOF
uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json'
uci commit dockerd

# ⑥ 启服务 + 无条件开自启（只判 docker info 会漏掉「在跑但没开自启」）
/etc/init.d/dockerd enable
/etc/init.d/dockerd restart
```

**桩包清单为什么是这 6 个（不多不少）**：对 `opkg status dockerd | grep '^Depends:'` 的每一项跑
`opkg list | grep -c "^$dep "`，为 `0` 的就是必须靠桩包兜住的 —— 实测恰好是这 6 个
（`kmod-dm` 由 `libdevmapper` 带出，`kmod-fs-btrfs` 由 `btrfs-progs` 带出）。

---

## 3. 装 1Panel

### 3.1 为什么它能在这台机器上原生跑（三个前提）

1. **musl 兼容**：官方 arm64 二进制是**静态链接**。自检：`head -c 4096 1panel | grep -c ld-linux` → `0`。
2. **无 systemd 也能跑**：官方包自带 4 套 init（systemd / openrc / **procd** / sysvinit），
   `install.sh` 在 `[ -f /etc/rc.common ]` 时用 `1paneld.procd`（`USE_PROCD=1`，`START=95`）。
3. **bash 依赖**：`1pctl` 是 bash 脚本（用了 `${var,,}`），需先 `opkg install bash`。

### 3.2 非交互安装的关键顺序（**顺序不能反**）

`1panel` 二进制启动时会**解析 `/usr/local/bin/1pctl`**，取 `BASE_DIR=` 与 `ORIGINAL_*=` 来初始化
DB（`$BASE_DIR/1panel/db/1Panel.db`）。
→ **非交互安装 = 先把 `1pctl` 复制到位并 `sed` 写好这些值，再启动服务。**

官方 `install.sh`（v1.10.34-lts）的 `init_configure` 顺序：
`cp 二进制` → `ln -s /usr/bin` → `sed 1pctl`（BASE_DIR / ORIGINAL_PORT / USERNAME / PASSWORD(转义) /
ENTRANCE / LANGUAGE）→ `GeoIP.mmdb` → `lang` → `1paneld.procd` → `/etc/init.d/1paneld` →
`enable` → `start`。

```sh
# 版本通道（实测国内 CDN 35MB/s）
#   .../package/stable/latest          -> v1.10.34-lts（单二进制，1GB 内存友好）★ 用这个
#   .../package/v2/stable/latest       -> v2.2.5（core+agent 双二进制，更重）不建议
# 包 URL： https://resource.fit2cloud.com/1panel/package/{channel}/{ver}/release/1panel-{ver}-linux-arm64.tar.gz
# 校验：   同目录 checksums.txt（每包一行 sha256）
```

### 3.3 三个必须知道的坑

- 🔴 **官方 `install.sh` 的 `configure_accelerator` 会把 UCI 里的镜像加速源覆盖掉**
  （只留 `docker.1panel.live` 一个）。→ **不要执行那一段。**
- 官方 OpenWrt 分支还会装 `luci-i18n-dockerman-zh-cn`（无用的 UI 翻译包）→ 跳过。
- 🔴 **绝不 `rm -rf $BASE_DIR/1panel`**：该目录含 `db/1Panel.db`（约 7.5 MB = 面板全部状态：
  账号 / 入口码 / 应用与站点配置）+ `geo/` 18.7 MB + `resource/` 4.6 MB。
  若删除发生在解包校验**之前**，tar 一失败就无法回滚。
  → **正确做法：先解包校验，再把旧目录改名保留**（`1panel.bak-<时间戳>`），不是删除。

### 3.4 幂等重跑（第二次跑不要重新生成凭据）

`1pctl` 里**始终保留明文配置**，所以重跑时应从它回读而不是重新生成（否则凭据文件会被垃圾覆盖）：

```sh
pv() { grep "^$1=" /usr/local/bin/1pctl | head -1 | cut -d= -f2- | sed 's/\\//g'; }
PORT=$(pv ORIGINAL_PORT); USER=$(pv ORIGINAL_USERNAME)
PASS=$(pv ORIGINAL_PASSWORD); ENT=$(pv ORIGINAL_ENTRANCE)
```
另外 `1pctl version` **输出两行**（版本行 + 模式行），取版本要用
`grep -m1 -oE 'v[0-9][0-9A-Za-z.-]*'`，别 `tail -n1`。

---

## 4. host 网络默认化（**必做**，否则 1Panel 装应用必挂）

**问题**：1Panel 的应用商店模板一律引用外部 bridge 网络 `1panel-network`，
而本机内核没有 veth → 容器 `up` 时报
`failed to add the host (veth...) <=> sandbox (veth...) pair interfaces: operation not supported`。
`docker network create -d host` 也被拒（docker 只允许一个预定义 host 网络）→ **改网络不可行，只能改模板**。

**正解**：换掉 `/usr/bin/docker-compose` 为 wrapper（真件改名 `.real` 保留），
每次被调用时把 `-f` 指向的 compose **幂等 host 化** → 面板 / 商店 / 手工全部生效，
而且容器由 1Panel 自己 `up`（会进「已安装应用」）。

```sh
# PC 侧推送三件套（用 revtunnel_put.py）
python scripts/revtunnel_put.py scripts/payload/install-hostnet-default.sh /tmp/kp1pt/
python scripts/revtunnel_put.py scripts/payload/kp-compose-host.sh          /tmp/kp1pt/
python scripts/revtunnel_put.py scripts/payload/docker-compose.wrapper      /tmp/kp1pt/
python scripts/revtunnel_put.py scripts/payload/kp-compose-selftest.sh      /tmp/kp1pt/
python scripts/revtunnel_put.py scripts/payload/fixtures/compose.panel4sp.yml /tmp/kp1pt/fixtures/

# 设备侧：先回归自测，再装
cd /tmp/kp1pt && sh ./kp-compose-selftest.sh      # 期望 PASS 全过 / FAIL=0
sh ./install-hostnet-default.sh --dry-run         # 看它打算改什么
sh ./install-hostnet-default.sh                   # 实装
```

**转换器必须「缩进无关」**：1Panel v1.10 落盘的 compose 是 **4 空格缩进 + 多一个 `deploy` 段**，
而商店 tarball 是 2 空格 —— 写死缩进会让面板装应用报
`Service "x" uses an undefined network`（2026-09-19 真机事故）。
本仓库的 `kp-compose-host.sh` 已改为先量出服务名/属性缩进再操作；
`fixtures/compose.panel4sp.yml` 就是那份事故原件，别删。

**回滚**：`sh install-hostnet-default.sh --restore`

---

## 5. 一条命令全装（换卡 / overlay 丢失后）

```sh
wget -qO /tmp/kp.sh https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh && sh /tmp/kp.sh
```

四阶段：**预检换源 → OpenClash → Docker → 1Panel**（之后还会跑 `kp-ocspeed.sh`）。
存储没就绪会先分区 + 重启，重启后靠**预置到新卡 p1 的 `upper/etc/rc.local`** 自动续跑。

- 跳过某步：`SKIP=oc,docker,panel,ocspeed`
- 只跑某步：`SCRIPT=kp-install.sh sh /tmp/kp.sh` / `SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh`
- 强制重建卡：`REBUILD=1`（**会清空卡上全部数据，先向用户确认**）
- 自定义面板端口：`PANEL_PORT=10091 sh /tmp/kp.sh`

> ⚠️ **这条链需要网络**：`install.sh` 的 `fetch()` 不做本地回退，永远去三源下载。
> `offline/panel/` 里的脚本是**单步执行**用的（且 opkg 装包本身也依赖阿里云源），
> 所以"完全离线"只对**已装好系统、只差内核 / 插件**的场景成立。

---

## 6. 验证判据

```sh
# ① 驱动与数据根（最重要的一条）
docker info | grep -E 'Storage Driver|Backing Filesystem|Docker Root Dir|Registry Mirrors'
#    期望：overlay2 / f2fs / /mnt/storage/data/docker / 至少一个加速源
# ② dockerd 实际读的配置文件
ps w | grep -o -- '--config-file=[^ ]*'          # 期望 /tmp/dockerd/daemon.json
# ③ 冒烟（两步做，别只看 docker info）
docker pull hello-world
docker run --rm --network host hello-world       # 不带 --network host 必报 veth 错
# ④ 自启
ls -l /etc/rc.d/S99dockerd
# ⑤ 1Panel
1pctl user-info                                  # 打印地址 / 用户 / 密码
curl -o /dev/null -w '%{http_code}\n' http://127.0.0.1:10090/     # 非 000
# ⑥ host 默认化装置在位
ls -l /usr/bin/docker-compose /usr/bin/docker-compose.real
sh /tmp/kp1pt/kp-compose-host.sh --check /mnt/storage/data/1panel/apps/<应用>/<实例>/docker-compose.yml
#    rc=1 表示「已是 host」；rc=0 表示「需要转换」（说明 wrapper 没生效）
```

| 期望 | 说明 |
|---|---|
| `Storage Driver: overlay2` + `Backing Filesystem: f2fs` | 出现 `vfs` 说明 data-root 没落在裸 f2fs 上 |
| `Docker Root Dir: /mnt/storage/data/docker` | 出现 `/opt/docker` 说明 UCI 的 `data_root` / `alt_config_file` 没生效 |
| `docker run --network host` 成功 | 报 veth 错 = 忘了加 `--network host`，不是镜像问题 |
| `docker-compose.real` 存在 | 这是回滚凭据，**不能删** |

> **`docker info` 通过 ≠ 能拉镜像**：本机直连 `registry-1.docker.io` 实测 15 s 无响应。
> 拉不动就**逐个加速镜像单独试**（清 `dockerd.globals.registry_mirrors` → `uci add_list` 单个 →
> `commit` → `restart dockerd` → 再拉），把能用的那个留在 UCI 里。

---

## 7. 回滚

```sh
# Docker
/etc/init.d/dockerd stop
opkg remove dockerd containerd docker runc libnetwork tini libseccomp
cp -a /etc/opkg/distfeeds.conf.kp-bak-* /etc/opkg/distfeeds.conf
# （docker 数据目录 /mnt/storage/data/docker 保留，不影响系统）

# 1Panel（数据不删，只改名）
1pctl uninstall                                  # 交互确认；或手动：
mv /mnt/storage/data/1panel /mnt/storage/data/1panel.bak-$(date +%Y%m%d_%H%M%S)
rm -f /usr/local/bin/1panel /usr/local/bin/1pctl /etc/init.d/1paneld

# host 默认化
sh /tmp/kp1pt/install-hostnet-default.sh --restore
```

---

## 8. 已知坑速查（本任务相关）

| 症状 | 原因 | 修法 |
|---|---|---|
| `dockerd` 报 `incompatible with the architectures configured` / `Unknown package` | 6 个 kmod 在厂商内核里根本不存在，opkg 在「选候选包」阶段就失败 | 造空桩包；`--force-depends` **无效** |
| 本地 stub ipk 报出桩里没有的依赖 | opkg 被 feed 同名包截胡 | 装前 `mv /var/opkg-lists /var/opkg-lists.off` |
| 写了 `/etc/docker/daemon.json` 却不生效（仍是 vfs、Root Dir 还是 /opt/docker） | dockerd 读的是 `/tmp/dockerd/daemon.json` | `uci set dockerd.globals.alt_config_file=...` |
| 容器起不来报 veth pair 错误 | 内核无 veth | `--network host`；1Panel 应用走 §4 的 host 默认化 |
| 1Panel 装应用报 `Service "x" uses an undefined network` | compose 转换器**缩进假设失效**导致"半转换"（顶层 networks 被删、服务级 networks 留下） | 用缩进无关的 `kp-compose-host.sh`；`fixtures/compose.panel4sp.yml` 是回归样本 |
| 1Panel 装应用卡在「安装中」永不动 | 容器在崩溃重启循环，面板在等健康检查 | `docker ps -a` 看状态、`docker logs` 看原因；**面板的"运行中/安装中"永远不可信** |
| 1GB 内存设备上大镜像容器消失但面板显示「运行中」 | **全局 OOM** 杀掉容器（`exit=143 oom=true`），面板库状态没回写 | `dmesg \| grep -E 'oom\|task_memcg'` 归属到容器；`python scripts/kp-1panel-status.py` |
| 1Panel 面板 API 自动化登录失败 | v1.10 有**图形验证码**硬阻断（明文提交返回 `code=406 ErrCaptchaCode`；加 `ignoreCaptcha:true` 又报 `encrypted data format error`） | **纯脚本绕不过去**，只能人工在浏览器点一次；证据源改用 `/tmp/kp-compose.log` |
| 商店里 1Panel / ocspeed 永远显示「未安装」 | 商店「已安装」由守护进程实时跑 `opkg info <子包名>` 判定，而它们是脚本装的 | 造空占位 ipk（`app-1panel` / `app-ocspeed`） |
| 面板表单端口填了却访问不到 | host 化会剥掉 `ports:`，宿主端口 = **模板 `ports:` 冒号右边的值** | 端口字段填容器内端口；判据是 `netstat` 里那个端口在 LISTEN |
| 重装脚本一跑旧数据就没了 | `rm -rf $BASE_DIR/1panel` 是数据炸弹 | 先解包校验，旧目录**改名保留** |

---

## 9. 完成后

1. `docker info` / `1pctl user-info` / `ls -l /usr/bin/docker-compose.real` 三处读回验证
2. `free -k` 复核：dockerd ~60MB + containerd ~38MB + 1Panel ~100MB
3. 向用户报告：装了什么、数据根在哪、`.real` 备份在哪、怎么回滚

**延伸**：验证「1Panel 到底能不能装容器」→ `tasks/index.json` 的 `panel.install-test`；
盘点现有容器与 OOM 归属 → `panel.status`。
