---
id: REF-store-patching
title: "在线应用商店增强"
tags: [store, appcenter, installed-list, patch]
risk: medium
preconditions:
  - "改 Lua/htm 前必备份"
  - "改完清 LuCI 缓存"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# 在线应用商店增强

官方鲲鹏商店（appcenter）被扩展为：3 个在线源聚合（iStore/Are-u-ok/opkg，147 个应用）+ 安装百分比 + 自维护「已安装注册表」（支持 opkg/areuok/docker 三种来源）+ 卡片外链一键打开。

## 核心机制

### 后端 appcenter.lua
- 合并链（action_app_list_data 尾部）：
  `version_sync(local_apps_merge(online_installed_merge(extra_installed_merge(areuok_installed_merge(runtime_compat_v2(...))))))`
- `_kp_installed_registry()`：读 /etc/kp_store/installed.list 每行 `|` 分隔 8 字段
  `id|名称|pkg|版本|安装时间|route|source|简介`
- `nradio_appcenter_extra_installed_merge()`：把注册表条目合并进 applist。
  合并条件 `(inst[pkg] or src == "docker")` —— opkg 来源要求包确实已装，docker 来源直接放行
  `has_luci = (#route_n > 0) and 1 or 0`
- `nradio_appcenter_extra_action(name, action)`：卸载分发，按 source 字段路由到
  areuok → `kp-areuok uninstall <id>`；opkg → `is-opkg remove <pkg>`；docker → `docker rm -f <容器名>`；卸载后 `kp-store-unregister <pkg>`
- `_online_install_percent()`：安装进度百分比。解析安装日志阶段加权：
  Downloading 每包 +6%（上限 60）/ Installing 72 / Configuring 每包 +2%（上限 96），
  外加时间兜底 `min(95, 5 + elapsed/4)`；`online_install_status` 返回 `percent` 字段

### 注册/注销脚本
- `/usr/bin/kp-store-register <pkg>`：从 /etc/kp_store/plugins.json 清单取元数据 +
  从 /usr/lib/opkg/status 取实际版本，写入 installed.list（去重后追加）
- `/usr/bin/kp-store-unregister <pkg>`：按 pkg 字段移除行
- 安装命令尾部追加：`is-opkg install <pkg> && kp-store-register <pkg>`

### 前端 appcenter.htm
- 来源筛选、搜索
- `aurora_open_app` 助手：`route` 以 `http` 开头 → `window.open` 新窗口打开管理页；
  否则走原 callback。这就是 Docker 容器（无 LuCI 页）能从商店一键打开 AGH :3000 的原理

## 踩坑
- 注册表 route 为空 → has_luci=0 → 不渲染打开按钮。Docker 容器条目直接填完整 URL
- 卸载分发插入点必须判断「调用点」文本而非函数定义，否则误判已打过补丁
- 改 installed.list 字段时注意 split('|') 后 pkg 是 f[2]、版本是 f[3]

---

## ⭐ 数据源真相：是 ubus，不是文件（2026-09-11 C2000 U 实测）

这一点决定了补丁怎么写：

```sh
ubus call appcenter list
# → {"name":"appcenter","parameter":{"status":0,"appstore_code":5,
#     "md5":"4d65da34829c76b2ce3553387e82a4de","applist":[ ... ]}}
```

- 数据来自 **ubus 服务 `appcenter`**（背后是 C 程序 `/usr/sbin/appcenter`，66267 B）
- 它的配置在 **`/etc/config/appcenter` —— 标准 UCI**：
  ```
  config package        → name 'FileBrowser' / '鲲鹏智能体' / 'VPN' / 'UU加速器'
  config package_list   → url 'https://www.appstore.vapyun.com/nradio-appstore/aarch64_cortex-a53/<应用>/<版本>/<包>.ipk'
  ```
  → 商店的「在线应用」= **厂商自己的 vapyun.com 源**，跟 iStore / Are-u-ok 无关
- **原版 `action_app_list_data()` 只做 i18n 翻译后 `return applist.parameter`，没有任何 merge**
  （`nradio_appcenter_.*_merge` 计数 = 0）
- → 要接 iStore / Are-u-ok，**只能在 Lua 层做聚合**（C 程序不认第三方源）
- → 但 UCI 可读可写，**"直接往 `/etc/config/appcenter` 塞 `config package` 条目"是一条未验证的短路径**
  （需先读 `/usr/sbin/appcenter` 的字符串确认它如何加载 UCI、是否校验 md5/timestamp）

### 原版补丁锚点（B 机 `appcenter.lua` 474 行原版上确认存在）

| 锚点 | 位置 | 可挂什么 |
|---|---|---|
| `function action_app_list_data()` … 末尾 `return applist.parameter` | 第 31 行起 | 包一层 merge：`return extra_merge(applist.parameter)` |
| `function action_app_core(name,action)` | 第 188 行 | 卸载/打开分发 |
| `function action_app_uninstall()` | 第 230 行 | 同上 |
| `function action_app_open()` | 第 236 行 | 同上 |

> 原版函数全表（20 个）：index / action_app_list_data / action_app_list / get_overlay_free_memory /
> get_app_required_bytes / action_app_core / action_app_install / action_app_uninstall / action_app_open /
> action_app_close / action_app_update / action_appstore / action_app_check / action_appstore_check /
> check_size / file_deal / fork_exec / action_import_status / action_import / action_get_memory

## 已有补丁脚本的位置（PC 侧，别从零写）

`C:\Users\91005\Desktop\鲲鹏无限路由器美化\patches\`（**kunpeng-istoreos** 项目，与技能包仓库不同）：

执行顺序（README 记载，A 机实测通过）：

```bash
python patch_extra_plugins.py      # 部署 /etc/kp_store/plugins.json + 后端合并 + 安装分发
python patch_extra_installed.py    # 装完自动进「已安装」+ 商店内卸载
python patch_online_ui.py          # 前端来源筛选与徽章
python patch_install_percent.py    # 安装进度百分比
```

基础层：`fix_install_backend.py` → `patch_backend_tags.py` → `build_depcache.py` → `patch_list_depcache.py`
→ `patch_register.py` → `patch_ver_fix.py`。

**两个必知前提**：
1. **`fix_install_backend.py` 依赖一段更早的「iStore 在线集成」Lua**（它断言 `function action_online_install()`
   已存在，并找 `-- ========= /iStore online install integration =========` 结束锚点）。
   这段 **PC 侧无存档**（`kunpeng-istore.sh` 完全不碰 appcenter.lua）→ 新设备上要跑这条链，必须先重建这层。
2. **所有这些脚本用的是 `c.open_sftp()`**，而固件**没有 sftp-server** → 必须改用 `scripts/rtr_lib.py`。

