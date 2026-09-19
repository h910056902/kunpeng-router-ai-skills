---
id: REF-nr-webui-reverse
title: "nr_webui 解析与还原手册"
tags: [nr_webui, reverse, ota, portal-hijack, restore]
risk: high
preconditions:
  - "改前备份原件"
  - "还原会改动系统服务与门户行为"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# nr_webui 解析与还原手册

> 目标仓库：`https://github.com/h910056902/nr-webui-archive`（私有）
> 本地副本：`<工作区>\nr-webui-archive\`
> 解析时间：2026-09-12　样本：后端 `nr_webui` V2.0.8 二进制 / 前端 V2.0.15 / PC 工具 V1.1.2
> 已实测还原到鲲鹏 C2000 U（`192.168.66.1:10086`）

---

## 0. 一句话

**nr_webui 是第三方给鲲鹏/NRadio CPE 做的"美化版后台"**：一个 aarch64 的 C 程序（内嵌 mongoose HTTP 服务器）
在 `:10086` 提供一套 `/api/*` 接口 + 一套 layui 写的中文前端，功能覆盖蜂窝网络、短信收发与转发、
网络/防火墙、系统管理，并且**会接管厂商 LuCI 的首页**做入口跳转。

它不是 LuCI 应用，不依赖 uhttpd/Lua，是**完全独立的一套东西**。

---

## 1. 三层架构

```
┌──────────── PC 侧 ────────────┐
│ WebUI刷入工具_V1.1.2.exe      │  .NET x64 控制台程序
│  登录厂商 LuCI → 注入 curl|sh │
└──────────────┬────────────────┘
               │ http://%s/cgi-bin/luci/index
               ▼
┌──────────── 路由器侧 ─────────┐
│ nradio.sh (V1.6)              │  明文 HTTP 从 la.2014816.xyz 拉二进制
│   → /root/nr_webui            │
└──────────────┬────────────────┘
               │ ./nr_webui downloads
               ▼  前端从**另一台** OTA 服务器拉（不是 la.2014816.xyz！）
┌──────────── 运行时 ───────────┐
│ /root/nr_webui  (aarch64 ELF) │  mongoose HTTP 服务器，监听 [::]:10086
│   ├── /api/*  22 个路由模块   │  内部走 uci / ubus / ubox / curl / openssl
│   └── 静态前端 /root/webui    │  V2.0.15（167 文件 / 2.7MB）
│ 门户：改写 /www/index.html    │  原版备份为 /www/index.html.bak
└───────────────────────────────┘
```

---

## 2. 后端 nr_webui 逆向结果

### 2.1 技术栈（从 ELF 动态符号读出）

| 项 | 值 |
|---|---|
| 格式 | ELF 64-bit，machine `0xB7` = **aarch64**，静态符号已 strip（无 `.symtab`） |
| 编译器 | `GCC: (OpenWrt GCC 8.4.0 r16847-f8282da11e) 8.4.0` → OpenWrt SDK 原生编译 |
| HTTP 服务器 | **mongoose / civetweb**（特征串 `MG_MAX_RECV_SIZE`、`chunked`、`/api/websocket`、全套 HTTP 状态码表） |
| 依赖库 | `libcurl`、`libuci`、`libubus`、`libubox`、`libblobmsg_json`、`libjson-c`、`libcrypto`(HMAC-SHA256)、`libpthread` |
| 监听 | `[::]:10086`（IPv6 通配，同时吃 v4） |
| 二进制大小 | 233944 B（V2.0.8 是 229840 B，差 4104 B） |

### 2.2 认证：复用了 OpenWrt 的 ubus 登录体系

```
POST /api/login  {username, password}
   → 走 ubus 拿 ubus_rpc_session（和 LuCI 同一套 rpcd）
   → 成功后 Set-Cookie: access_token=<HMAC-SHA256 签名>; Path=/; HttpOnly; Max-Age=2147483647
```

- 失败返回 `{"code":401,"msg":"invalid username or password"}` / `invalid password` / `{"code":503,"msg":"auth service busy"}`
- 登出：`Set-Cookie: access_token=; Max-Age=0`
- 探活：`GET /api/islogin` → `{"code":0,"loggedin":false}`
- 未登录访问业务接口 → `{"code":401,"msg":"Unauthorized"}`

**关键点**：它不是自己存密码，而是把账号密码转交给 ubus/rpcd 校验——
所以**路由器 root 密码就是 WebUI 密码**，改密码两边同步。

### 2.3 配置（`/root/webui.conf`）

```ini
WEBUI_ROOT=/root/webui              # 前端静态目录
FORWARD_CONFIG=/root/forward.config # 短信转发配置
WEBUI_PORT=10086
WEB_ENTRY_SELECT=0                  # 0=不做入口选择 1=打开 80 端口选择页
WEB_ENTRY_DEFAULT_BEAUTY=0          # 入口页默认进美化版(=1)还是官方版(=0)
```

启动时还读环境变量 `WEBUI_ROOT` / `FORWARD_CONFIG` / `WEBUI_PORT` / `WEB_ENTRY_SELECT` / `WEB_ENTRY_DEFAULT_BEAUTY`，
读不到才回落到 `%s/webui.conf`，再回落到内置默认值。

### 2.4 CLI 子命令（`-h` 里的 OPTIONS 段）

```
-h / init / start / stop / restart / download / downloads / update
```

- `downloads` = 拉前端资源（**nradio.sh 里这步没有任何错误检查，失败也继续**——这就是之前 `/root/webui/` 为空的根因）
- `init` = 写 `/etc/init.d/nrwebui` + rc.d 软链 + 门户 `/www/index.html`
- `update` = 自检更新

### 2.5 自更新机制（`/etc/init.d/nrwebui` 内嵌在二进制里）

```
新版本下载到 /tmp/nr_webui.new
  → start 时：kill 旧进程 → rm -f /root/nr_webui → mv /tmp/nr_webui.new /root/nr_webui → chmod +x
  → start-stop-daemon -S -b -x /root/nrwebui
```

启动脚本版本标记 `# NRWEBUI_INIT=1.1`，`START=99 STOP=10`。
**注意**：更新包是明文 HTTP 拉取、无签名校验，落盘即 root 执行。

---

## 3. 完整 API 表

前端 60 处调用 + 二进制 22 条路由交叉验证得出。格式统一 `/api/<模块>?type=<子功能>`。

### 认证 / 框架

| 端点 | 方法 | 说明 |
|---|---|---|
| `/api/login` | POST | 用户名密码登录，下发 access_token Cookie |
| `/api/logout` | POST | 清除 Cookie |
| `/api/islogin` | GET | `{"code":0,"loggedin":bool}` |
| `/api/initPage` | GET | 页面初始化（菜单/权限） |
| `/api/status` | GET | 顶部状态栏轮询 |
| `/api/hi` | GET | 健康检查 |
| `/api/websocket` | WS | 长连接 |

### 首页 /api/home

| type | 说明 |
|---|---|
| `runtime` | 运行时长、内存、流量 |
| `cellinfo` | 蜂窝小区信息 |
| `neighbor` | 邻区扫描 |
| `terminal` | 已连接终端列表 |

### 蜂窝 /api/cellular

| type | 方法 | 说明 |
|---|---|---|
| `mode` | GET/POST | 网络制式（5G/4G/3G） |
| `apn` | GET/POST | APN 配置，POST 支持 `action=del` / `action=bind` |
| `simconfig` | GET/POST | SIM 卡切换，可带 `&sim=<n>` |
| `lock` | GET/POST | 小区锁定 |
| `limit` | GET/POST | 流量限额，`action=clean` / `action=modify` |
| `cellinfo` | GET | 小区详细 |
| `rfparamters` | GET | RF 射频参数 |
| `at` | POST | **AT 指令直通**（`atcmd`, `timeout`） |

### 网络 /api/internet

| type | 方法 | 说明 |
|---|---|---|
| `lan` | GET/POST | LAN 口配置 |
| `ipv6` | GET/POST | IPv6 |
| `dhcp` | GET/POST | DHCP 服务 |
| `dhcp_host_add` / `dhcp_host_edit` / `dhcp_host_del` / `dhcp_host_setname` | POST | 静态租约增删改名 |
| `dividing` | GET/POST | 网络分流（clients / protocols） |

### 特性 /api/feature

| type | 方法 | 说明 |
|---|---|---|
| `firewall` | GET/POST | 防火墙开关 |
| `dmz` | GET/POST | DMZ（`enabled`, `dest_ip`） |
| `upnp` | GET/POST | UPnP，`&sub=leases` 看映射、`&sub=delete` 删映射 |
| `ssh` | GET/POST | SSH 开关 |
| `adb` | GET/POST | ADB 开关 |
| `debug` | POST | **执行 shell 命令**（`cmd`, `timeout`） |

### 系统 /api/system

| type | 方法 | 说明 |
|---|---|---|
| `devinfo` | GET | 设备信息 |
| `led` | GET/POST | LED 指示灯控制 |
| `usbswitch` | GET/POST | USB 模式切换 |
| `reboot` | POST | 重启 |
| `autoreboot` | GET/POST | 定时重启 |
| `localver` | GET | 本地固件版本 |
| `update` | POST | 检查更新 |
| `getUpdate` / `doUpdate` / `queryUpdate` | POST | OTA 流程 |

### 短信 /api/sms

| type | 方法 | 说明 |
|---|---|---|
| `smsbox` | GET | 收件箱/发件箱/草稿（`box=`, `unread=`） |
| `send` | POST | 发短信 |
| `del` | POST | 删除短信 |
| `log` | GET | 转发日志 |
| `forward` | POST | 转发配置 `type=get` / `type=set` / `type=testpush` |

### 其他

| 端点 | 说明 |
|---|---|
| `/api/wifi` | 无线（**后端有，但前端 V2.0.15 未接**） |
| `/api/ota` + `/fs/*/*` | 固件 OTA |
| `/api/upload` | 文件上传 |
| `/api/get/*`、`/api/get/*/*`、`/api/get/*/*/*` | 通用 uci **读** |
| `/api/set` | 通用 uci **写** |
| `/api/add/*` | 通用 uci **新增段** |
| `/api/del/*/*`、`/api/del/*/*/*` | 通用 uci **删除** |

---

## 4. 前端页面清单（`html/leftmenu.html` 菜单）

| 分组 | 页面 |
|---|---|
| **首页** | status（状态总览） |
| **短信** | shortmessage（收发）、smsforward（转发设置） |
| **移动网络** | profilemanagement(APN)、networksetting(制式)、simswitch(SIM切换)、pinmanagement、celllock(小区锁定)、limit(流量限额)、bandcheck(频段)、atcommand(AT指令)、rfparamters(RF参数) |
| **网络** | wan、dhcp、lan、ipv6、linkdetect、dividing |
| **无线** | wlansettings、wifiadvanced、wps、wlanmacfilter |
| **功能** | macfilter、ipfilter、portforwarding、dmz、diagnosis、firewall、upnp、security |
| **管理** | battery(隐藏)、sntp、deviceinfo、statistics、systemlog、systemadmin、backuprestore、upgrade、rebootreset、**shell(隐藏)**、cwmpsettings、ledctrl、usbfunc、webuiconf |
| — | **进入官方后台**（跳 `/cgi-bin/luci`） |

技术栈：`layui` + `bootstrap.min.css` + 原生 JS，`index.html` 单页 + `#hash` 路由加载 `html/*.html` 片段。

> 实测：wan / wlansettings / wifiadvanced / webuiconf 这几个页面在 V2.0.15 里 **JS 存在但没有任何 `/api/` 调用**——
> 菜单已预留、后端 `/api/wifi` 也已实现，但前端尚未对接。

---

## 5. 三大特色子系统

### 5.1 短信转发（`/root/forward.config`）

```ini
Forward_Open=0            # 总开关
Forward_Type=0            # 转发渠道 0=?
Forward_title=            # 推送标题
Forward_sleep=3           # 转发间隔(秒)
Pushplus_token=           # PushPlus
Dingtalk_webhook=         # 钉钉群机器人
Dingtalk_secret=          # 钉钉加签密钥
Feishu_webhook=           # 飞书机器人
Feishu_secret=            # 飞书加签密钥
Meow_webhook=             # 喵提醒
Delete_When_Pushed=0      # 推送后删除本机短信
```

后端内置 URL：`https://oapi.dingtalk.com/robot/send`、`https://open.feishu.cn/open-apis/bot`、
`https://www.pushplus.plus/send`。日志落 `/tmp/sms_log.txt`。
签名用 HMAC-SHA256（二进制里的 `HMAC_Init_ex` / `EVP_sha256`）。

### 5.2 OTA 自更新

- 版本探测 URL 模板：`http://%s/%s?devtype=%s&ver=%d&device_code=%s&ver_s=%s`
- 包地址：`http://%s/package/%s/%s`
- 状态机（中文串还原）：`正在从服务器检测版本` → `发现新版本` → `是否下载更新` →
  `正在下载`(进度) → `正在刷入` → `正在后台重启以完成更新` → `刷入成功`
- 有防护：`不支持降级到`、`当前更新包要求最低版本为`、`请确认文件是否适用于此设备`、超时/已有任务互斥

### 5.3 门户劫持 / 入口选择（**最容易忽略的行为**）

当 `WEB_ENTRY_SELECT=1` 时，程序会：

1. 把厂商首页备份为 `/www/index.html.bak`
2. 写入自己的 `/www/index.html`（内嵌模板，两个入口卡片：
   `__BEAUTY__` 美化版 `:10086` / `__OFFICIAL__` 官方版 `/cgi-bin/luci`）
3. 写入 `/www/cgi-bin/portal`（标记 `-- NRWEBUI_PORTAL=1.0`）
4. 支持倒计时自动进入：`秒后自动进入美化版界面`

**当前 C2000 U 上的实际状态：`/www/index.html` 已被改写（369B），原版在 `.bak`（368B），
`/www/cgi-bin/portal` 存在 —— 说明部署脚本执行过一次门户写入。**

---

## 6. 部署链路（PC 工具视角）

PC 端 `WebUI刷入工具_V1.1.2.exe` 是 **.NET x64 控制台程序**（PE machine=0x8664，有 CLR header）。

从字符串还原的交互流程：

```
输入设备地址（回车默认 192.168.66.1，直接回车沿用上次）
  ↓
输入型号（"支持型号" / "当前选择型号" / "使用默认"）
  ↓
输入账号密码  → "正在尝试登录设备" → "登录成功" / "密码错误" / "登录异常"
  ↓
POST http://<ip>/cgi-bin/luci/index          # 登录厂商 LuCI
  ↓
下发指令： (curl -ksL http://la.2014816.xyz/webui/<型号>.sh | sh) >/dev/null 2>&1 &
  ↓
"指令已发送" → 等待 → "秒后尝试访问验证是否刷入成功" → "刷入成功" / "刷入失败"
```

提示语还包括："刷入前请保持设备联网"、"刷入过程中请勿断电或重启设备"、"网络不通/不通或设备未开机"、
"是否继续刷入其他设备"、"按任意键退出"。

`nradio.sh` V1.6 的流程（见 `upstream/nradio.sh`）：
检查 4MB 空间 → 清理 → 下载 `nr_webui` → 写 `webui.conf` → `./nr_webui downloads` → `start` → 打印访问地址。

---

## 7. 还原方法（已实测通过）

### 难点

路由器**没有 SFTP、没有 base64**，且 **SSH 单条命令 >8KB 会被 dropbear reset**。
167 个文件 / 2.7MB 的前端目录用 heredoc 分块写不现实（要几百条命令）。

### 解法：反向 HTTP

**在 PC 上起临时 http.server，让路由器用 curl 拉。**

```
C:\...\nr-webui-archive\router\webui  --tar-->  webui.tar (2.86MB)
                                                    │
PC 192.168.66.100:18899  ──── HTTP GET ────>  路由器 curl -o /tmp/webui.tar
                                                    │
                                              tar xf -C /root
```

实测：2.86MB 秒传，比 SSH 分块快几个数量级。

### 一键脚本

```bash
set ROUTER_PW=<密码>
python restore_nrwebui.py --check      # 只测连通性
python restore_nrwebui.py              # 完整还原
python restore_nrwebui.py --only frontend
python restore_nrwebui.py --only bin
```

脚本会：备份现状（`/root/webui.bak-<ts>`、`/root/nr_webui.bak-<ts>`）→ 传前端 → 传二进制 →
写 `webui.conf` / `/etc/init.d/nrwebui` → enable + restart → 验证进程、端口、`/api/islogin`、
静态资源、`/root/webui/ver`、文件数。

**实测结果（2026-09-12）**：

```
文件数: 167     版本: V2.0.15     二进制: 233944 B
进程: 21129     端口: :::10086 LISTEN
islogin: {"code":0,"loggedin":false}
/ 200   /login.html 200   /css/common.css 200   /js/common.js 200   /ver 200
```

> 如果 PC 防火墙挡了入站（探测返回非 200），脚本会提示：
> `New-NetFirewallRule -DisplayName 'nrwebui-restore' -Direction Inbound -LocalPort 18899 -Protocol TCP -Action Allow`

---

## 8. 安全观察（客观事实，供你自行判断）

这套东西是**第三方闭源程序，以 root 常驻运行**。逆向能看到的事实：

| 观察 | 说明 |
|---|---|
| **通用 uci 读写接口** | `/api/get/*`、`/api/set`、`/api/add/*`、`/api/del/*/*` 可以读写**任意** uci 配置，不限于前端用到的那些 |
| **远程 shell** | `/api/feature?type=debug` 接受 `cmd` + `timeout`，可直接执行系统命令（前端 shell.html 默认 `display:none` 隐藏） |
| **AT 指令直通** | `/api/cellular?type=at` 可下发任意 AT 指令到基带 |
| **token 有效期** | `Max-Age=2147483647`（约 68 年），登出才失效；设备重启不失效 |
| **更新无签名** | 二进制与前端都从**明文 HTTP** 源站拉取，无签名/校验和中途校验，落盘即 root 执行 |
| **门户劫持** | 会改写 `/www/index.html` 并新增 `/www/cgi-bin/portal` |
| **短信外发** | 短信内容会被推送到钉钉/飞书/PushPlus 公网 webhook |
| **两个不同源站** | `la.2014816.xyz` 只放 `nradio.sh` 和后端二进制；前端来自**另一台**明文 HTTP:80 的国内 OTA 服务器 |

建议（如果你在意）：

1. **不要做端口转发把 10086 暴露到公网**
2. 不用时 `/etc/init.d/nrwebui disable && stop`，用的时候再开
3. 定期比对 `/root/nr_webui` 的 md5（归档里 `MANIFEST.md5` 有基线）
4. 若发现异常，回滚：`mv /www/index.html.bak /www/index.html; rm /www/cgi-bin/portal`

---

## 9. 文件清单（`nr-webui-archive`，179 文件）

```
router/
  nr_webui_current        233944  aarch64 ELF，当前运行版本（自更新后 V2.0.15）
  nrwebui.init              764  /etc/init.d/nrwebui（含自更新逻辑）
  webui.conf                122  主配置
  forward.config.example    178  短信转发配置模板（token 已留空）
  webui/                   167 文件 2.7MB，前端 V2.0.15
      index.html / login.html / ver / config.js
      html/   28 个页面片段（含 leftmenu.html 菜单）
      js/     29 个页面逻辑 + common.js/global.js/login.js
      css/    common.css + login.css
      lib/    layui + bootstrap
      images/ ~90 个图标（信号格/电池/网络制式…）
upstream/
  nradio.sh               1901  V1.6 部署脚本
  nr_webui_v2.0.8       229840  源站原版二进制（与 current 差 4104 B = 自更新增量）
pc-tool/
  WebUI刷入工具_V1.1.2.exe  4987392  .NET x64 控制台刷入工具
MANIFEST.md5 / README.md / .gitattributes
```
