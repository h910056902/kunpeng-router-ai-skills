---
id: REF-kpwebui
title: "kp-webui —— 鲲鹏 C2000 U 的 iStoreOS 风格独立控制台（v2）"
tags: [kpwebui, uhttpd, cgi, luci]
risk: medium
preconditions:
  - "uhttpd 可起第二实例"
  - "端口 10087 未被占用"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# kp-webui —— 鲲鹏 C2000 U 的 iStoreOS 风格独立控制台（v2）

一个**不依赖厂商 LuCI、不依赖 Docker、不占内存常驻进程**的纯 shell 控制台。
技术路线：**第二个 uhttpd 实例 + POSIX ash CGI + 设备端 lua 直调厂商库**。

- 访问地址：`http://<lan_ip>:10087`（C2000 U 上是 `http://192.168.66.1:10087`）
- 服务脚本：`/etc/init.d/kpwebui`（START=98，开机自启，绑定 `network.lan.ipaddr`）
- 目录：`/root/kpwebui/www`（index.html + css/js + cgi/api.sh）+ `/root/kpwebui/lua/`（4 个 lua 助手）
- 源码副本：本技能包 `src/kpwebui/`
- 一键部署：`python scripts/deploy_kpwebui.py`（需 `ROUTER_PW` 环境变量；**不会覆盖** `/root/kpwebui/forward.conf`）

## v2 新增（2026-09-12，参考 nr-webui 逆向结果复刻）

| 页面 | 数据来源 | 说明 |
|---|---|---|
| 短信 | `luci.nradio.sms_list/sms_send/sms_del` | 收件箱/未读、发短信（PDU 由厂商库处理）、删除 |
| 蜂窝 | ubus `infocd cpestatus/runtime`（cpe + cpe1 双通道） | RSRP/SINR/RSRQ/频段/PCI/IMSI/ICCID/IMEI/模块温度 |
| AT 控制台 | ubus `atsdcpe at_cmd`（备用 atsdcpe1） | 直通基带，实测 ATI/AT+CSQ/AT+CGMI |
| 无线 | uci wireless wlan0/wlan1 | SSID/密码/加密/信道/功率/隐藏/开关，`cloudd_reload_service network reload` 应用 |
| 终端 | ubus `infocd terminal` + /tmp/dhcp.leases | 在线设备、信号、速率、在线时长 |
| 端口转发 / DMZ | uci firewall redirect | 增删/启停/DMZ 开关，`/etc/init.d/firewall reload` |
| 推送 | `/root/kpwebui/forward.conf` + cron | PushPlus/钉钉/飞书/MeoW，每分钟查新短信（**非常驻**），测试推送、日志 |

**lua 助手**（`/root/kpwebui/lua/`）是全方案的关键：`reqdec.lua` 把 urlencoded
POST body/QS 解成 shell 安全赋值（R_* 变量），`smsapi.lua`/`atapi.lua`/`cellapi.lua`
从**环境变量**收参数——彻底绕开 shell 引号转义问题。

## 页面（v1）

概览 / 应用 / 容器 / 网络 / 文件 / 系统

- 概览：型号、运行时长、内存、CPU 温度（thermal_zone0）、系统盘/数据盘、LAN/WAN、OpenClash 版本与当前节点、Docker 状态、未读短信徽标
- 应用：读 `/etc/kp_store/plugins.json` + `installed.list`，卡片式展示（iStoreOS 观感）
- 容器：`docker ps -a` / `docker images`，启停重启
- 网络：接口、DHCP 客户端、**53 端口监听进程**、iptables nat 劫持链
- 文件：目录浏览、下载、上传（raw stdin）、URL 拉取
- 系统：LED 开关（ubus ledctrl）、配置备份到 `/mnt/storage/data/backup/`、重启网络/Docker/路由器、opkg、命令控制台

## 写 CGI 后端必踩的 5 个坑（都实测过）

1. **`printf` 拆成多条时，参数只挂在最后一条上**。
   ```sh
   printf '{"a":%s,'      # ← 这条拿不到参数，%s 打成空
   printf '"b":%s}\n' "$a" "$b"   # ← 18 个参数全给它，会重复打印格式串
   ```
   正确做法：每个 `printf` 自带它要用的参数。

2. **管道里的 `while` 是子 shell**，`first=0` 改不回父 shell → 逗号拼接永远不加逗号，
   输出 `{...}{...}` 这种非法 JSON。
   解决：子 shell 里把对象**逐行写临时文件**，父 shell 用 `awk 'NF{c++; if(c>1) printf ","; printf "%s", $0}'` 拼。

3. **busybox awk（v1.33.2）功能很弱**：三元表达式 + 嵌套 for/if 会报
   `awk: cmd. line:1: Call to undefined function`。
   文件列表解析改用纯 shell：`ls -la | while read -r perm lk own grp sz mo d tm name`。
   busybox `ls -la` 字段固定：1权限 2链接数 3属主 4属组 5大小 6月 7日 8时间或年 9+名称。

4. **`/etc/kp_store/plugins.json` 是跨行 pretty JSON**，字段各占一行。
   不能按行 grep（一行只有一个字段）。要先 `tr -d '\n'` 压平，再 `tr '{' '\n'` 切开，每个对象一行。
   `installed.list` 是 `|` 分隔：`id|name|pkg|ver|time|route|source|des|url`。

5. **iptables `-S` 的 comment 带引号**，用 `s/.*comment \([^ ]*\).*/\1/p` 会抓到 `"OpenClash`。
   改成 `s/.*--comment "\([^"]*\)".*/\1/p`。

## 注册进鲲鹏原生商店（让它出现在厂商 UI 里）

1. 往 `/etc/kp_store/plugins.json` 的 `plugins` 数组追加条目（字段：
   `id/name/pkg/route/source/des/open_url`；外链服务把 URL 同时写进 `route` 和 `open_url`，
   照 `dpanel` 那条照抄即可）
2. `kp-store-register <pkg>`（它按 `pkg` 去清单里找，找不到会 `pkg not in manifest`）
3. 回写结果在 `/etc/kp_store/installed.list`

改完用 lua 验一下没写坏：`lua -e 'local c=require "cjson";local f=io.open("/etc/kp_store/plugins.json");print(#c.decode(f:read("*a")).plugins)'`

## 已知限制

- 商店页只做**浏览 + 打开**，不做在线安装（安装路径太依赖具体源，容易把机器搞挂）
- 文件上传走原始 POST body，没有 base64，大文件（>10MB）在 992MB 内存的机器上不友好
- 没有任何鉴权，**只在 LAN 内使用**；`uhttpd` 绑定的是 LAN IP 而非 `0.0.0.0`
- 短信**发送**未实测（要花钱），链路与厂商 LuCI 完全一致（`luci.nradio.sms_send` PDU 路径）
- 钉钉/飞书机器人若开启「加签」暂不支持签名（固件无 openssl CLI），用「自定义关键词」即可
- OTA / 门户劫持 / APN·小区锁定 / SIM 切换**刻意没复刻**（明文源站更新有投毒风险；锁小区可能导致失联）

## v2 部署期踩的新坑（都实测过）

6. **lua urldecode 必须先还原 `+` 再解 `%XX`**——反过来的话 `%2B` 解出的 `+` 会再变成空格，
   `AT+CSQ` 就成了 `AT CSQ`（AT 指令静默变形）。
7. **`uci set x=$(sq "$var")` 会把引号写进配置值**！命令替换的结果不参与引号解析，
   uci 收到的 argv 里带着字面 `'`。直接 `uci set x="$var"` 就是安全的（变量本身就是单个 argv）。
   `sq()` 只用于**生成将来要被 shell 再解析的文本**（如写 forward.conf）。
8. **redirect 段的类型不是选项**：`uci get firewall.@redirect[1].type` 查不到 → 校验该段是否
   是 redirect 要用 `uci show firewall | grep -Fc "firewall.$R_sec=redirect"`。
9. **cjson.encode 把空 lua table 编码成 `{}` 而不是 `[]`**——空短信箱的 smslist 变成对象，
   前端 `.forEach` 直接炸。前端用 `Array.isArray(x) ? x : []` 兜底。
10. **`ubus call ledctrl get` 偶发返回 `{\t}`**——不要对它的输出做结构假设，
    用 `grep -o '"status":"[a-z]*"'` 提取 + 白名单校验（on/off），否则 TAB 字符会打进 JSON 字符串。
