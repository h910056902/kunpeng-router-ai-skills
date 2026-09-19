---
id: REF-c2000u-1panel
title: "C2000 U（B 机）· Docker + 1Panel 实装档案（2026-09-13）"
tags: [1panel, install, archive, c2000u]
risk: low
preconditions:
  - "读档用途（含实装记录与踩坑）"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# C2000 U（B 机）· Docker + 1Panel 实装档案（2026-09-13）

> 192.168.66.1 = B 机。本文是实测记录 + 可复用 playbook。
> 一键脚本（工作区留档）：`kp-docker1panel/install-docker-1panel.sh`（幂等、非交互、五阶段门禁）+ `README.md`
> **已推 GitHub**：github.com/h910056902/kunpeng-istoreos 的 `kp-docker1panel/`（commit 62942fd）。
> **一行命令安装**：`ssh root@<IP> "wget -qO- https://raw.githubusercontent.com/h910056902/kunpeng-istoreos/main/kp-docker1panel/remote-install.sh | sh"`
> （remote-install.sh 三源回退：raw → ghfast.top → gh-proxy.com，从路由器实测全通；落盘 /tmp 再执行，支持 env 透传如 `| PANEL_PORT=10091 sh`）

## v2 修复（2026-09-13 晚，幂等重跑实测 RC=0）

1. **[严重] 幂等凭据回填**：重跑时凭据变量仍为 auto → Stage3 探测 404 误报 + 凭据文件被垃圾覆盖。
   修法：从 `/usr/local/bin/1pctl` `grep '^ORIGINAL_xxx='` 回读（pv() 函数，cut -d= -f2- + `sed 's/\\//g'` 反转义）。
   **这是 1Panel 幂等重跑的通用解**：1pctl 里始终保留明文配置。
2. daemon.json 备份必须在 sed **之前**（原脚本顺序反了，备份的是已改文件）
3. `cp -r lang` 前先 `rm -rf /usr/local/bin/lang`（否则嵌套 lang/lang）
4. procd status 判断用 `grep -q '^running'`（裸 `grep running` 会匹配 "not running"）
5. `1pctl version` 输出两行（版本行+模式行），取版本用 `grep -m1 -oE 'v[0-9][0-9A-Za-z.-]*'`
6. docker-compose / opkg update 失败降级 warn（不阻塞面板安装）

## 硬事实（probe 实测）

- 内核 5.4.281：`BRIDGE_NETFILTER/OVERLAY_FS/MEMCG/NAMESPACES/USER_NS` =内建；
  **`CONFIG_VETH is not set`** → 靠 mt7987 target 源 `kmod-veth 5.4.281-1`（与 kernel 包 hash 匹配，可正常 opkg 安装，无需 stub ipk）
- cgroup2 已挂载 `/sys/fs/cgroup`（controllers: cpuset cpu io memory pids rdma）
- dockerd 20.10.17（procd, START=99）+ containerd + containerd-shim 常驻；overlay2；
  data-root `/mnt/storage/data/docker`（TF 卡 p2, f2fs 3.5G）；daemon.json：
  镜像加速 `docker.1ms.run` + `docker.m.daocloud.io`，日志轮转 10m×3，
  **`"bridge":"none"` + `"iptables":false`**（host 网络为主，容器无 NAT/端口映射）
- 存储：**TF 卡**（不是 eMMC）p1 4G=`/overlay`，p2 3.5G=`/mnt/storage/data`（docker 数据在这里）
- 端口占用：10086=nr_webui、10087=kpwebui、10088=kp-quickstart-webui、3038=quickstart

## 1Panel 为什么能原生跑（三个前提的验证方法）

1. **musl 兼容**：官方 arm64 二进制是**静态链接**。验证：
   `head -c 4096 1panel | grep -c ld-linux` → 0（无 INTERP 即静态）
2. **无 systemd**：官方包自带 4 套 init（`initscript/`：systemd/openrc/**procd**/sysvinit），
   install.sh 的 OpenWrt 分支（`[ -f /etc/rc.common ]`）就用 1paneld.procd（USE_PROCD=1, START=95）
3. **bash 依赖**：1pctl 是 bash 脚本（用了 `${yn,,}`），opkg bash 5.1.16 已装

## 首启机制（非交互安装的核心）

1panel 二进制**解析 `/usr/local/bin/1pctl`**（strings 验证：二进制内含
`/usr/local/bin/1pctl` 与 `ORIGINAL_PORT/USERNAME/PASSWORD/ENTRANCE/VERSION` 字面量），
取 `BASE_DIR=`、`ORIGINAL_*=` 值初始化 DB（`$BASE_DIR/1panel/db/1Panel.db`）。
→ **非交互安装 = 先把 1pctl 复制到位并 sed 写好这些值，再启动服务**。顺序不能反。
官方 install.sh（v1.10.34-lts）的 init_configure 顺序：cp 二进制 → ln -s /usr/bin →
sed 1pctl（BASE_DIR/ORIGINAL_PORT/USERNAME/PASSWORD(转义)/ENTRANCE/LANGUAGE）→
GeoIP.mmdb→`$BASE_DIR/1panel/geo/`、lang→`/usr/local/bin/lang` →
1paneld.procd→/etc/init.d/1paneld → enable → start → cp initscript 到 RUN_BASE_DIR。

## 版本通道

- `https://resource.fit2cloud.com/1panel/package/stable/latest` → **v1.10.34-lts**（官方主安装脚本通道，单二进制，1GB 内存友好）
- `.../v2/stable/latest` → v2.2.5（core+agent 双二进制，更重，未采用）
- 包 URL：`.../package/{channel}/{ver}/release/1panel-{ver}-linux-arm64.tar.gz`（43MB，国内 CDN 实测 35MB/s）
- 校验：同目录 `checksums.txt`（每包一行 sha256）

## 已完成安装（2026-09-13）

- 面板：v1.10.34-lts，端口 **10090**，用户 admin，入口/密码随机（凭据：路由器
  `/root/1panel-credentials.txt`，600 权限；**不入库任何记忆/仓库**）
- 数据根：`/mnt/storage/data/1panel`；服务：`/etc/init.d/1paneld`（S95 自启）；RSS ~100MB
- 商店：installed.list + plugins.json 已加 `1panel` 条目（source=docker 免 opkg 校验，open_url 指向入口）
- docker-compose：1.28.2（python 版，连带全套 python3 ~40MB overlay）。
  **不必换 v2** —— 实测 v1 能完整解析 1Panel 的 compose（见下"实测更正"第 3 条）。

## 大坑与对策

- **官方 install.sh 的 `configure_accelerator` 会把 /etc/docker/daemon.json 整个覆盖成
  只含 `docker.1panel.live` 一个源**（备份到 daemon.json.1panel_bak）→ 本机脚本明确不执行
- 官方 OpenWrt 分支还会装 `luci-i18n-dockerman-zh-cn`（无用 UI 翻译包）→ 跳过
- `bridge:none + iptables:false` 下 1Panel 应用商店需要端口映射的容器跑不起来；
  要网桥模式：停 dockerd → `/etc/init.d/dockerd uciadd`（建 docker 防火墙区）→
  sed 删 `"bridge"` 行、`iptables:false→true` → 起 dockerd（脚本 DOCKER_ENABLE_BRIDGE=1 分支）
  - ⚠️ **但本机内核没有 veth**（`lsmod | grep -c veth` = 0，厂商 `kmod-veth` 是空包），
    开网桥后容器**一定**报 `failed to add the host <=> sandbox (veth...) pair interfaces`。
    → 该分支在本机是**不可用**的，端口映射只能靠 host 网络 + 容器自己改端口。
- `1pctl version` 输出两行（版本/模式），`tail -n1` 会只抓到"模式"行——解析时取整段
- procd 服务的 stderr 进 syslog：`logread | grep 1panel`

### 2026-09-16 实测更正（三条，重要）

1. **`/etc/docker/daemon.json` 写了等于没写。** 设备实况：该文件 **不存在**，
   而 dockerd 的 Root Dir / 驱动 / 镜像源**全部正确**。固件 `/etc/init.d/dockerd`
   把 **UCI** 渲染成 `/tmp/dockerd/daemon.json`，用
   `dockerd --config-file=/tmp/dockerd/daemon.json` 加载（`ps w | grep dockerd` 可见）。
   只有在 UCI 设了 `alt_config_file` 时才 `ln -s` 外部文件（init 第 166–168 行）。
   → 一切 docker 配置**只走 UCI**（`dockerd.globals.{data_root,log_level,registry_mirrors}`）。
   所以上面"官方覆盖 daemon.json"那条其实无关痛痒（那文件本来就没用），
   真正要护的是 **UCI 里的 `registry_mirrors`**。
2. **上面"要网桥模式"那条要作废**（原因见 veth 说明）：本机唯一可行的是 host 网络。
3. **不需要 docker compose v2。** 曾经流传"python 版 1.28.2 无法解析 1Panel 的 compose"
   —— **实测推翻**。用 1Panel 商店典型 compose（`version: '3.8'` + 外部网络
   `1panel-network` + `depends_on` 长格式 `condition: service_healthy` + `healthcheck`
   + `${CONTAINER_NAME}` 变量）跑 `docker-compose config`，**退出码 0、解析结果完整正确**。
   本机也没有 v2 插件（`docker compose` 报 `'compose' is not a docker command`）。
   → 1Panel 应用装不上时，**先查 veth，不要浪费时间换 compose 版本**
   （aarch64 + musl 下 v2 官方二进制还不一定能跑）。
   模板改造：把 `networks:` 段删掉、给每个服务注入 `network_mode: host`
   （见 `nros-panel` 与 `kp-docker1panel/1panel-hostnet-fix.sh`，
   注意 YAML 是 **2 空格/级**，服务名行只有 2 空格缩进）。


4. **opkg 的「已安装」判据必须用 `Status:`，不能写死 `Status: install ok installed`。**
   实测本机两种值并存：`install ok installed`（依赖/系统装）**296 个**、
   `install user installed`（用户显式装）**273 个**。OpenWrt 用第三个字段记录安装来源。
   而 `docker` / `dockerd` / `docker-compose` / `zoneinfo-asia` / `app-1panel` **全是 `user installed`**
   → 写死前者的代码会把它们判成未装，**每次重跑都白跑一次 `opkg install`**，
   源不通时还会打出误导性警告。稳健写法：`opkg status "$p" 2>/dev/null | grep -q 'Status:'`
5. **`curl -LOk -o <名> <URL>`：`-O` 胜、`-o` 被静默忽略**（只打印
   `Warning: Got more output options than URLs`），落盘的是 **URL 的 basename**。
   实测：指定 `-o /tmp/_n1.txt` 结果生成的是 `checksums.txt`，`_n1.txt` 根本没创建。
   → 下载一律只写 `-o`，别混 `-O`（否则 CDN 一改路径，文件名就对不上，后续 `sha256sum` 直接找不到文件）
6. **`curl` 不加 `-f` 时 404 也返回 0**，并会把错误页写进目标文件（实测 `http=404 size=112 rc=0`）。
   下载后做校验的脚本会因此报出"内容里找不到某某"，**把 404 这个真实原因完全掩盖**。
   → 一律 `curl -fsSL -o`（`-L` 也一起带上，防 CDN 跳转）
7. **商店注册表不是 `installed.list`。** 本机实测 `/etc/kp_store/` 下**只有 `routes.list`**，
   `installed.list` 与 `plugins.json` 全盘 `find` **无结果**；真实注册表是
   **`/etc/config/appcenter`**（由 `nros-panel/kp-store-lib.sh` 维护）。
   → 任何读 `installed.list` 的代码都是**静默死代码**（守卫恒假 → 无声跳过 → 使用者以为注册过了）
8. **重装脚本里的 `rm -rf $BASE_DIR/1panel` 是数据炸弹。** 实测该目录含
   `db/1Panel.db` **7.5M**（= 面板全部状态：账号/入口码/应用与站点配置）+ `geo/` 18.7M + `resource/` 4.6M。
   若删除动作发生在解包/校验**之前**，tar 一失败就无法回滚。
   → 正确做法：先解包校验，再把旧目录**改名保留**（`1panel.bak-<时间戳>`）而不是删除

### dockerd 依赖矩阵（2026-09-16 逐项实测，用于确认桩包清单是否完整）

dockerd 的 `Depends` 共 15 项，逐项查 `opkg list` 的结果：**恰好 6 项源里命中数为 0**，
其余 9 项（libc / btrfs-progs / ca-certificates / containerd / libdevmapper / libnetwork /
tini / libseccomp / iptables-mod-extra / kmod-nf-conntrack-netlink / kmod-nf-nat）**都取得到**：

| 源里为 0 的包 | 是谁点名的 |
|---|---|
| `kmod-veth` / `kmod-br-netfilter` / `kmod-ikconfig` / `kmod-nf-ipvs` | dockerd 直接点名 |
| `kmod-dm` | `libdevmapper` 带出 |
| `kmod-fs-btrfs` | `btrfs-progs` 带出（← `containerd` ← dockerd）|

⇒ **桩包清单 `kmod-veth kmod-dm kmod-fs-btrfs kmod-br-netfilter kmod-ikconfig kmod-nf-ipvs`
恰好完整、不多不少，无缺口。** 复现方法：对 `opkg status dockerd | grep '^Depends:'` 的每一项
跑 `opkg list | grep -c "^$dep "`，为 0 的就是必须靠桩包兜住的。

### busybox ash 的两个坑（写脚本时必踩）

- **没有 `$LINENO`** —— `trap` 里写它会原样打印或报错。要定位中断位置得靠自己的阶段变量。
- **不认 `trap '...' ERR`**，只能用 `EXIT`；且陷阱里**不能裸写 echo**
  （正常退出也会打一行"中断"，看着像失败），必须先判 `rc`，用 `|| :` 收尾防陷阱自触发。

## 重装/卸载

- 重装：删 `/mnt/storage/data/1panel/db/` 后重跑脚本（凭据重新生成）
- 卸载：`1pctl uninstall`（交互确认；会删 /usr/local/bin/{1panel,1pctl,lang}、/etc/init.d/1paneld、$BASE_DIR/1panel）
- 手动看信息：`1pctl user-info`（从 DB 读，展示地址/用户/密码）

### 2026-09-19 追加：装容器能力测试（脚本就绪，设备端待跑）

**工具**：`scripts/kp-1panel-install-test.py`（PC 驱动）+ `scripts/payload/kp-1panel-test.sh`（设备 harness）。
一条命令跑完 probe → pull → control →[授权]→ hostnet-install → install → panel → panelcheck → verify。
详见 `references/1panel-hostnet-default.md` 第七~九节。

**本次查证到的、之前档案里没有的事实**：

1. **应用商店远端**：索引 `https://apps-assets.fit2cloud.com/stable/1panel.json.zip`（263 个应用）；
   应用包 `<该前缀>/stable/1panel/<key>/<ver>/<key>-<ver>.tar.gz`（几十 KB）。
   之前误以为在 `resource.fit2cloud.com/1panel/apps/...` —— **那是 404**，别再用。
2. **应用包内不带 `.env`**：`CONTAINER_NAME` / `PANEL_APP_PORT_*` 是 1Panel 按 `data.yml` 的
   formFields **现场生成**的。复刻安装必须自己合成 `.env`，否则 compose 里 `${CONTAINER_NAME}` 直接解析失败。
3. **目录布局修正**：1Panel 根 = `<base_dir>/1panel/`（`apps/` `db/` `resource/` `conf/`）。
   之前的档案写 `应用目录 $BASE/apps/<app>/<name>/` 是把 `base_dir` 与 1Panel 根混了
   —— `<base_dir>` 本身可能就带 `/1panel` 后缀。**不要写死 `$BASE/apps`**，
   判据改成"根下有 db/ 或 resource/ 或 apps/"。
   `$BASE/1panel/resource/apps/` 是应用商店的本地同步缓存（装机后 4.6M）。
4. **alist 是理想的测试样本**：v3.64.0，`xhofe/alist:v3.64.0`，容器端口 5244/5246，
   模板是标准 bridge（外部网络 `1panel-network` + `ports:`），且声明了 arm64。
5. **`1pctl` 里有装机的全部明文**：`BASE_DIR=` / `ORIGINAL_PORT=` / `ORIGINAL_USERNAME=` /
   `ORIGINAL_PASSWORD=` / `ORIGINAL_ENTRANCE=` —— 安全入口码也能从这里读，做引导卡片时直接用。
6. **面板 API 自动化不可靠（2026-09-19 二次更正）**：v1.10 没有 API Key / 没有 `/api/v2`，只能走 `auth/login`。
   ⚠️ **真实拦截点是「图形验证码」，不是加密**：PC 侧直连 `POST /api/v1/auth/login`
   （明文 + `name/password/authMethod/language`）→ **HTTP 200 且无需安全入口码**，
   但返回 `code=406 message=ErrCaptchaCode`；而加上 `ignoreCaptcha:true` 又会得到
   `encrypted data format error`。结论：**存在一条"图形验证码"的硬阻断，纯脚本绕不过去**，
   早期档案里"密码是 RSA+AES 三段式加密所以做不到"的说法不准确，别再据此推理。
   → 测试脚本把它做成"尽力而为 + 降级成操作卡"，**不要让面板 API 卡住整个验收**。
   真正的证据源是 `/tmp/kp-compose.log`（wrapper 记录 1Panel 到底调了什么）。
7. **宿主端口以「容器内端口」为准**：host 化会剥掉 `ports:`，所以面板表单里的端口字段
   要填**模板 `ports:` 冒号右边的值**（如实测 DSH：填 8443 而不是默认的 10443）；
   判据是"宿主 netstat 里那个端口在 LISTEN"。

### 2026-09-19 追加·之二：状态盘点工具 + 1GB 内存的 OOM 事故

**新增只读工具** `scripts/kp-1panel-status.py` —— 一条命令回答"现在有哪些 1Panel 容器"：
容器清单（含 `OOMKilled`/exit/nm/restart 策略）+ 面板 `app_installs` 记账对照 +
磁盘实例是否已 host 化 + 宿主端口监听 + host 化装置是否在位 + **dmesg OOM 归属**（`task_memcg` 指认容器）。
**纯只读**，可随时跑。用法与陷阱见 `references/1panel-hostnet-default.md` §十一。

**🔴 必须记住的实机事故**：`deepseek-harness`（649MB 镜像）在 13:52 被**全局 OOM**杀掉 ——
`exit=143 oom=true`，dmesg `global_oom` + `task_memcg=/docker/0c5d76841deb…`（正是该容器 ID）。
**但面板 UI 仍显示「运行中」**（库状态没回写）⇒ **"面板说在跑"永远不可信，必须用 `docker ps`/本脚本复核**。
该机总内存仅 993 MB，DSH 单进程 RSS 443 MB，重启后大概率二次 OOM —— 属超配而非配置错误。

**已知残留（未处理，供后续参考）**：`ai-gateway` = `exited(0)`（用户手动停，库状态 `Stopped` 一致）；
`alist`（库 `Error`，容器已被面板清理）、`siyuan`（库 `UpErr`，残留修复前的旧错）——
恢复流程 = 改库 + 改 `.env` + `up -d --force-recreate`。
