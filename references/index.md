# references 索引（机器可读目录）

> 本页由 `SKILL.md` 的任务路由表配套使用：先按任务定位 `id`，再只读该篇，避免整包加载。
> `risk` 为 `high` 的文档在执行前必须先向用户确认。

| id | 文档 | 标题 | risk | tags |
|---|---|---|---|---|
| `REF-1panel-hostnet` | [`1panel-hostnet-default.md`](1panel-hostnet-default.md) | 1Panel 应用「默认 host 网络」方案（C2000 U / 无 veth 内核） | high | 1panel, docker, compose, host-network, no-veth, wrapper |
| `REF-adguard` | [`adguard-setup.md`](adguard-setup.md) | AdGuard Home：部署、全网接管、国内去广告规则 | high | dns, adguard, adblock, dnsmasq, port-move |
| `REF-c2000u-1panel` | [`c2000u-1panel.md`](c2000u-1panel.md) | C2000 U（B 机）· Docker + 1Panel 实装档案（2026-09-13） | low | 1panel, install, archive, c2000u |
| `REF-c2000u-docker` | [`c2000u-docker.md`](c2000u-docker.md) | 第二台设备：鲲鹏 C2000 U（C2000-798 / WT9500）Docker 适配与实装 | high | docker, install, opkg, stub-ipk, c2000u |
| `REF-c2000u-media` | [`c2000u-media.md`](c2000u-media.md) | C2000 U（B 机）· NAS 影视墙容器实测档案（2026-09-14） | low | docker, media, alist, navidrome, archive |
| `REF-c2000u-openclash` | [`c2000u-openclash.md`](c2000u-openclash.md) | C2000 U · OpenClash + ocspeed 部署实录（2026-09-11） | medium | openclash, clash, mihomo, core, tproxy, ocspeed |
| `REF-docker-deploy` | [`docker-deploy.md`](docker-deploy.md) | Docker 面板部署 playbook | medium | docker, panel, luci, deploy |
| `REF-docker-panel` | [`docker-panel.md`](docker-panel.md) | Docker 面板（自建 LuCI 集成）· 完整记录 | medium | docker, panel, luci, unix-socket, archive |
| `REF-docker-porting` | [`docker-porting.md`](docker-porting.md) | Docker 移植（缺 kmod 的官方固件） | medium | docker, porting, kmod, stub-ipk |
| `REF-dsh-export` | [`dsh-export.md`](dsh-export.md) | 把 WorkBuddy 技能导出成 DeepSeek Harness (DSH) 技能 | low | dsh, deepseek-harness, skill-export |
| `REF-istore` | [`istore-integration.md`](istore-integration.md) | iStore 商店 / 1Panel 集成（鲲鹏 C2000 Max 实测） | medium | istore, 1panel, ipk, luci |
| `REF-kpwebui` | [`kpwebui.md`](kpwebui.md) | kp-webui —— 鲲鹏 C2000 U 的 iStoreOS 风格独立控制台（v2） | medium | kpwebui, uhttpd, cgi, luci |
| `REF-maye` | [`maye-assistant.md`](maye-assistant.md) | maye 插件安装助手兼容性（nradio.mayebano.shop） | high | maye, third-party, plugin-installer, snapshot |
| `REF-nas` | [`nas-upgrade.md`](nas-upgrade.md) | NAS 升级路线（C2000 Max） | medium | nas, mount, ksmbd, aria2, minidlna |
| `REF-no-ssh-recovery` | [`no-ssh-recovery.md`](no-ssh-recovery.md) | 无 SSH 时的取数与命令通道（LuCI 旁路） | medium | rescue, luci, dmesg, crontab, reboot |
| `REF-nr-webui-reverse` | [`nr-webui-reverse.md`](nr-webui-reverse.md) | nr_webui 解析与还原手册 | high | nr_webui, reverse, ota, portal-hijack, restore |
| `REF-nr-webui-service` | [`nr-webui-service.md`](nr-webui-service.md) | nr_webui 第三方 WebUI 服务（:10086）档案 | medium | nr_webui, service, port-10086 |
| `REF-one-command-restore` | [`one-command-restore.md`](one-command-restore.md) | 一条命令恢复（nros-panel） | high | restore, nros-panel, partition, overlay, reboot |
| `REF-pc-toolchain` | [`pc-toolchain-limits.md`](pc-toolchain-limits.md) | 本机（PC 侧）工具链限制与绕行方案 | low | pc-side, toolchain, powershell, encoding, sandbox |
| `REF-portainer-i18n` | [`portainer-i18n.md`](portainer-i18n.md) | Portainer CE 汉化（鲲鹏 C2000 Max 实测） | low | portainer, i18n, zh-cn, static-js |
| `REF-script-ui` | [`script-ui.md`](script-ui.md) | 路由器运维脚本的终端界面（kp-ui.sh） | low | scripting, busybox, printf, ui |
| `REF-store-patching` | [`store-patching.md`](store-patching.md) | 在线应用商店增强 | medium | store, appcenter, installed-list, patch |
| `REF-tf-resize` | [`tf-partition-resize.md`](tf-partition-resize.md) | TF 卡分区扩容（系统分区装不开时） | high | partition, resize, f2fs, nor-window, tf-card |
