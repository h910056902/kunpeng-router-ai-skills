# 任务 01 · 装 OpenClash 并拉取 Mihomo 内核

> `id: openclash.install` / `openclash.core` · `risk: write`
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，内核 5.4.281，OpenWrt 21.02）
> 目标：OpenClash 的 LuCI 应用装好、Mihomo Meta 内核就位、服务起来、控制 API 可达。
> 参考档案：[`references/c2000u-openclash.md`](../references/c2000u-openclash.md)（实测实录）、
> [`references/one-command-restore.md`](../references/one-command-restore.md) §一/§二（换源与桩包）。

---

## 0. 一句话流程

**备份 → 换源 → 投递 ipk 与内核 → 装包 → 补 ruby-yaml → 解压内核并按 `clash_meta` 落位 → 写 UCI → 起服务 → 验端口与 API。**

---

## 1. 前置检查（**逐条实测，不满足就不要开始**）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| 1 | opkg 源可用 | `grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf` | **`0`** | 先按 §2 换源；出厂 6 个源全返回 `000`（不是 404），不换源连 `bash` 都装不上 |
| 2 | 可用内存 | `free -k \| awk '/MemAvailable/{print $2}'` | **> 100000**（kB，即 >100MB） | 先停重容器 / 按 `AGENTS.md` 的省内存清单腾；启动瞬间内核 + GeoSite 要吃 ~50MB |
| 3 | 依赖包已在 | `opkg list-installed \| grep -c pkg-openclash-dep` | **`1`** | 厂商预装包，正常都在；不在就先 `opkg install pkg-openclash-dep` |
| 4 | 唯一缺件确认 | `opkg list-installed \| grep -c ruby-yaml` | 通常 `0`（缺） | 缺就装（§4 第 5 步），这是**唯一**缺的依赖 |
| 5 | TUN / TPROXY 能力 | `modprobe tun; echo $?` 与 `modprobe xt_TPROXY; echo $?` | 两个都 **`0`** | 非 0 说明内核能力缺失——但 C2000 U 实测都可用，报错先怀疑命令拼写 |
| 6 | 端口空闲 | `netstat -ltn \| grep -cE ':(7890\|7891\|7892\|7893\|7874\|9090)\b'` | 通常是 `0` | 非 0 说明已有一套代理在跑 —— **B 机 OpenClash 进程名是 `clash` 而不是 `mihomo`**，`pidof mihomo` 查不到它，别误判"没装" |

> 💡 第 5 条的意义：**别因为"内核没有 veth"就以为代理也跑不了**。veth 只影响 Docker 桥接网络，
> 与 TPROXY/TUN 完全无关。实测 `tun.ko` 与 `xt_TPROXY` 都能加载。

```sh
# 一次性跑完 6 项（设备侧，只读）
echo "--- 1 source";  grep -c '21.02-SNAPSHOT' /etc/opkg/distfeeds.conf
echo "--- 2 mem";     free -k | awk '/MemAvailable/{print $2}'
echo "--- 3 dep";     opkg list-installed | grep -c pkg-openclash-dep
echo "--- 4 yaml";    opkg list-installed | grep -c ruby-yaml
echo "--- 5 mods";    modprobe tun; echo "tun=$?"; modprobe xt_TPROXY; echo "tproxy=$?"
echo "--- 6 ports";   netstat -ltn | grep -cE ':(7890|7891|7892|7893|7874|9090)\b'
```

---

## 2. 换源（前置 1 不满足时）

出厂 6 个源（base / packages / routing / mtk_openwrt_feed / openmptcprouter + core 的
`targets/mediatek/mt7987`）**全部返回 `000`** —— 是连接根本建不起来（DNS 能解析到
`146.75.46.132` 但 `conn=0.000000s`），不是 404。

```sh
# 设备侧
cp -a /etc/opkg/distfeeds.conf /etc/opkg/distfeeds.conf.kp-bak-$(date +%Y%m%d_%H%M%S)
cat > /etc/opkg/distfeeds.conf <<'EOF'
src/gz openwrt_base     https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/base
src/gz openwrt_packages https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages
src/gz openwrt_routing  https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/routing
EOF
opkg update          # 实测 ~3.0s，签名校验通过
```

**故意不保留 `core` 与 target 源**：官方根本没有 mt7987 这个 target，留着只会让 `opkg update` 卡在超时上。

---

## 3. 素材位置（本仓库 `offline/`，版本已钉死）

| 文件 | 大小 | md5 |
|---|---|---|
| `offline/openclash/luci-app-openclash_0.47.156_all.ipk` | 9.9 MB | `c37e00b26140090d715fb89cae76507c` |
| `offline/core/mihomo-linux-arm64.gz` | 16.6 MB | `8cc282b6b8f1a14cb7639e8ed6ca0e30` |
| `offline/openclash/config.openclash.template` | 7.9 KB | 见 `offline/checksums.md5` |

内核身份：**Mihomo Meta v1.19.30（linux-arm64, with_gvisor）**。
自检串形如 `Mihomo Meta v1.19.30 linux arm64 with go1.26.6 ...`。

文件投递 → **设备没有 SFTP，PC 的 HTTP 服务也被 Windows 防火墙拦入站**，唯一可靠通道是
**SSH 反向端口转发**（实测 10.2 MB / 1.6 s、16.6 MB / 2.2 s）：

```bash
# PC 侧，仓库根目录
export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<设备密码>
python scripts/revtunnel_put.py offline/openclash/luci-app-openclash_0.47.156_all.ipk /tmp/oc_stage/
python scripts/revtunnel_put.py offline/core/mihomo-linux-arm64.gz               /tmp/oc_stage/
```

投递后**必须在设备上对账**：

```sh
md5sum /tmp/oc_stage/luci-app-openclash_0.47.156_all.ipk   # 对上 c37e00b2...
md5sum /tmp/oc_stage/mihomo-linux-arm64.gz                 # 对上 8cc282b6...
```

---

## 4. 分步骤执行

### 4.1 装 OpenClash 包

```sh
opkg install /tmp/oc_stage/luci-app-openclash_0.47.156_all.ipk
```
**期望**：零依赖报错装完（厂商 `pkg-openclash-dep` 已把 bash / curl / ip-full / ruby /
dnsmasq-full / kmod-tun 全带齐）。

- 若报 `Malformed package file` → 这是 **ar 格式 ipk**，本固件 opkg 只认老式 gzip+tar 嵌套，
  需 PC 侧重打包（见 `SKILL.md` 踩坑速查对应两行）。
- 若报出「本地 ipk 里根本没有的依赖」→ **opkg 被 feed 同名包截胡**：
  `mv /var/opkg-lists /var/opkg-lists.off` → 装 → `rm -rf /var/opkg-lists; mv /var/opkg-lists.off /var/opkg-lists`。

### 4.2 补唯一缺件

```sh
opkg install ruby-yaml
```
**期望**：从阿里云源装成功。这是厂商依赖包里**唯一**缺的一项。

### 4.3 部署内核（两条路，任选）

**路径 A —— 离线包（推荐，可控）**

```sh
mkdir -p /etc/openclash/core
gunzip -c /tmp/oc_stage/mihomo-linux-arm64.gz > /etc/openclash/core/clash_meta.new
chmod 755 /etc/openclash/core/clash_meta.new
/etc/openclash/core/clash_meta.new -v          # 自检：必须打印 Mihomo 版本与架构
mv -f /etc/openclash/core/clash_meta.new /etc/openclash/core/clash_meta
ln -sf /etc/openclash/core/clash_meta /etc/openclash/core/clash
```

> `-v` 自检是**强制关卡**：不打印版本就别 mv，先看 `gunzip` 有没有 `invalid magic`。

**路径 B —— 设备侧直下（有网时）**

```sh
cd /tmp && wget -q -T 180 -O mihomo.gz \
  https://github.com/MetaCubeX/mihomo/releases/download/v1.19.30/mihomo-linux-arm64-v1.19.30.gz
```
- ⚠️ **设备上 `curl` 拉 raw/release 会失败，同一 URL `wget` 可以**（两条不同网络栈）。
  下载函数必须 **curl 失败立刻换 wget**，再试镜像 `https://ghfast.top/...` / `https://gh-proxy.com/...`。
- 落到 `/usr/bin/mihomo` 的是**另一套内核**（clash-verge-router 用的），与 OpenClash 的
  `/etc/openclash/core/clash_meta` 互不相干，别搞混。

**已知坑：`gzip: invalid magic`（下载 100% 完成后才报）**
某些第三方"装内核"脚本写的是 `OUT="${TMP%.gz}"`，而下载临时名带 `.$$` 后缀
（`xxx.gz.30523`，不以 `.gz` 结尾）→ `%` 匹配失败 → `OUT == TMP` →
`gzip -dc 读的同时 > 截断写同一文件`。修法：
```sh
sed -i 's|OUT="${TMP%.gz}"|OUT="${TMP%.gz.*}"|' <那个脚本>   # 先备份原脚本
```

### 4.4 写 UCI 配置

最小可用集合（其余字段可用 `offline/openclash/config.openclash.template` 整份替换）：

```sh
cp -a /etc/config/openclash /etc/config/openclash.bak-$(date +%Y%m%d_%H%M%S)
uci set openclash.config.enable='1'
uci set openclash.config.en_mode='fake-ip'
uci set openclash.config.enable_redirect_dns='1'
uci set openclash.config.redirect_dns='1'
uci set openclash.config.core_type='Meta'
uci set openclash.config.core_version='linux-arm64'
uci set openclash.config.release_branch='master'
uci set openclash.config.config_path='/etc/openclash/config/<你的订阅配置>.yaml'
uci set openclash.config.dashboard_password='<面板密码>'
uci commit openclash
```

- 用模板整份替换时，**必须填掉 3 处 `<...>` 占位符**（面板密码 / 代理认证密码 / 订阅地址），
  否则面板 API 会 401、测速出网会 407。
- **订阅文件要自己准备**：`/etc/openclash/config/<name>.yaml`。没有订阅时内核仍会起来，
  但 `7890` 不会 LISTEN —— 那是**预期行为**，不是安装失败。

### 4.5 起服务

```sh
/etc/init.d/openclash enable && /etc/init.d/openclash start
```
**期望启动耗时 ~40 s**（内核 + GeoSite 10.5MB）。老 Max 在内存压力下要 2.5 分钟。

> ⚠️ **启动后 30–60 s 内防火墙规则尚未落定，此时直连 curl 也可能全 `000` —— 等它落定再测，别急着回滚。**

---

## 5. 验证判据（**这四条全过才算成功**）

```sh
# ① 进程在（注意：进程名是 clash，不是 mihomo）
pidof clash
# ② 端口在听
netstat -ltn | grep -E ':(7890|7891|7892|7893|7874|9090)\b'
# ③ 控制 API 通
curl -s -H "Authorization: Bearer <dashboard_password>" http://127.0.0.1:9090/version
# ④ 出网通（必须带代理认证，否则 407）
curl -o /dev/null -w '%{http_code}\n' -U Clash:<代理认证密码> -x http://127.0.0.1:7893 https://www.google.com
# ⑤ 节点数（有订阅时）
curl -s -H "Authorization: Bearer <dashboard_password>" http://127.0.0.1:9090/proxies | grep -o '"name"' | wc -l
```

| 期望 | 说明 |
|---|---|
| `pidof clash` 有输出 | 进程名是 `clash`，`pidof mihomo` 查不到是正常的 |
| 端口 7890/7891/7892/7893/7874/9090 全在 LISTEN | 缺 7890 通常是没有订阅/配置，不是安装失败 |
| `/version` 返回 `{"meta":true,"version":"v1.19.30"}` | 401 说明 `dashboard_password` 没对上 |
| google 返回 `200`/`204` | 407 说明没带 `-U`；`000` 先等 30–60 s 再测 |

**判活不要用 ping / TCP 握手**：fake-ip + TUN 会本地接管，`ping` 0% 丢包、
TCP 连外网 IP 0.00s 成功都可能是假象。**必须发真 HTTP/HTTPS 请求看响应码。**

---

## 6. 回滚

```sh
/etc/init.d/openclash stop
cp -a /etc/config/openclash.bak-<时间戳> /etc/config/openclash
opkg remove luci-app-openclash
rm -f /etc/openclash/core/clash_meta /etc/openclash/core/clash
```
内核是纯文件，删除即可，无副作用。UCI 备份必须保留到确认业务正常为止。

---

## 7. 已知坑速查（本任务相关）

| 症状 | 原因 | 修法 |
|---|---|---|
| `gzip: invalid magic` | 第三方脚本 `${TMP%.gz}` 自我覆盖 bug | `sed` 改成 `${TMP%.gz.*}` |
| 7893 代理测出 `407` | UCI `authentication` 生效 | curl 加 `-U Clash:<密码>` |
| 启动后 curl 全 `000` | 防火墙规则未落定 | 等 30–60 s，别回滚 |
| 装完 `7890` 不监听 | 没有订阅配置 | 正常；填订阅即可 |
| `pidof mihomo` 空但代理在跑 | 进程名是 `clash` | 用 `pidof clash` |
| opkg 报 `Malformed` | ipk 是 ar 格式 | 用 GNU/USTAR 重打包成 gzip+tar 嵌套 |
| 本地 stub ipk 报出它没有的依赖 | feed 同名包截胡 | 装前 `mv /var/opkg-lists /var/opkg-lists.off` |
| busybox `sed '/p/a\ text'` 追加行带前导空格 | GNU sed 吞空白、busybox 不吞 | 追加行顶格写 `a\text`，改完 `mihomo -t` 校验再 restart |
| 装任何新代理类服务后全网异常 | 端口撞车（B 机 OpenClash 占 7890-7893 与 9090） | 装前 `netstat -lntp` 预检；给新服务换 7897/9099 |

---

## 8. 完成后

1. `grep` 读回验证 UCI 与内核文件真的落盘
2. `free -k` 复核内存（clash VSZ 约 1.4 GB 是虚拟地址空间，看 `MemAvailable` 实际下降量）
3. 向用户报告：改了什么、备份在哪、怎么回滚

**下一步**：装自动测速插件 → [`tasks/02-ocspeed-install.md`](02-ocspeed-install.md)。
