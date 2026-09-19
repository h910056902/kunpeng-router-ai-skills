---
id: REF-docker-panel
title: "Docker 面板（自建 LuCI 集成）· 完整记录"
tags: [docker, panel, luci, unix-socket, archive]
risk: medium
preconditions:
  - "读档用途（自建面板实现与 200s 超时坑）"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# Docker 面板（自建 LuCI 集成）· 完整记录

状态：**已部署可用**。入口 `/cgi-bin/luci/nradioadv/system/dockerpanel`
文件：`/usr/sbin/dpctl`、`/usr/lib/lua/dpapi.lua`、`controller/nradio_adv/dockerpanel.lua`、`view/nradio_dockerpanel/dockerpanel.htm`
本地副本：`%USERPROFILE%\Desktop\鲲鹏无限路由器美化\patches\dockerpanel\`

> **⚡ 最重要的性能结论（2026-09-11）**：**别用 `docker` CLI 读数据**。
> 在本机实测 CLI 每条命令冷态 4-9 秒，而用 Lua `socket.unix` 直连 Docker HTTP API 只要 **0.03-0.3 秒**，
> 整页从 28s+ 降到 <1s（热态）。详见第六节。

---

## 一、设备硬约束（决定了全部设计）

| 项 | 值 | 影响 |
|---|---|---|
| 内存 | 493MB 总，**可用仅 40-100MB**，swap 已用 130-175MB | 禁止任何常驻进程 |
| 存储驱动 | **vfs** | 空间放大 2-3 倍；`{{.Size}}` 灾难性慢 |
| 真实配置 | `/tmp/dockerd/daemon.json`（init 每次从 UCI 生成） | 改文件无效，改 UCI |
| 网络 | **bridge 不可用**（veth `operation not supported`） | 只能 host 模式 |
| 工具 | 无 jq、无 compose、**无 timeout 命令** | 用 `docker --format` / 后台 PID+轮询 |
| 可用 | `luci.jsonc`、`cjson`、`ttyd`(源里有) | Lua 层 JSON 无碍 |

---

## 二、必须记住的 7 个坑

### 1. `docker ps --format '{{.Size}}'` = 自杀
vfs 下要遍历可写层，实测 **200s 未返回**。容器列表字段只用：
ID / Names / Image / Status / State / Ports / CreatedAt。

### 2. `{{json .}}` 可用于 images，不可用于 ps
`docker images --format '{{json .}}'` ✅
`docker ps -a --format '{{.json .}}'` ❌ 挂起超时（20.10.17）
→ ps 用显式字段拼 JSON。

### 3. dockerd 被 swap 换出，冷调用 10-20s
连续调用：4.8s → 2.5s → 0.2s → 0.1s。
对策三件套：
- 合并调用 `docker info --format '{{.ServerVersion}}|{{.Driver}}|{{.DockerRootDir}}'`
- 缓存：info 30s / containers 15s，写操作后 `rm -f /tmp/dp/*.cache`
- 异步拆分：网络、卷数量不进概览

### 4. 加速源必须写 UCI 才持久化
```sh
uci add_list dockerd.globals.registry_mirrors='https://docker.m.daocloud.io'
uci commit dockerd
# 立即生效：改 /tmp/dockerd/daemon.json 后 kill -HUP $(pidof dockerd)
```
`kill -HUP` 热重载**实测容器不中断** ✅（比 restart 安全）
配置路径解析要支持 `--config-file=PATH` 形式（`grep -o '^--config-file=.*' | cut -d= -f2-`）。

### 5. bridge 网络不可用 → 一律 host
报错：`failed to add the host (veth...) <=> sandbox (veth...) pair interfaces: operation not supported`
生成命令固定 `docker run -d --network host ...`，端口直接占路由器端口。

### 6. 上传脚本两个隐蔽 bug
- heredoc 结束标记后**必须换行**再拼其他命令，否则 `MARKER 2>&1` 连成一行 → heredoc 永不结束
- Windows 下 Python 文本模式写文件会产生 CRLF → shebang 变 `#!/bin/sh\r` → `not found`。
  部署脚本强制 `raw.replace(b'\r\n', b'\n')`

### 7. SSH 通道对含 heredoc 的命令不回传 stdout
无法用 rc 判断，**只能 md5 最终校验**。

---

## 三、LuCI 集成要点

- 路径是 **`nradioadv/system/xxx`**（不是标准 `admin/...`）
```lua
page = entry({"nradioadv","system","dockerpanel"}, template("nradio_dockerpanel/dockerpanel"), _("Docker 面板"), 91, true)
entry({"nradioadv","system","dockerpanel","api"}, call("action_api"), nil,nil,true).leaf = true
page.show = true
```
- view 用 `<%+header%>` / `<%+footer%>`，有 jQuery
- API 地址注入：`<%=require("luci.dispatcher").build_url("nradioadv","system","dockerpanel","api")%>`
- **只新增文件，绝不改 appcenter.lua**（502 事故教训）
- 安全：参数白名单双重校验（Lua + shell）。实测 `; rm -rf /`、`$(id)`、`../` 全部拒绝

---

## 四、镜像加速实测（2026-09-10）

**27 个源仅 7 个存活**（返回 200/401 判定可用）：

| 源 | 延迟 |
|---|---|
| `docker.m.daocloud.io` | 0.17s |
| `docker.1ms.run` | 0.20s |
| `docker.imgdb.de` | 1.41s |
| `docker.367231.xyz` | 1.59s |
| `docker-0.unsee.tech` | 1.62s |
| `docker.fxxk.dedyn.io` | 1.88s |
| `registry-1.docker.io`（经 Clash） | 2.36s |

已阵亡：轩辕、1Panel、rat.dev、南大 NJU、dockerpull.org、dockerproxy.cn、mrxn、kejilion 等 20 个。

**重要认知**：Clash TUN 已全局接管本机流量，官方源本来就通（1.5s 握手）。
第三方源是"Clash 挂掉时的兜底"，不是唯一出路。
注意 `curl -x 127.0.0.1:7890` 显式走 HTTP 代理反而不通（返回 000）。

---

## 五、遗留待办

1. **僵尸容器 `t1`**（image `6f5c44eebf23`，Created 从未启动）——疑似 Dockge 残留
2. **7.5GB vfs 孤儿层**：`/opt/docker` 实际 7.8G，docker 只认 234MB
3. 专卖店可加"一键创建容器"（后端 `container_create`，强制 host 模式）
4. ttyd 终端（源里有 1.6.3，按需装）

---

## 六、性能修复：Lua socket.unix 直连 Docker API（2026-09-11）

### 问题
面板打开慢、容器识别慢。实测根因：**`docker` CLI 每次调用 4-9 秒**
（`docker version` 4.58s、`docker info` 9.85s、`docker ps -a` 7.43s、`docker images` 8.21s；
`docker network ls`/`volume ls` 仅 1.1s → 慢在容器/镜像元数据 + dockerd 被 swap 换出）。
概览原本串行跑 4 条命令 ≈ 28 秒。

### 方案：绕过 CLI，直接说 Docker HTTP API
`curl` **不支持** `--unix-socket`（`curl -V` 的 Protocols 里没有），但 **LuaSocket 的 `socket.unix` 可用**，
且 LuCI 已加载 Lua 解释器 → 零额外进程开销。

```lua
-- /usr/lib/lua/dpapi.lua
local socket = require("socket")
local unix   = require("socket.unix")     -- 注意：是函数，unix() 创建对象
local jsonc  = require("luci.jsonc")

function M.get(path, timeout)
  local u = unix()
  u:settimeout(timeout or 15)
  local ok, err = u:connect("/var/run/docker.sock")
  if not ok then return nil, "connect: "..tostring(err) end
  u:send("GET "..path.." HTTP/1.0\r\n\r\n")   -- HTTP/1.0 → 连接关闭界定 body，免处理 chunked
  local body = u:receive("*a")                -- 读到底；不要用 "*l" 逐行（响应头混在 body 里）
  u:close()
  local _, idx = body:find("\r\n\r\n")
  return body:sub(idx + 1)                    -- 切掉响应头
end
```

### 端点与字段映射
| 面板数据 | API 端点 | 耗时(热) |
|---|---|---|
| info | `/info` | 0.03s |
| containers | `/containers/json?all=1` | 0.09s |
| images | `/images/json` | 0.07s |
| networks | `/networks` | 0.007s |
| volumes | `/volumes` | 0.001s |

映射要点（返回值与 docker CLI 的 `--format` 不同，前端按原格式消费）：
- 容器：`Id→id`(取前12位) / `Names[1]`(去掉前导 `/`) / `Image` / `State` / `Status` /
  `Ports[]`(拼 `0.0.0.0:9000->9000/tcp`，host 模式为空数组) / `Created`(epoch → `os.date("!%Y-%m-%d %H:%M")`)
- 镜像：`RepoTags[1]` 用 `rt:match("^(.*):([^:]*)$")` 拆 repo/tag（贪婪匹配可正确切分 `ghcr.io/user/app:1.0`）/
  `Id` 去 `sha256:` 前缀取 12 位 / `Size`(字节→人类可读)
- **`/info` 一次调用就够**：`Version` / `ApiVersion` / `Driver` / `DockerRootDir` / `Containers` /
  `ContainersRunning` / `Images` 全在里面，不用再调 `/version` 和 `docker info`
- 内存/swap 从 `/proc/meminfo` 读（`MemTotal`/`MemAvailable`/`SwapTotal`/`SwapFree`，是 KB）；
  磁盘用 `nixio.fs.statvfs("/opt/docker")` 的 `blocks*frsize`、`bavail*frsize`

### 配套三件事（缺一效果打折）
1. **缓存**：`/tmp/dp/<name>.cache`，info/containers/images 20s、networks/volumes 60s；
   变更类 action（container_action / image_action / prune / pull_start / docker_service）后清缓存
2. **预热**：页面渲染时 fire-and-forget，把被 swap 换出的 dockerd 拉回内存
   ```lua
   pcall(os.execute, "lua -e 'require(\"dpapi\").preheat()' >/dev/null 2>&1 &")
   ```
3. **失败回退**：快速通道返回 nil 时落回 `dpctl`（CLI），保证极端情况仍可用

### 效果
| 接口 | 修复前 | 修复后 |
|---|---|---|
| info | 4.6+9.9s | **1.4s（首次冷）/ 0.03-0.6s** |
| containers | 7.4s | **0.19s** |
| images | 8.2s | **0.31s** |
| 整页 | 28s+ | 冷态 5-10s 一次，之后 <1s |

---

## 七、坑：`du` 扫描的并发泄漏（务必加锁）

`dpctl disk_size` 需要 `du -sk /opt/docker` 统计真实占用，但 vfs 上这个目录有 **7.8G**，跑一次数十秒。
若实现成"缓存过期就起一个 du"，而前端在 `computing` 期间每 5 秒轮询一次 → **叠加出 6+ 个 du 进程互相抢 IO**（实测内存排行里躺着 6 个）。

**正确写法：`mkdir` 原子锁**（不要用「先起进程再写 pid 文件」，那之间有竞态窗口）：
```sh
if [ -d "$L" ]; then                      # 残留锁清理（进程被杀的异常情况）
  LT=$(date -r "$L" +%s 2>/dev/null)
  if [ $(( NOW - LT )) -gt 600 ]; then rmdir "$L" 2>/dev/null; fi
fi
if mkdir "$L" 2>/dev/null; then           # mkdir 是原子的 → 只有一个请求能拿到锁
  nohup sh -c "du -sk '$ROOT' ... > '$C'; rmdir '$L'" >/dev/null 2>&1 &
fi
```
另外 **dockerd 未运行时直接短路**，不要起 7.8G 的扫描。

> ⚠️ 验证计数的坑：`ps | grep 'du -sk'` 会同时匹配 `sh -c "du -sk ..."` 包装进程和 `du` 本体，
> 容易误判为"泄漏了 2 个"。精确计数要用 `/proc/<pid>/comm == du`。

---

## 八、省内存：面板内一键启停 Docker + 插件瘦身（2026-09-11）

### 面板能力
- 后端 `dpctl docker_service start|stop|autostart_off`（内部调 `/etc/init.d/dockerd start|stop|disable`）
- 控制器 `action=docker_service`，`do` 参数白名单校验，执行后清缓存
- 前端：dockerd 未运行时概览页渲染「一键启动」卡片；设置页有「停止 Docker（省内存）」
- **优雅降级**：dockerd 未运行时只读接口 **0.16-0.22s** 返回
  `{"ok":false,"error":"Docker 服务当前未运行","dockerOff":true}`，各标签页显示提示，
  不会像以前那样卡 60 秒超时
- 闭环实测：start 2.6s / stop 4.6s；显式 `docker stop` 过的容器**不会**被 restart 策略唤醒

### 插件瘦身配方（保留 OpenClash 与基础设施）
```sh
docker stop adguardhome portainer
/etc/init.d/dockerd stop && /etc/init.d/dockerd disable
rm -f /etc/rc.d/S99dockerd                 # disable 有时留残余链接
for s in mosquitto mqttagent miniupnpd telnetd wifidogx xl2tpd igmpproxy; do
  [ -x /etc/init.d/$s ] && /etc/init.d/$s stop && /etc/init.d/$s disable
done
```
**绝不能停**：`network` / `firewall` / `dnsmasq`(DNS+DHCP) / `uhttpd`(Web) / `dropbear`(SSH) / `odhcpd` / `rpcd` / `cron` / `sysntpd`

### 实测收益
- 可用内存 **47MB → 150MB**；used 383MB → 283MB
- **swap 占用 178MB → 32MB**（最关键）
- 出网 baidu 0.25s → **0.046s**（卡顿主因就是换页）
- 停用后 OpenClash / dnsmasq / uhttpd / dropbear / 路由 全部正常

### 相关：路由器侧 DNS 中断的独立成因
OpenClash 重启要加载 **10.5MB GeoSite 规则 + 46MB clash_meta**，在本机内存压力下耗时约 **2.5 分钟**
（日志：00:46:52 开始 → 00:49:28 `OpenClash Start Successful!`），期间 dnsmasq 上游 `127.0.0.1#7874`
不可用且 `noresolv=1` 无备用 → **整个 LAN 失去 DNS**。腾出内存后恢复正常。
> 排查提醒：路由器 OpenClash 本身就是 fake-ip 模式，向 LAN 客户端返回 `198.18.x.x` 属**正常**现象；
> 与 PC 端 mihomo 的 fake-ip 同用 `198.18.0.0/16`，仅凭 IP 段无法区分来源。
