---
id: REF-maye
title: "maye 插件安装助手兼容性（nradio.mayebano.shop）"
tags: [maye, third-party, plugin-installer, snapshot]
risk: high
preconditions:
  - "改前先 snapshot"
  - "严禁在其菜单装 AGH/mosdns（端口与 Docker AGH 冲突）"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# maye 插件安装助手兼容性（nradio.mayebano.shop）

社区脚本「NRadio 官方系统插件安装助手」（作者 maye，V3.0.7 / 2026-09-07），
7 万行 sh 菜单式工具，支持机型含 NRadio_C2000MAX。本机已跑过 V2.9.9（2026-08-22，
装过哈基米插件，htm 内有 Design By MaYe 标记）。**与我们的商店补丁可共存**。

## 它改什么（legacy_appcenter 模式，即 C2000MAX 当前画像）

- appcenter.htm：加卸载按钮入口、图标缓存刷新、MaYe 产权标识（增量）
- appcenter.lua：awk 插入 sys_status entry + 追加 sys-status Lua 块、runtime compat 包装（增量）
- C2000Pro/AK798 画像才是整文件替换（compat layer），我们不受影响
- 自带备份到 `/root/nradio-plugin-fix/`；状态目录 `/root/.nradio-plugin-menu/`
- 它有自己的插件清单/卸载体系（`nradio_plugin_uninstall_action` + `plugin_uninstall/start` 异步端点），与我们的 `installed.list`/`nradio_appcenter_extra_action` 是**并行的两套**

## 冲突风险点

| 风险 | 说明 | 对策 |
|---|---|---|
| 它升级时重写 controller/htm | 增量补丁可能被覆盖或顺序错乱 | 跑完立刻用 `adapt_maye_assistant.py check` 检测 |
| 它的 AdGuardHome/mosdns 插件 | native 版，DNS 端口 554/553 + uci 配置，与我们的 Docker AGH(:53) 全网接管冲突 | **不要在它菜单里装 AGH/mosdns**，去广告用我们现成的 |
| 哈基米等插件 | 已装过，PASS，无冲突 | 正常 |

## 标准操作流程

```
1. python adapt_maye_assistant.py snapshot   # 跑 maye 之前（已有基线可跳过）
2. 用户在路由器上跑: cd /tmp && wget -O ssh-nradio-plugin-installer.sh \
     https://nradio.mayebano.shop/ssh-nradio-plugin-installer.sh && sh ssh-nradio-plugin-installer.sh
3. python adapt_maye_assistant.py check        # 检测 6 个补丁指纹
4. 有丢失 → python adapt_maye_assistant.py check --fix   # 自动重放对应 patches 脚本
5. 复核: 再跑一次 check; 清缓存 rm -rf /tmp/luci-indexcache*（重放脚本会自己清）
```

## 补丁指纹清单（adapt_maye_assistant.py 的 MARKERS）

- appcenter.lua：extra_installed_merge / extra_action / _kp_installed_registry /
  _online_install_percent / `&& kp-store-register`
- appcenter.htm：aurora_open_app

基线存储：本地 `patches/maye-baseline.json` + 路由器 `/etc/kp_store/patch-baseline.json`
（首次快照 2026-09-08：全部指纹在位；当时 maye 助手已存在但未升级 V3）
