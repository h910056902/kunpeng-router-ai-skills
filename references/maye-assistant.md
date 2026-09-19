---
id: REF-maye
title: "maye 插件安装助手兼容性（nradio.mayebano.shop）"
tags: [maye, third-party, plugin-installer, snapshot]
risk: high
preconditions:
  - "🔴 它不产生任何备份，跑前必须自己备份目标文件"
  - "🔴 严禁在其菜单选「卸载 Docker」"
  - "🔴 严禁在其菜单装 AGH/mosdns（端口与 Docker AGH 冲突）"
  - "改前先 snapshot"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# maye 插件安装助手兼容性（nradio.mayebano.shop）

社区脚本「NRadio 官方系统插件安装助手」（作者 maye），**V3.2.0 / 2026-09-14**，
约 7 万行 sh 菜单式工具。上游 <https://github.com/561410590/ssh-nradio-plugin-installer>
（镜像页 <https://nradio.mayebano.shop/>）。**与我们的商店补丁可共存**。

完整操作流程见 [`tasks/05-nros-plugin-installer.md`](../tasks/05-nros-plugin-installer.md)。

## 三条红线（2026-09-19 实测）

1. **它不产生任何备份。** 脚本第 19 行有 `BACKUP_DIR="/root/nradio-plugin-fix"`，
   但 `backup_file()`（第 2575-2578 行、第 54767-54769 行）是**空实现**，函数体只有 `return 0`，
   注释写「…不在路由器上生成持久备份」。全脚本 100+ 处 `backup_file "..."` 全是空操作，
   没有任何 `mkdir`/`cp` 落到 `$BACKUP_DIR`。真机实测该目录**不存在**。
   → 想回滚只能靠自己跑前备份。（**旧版档案写「自带备份到 `/root/nradio-plugin-fix/`」是错的。**）

2. **别选「卸载 Docker」**（第 4512-4530 行）。它 `rm -f /etc/config/dockerd` 并
   `rm -rf /etc/docker /usr/libexec/docker $DOCKER_ROOT`。本机 `/etc/config/dockerd`（304 B）
   是 Docker `data_root` 与镜像加速源的**唯一载体**（`data_root '/mnt/storage/data/docker'` +
   2 条 `registry_mirrors`），删掉 = 1Panel 的 Docker 环境连带数据一起报废。

3. **别装 AdGuardHome / mosdns**。它给的是 native 版（DNS 端口 554/553 + uci 配置），
   与本机 Docker AGH（`:53` 全网接管）冲突。去广告用我们现成的方案。

额外：**奇游 / 雷神走明文 HTTP 下载后直接 root 执行**
（第 97 行 `http://sd.qiyou.cn`、第 106 行 `http://119.3.40.126/...`），
下载后只做 `grep` 内容检查与 `sh -n` 语法检查，**无校验和/签名**，然后 `sh` 执行 —— 等于远程代码执行面。

## 环境门禁：本机全 PASS（2026-09-19 逐关卡实测）

| 门禁 | 本机结果 |
|---|---|
| 机型归一化 | `HC-WT9500` → `NRadio_C2000Ultra`（第 1209-1210 行） |
| 版本受支持 | `2.3.0.n0.c1` 匹配 `2.*` → PASS（`is_supported_nros_revision` 第 1224-1240 行） |
| SD 卡前置 | `/tmp/storage/mmcblk0p1`，可用 15438 MiB → PASS |
| 商店环境 | profile = `legacy_appcenter`，三路径齐全 → PASS |

⚠️ **最容易误判的坑**：版本判据读的是 `ubus call system board` 的 `release.revision`，
**不是** `/etc/openwrt_release` 的 `DISTRIB_RELEASE`。
本机 `DISTRIB_RELEASE='21.02-SNAPSHOT'`（看着不匹配 `2.*`），但脚本第一优先级读
`ubus` 的 `"revision": "2.3.0.n0.c1"` → 匹配 `2.*` → 放行。

⚠️ **门禁触发时机**：主菜单选分类 `1/2/3/4` 才检查（第 72416 行），
选分类 `5`（设备维护与检测）不检查；`run_menu_feature` 里 feature `33|34` 豁免（第 69922 行）。

## 可用性实测：真终端已跑通（2026-09-19 晚）

PTY 真终端按**正确用法**（**不带参数**）完整走通：
免责声明 → 主菜单 → `1)` 常用插件子菜单 → 返回 → `0` 退出。
菜单顶部是**脚本自己打印**的 `设备 NRadio_C2000Ultra` / `系统 NROS 2.3.0.n0.c1`（与我方探针结论一致）；
选 `1` 时打印 `环境检测: 已检测到 NRadio 应用商店`。
跑后 `pidof clash`（16659）、`/etc/config/dockerd`、`appcenter.lua` / `appcenter.htm`、`distfeeds.conf`
的 sha256 **全部与跑前一致**；`/etc/config`、`/usr/lib/lua/luci`、`/etc/kp_store` 零改动。

⚠️ **运行命令不能带参数**：上游 README 的写法是 `sh ssh-nradio-plugin-installer.sh`。
带仓库 URL 会被当作菜单编号 → `ERROR: 无效编号：https://…` → 退出。合法位置参数只有 `0`~`5`。

⚠️ **状态目录**：`/root/.nradio-plugin-menu/`，内含
`disclaimer_accepted_20260615-v260-model-disclaimer-c2000pro-risk-v1.flag`（27 B，`accepted V3.2.0 2026-09-14`）。
同意一次后不再询问；删掉它下次会重新问。**它不是备份**（见红线 1）。

⚠️ **stdin 三种行为**：`< /dev/null` → `die "input cancelled"`；`exec_command` 不喂不关 → **永久挂住**；
管道喂够 `y`+编号 → 能跑通（rc=0）。**技术可自动化，但流程上必须人工选菜单项**。

## 它改什么（legacy_appcenter 模式，即本机当前画像）

- appcenter.htm：加卸载按钮入口、图标缓存刷新、MaYe 产权标识（增量）
- appcenter.lua：awk 插入 sys_status entry + 追加 sys-status Lua 块、runtime compat 包装（增量）
- C2000Pro/AK798 画像才是整文件替换（compat layer），我们不受影响
- 状态目录 `/root/.nradio-plugin-menu/`（只存免责声明 flag 与菜单偏好，**不是备份**）
- 它有自己的插件清单/卸载体系（`nradio_plugin_uninstall_action` + `plugin_uninstall/start` 异步端点），
  与我们的 `installed.list`/`nradio_appcenter_extra_action` 是**并行的两套**
- `/etc/opkg/distfeeds.conf`：**有守卫**（第 5699-5703 行，遇到规范 `src/gz + http(s)` 源即
  「保留当前固件源」），本机实测**不会被重写**

## 冲突风险点

| 风险 | 说明 | 对策 |
|---|---|---|
| 它升级时重写 controller/htm | 增量补丁可能被覆盖或顺序错乱 | 跑完立刻用 `adapt_maye_assistant.py check` 检测 |
| 它的 AdGuardHome/mosdns 插件 | native 版，DNS 端口 554/553 + uci 配置，与我们的 Docker AGH(:53) 全网接管冲突 | **不要在它菜单里装 AGH/mosdns** |
| 它的 Docker 卸载分支 | `rm -f /etc/config/dockerd` + `rm -rf` Docker 全套 + `cleanup_appcenter_entry` | **不要在它菜单里选卸载 Docker** |
| 奇游/雷神 | 明文 HTTP 下载 + 直接 root 执行，无校验和 | 不要在它菜单里装；要用就自己下、先核对 |
| 它不备份 | 任何改动都无回滚依据 | 跑前自行备份，见 playbook §4① |
| 哈基米等插件 | 与我们的补丁无冲突 | 正常 |

## 标准操作流程

```
0. 🔴 自行备份它可能改到的文件（它自己不备份）
1. python scripts/adapt_maye_assistant.py snapshot   # 跑 maye 之前（已有基线可跳过）
2. 用户在路由器上跑:
     cd /tmp && wget -O ssh-nradio-plugin-installer.sh \
       https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/refs/heads/main/00-current/ssh-nradio-plugin-installer.sh
     sha256sum ssh-nradio-plugin-installer.sh   # 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8
     sh -n ssh-nradio-plugin-installer.sh && sh ssh-nradio-plugin-installer.sh
3. python scripts/adapt_maye_assistant.py check        # 检测 6 个补丁指纹
4. 有丢失 → python scripts/adapt_maye_assistant.py check --fix   # 自动重放对应 patches 脚本
5. 复核: 再跑一次 check; 清缓存 rm -rf /tmp/luci-indexcache*（重放脚本会自己清）
```

> 旧版的下载地址 `https://nradio.mayebano.shop/ssh-nradio-plugin-installer.sh` 已不作为首选 ——
> 实测可用且带完整性对账的是上面的 `ghproxy.vip` 链（配上游 `CHECKSUMS.txt` 校验 sha256）。

## 补丁指纹清单（adapt_maye_assistant.py 的 MARKERS）

- appcenter.lua：extra_installed_merge / extra_action / _kp_installed_registry /
  _online_install_percent / `&& kp-store-register`
- appcenter.htm：aurora_open_app

基线存储：本地 `maye-baseline.json`（与适配器脚本同目录）+ 路由器 `/etc/kp_store/patch-baseline.json`。

> 基线现状（2026-09-19 实测）：本地基线文件与路由器 `/etc/kp_store/patch-baseline.json`
> **均不存在**，`/etc/kp_store/` 里只有 `routes.list`；appcenter 三个 marker 全为 0 ——
> 即**本机还没跑过我们的商店补丁**，当前无冲突面。（档案旧版记的「已在 C2000 Max 上跑过 V2.9.9」
> 指的是**已下线的另一台机器**；这台 C2000 U 上 `/root/.nradio-plugin-menu/` 与
> `/root/nradio-plugin-fix/` 均不存在，appcenter.htm 的 `Design By MaYe` 计数为 0，**从未跑过**。）
