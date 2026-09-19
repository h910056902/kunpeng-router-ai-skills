# Docker 面板部署 playbook

> 完整源码在 `src/dockerpanel/`，一键部署脚本在 `src/deploy/`，
> **详细部署手册见 `src/deploy/README.md`**（含验证清单、回滚、排障速查）。
> 本文只记录「部署时最容易翻车的点」。

## 四个文件与目标路径

| 源文件 | 部署到 |
|---|---|
| `dpctl` | `/usr/sbin/dpctl`（chmod 755） |
| `dpapi.lua` | `/usr/lib/lua/dpapi.lua` |
| `dockerpanel.lua` | `/usr/lib/lua/luci/controller/nradio_adv/dockerpanel.lua` |
| `dockerpanel.htm` | `/usr/lib/lua/luci/view/nradio_dockerpanel/dockerpanel.htm` |

入口 `/cgi-bin/luci/nradioadv/system/dockerpanel`；
API `/cgi-bin/luci/nradioadv/system/dockerpanel/api?action=<动作>`。

## 部署三步（顺序不能错）

1. **上传** 4 个文件 —— ⚠️ 上传前强制 `\r\n` → `\n`
   （CRLF 会让 `#!/bin/sh` 变 `#!/bin/sh\r`，报 `dpctl: not found`）
2. **配加速源** —— 必须写 UCI `dockerd.globals.registry_mirrors`
   （`/tmp/dockerd/daemon.json` 每次启动从 UCI 重新生成，直接改文件必丢）
   然后 `kill -HUP $(pidof dockerd)` 热重载
3. **清缓存** —— `rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache`

## 部署时的三个高频坑

| 坑 | 症状 | 修法 |
|---|---|---|
| **CRLF 毁 shebang** | `dpctl: not found`，页面全废 | 上传时 `replace(b'\r\n', b'\n')`；用 `od -c` 或 Python 读字节确认前 12 字节是 `# ! / b i n / s h \n` |
| **改错配置文件** | 加速源重启后失效 | 写 UCI，别碰 `/tmp/dockerd/daemon.json` |
| **漏清 LuCI 缓存** | 页面 404 / 改了没变化 | `rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache` |

## 验证顺序（由内到外）

```sh
# 1. dpctl 自身
sh -n /usr/sbin/dpctl && echo OK
# 2. Lua 语法
lua -e 'print(loadfile("/usr/lib/lua/dpapi.lua") and "OK" or "ERR")'
# 3. dpapi 真连 docker.sock（最关键的一步）
lua -e 'local ok,m=pcall(require,"dpapi"); print("load:",ok);
        if ok then local b,e=m.get("/version",15); print("sock:", b and #b or e) end'
# 4. 页面/接口
curl -s -m 10 "http://127.0.0.1/cgi-bin/luci/nradioadv/system/dockerpanel/api?action=info"
```

**第 3 步是分水岭**：如果它返回 JSON，面板必然快；
如果失败，控制器会回退到 `dpctl`（走 docker CLI），接口会退化到 4-9 秒。

## 性能基准（热态）

| 接口 | 正常 | 异常（>3s 说明走了 CLI 回退） |
|---|---|---|
| info | 0.03-0.6s | 4.6 + 9.9s |
| containers | 0.09-0.19s | 7.4s |
| images | 0.07-0.31s | 8.2s |
| networks / volumes | < 0.3s | 1.1s |

用 `src/deploy/dp_perf.py` 实测。

## 回滚

```sh
rm -f /usr/sbin/dpctl /usr/lib/lua/dpapi.lua \
      /usr/lib/lua/luci/controller/nradio_adv/dockerpanel.lua
rm -rf /usr/lib/lua/luci/view/nradio_dockerpanel
rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache
sed -i '/^dockerpanel|/d' /etc/kp_store/installed.list
```

## 凭据纪律

`src/deploy/` 里的脚本全部走环境变量（`ROUTER_HOST` / `ROUTER_USER` / `ROUTER_PW` / `AGH_USER` / `AGH_PASS`）。
**新增脚本入库前必须扫一遍明文密码** —— 桌面原始 `patches/` 目录里
`add_filterlists.py` 曾出现 `AGH_PASS = '<AGH_PASS>'` 这样的明文，**该文件未收录**。
