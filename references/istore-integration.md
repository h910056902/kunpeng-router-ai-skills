---
id: REF-istore
title: "iStore 商店 / 1Panel 集成（鲲鹏 C2000 Max 实测）"
tags: [istore, 1panel, ipk, luci]
risk: medium
preconditions:
  - "iStore ipk 已下载（手动解包安装）"
  - "与鲲鹏商店并存"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# iStore 商店 / 1Panel 集成（鲲鹏 C2000 Max 实测）

## 一、结论速览

| 目标 | 结论 |
|---|---|
| iStore 商店框架（luci-app-store） | ✅ **可装可用**，与鲲鹏商店（appcenter）并存不冲突，入口 `/cgi-bin/luci/admin/store` |
| iStore 里的 1Panel（luci-app-istorepanel） | ❌ **取不到包**——iStore 应用走 `is-opkg` 私有元数据，不在公开 opkg 源；GitHub releases 也无 ipk |
| 1Panel 原生安装脚本 | ❌ 不支持 OpenWrt（依赖 systemd） |
| 1Panel 本体（Go 静态二进制 arm64） | ⚠️ 理论可手动跑（无 systemd 需自己托管进程），内存 ~150MB+，未验证 |

## 二、iStore 框架安装步骤

### 1. 源与包位置（2026-09 实测）

```
框架（all 架构）: https://istore.istoreos.com/repo/all/store
应用（本架构）:   https://istore.istoreos.com/repo/aarch64_cortex-a53/nas   （61 个包，全是后台服务类，无 luci-app-*）
安装脚本:        https://github.com/linkease/openwrt-app-actions/raw/main/applications/luci-app-systools/root/usr/share/systools/istore-reinstall.run
```
- 旧的安装脚本地址（istore.linkease.com/downloads/*.sh）已全部 404
- github.com 直连常失败 → 前面加 `https://gh-proxy.com/` 前缀

### 2. 依赖

iStore 文档说 OpenWrt 21 需要 `luci-compat` —— **本机绝对不能装**（见 SKILL.md 禁令）。
实际只需补：
```sh
# script-utils / mount-utils 从 21.02.7 正式版 base 源取（SNAPSHOT 源早已失效）
B=https://downloads.openwrt.org/releases/21.02.7/packages/aarch64_cortex-a53/base
curl -O $B/script-utils_2.36.1-2_aarch64_cortex-a53.ipk
curl -O $B/mount-utils_2.36.1-2_aarch64_cortex-a53.ipk
# tar 是 busybox 内置，可跳过
```

### 3. opkg 装不上时的手动解包法（本机必用）

busybox opkg 报 `incompatible with the architectures configured`，且**没有 `--force-architecture`**。
ipk 本质是三个 tar 包，手动解即可：

```sh
cd /tmp/istore-ipk
for f in luci-app-store_0.2.1-r1_all.ipk luci-lib-taskd_1.0.26_all.ipk \
         luci-lib-xterm_4.18.0_all.ipk taskd_1.0.3-2_all.ipk; do
  curl -sL -O https://istore.istoreos.com/repo/all/store/$f
done
rm -rf /tmp/ipk_x && mkdir /tmp/ipk_x && cd /tmp/ipk_x
tar xzf /tmp/istore-ipk/luci-app-store_0.2.1-r1_all.ipk   # 得到 control.tar.gz / data.tar.gz / debian-binary
tar xzf data.tar.gz -C /                                   # 直接解到根
```
注意：手动解包不会写 opkg status，后续卸载需手动删文件。

### 4. 验证

```sh
rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache
/etc/init.d/uhttpd restart; sleep 6
# 带 cookie 请求，200 即成功（不带 cookie 会 302/403）
```

## 三、⛑️ 事故还原：旧 luci-compat 打挂 LuCI 后的修复

**现象**：所有 LuCI 页面 502 `Bad Gateway`，SSH 正常、网络正常。

**原因链**：新 LuCI 把 cbi 相关文件放进 luci-compat → 旧包装入覆盖 → 回滚卸载时把这些文件删掉 → `require "luci.cbi"` 失败 → dispatcher 崩溃。

**修复（从 /rom 只补不覆盖）**：

```sh
cd /rom/usr/lib/lua/luci && find . -type f | while read f; do
  if [ ! -f "/usr/lib/lua/luci/$f" ]; then
    mkdir -p "/usr/lib/lua/luci/$(dirname $f)"
    cp "/rom/usr/lib/lua/luci/$f" "/usr/lib/lua/luci/$f"
    echo "补回: $f"
  fi
done
rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache
/etc/init.d/uhttpd restart
```
实测补回 40 个文件后 system/appcenter/openclash 全部恢复 200。

**诊断手法**（比看页面有用得多）：
```sh
cd /www && REQUEST_URI='/cgi-bin/luci/admin/system' lua /www/cgi-bin/luci 2>&1 | head -15
```

## 四、1Panel 相关事实

- `luci-app-istorepanel` 的 Makefile 明确写着 `LUCI_TITLE:=LuCI support for 1Panel`，依赖 `+lsblk +zoneinfo-asia +docker +luci-lib-taskd +luci-lib-docker` → 证明 **1Panel 有 OpenWrt 适配版，本体是 Go 静态二进制（musl 可跑）**
- 但包本身只在 iStoreOS 固件的私有通道分发，公开源拿不到
- 若坚持要装：可自行下载 `1panel-v*-linux-arm64.tar.gz`，手动跑 core 二进制（监听 :10086），需自己写 init.d 托管进程、处理 1pctl 对 systemd 的依赖
- 内存预算：1Panel 空载 ~150MB，本机可用常年 30~90MB + 1G swap，装上后基本告别其他容器
  （**2026-09-11 起 1Panel v1.10.34-lts 已原生装成，端口 10090**，见 `c2000u-1panel.md`）

## 五、2026-09-16 补测（C2000 U）：三个决定性约束

给「iStoreOS 风格化」立项前**必须先确认这三条**，否则会白做：

### 5.1 本机 LuCI 是「经典菜单」，没有 menu.d —— 装上也不出菜单

```sh
ls /usr/share/luci/            # 空 / 目录不存在
ls /usr/share/luci/menu.d      # MISSING
grep -c 'menu\.d' /usr/lib/lua/luci/dispatcher.lua   # → 0
```

厂商与所有可用插件都走**经典 `entry()`**：
`entry({"nradioadv","network","access"}, template("nradio_access/index"), _("AccessTile"), 80, true)`

→ 按 `menu.d/*.json` 注册的现代插件（`luci-app-quickstart`、部分 `luci-app-filetransfer`）
**页面能开但侧边栏不出现**，属最难排查的一类故障。
**对策**：给插件补**经典 controller 垫片**（样板见 `unm_luci_shim/controller.lua`）。

### 5.2 feed 里没有 luci 源 —— luci-* 包一概不能用 opkg 装

distfeeds 只有 `base / packages / routing` 三个。`opkg list` 里
`luci-theme-argon` / `luci-app-quickstart` / `luci-app-store` / `luci-compat` /
`luci-lua-runtime` / `luci-lib-ipkg` **全部为 0**。
官方 luci 源（`.../packages/aarch64_cortex-a53/luci/Packages.gz`）**可达（200）但绝不能加**
—— 那一代是 git-22，与本机 `luci-base git-26.253` 冲突，会打挂 LuCI。

→ 所有 luci 系包只能从**第三方 IPK** 手动装（`wukongdaily/gl-inet-onescript` 的 `theme/` 与
`luci-app-filetransfer/` 目录，实测 URL 均 200）。下载必须 **curl + wget 双栈**。

### 5.3 私源域名：linkease 已死，改用 istoreos

```sh
https://istore.linkease.com/repo/all/store/Packages.gz    # → 000（已死）
https://istore.istoreos.com/repo/all/store/Packages.gz    # → 200（luci-app-store 0.2.1-r1
                                                          #      taskd 1.0.3-2 / luci-lib-taskd 1.0.26
                                                          #      luci-lib-xterm 4.18.0）
https://istore.istoreos.com/repo/aarch64_cortex-a53/nas   # → 60+ 包（alist/ddns-go/cups…）
```

**上游 `gl-inet.sh` 写的是 linkease 域名 —— 照抄必然失败**，必须替换。

### 5.4 ⚠️ 全局切 Argon 主题会毁掉厂商页面（换肤要「换肤不换骨架」）

`luci.main.mediaurlbase` 是**全局唯一**的。切成 `/luci-static/argon` 后，主题自己的
`header.htm` 只加载 Argon 的 CSS，**不再加载** `nradio.min.css` / `bootstrap-dialog.min.css`
/ `cascade.min.css` —— 而厂商 50+ 个 `nradio_adv` 页面（CPE 状态 / 短信 / APN / 锁频 / 风扇）
全部照这些类名写 → **破相甚至不可用**。

**推荐做法（风险低、可秒回滚）**：

```sh
cp -r /www/luci-static/nradio /www/luci-static/istoreos
# 在副本上只覆盖主色 / 卡片圆角 / 阴影 / 间距，保留原有全部 CSS 与类名
uci set luci.main.mediaurlbase='/luci-static/istoreos'; uci commit luci
rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache; /etc/init.d/uhttpd restart
# 回滚
uci set luci.main.mediaurlbase='/luci-static/nradio'; uci commit luci
```

副本里 `images/` 一并复制；厂商页面里写死的 `/luci-static/nradio/...` **绝对路径仍指向原目录**
（原目录未删），所以是**双向安全**的。

### 5.5 基线体检（立项前跑一遍）

| 检查 | 期望 |
|---|---|
| `ls /usr/lib/lua/luci/cbi.lua` | 存在（本机 42.7KB）→ **不要装 luci-compat** |
| `ls -d /www/luci-static/*` | 只有 `nradio` + `resources` = 未风格化 |
| `uci get luci.main.mediaurlbase` | `/luci-static/nradio` |
| `opkg list-installed \| grep -E 'store|quickstart|argon|ttyd\|filetransfer'` | 空 = 全未装 |
| `opkg list \| grep -c '^luci-'` | 只含已装的 `nradio-*`；**不代表 feed 有 luci 源** |
| `free -m` / `df -h /overlay` | 本机 992MB / 16G，充裕 |
