# nr_webui 第三方 WebUI 服务（:10086）档案

> 2026-09-11 建档；**2026-09-12 00:15 重大更正**：建档时的根因判断是错的（见 §"故障案例"），
> 前端**不是**从 `la.2014816.xyz/webui/` 下的，而是 `nr_webui` 自己从另一台 OTA 服务器拉的。

## 架构硬事实

| 项 | 值 |
|---|---|
| 进程 | `/root/nr_webui`（Go 编写，单线程，RSS ~4MB），监听 `:::10086` |
| 服务脚本 | `/etc/init.d/nrwebui`（START=99 / STOP=10；start 时若存在 `/tmp/nr_webui.new` 先杀旧进程换新 —— 热升级机制） |
| 配置 | `/root/webui.conf`：`WEBUI_ROOT=/root/webui`、`WEBUI_PORT=10086`、`FORWARD_CONFIG=/root/forward.config`、`WEB_ENTRY_SELECT=0`、`WEB_ENTRY_DEFAULT_BEAUTY=0` |
| 前端目录 | `/root/webui/`（`index.html` + `login.html` + `config.js` + css/js/lib/images/font/`ver`） |
| 推送配置 | `/root/forward.config`：短信转发到 Pushplus / 钉钉 / 飞书 / Meow 的 webhook |
| 部署来源 | PC 端 `WebUI刷入工具_V1.1.2.exe`（Go x64，PE32+，非 .NET，主源 `dd5g.go`；纯 HTTP LuCI 客户端，表单字段 `luci_username`/`luci_password`/`luci_channel`） |
| 落地脚本 | `http://la.2014816.xyz/webui/nradio.sh`（**V1.6，实测 200**）—— exe 只负责让路由器执行 `(curl -ksL %s%s \| sh)` |

### 两个源，别搞混

| 源 | 内容 | 探测结果 |
|---|---|---|
| `la.2014816.xyz/webui/` | 只有 `nradio.sh`（200）和 `nr_webui`（200，229840 B，md5 `a383db8f82cfb50148dff48a56e4dfc6`，版本 V2.0.8） | 目录列表 403；`webui_update.zip`/`webui_decode.zip`/`webuiver`/`index.html`/`dashboard.html`/`updateLog.txt`/`config.k`/`webui.bin` **全是 404 —— 它们从来不在这个源上**，是 OTA 阶段的产物 |
| OTA 服务器（`nr_webui` 内嵌，模板 `http://%s/%s?devtype=%s&ver=%d&device_code=%s&ver_s=%s`） | 前端包 `WEBUI_nradio_V2.0.15.bin` + 后端自更新 | 明文 **HTTP:80**，国内 IP（实测抓到 `110.242.74.203:80`、`110.242.70.52:80`，均为 nginx） |

> ⚠️ 早期建档时把「前端包 404」当成「资源源缺货」，据此建议"向发布者索取前端包"——**该结论错误，已作废**。

## 部署/修复流程（可复用）

```sh
# 首次部署（PC 工具做的就是这段）
curl -ksL http://la.2014816.xyz/webui/nradio.sh | sh

# 手动补跑（前端为空时的唯一正解）
cd /root && ./nr_webui downloads
```

`nr_webui downloads` 的实际行为：检测版本 → 下载 `WEBUI_nradio_V2.0.15.bin` → 解包到 `/root/webui` →
把新后端放到 `/tmp/nr_webui.new`（init 脚本热升级，本体 229840 B → 233944 B）→ 后台重启。

## API 面（二进制内嵌路由）

`/api/{add, cellular, del, feature, get, hi, home, initPage, internet, islogin, login, logout, ota, set, sms, status, system, upload}`

- 免鉴权探测：`/api/islogin` → `200 {"code":0,"loggedin":false}`；其余一律 `401 {"code":401,"msg":"Unauthorized"}`
- 页面 404 时响应体为 text/plain `404 NOT FOUND`
- ⚠️ `/api/ota` `/api/set` `/api/add` `/api/del` `/api/upload` 是写操作端点，诊断时**禁止触碰**

## 短信端点：不是 C2000 U 的兼容性问题

工具打的 `/cgi-bin/luci/nradio/cellular/sms/send`（`msg=%s&phone_num=10086&channel=`）在 C2000 U 上**存在**。
它注册在 **`/usr/lib/lua/luci/controller/nradio_adv/sms.lua`**（不是 `nradio/cellular.lua` —— 那个文件确实不存在，
但路由是由 `nradio_adv` 挂到 `nradio/cellular/sms/*` 路径下的）：

```lua
entry({"nradio","cellular","sms","send"}, call("action_sms_send"), nil, nil, true).leaf = true
```

配套守护进程实测在跑：`/usr/sbin/atsd -i cpe`、`/usr/sbin/atsd -i cpe1`、`/usr/sbin/smsd -i cpe`、`/usr/sbin/smsd -i cpe1`。
所以「C2000 U 不支持短信 → 工具用不了」**是错误归因**。

## 故障案例（2026-09-12 定案）：页面全 404、API 正常

- 现象：`http://192.168.66.1:10086/` 及所有页面 404，但 TCP 通、`/api/islogin` 200
- 真因：`/root/webui/` 为空 —— `nradio.sh` 里的前端下载步骤 **没有错误检查**：
  ```sh
  echo "下载webui前端资源..."
  ./nr_webui downloads      # ← 失败也不会中断，没有 if / $? 判断
  echo "请等待5秒..."
  sleep 5
  if [ ! -x ./nr_webui ];then ...   # ← 只检查后端在不在
  ```
  下载失败（当时整机出网正处在 OpenClash/ocspeed 故障窗口）后脚本照常打印"**webui全部部署完成**"，
  于是 `/root/webui` 被建出来但空着 → 页面全 404
- **修复**：`cd /root && ./nr_webui downloads`（一次成功）
- 修复后实测：`/` 200、`/login.html` 200、前端 `V2.0.15`（2.7 MB / 167 文件）、
  后端自更新 229840→233944 B、`/etc/rc.d/S99nrwebui` 已启用、`pidof nr_webui` 正常

## 排查口诀

1. `netstat -tlnp | grep 10086` → 确认 nr_webui 在听
2. `curl http://192.168.66.1:10086/api/islogin` → 200 = 后端活着，是前端缺失
3. `ls -la /root/webui/` → 空目录 = 前端没落地
4. **`cd /root && ./nr_webui downloads`** ← 补跑这一句即可，不要去找"缺货的 zip"
5. 仍失败再看出网：`nslookup` + `curl -v http://<OTA IP>/`；OTA 走明文 80，国内直连，不翻墙
