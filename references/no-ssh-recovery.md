---
id: REF-no-ssh-recovery
title: "无 SSH 时的取数与命令通道（LuCI 旁路）"
tags: [rescue, luci, dmesg, crontab, reboot]
risk: medium
preconditions:
  - "LuCI 仍可登录"
  - "TF 卡为可插拔（掉线需物理复位）"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# 无 SSH 时的取数与命令通道（LuCI 旁路）

适用：SSH 不通（防火墙 REJECT / dropbear 未起 / 存储掉线导致服务全丢），但 **80 端口 uhttpd 还活着**。
全程只读或可完全回滚，不改动防火墙、不重启设备。

## 0. 先判断 SSH 属于哪种"不通"

| 现象 | 含义 |
|---|---|
| `Connection refused` | 端口无进程监听 |
| `Connection timed out` | 被防火墙 DROP |
| 之前能连、现在不能，且第三方服务全消失 | **存储掉线**导致 overlay 回落，见第 4 节 |

用 `curl -v telnet://IP:22` 可区分 refused / timeout。

## 1. 登录拿 sysauth（node 脚本）

```js
const http = require('http');
// POST /cgi-bin/luci/  body: luci_username=root&luci_password=<你的LuCI密码>
```
返回 200 + `Set-Cookie: sysauth=xxxx`。后续请求带 `Cookie: sysauth=xxxx`。

⚠️ **两个必踩的坑**：
- `Content-Length` 必须是 `Buffer.byteLength(body)`。写 0 会让服务器收不到账号密码
  → 返回 **403 且无任何提示**，极易误判成"密码错了"
- PowerShell 调 node 时**空字符串实参会被吞**：`& node a.js "" "/x"` 里 `argv[2]` 会变成 `/x`。
  要拆成不同脚本或用开关参数，不要靠位置参数区分"有没有传"

## 2. 最快通道：直接读日志页（零延迟，推荐先做）

这两个页面是**服务端渲染的 textarea**，GET 下来正则取最长的 `<textarea>` 内容即可，
**不需要等 cron**：

| 路径 | 内容 |
|---|---|
| `/cgi-bin/luci/admin/status/dmesg` | 内核环形缓冲（本次启动，实测 1382 行 / 117KB） |
| `/cgi-bin/luci/admin/status/syslog` | logread 系统日志 |

取到后本地过滤：`/mmc|msdc|mmcblk|sd card|sdio|vmmc|I\/O error|EXT4-fs|f2fs|overlay/i`。
注意 HTML 实体要反转义（`&quot;` `&lt;` `&gt;` `&amp;`）。

## 3. 命令通道：借 crontab 页面执行任意命令

仅当第 2 步不够用（需要 `ls /sys/...`、跑 unbind/rebind 等）时使用，代价是要等 ≤60s。

1. GET `/cgi-bin/luci/admin/system/crontab` → 取 `<input name="token" value="...">`
2. **multipart** POST 同路径，字段：`token`、`cbi.submit=1`、`cbid.crontab.1.crons=<全文>`
3. 任务里把输出重定向到 `/www/xxx.txt`，再 `curl http://IP/xxx.txt` 读回
4. **用完必须把 crons 写回原文**

要点：
- `X-CBI-State: 1` **不代表失败**，以回读页面内容为准
- 页面里那些 `cbid.table.N.svc.index` 隐藏 input **只有 id 没有 name**，不要提交
- **一次性任务要加锁**：`[ -f /tmp/done ] || { touch /tmp/done; ...; }`，否则每分钟重复执行
- ⚠️ 输出文件**不要用 `>` 配合守卫**，第二次 cron 会先截断文件再退出，把首轮有效输出冲成 0 字节
- 清理用**自删除 cron**：`* * * * * rm -f /www/xxx.txt; sed -i '/xxx/d' /etc/crontabs/root`
- 诊断文件放 /www 会占 overlay（存储掉线时 overlay 可能只有 2MB），控制输出体积并及时删

## 4. 案例：存储（SD/TF 卡）掉线的定性流程

**现象**：OpenClash / 1Panel / Docker / swap 集体"消失"，hostname 回到出厂值，内存变大、无 swap。

**根因链**：fstab 要把 `/dev/mmcblk0p1` 挂 `/overlay` → 卡识别失败 → overlayfs 回落到
NOR flash 的 `mtdblock8`（jffs2，**仅 2MB**）→ 卡上的一切都不在挂载树里。数据本身没丢。

**快速普查（一条 cron 搞定）**：
```sh
ls /sys/block; cat /proc/partitions; ls /dev/mmcblk*; df -h
cat /sys/kernel/debug/mmc0/ios     # 注意 debugfs 通常已挂载
```

**日志判读**：
```
mmc0: card never left busy state                  ← 卡从未释放 busy，最致命
mmc0: error -110 whilst initialising SD card      ← -110 = ETIMEDOUT，反复重试
mmc0: problem reading SD Status register          ← ACMD13/CMD13 无响应
mtk-msdc 11230000.mmc: msdc_request_timeout: ... cmd=13
```
- **没有** `mmc0: new high speed SDHC card at address xxxx` → 本次上电**一次都没识别成功**
- 若日志里先有 `mmcblk0: error` / I/O error / `remount read-only`，才是"运行中掉卡"
- `-84`(EILSEQ) 偏时序/CRC；**全是 `-110` = 完全静默**，属物理层

**`/sys/kernel/debug/mmc0/ios` 正常应显示**：
`clock 100kHz / 1bit / legacy / 3.30V / power on`
→ 已经是 SD 初始化最保守档位仍超时，可**排除速率与时序问题**。

**软件层能试的（全部无效也要试完以便定性）**：
1. 软重启：`POST /cgi-bin/luci/admin/system/reboot/call`（表单只有 `token`），返回 chunked 200 即触发
   —— 注意**不在** `/admin/system/reboot`（那页是 flashops 刷机表单）
2. 控制器复位：`echo 11230000.mmc > /sys/bus/platform/drivers/mtk-msdc/{unbind,bind}`
3. sysrq 硬重启：本内核**没编**（`/proc/sysrq-trigger` 不存在）
4. 给卡断电：`/sys/class/regulator/` 只有 `dummy / proc / fixed-3.3V` 且 fixed 无 state → **软件断不了电**

**定性结论**：卡完全没插好 / 触点氧化 / 卡控制器损坏 / 卡槽走线断，四选一。
（注意：**卡根本没插时主机表现完全一样**，别排除接触问题。）
只剩物理处理：**断电 → 取卡 → 擦触点 → 重插 → 上电**；仍不行就把卡插 PC 读，或换卡。

## 5. 介质定性：不是 eMMC，是 SD/TF 卡

`/proc/device-tree/soc/mmc@11230000/`：
```
no-mmc  no-sdio  broken-cd  cap-sd-highspeed
vmmc-supply / vqmmc-supply
status=okay  compatible=mediatek,mt7986-mmc
```
全机只有 `mmc0` 一个节点 → 存储就是**可插拔 SD/TF 卡**。
`broken-cd` = 无卡检测 GPIO，靠轮询，所以系统感知不到插拔。

⚠️ 设备树属性是**二进制（带 `\0`）**，落盘后 Read 工具读不了，
要先 `-replace "\0"," "` 并过滤非 ASCII。
