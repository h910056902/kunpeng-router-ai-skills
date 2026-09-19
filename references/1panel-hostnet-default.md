---
id: REF-1panel-hostnet
title: "1Panel 应用「默认 host 网络」方案（C2000 U / 无 veth 内核）"
tags: [1panel, docker, compose, host-network, no-veth, wrapper]
risk: high
preconditions:
  - "设备已装 1Panel（v1.10.x）与 Docker"
  - "内核无 veth（bridge 不可用）"
  - "已备份 /usr/bin/docker-compose"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# 1Panel 应用「默认 host 网络」方案（C2000 U / 无 veth 内核）

> 状态：**设计与脚本已就绪并通过 PC 侧自测；设备端待实测**（2026-09-19）
> 脚本包：工作区 `1panel-hostnet-default/`（kp-compose-host.sh / docker-compose.wrapper /
> install-hostnet-default.sh / kp-install.snippet.sh）；计划见同批次的
> `Docker与1Panel-下一步测试适配计划.md`
> 落仓库时：两个工具文件进 `nros-panel/tools/`，接线进 `nros-panel/kp-install.sh`

## 一、要解决的问题

C2000 U 内核 `CONFIG_VETH/MACVLAN/IPVLAN` 全 not set（厂商 `kmod-veth` 是空包）→
**docker 桥接网络物理不可用**，任何走 bridge 的 compose 都会停在：

```
failed to add the host (veth...) <=> sandbox (veth...) pair interfaces: operation not supported
```

而 1Panel 应用商店的模板**一律**引用外部 bridge 网络 `1panel-network` + `ports:`，
所以「面板装应用」100% 失败。改 `daemon.json` / UCI / compose 版本都救不了。

## 二、三个方案与取舍

| 方案 | 做法 | 结论 |
|---|---|---|
| **A. compose wrapper（默认化）** | `/usr/bin/docker-compose` 换成 wrapper，真件改名 `docker-compose.real`；wrapper 在调用前把 `-f` 指向的 compose 幂等 host 化 | ✅ 主方案。不论面板/商店/手工调用都生效；容器由 1Panel 自己 up → **会出现在面板「已安装应用」** |
| B. 装完扫描补救 | 事后跑转换器扫 `$BASE/apps/*/*/docker-compose.yml` | ✅ 兜底（A 的备份路径）；缺点是"先报错再修"，手工 up 的容器不在面板应用列表 |
| C. 改 1Panel 应用模板 | 直接改模板让 compose 天生 host | ❌ 不可行：模板来自远端应用商店/DB，每次安装重新生成 |

→ 采用 **A + B**：A 负责"以后都默认"，B 负责"把存量转过来"。

## 三、转换规则（kp-compose-host，幂等）

1. 删每个服务里的 `network_mode` / `networks` / `ports` 段（连同 6 空格子项）
2. 在**每个服务名下**注入 `network_mode: host`
3. 删顶层 `networks:` 段（外部网络声明）
4. 服务含 `redis-server` → 追加 `--ignore-warnings ARM64-COW-BUG`（5.4 内核 ARM64-COW-BUG
   自检会直接退出，且该检测早于配置文件加载，写 redis.conf 无效；参数必须放 conf 之后）
5. 首次转换留备份 `<file>.bridge.bak`

判据（`--check`）：**已有 `network_mode: host` 且没有残留 `networks:`/`ports:`** 才算"已 host"。
只判前者不够 —— "host + 残留 ports" 的文件 compose 会直接报错，必须继续转换。

## 四、busybox 适配的两个坑（本方案踩出来的）

1. **方括号里不要写 `\t`**。POSIX bracket expression 中反斜杠转义是未定义行为，各实现各异；
   若某 awk 把 `[^ \t-]` 的 `\t` 当字母 `t`，服务名以 `t` 开头（`transmission` 等）就匹配不上，
   **静默不注入**。YAML 本来就禁止 tab 缩进，所以一律用**字面空格类**：`/^[^ ]/`、`/^  [^ ][^ :]*:[ ]*$/`。
2. **必须跟踪"当前在不在 services 段内"**。2 空格缩进的行不只有服务名，顶层 `volumes:`/`configs:`
   的子项同样 2 空格，裸键行（`  redis_data:`）跟服务名长得一模一样 —— 不限制就会往 `volumes:`
   里注入 `network_mode`（compose 语法错）。做法：顶层每遇到非 `services:` 的键就 `in_svc = 0`。

## 五、PC 侧自测（已通过，可复跑）

用 node + PortableGit 的 bash（`export PATH=/usr/bin:/bin`）跑 `bash -n` 与语义用例：

| 用例 | 结果 |
|---|---|
| 4 个脚本 `bash -n` | 全 PASS |
| 典型 1Panel 模板（多服务 + ports + networks + 顶层 networks + 裸键 volumes + redis） | ✅ 每服务注入 host、ports/networks 清零、顶层 networks 移除、`volumes:` 保留、redis 参数注入 |
| 幂等（连转两次） | ✅ 第二次输出 "已是 host，跳过"，无重复键（network_mode 计数 = 服务数） |
| `--check` | ✅ 已 host → rc=1；需要转换 → rc=0 |
| 备份 | ✅ `*.bridge.bak` 生成 |
| "host + 残留 ports" | ✅ 继续转换，ports 被清掉 |
| `volumes:`/`configs:` 裸键 | ✅ 未被注入（污染计数 = 服务数） |
| 服务名以 `t` 开头 | ✅ 正常注入（验证坑 1 的修法有效） |

## 六、已知代价（必须写进面板说明）

- **端口映射失效**：host 网络下应用直接占宿主机端口，以**镜像默认端口**为准，
  面板里选的端口不再生效；同一端口不能被两个应用同时用。
- 装完后不要在面板里"改端口"——会被转换器再抹掉。
- 回滚：`install-hostnet-default.sh --restore`（真件一直在 `/usr/bin/docker-compose.real`）。

## 七、设备端验收（工具已就绪，尚未实测）

**测试脚本**：`scripts/kp-1panel-install-test.py`（PC 侧驱动）+ `scripts/payload/kp-1panel-test.sh`
（设备端 harness）。一条命令跑 `probe → pull → control →[授权]→ hostnet-install → install → panel → panelcheck → verify`。
PC 侧自测全通过；**设备端一次都没跑过**（编写时会话内无 `ROUTER_PW`）。

验收要点（脚本已实现为自动判据）：

1. `/tmp/kp-compose.log` 里能看到 1Panel 的真实调用（验证 wrapper 命中；若为空说明
   1Panel 走的不是 `/usr/bin/docker-compose`，方案 A 不成立，退回方案 B）
2. 面板装一个轻量应用，全程零手工干预成功，且出现在「已安装应用」
3. `docker-compose --version` 仍正常（wrapper 不打断链路）
4. 重启后 wrapper 与转换结果都在（都在 overlay 内 → 一键链必须包含本阶段，否则重建 overlay 后丢失）

## 八、1Panel 装应用的机制（2026-09-19 查证）

| 项 | 事实 |
|---|---|
| 调用形态 | 1Panel v1 装应用最终是 `docker-compose -f <file> up -d`，`docker-compose` **走 PATH 查找** → 换掉 `/usr/bin/docker-compose` 能拦到 install/up/down/stop/restart 全部动作。**这是方案 A 成立的根据**（脚本 `probe` 阶段用 `grep -a -c docker-compose <1panel 二进制>` 实证）|
| 应用商店索引 | `https://apps-assets.fit2cloud.com/stable/1panel.json.zip`（解出 `1panel.json`，263 个应用，每个应用带 `versions[].downloadUrl`）|
| 应用包 | `https://apps-assets.fit2cloud.com/stable/1panel/<key>/<ver>/<key>-<ver>.tar.gz`（仅几十 KB，里面是 `docker-compose.yml` + `data.yml` + `data/` + `scripts/`）|
| **包内没有 `.env`** | `CONTAINER_NAME` / `PANEL_APP_PORT_*` 这些变量是 1Panel **按 `data.yml` 的 formFields 现场生成** `.env` 的 —— 复刻安装时必须自己合成，否则 `${CONTAINER_NAME}` 解析失败 |
| 目录布局 | 1Panel 根 = `<base_dir>/1panel/`，内含 `apps/`（已装应用）`db/` `resource/`（应用商店本地缓存）`conf/`。**注意 `<base_dir>` 可能本身就带 `/1panel` 后缀**，所以不能写死 `APPS="$BASE/apps"` —— 判据用"根下有 db/ 或 resource/ 或 apps/"逐个候选试（脚本已这么做）|
| alist 实测样本 | v3.64.0，镜像 `xhofe/alist:v3.64.0`，容器端口 5244(HTTP)/5246(S3)，模板**确实是 bridge**（外部网络 `1panel-network` + `ports:`）→ 最佳对照组 |

## 九、PC 侧自测（真实模板，2026-09-19 已通过）

用 1Panel 官方商店下载的 **alist 3.64.0 真模板**（不是人造样本）跑转换器：

| 用例 | 结果 |
|---|---|
| 4 个脚本 `sh -n` | 全 PASS |
| 真模板 `--check` → 需要转换 | rc=0 ✅ |
| 真模板转换 | 每服务注入 `network_mode: host`（1 条）、`ports:`/`networks:` 段清零、顶层 `networks:` 移除、`volumes:`/`environment:`/`image:`/`labels:` 原样保留 ✅ |
| 转换后 `--check` | rc=1（已是 host）✅ |
| 幂等（连转两次） | 第二次 "已是 host，跳过"，`network_mode` 计数仍为 1 ✅ |
| `*.bridge.bak` 备份 | 生成 ✅ |
| 容器侧端口解析 awk | `5244 5246` ✅ |
| wrapper 参数扫描 | `-f x.yml up -d`→F=x.yml/SUBCMD=up；`--file=x.yml`→F=x.yml；`--version`/`help`→F 为空（不会误改 CWD 里的 yml）✅ |

> **真模板带来的新坑（已被现有实现吃掉）**：alist 模板的顶层写的是 `networks:  `（**带行尾空格**），
> 子项是 `  1panel-network:  `（2 空格缩进 + 行尾空格）。后者长得跟服务名一模一样，
> 靠 `skip_top` 在 `skip_top { next }` 里被丢弃 —— 如果哪天把这条 `next` 挪到服务名规则之后，
> 就会往外部网络段里注入 `network_mode`。

## 九·补、⚠️ 真机事故与修复（2026-09-19 面板实装，必读）

**现象**：面板 UI 里装 alist 报
`ERROR: Service "alist" uses an undefined network "1panel-network"`。
（注意：这条文案是 **compose v1 python** 的（`ERROR: Service ... uses an undefined network`），
compose v2 / compose-go 写的是 `service "x" refers to undefined network y: invalid compose project`
—— 反过来可用来判断"到底是哪个二进制在跑"。）

**根因：同一份应用，商店包与面板落盘的 YAML 缩进不一样。**

| 来源 | 文件 | 缩进 | 其它特征 |
|---|---|---|---|
| 商店 tarball `alist/3.64.0/docker-compose.yml` | 463 B，md5 `525d4777…` | **2 空格** | 无 `deploy`，端口 `"${PANEL_APP_PORT_HTTP}:5244"` |
| 面板 v1.10 **实际落盘** `apps/alist/<inst>/docker-compose.yml` | 707 B，md5 `41e95519…` | **4 空格** | **有 `deploy.resources.limits`**、端口带 `${HOST_IP}:` 前缀、顶层 `networks:` 排在 `services:` **之前** |

面板不是照抄 tarball，而是"解析模板 → 套 formField → 用 Go yaml 重新序列化"（4 空格默认缩进）。
旧转换器把「服务名 2 空格 / 服务属性 4 空格」**写死**，于是：
列 0 的顶层 `networks:`（前缀匹配 `/^networks:/`，与缩进无关）被删掉，而
`    alist:`(4) / `        networks:`(8) / `        ports:`(8) **全部漏网**、`network_mode` 也没注入
→ 半转换 → compose 报 "undefined network"。

**为什么之前"PC 自测全过"还是翻车**：`install` 阶段喂的是商店 tarball 模板（2 空格），
**没有覆盖"面板实际落盘形态"**。这是本次最贵的教训：*测试样本必须来自被测系统真正写出的文件。*

**修复（已验证）**：
1. `kp-compose-host.sh` 改为**缩进无关**：先量出 `svc_ind`（服务名缩进）与 `prop_ind`（属性缩进），
   删除一律按 `缩进 > svc_ind`、注入一律按 `prop_ind`；`--check` 判据同步改为按行分类统计
   （服务数 / 已注入 host 数 / 残留 networks·ports 键数 / 顶层 networks 数）。
2. `docker-compose.wrapper` 改为**转换全部 `-f` 目标**（旧版只记最后一个），并纳入 CWD 里
   compose 会自动加载的 `*.override.y*ml`。
3. 新增回归自测 `kp-compose-selftest.sh` + 固定样本 `fixtures/`（`compose.store2sp.yml` 商店 2 空格、
   `compose.panel4sp.yml` **面板 4 空格**、`compose.weird3sp.yml` 3 空格、CRLF 设备端生成），
   已接进 `probe` 阶段（缺样本则显式跳过，不静默）。
4. harness 里所有 `'^    xxx:'` 硬编码判据一律改成 `'^[ ]+xxx:'`。

**验收证据**：设备端自测 45–59 条断言全过；面板那份原件（`*.bridge.bak`）转换后
`network_mode: host` 注在 ind=8、两处 networks/ports 清零、`deploy`/`environment`/`volumes` 原样保留、幂等；
按**面板真实调用形态**（`cwd=/ -f <绝对路径> up -d`）`up_rc=0`、容器 `network_mode=host`、
`createdBy=Apps`、`http://192.168.66.1:5244` → **200**（启动约 15 s 后才可用，别在 5 s 时判死）。

**同批受影响**：面板试装的 `siyuan`（13:08）也是半转换；重装转换器时一并修好（`--check` 复核 nm=1、残留 0）。

**面板点安装仍然只能人工**：1Panel v1.10 的 `/api/v1/auth/login` 除图形验证码外，
请求体还是**加密传输**的（明文直接 `ignoreCaptcha=true` 会得到 `encrypted data format error`），
PC 侧 API 自动化此路不通 —— 只能"人在浏览器点一次 + 脚本收尾取证"。

## 十、host 化的副作用：`ports:` 被剥掉 ⇒ **端口以「容器内端口」为准**

`kp-compose-host.sh` 会删除服务级 `ports:`（host 模式下 compose 本身也会忽略并告警）。
后果：**面板表单里那个"端口"字段只喂给 `ports:` 映射，host 化后完全失效；
真正监听的是模板 `ports:` 冒号右边（容器内）那个值。**

一般规则：**填面板端口时一律填模板 `ports:` 右边那个数字**，这样面板显示的"访问地址"才和实际一致。

实例 · 1Panel 商店的 **`deepseek-harness`**（0.1.5-rc.1，key `deepseek-harness`，AI 标签，
镜像 `1panel/deepseek-harness:0.1.5-rc.1`，arm64 支持）：

- 模板：`ports: - ${PANEL_APP_PORT_HTTPS}:8443`，表单默认 `PANEL_APP_PORT_HTTPS=10443`
- 表单共 4 项：`HTTPS 端口`(默认 10443) / **`访问地址`(`HTTPS_ACCESS_HOST`)** /
  `Web 用户名`(`DSH_AUTH_USERNAME`=admin) / `Web 访问密码`(`DSH_AUTH_PASSWORD`，`random:true`，≥12 位)
- `访问地址` 的官方口径：填**浏览器实际使用的 IPv4 或主机名**，**不要带 `https://`、路径或端口**
  （例 `192.168.66.1`）；容器内 Caddy 用它签内部证书，首访会有证书告警，
  根证书在 `<应用目录>/data/caddy/pki/authorities/local/root.crt`，可导入客户端信任库消除
- **host 化后 → Caddy 直接监听 8443**，`https://<IP>:10443` 打不开；
  所以端口字段应填 **8443**（该路由上 8443 空闲，80/10090/8888/1883/7890-7895 已占）

该模板已用真机转换器预检（`--check` rc=0 → 转换 → `nm_host=1`、`svc_networks=0`、`svc_ports=0`、
`top_networks=0`，`read_only`/`tmpfs`/`security_opt`/`healthcheck` 均原样保留）。

### 十·补、表单文本字段填错 ⇒ 容器崩溃重启 ⇒ 面板永远"安装中"（2026-09-19 13:34 实例）

**现象**：面板装 `deepseek-harness` 后 UI 长期显示"安装中"。
`docker ps -a` 显示 `1Panel-deepseek-harness-zd4d | Restarting (1)`，`docker inspect` exit=1 / restarts=8；
`/tmp/kp-compose.log` 末尾是面板发起的 `... up -d` 紧跟一条 `... logs --tail 200 --since ... -f`
—— **面板在跟容器日志等健康检查**，容器起不来就永远等，所以"卡住"是结果不是原因。

**根因**：用户把「访问地址」填成了完整 URL `https://192.168.66.1:8443`（正确值应为裸 IP `192.168.66.1`）。
镜像入口脚本硬校验：

```bash
# /usr/local/bin/docker-entrypoint.sh
is_access_host() { node -e '...process.exit(isIPv4(v) || hostname ? 0 : 1)' "$1"; }
# 正例 203.0.113.10 / dsh.example.com；反例 https://dsh.example.com / 203.0.113.10:10443 / 203.0.113.999
# 另一路校验：DSH_AUTH_USERNAME 必须 ^[A-Za-z0-9._-]+$；DSH_AUTH_PASSWORD 至少 12 位
```
不合法 → `printf 'HTTPS_ACCESS_HOST must be an IPv4 address or hostname without a scheme, path, or port.' >&2; exit 1`
→ 立即退出 → `restart: unless-stopped` 无限重启。

**入口脚本还印证了端口结论**：它把 DSH web 起在 `127.0.0.1:3080`，再让 Caddy 在**容器内 8443** 上做 TLS
（脚本自身打印 `DeepSeek Harness is available at https://<host>:8443 inside the container.`）——
所以 host 化后宿主机监听的就是 **8443**，与第十节开头结论一致。

**修复姿势（面板侧，不能只改设备 `.env`）**：
1. 刷新页面 → 已安装应用 → 该应用 → **参数** → 改对后**重建**；
   或直接**卸载重装**（首次安装失败时数据目录为空，无损）
2. ⚠️ 只改设备上的 `.env` 无效：面板每次重建都用数据库里的旧参数重新生成 `.env`
3. 诊断口诀：**"面板一直转圈 + 容器 Restarting" ⇒ 先 `docker logs` 看容器自己为什么退出**，
   别看内核/网络（本次与 veth、wrapper、host 化全都无关）

**通用教训**：1Panel 表单里的**文本类字段**（`type: text`）往往有应用侧硬校验，官方 README 的 `description`
就是规格书 —— 在 data.yml 里把 `description.zh` 读出来转述给用户，比事后排障便宜得多。

### 十·补2、🔧 改错参数后的**无 UI 修复法**：直接改面板库（2026-09-19 13:41 实测通过）

**为什么需要它**：1Panel v1.10 面板登录有**图形验证码 + 请求体加密**两层，PC 侧 API 自动化走不通
（明文 + `ignoreCaptcha:true` → `encrypted data format error`），但"改参数 → 重建"这件事**不必非走 UI**。

**关键事实（本机已验证）**：

| 事实 | 值 |
|---|---|
| 面板库路径 | `/mnt/storage/data/1panel/db/1Panel.db`（**不在** `1panel/` 根下，在 `db/` 子目录） |
| 表 / 列 | `app_installs`；**参数存在 `env` 列（JSON 字符串）里，`param` 列是空的** |
| 设备工具 | **没有 `sqlite3`，但有 `python3`** → 直接用 python 标准库 `sqlite3` 在线改，不必停面板、不必拷库 |
| 应用目录 | `/mnt/storage/data/1panel/apps/<app>/<app>/`（`.env` 与 `docker-compose.yml` 都在这一层） |

**修复四步（幂等、可回滚）**：

```sh
# 0) 备份（数据库 + 应用 .env 各留一份带时间戳的 .kpbak-*）
# 1) 改库：读 app_installs.env → json.loads → 改键 → json.dumps(separators=(",",":")) 写回，
#       同时把 status 置为 'Running'
# 2) 改盘：把应用目录 .env 里对应的 KEY="值" 一并改成同值（否则不必重建就已生效）
# 3) 重建：docker-compose -f <应用目录>/docker-compose.yml up -d --force-recreate
#          （走 wrapper ⇒ 顺带再 host 化一次，幂等）
```

**验收判据（全绿才算好）**：

```
docker inspect → exit=0 health=healthy restarts=0 nm=host
docker inspect -f '{{json .State.Health}}' → 末条 ExitCode=0（能直接看到应用返回的 HTML）
设备侧 curl -sk https://127.0.0.1:8443/  → 200
PC 侧   curl -k  https://<host>:8443/    → 401/200（401=要求登录，说明服务活着；不是失败）
```

⚠️ **两个反直觉点，别误判**：
1. **首启前两条 healthcheck 会报 `Health check exceeded timeout (5s)`** —— DSH 冷启动 >5s，第三次即 healthy，
   不要据此判定安装失败。
2. **从 PC 用 urllib/curl 请求会看到 401**（登录页要求认证），而设备侧 `127.0.0.1` 请求可能返回 200 ——
   Caddy 按 Host 分流，两者都算"服务正常"。

**回滚**：`cp -f 1Panel.db.kpbak-<ts> 1Panel.db && cp -f .env.kpbak-<ts> .env && up -d --force-recreate`。

**顺带发现的同名坑**：同一批安装里 `siyuan`、`alist` 的库记录状态分别是 `UpErr`/`Error`，
它们的容器已被面板清理，恢复时**同样改库 + 改 .env + up -d** 即可，流程完全一致。

## 十一、一把查清「现在有哪些容器」：`kp-1panel-status.py`（只读，2026-09-19 实机验证）

```bash
python scripts/kp-1panel-status.py                 # 人类可读
python scripts/kp-1panel-status.py --json out.json # 结构化，便于后续比对
```

凭据同其它脚本（`ROUTER_PW` 环境变量或 `~/.workbuddy/kunpeng-router.env`）。**纯只读，不 stop/start/rm 任何东西。**

### 它回答的 6 个问题（每条都对应一次真实排障）

| 输出段 | 回答的问题 |
|---|---|
| 容器清单（state / exit / **OOMKilled** / nm / restart 策略 / restarts） | "面板说运行中，为什么打不开？" |
| 面板 `app_installs` 记账对照 | "面板记账和实际对得上吗？" |
| 磁盘应用实例是否已 host 化（+ 是否残留 `ports:`、有无 `.bridge.bak`） | "还有漏转换的 compose 吗？" |
| 宿主端口监听 | "host 模式下应用真的在听吗？" |
| host 化装置是否在位（wrapper / `.real` / `kp-compose-host` / 调用日志） | "重建 overlay 之后装置还在吗？" |
| **dmesg OOM 事件 + `task_memcg` 归属** | **"容器是被谁杀死的？"** |

### ⚠️ 两个必知陷阱（都踩过）

1. **面板库列名**：`app_installs` 里 **`name` 才是应用 key**（`alist`/`siyuan`…），
   `app_id` / `app_detail_id` 是商店里的数字 id。拿 `app_id` 当标签会打印出 `3 / 47 / 214` 这种莫名其妙的数字。
2. **本固件 busybox 的 `free -m` 不认 `-m`**，照样输出 **kB**（1GB 内存报 `1016432`）。
   别按 MB 读，会得出"可用内存 491428 MB"这种荒唐结论 → **一律改读 `/proc/meminfo`**（单位恒为 kB）。

### 🔴 1GB 设备的内存红线：DSH 被全局 OOM 杀掉，面板却仍显示"运行中"

2026-09-19 实机事故（`deepseek-harness`，649MB 镜像 / `1panel/deepseek-harness:0.1.5-rc.1`）：

```
docker inspect → State=exited exit=143 oom=true finished=13:52:51
dmesg → oom-kill:constraint=CONSTRAINT_NONE,global_oom,
        task_memcg=/docker/0c5d76841deb…,task=MainThread,pid=12686,uid=1000
        Out of memory: Killed process 12686 (MainThread) anon-rss:443568kB
容器 ID 0c5d76841deb… == DSH 容器          ← 归属确凿
面板库 app_installs → status=Running，message=「状态异常，请查看日志」
```

**判读要点**：
- `constraint=CONSTRAINT_NONE` + `global_oom` ⇒ **是全机内存耗尽**，不是容器自身限额
  （`.env` 里 `MEMORY_LIMIT=0`，模板的 `deploy.resources.limits` 根本没设限）；
- `exit=143` 是 **SIGTERM**，`oom=true` 才是 docker 记下的 OOM 标记 —— 只看 143 会误判成"被手动停的"；
- **面板 UI 会继续显示"运行中"**（库状态没跟着更新），所以"面板说在跑"完全不可信，
  **必须 `docker ps` 或本脚本复核**；
- 该机总内存 993 MB，DSH 单进程 RSS 443 MB + 1Panel(1.6GB 虚拟) + dockerd + clash ⇒ 余量只剩 ~477 MB，
  **重启后大概率二次 OOM**。在 1GB 路由器上跑 649MB 级应用属于超配，不是配置问题。

### 关联：面板记账 vs 实际的三类不一致（实机样本）

| 应用 | 库 status | 实际情况 | 含义 |
|---|---|---|---|
| `deepseek-harness` | `Running` | 容器 `exited` | **库状态滞后/错误**（OOM 后没回写）——最危险的一类 |
| `alist` | `Error` | 容器不存在 | 面板已清理容器，记录留痕 |
| `siyuan` | `UpErr` | 容器不存在 | 残留的是**修复前**的 `undefined network` 旧错，不代表当前转换器有问题 |
| `ai-gateway` | `Stopped` | `exited(0)` | 一致（用户手动停的） |



