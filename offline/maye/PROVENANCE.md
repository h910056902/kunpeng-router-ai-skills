# maye 助手精简版（maye-lite）· 来源与裁剪说明

本目录存放一份**第三方脚本的裁剪衍生版**及其可复现的裁剪工具链。
**它不是上游原版**，请勿与原版混用或互相校验哈希。

产物：`ssh-nradio-plugin-installer-lite.sh`

---

## 1. 上游与原版

| 项 | 值 |
|---|---|
| 上游项目 | <https://github.com/561410590/ssh-nradio-plugin-installer> |
| 原版版本 | `V3.2.0`（脚本内 `SCRIPT_RELEASE_DATE="2026-09-14"`） |
| 原版定点 | commit **`2daa69d8b4`**（唯一可取回 V3.2.0 的提交） |
| 原版体积 | 2,878,882 字节 / 72,458 行 / 1,255 处 `name() {`（其中 803 个是**顶层**定义，其余在内嵌 heredoc 里） |
| 原版哈希 | `sha256 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8` |
| 官方背书 | 与上游**仓库根目录** `CHECKSUMS.txt` 登记值一致（该文件抬头至今仍是 `# NRadio V3.2.0 release checksums`） |
| 作者 | maye |

**为什么必须定点 commit**：上游 `00-current/ssh-nradio-plugin-installer.sh` 是**滚动更新的单文件**，
同一条 URL 在 2026-09-24 已返回 V3.2.1（2,893,017 B / `67e57576…84403`），而 V3.2.1
**既无官方哈希、也无 CHANGELOG 条目**，属未登记版本。详见
[`references/maye-assistant.md`](../../references/maye-assistant.md) 的版本漂移一节。

## 2. 本版产物

| 项 | 值 |
|---|---|
| 文件 | `ssh-nradio-plugin-installer-lite.sh` |
| 体积 | 2,388,837 字节 / 60,590 行（原 −17.1%） |
| 函数 | 663 个顶层函数（原 803，删 140） |
| 哈希 | 见 [`SHA256SUMS`](SHA256SUMS) |
| 生成日期 | 2026-09-24 |
| 生成工具 | [`scripts/maye_trim/trim_maye.py`](../../scripts/maye_trim/trim_maye.py) |
| 配套工具 | [`scripts/maye_trim/reach.py`](../../scripts/maye_trim/reach.py) —— 静态调用闭包 + 写盘扫描，用来判定某个 handler 是否「只读」（真机冒烟靶子的筛选依据） |

> **验证状态（2026-09-24）**：语法（PC+设备）、0 悬挂引用、feature ID 一致性、
> **真机菜单走查**、**真机只读 handler 端到端**（统一体检增强版 25 段全跑通）、
> **真机安装类 handler 端到端**（`ttyd / Web SSH` 5 阶段全过、落地并监听 7681）、
> **副作用经 `-nt` 法实测**（只读操作 0 文件净变动；安装操作实测改动 19 文件 + 19 目录，
> 清单见 §7.1 ④）均已通过 —— 详见 §7 / §7.1。
> **未验证**：其余安装项未逐个真跑（只抽验了 ttyd 一项，见 §9 第 1 条）。

## 3. 裁剪目标：去掉"会动这台设备"的能力

本仓库对 maye 助手的红线（见 `AGENTS.md` §8.6 / `references/maye-assistant.md`）针对的是
**与现有 OpenClash 透明代理 + 1Panel/Docker 环境冲突或不可回滚**的功能。裁剪即按这张表执行。

### 3.1 按 feature ID 禁选（`run_menu_feature` 分派表）

| ID | 处理函数 | 行数 | 原因 |
|---|---|---|---|
| 2 | `install_openclash` | 160 | 「哈基米」= OpenClash 的显示名（`OPENCLASH_DISPLAY_NAME`）；禁止 maye 重装我们在管的 OpenClash |
| 4 | `install_adguardhome` | 125 | AGH 抢 554/553 DNS 端口，与 OpenClash DNS 链冲突 |
| 9 | `configure_openvpn_runtime` | 530 | 改运行时网络 |
| 10 | `configure_openvpn_routes` | 446 | 改路由表，可能夺走默认路由 |
| 11 | `configure_easytier_routes` | 122 | 同上 |
| 16 | `restore_appcenter_original` | 26 | 「还原应用商店」会抹掉本仓库的商店补丁 |
| 17 | `install_mosdns` | 243 | 与 AGH 同类的 DNS 抢占 |
| 19 | `run_hakimi_easy_rule_helper` | 88 | 「哈基米傻瓜分流助手」会改 OpenClash 规则 |
| 22 | `install_docker_plugin` | 41 | 会改 `dockerd.globals.data_root`，让 1Panel 现有容器数据"消失" |
| 23 | `run_openclash_dependency_repair_check` | 156 | OpenClash 依赖修复 |
| 33 | `manage_nradio_hardware_acceleration` | 30 | 硬件加速开关，影响转发路径 |
| — | `game_accelerator_menu` + `qiyou_integrated_menu` + `leigod_integrated_menu` | 95 | 分类 3「游戏加速器」整体移除：奇游/雷神走**明文 HTTP** 下载链 |

### 3.2 名字家族（显式归属，不做推断）

命中 `adguard` / `mosdns` / `qiyou` / `leigod` / `hakimi` / `docker` / `openclash` 的顶层函数。

### 3.3 关键红线：**禁止**做死代码清理

脚本里存在**动态拼名调用**（modem/AT 子系统）：

```
58970|  _func="_switch_sim_${_vendor}"
59075|  _func="command_${_vendor}_${_cmd}${_cmdset}"
59088|  _func="command_generic_${_cmd}"
60382|  _exec="_command_atcmd_${_vendor%%_*}"
```

因此 `command_huawei_*` / `command_generic_*` 这类"全文无人引用"的函数**全是活函数**。
任何基于可达性的死代码清理都会误删，**本工具链刻意不做**（`command_*` 81 个函数原样保留）。

### 3.4 不变式（删前必过）

> **被删函数在存活文本中必须零静态引用。**

`trim_maye.py` 迭代到不动点执行该约束（撤删 → 重新物化 → 再算引用）。
本次收敛用 4 轮：撤删 15 → 10 → 2 → 0。这条约束把「调用方被恢复、被调方没跟着恢复」这类
半删状态直接挡掉。

## 4. 删除清单（140 函数 / 11,841 行）

| 行数 | 个数 | 前缀 |
|---|---|---|
| 6,781 | 6 | `write_*`（最大单体：`write_adguard_wrapper_files` **5,881 行**） |
| 1,098 | 3 | `configure_*` |
| 671 | 36 | `docker_*` |
| 640 | 6 | `install_*` |
| 564 | 19 | `hakimi_*` |
| 401 | 6 | `ensure_*` |
| 372 | 15 | `qiyou_*` |
| 291 | 13 | `leigod_*` |
| 244 | 2 | `run_*` |
| 137 | 8 | `patch_*` |
| 83 | 8 | `openclash_*` |
| 其余 | 28 | `fix_*` / `download_*` / `is_*` / `restore_*` / `cleanup_*` / `game_*` / `manage_*` |

## 5. 菜单变化对照

| 位置 | 原版 | 精简版 |
|---|---|---|
| 顶层 | 1 常用插件 / 2 VPN 组网 / **3 游戏加速器** / 4 应用商店与页面 / 5 设备维护 / 0 退出，`[0-5]` | 1 常用插件 / 2 VPN 组网 / 3 应用商店与页面 / 4 设备维护 / 0 退出，**`[0-4]`** |
| 1 常用插件 | swap · 哈基米 · ttyd · AdGuardHome · OpenList · MosDNS · DDNS-GO · Docker · MT5700 · Open-Box（`[0-10]`） | swap · ttyd / Web SSH · OpenList · DDNS-GO · MT5700 · Open-Box（**`[0-6]`**） |
| 2 VPN 与组网 | ZeroTier · EasyTier · OpenVPN · OpenVPN 向导配置并运行 · OpenVPN 路由表向导 · EasyTier 路由表向导 · OpenVPN 自检（`[0-7]`） | ZeroTier · EasyTier · OpenVPN · OpenVPN 自检（**`[0-4]`**） |
| 3 游戏加速器 | 奇游联机宝 · 雷神加速器 | **分类整体移除** |
| 应用商店与页面 | 美化 · 还原 · OpenWrt 原版 LuCI（8080）· 轻量应用商店 | 美化 · OpenWrt 原版 LuCI（8080）· 轻量应用商店（**重编号为 1/2/3**） |
| 4 设备维护 | 统一体检 · 风扇控制 · 哈基米傻瓜分流 · eMMC 存储扩展 · 5G 聚合 · 哈基米依赖修复 · 封版工具箱 · 运营商显示修复 · 首页温度切换 · 5G 连接监听 · 硬件加速管理 · 返回 | 统一体检 · 风扇控制 · eMMC 存储扩展 · 5G 聚合 · 封版工具箱 · 运营商显示修复 · 首页温度切换 · 5G 连接监听 · 返回（**运行时计数器自动连续编号**） |

> 设备维护菜单原版用 `maintenance_next_choice=$((...+1))` 运行时计数器编号，
> 因此删项后编号**自动连续**，无需手工重排 —— 这是最安全的改法。

**额外移除**：`main_menu` 与各子菜单里 **AK68-798 / NRadio_C8-788 的机型专用分支**一并去掉，
统一为单一菜单。机型级功能门禁（`require_menu_feature_supported_for_current_model`）原样保留，
不支持的机型仍会被拦。

## 6. 保留的「红线邻近」函数（27 个）及理由

它们命中家族名，但**被存活功能引用**，按不变式保守保留。逐个判定为只读或良性：

| 函数 | 行数 | 判定 |
|---|---|---|
| `run_adguardhome_selfcheck` / `run_openclash_selfcheck` | 122 / 92 | 只读自检，被 4›1 统一体检引用；AGH 未装时只报"未安装" |
| `run_*_cdn_selfcheck` | 10 / 10 | 只读，调用下面的内存排序 |
| `optimize_adguardhome_cdn_order` / `optimize_openclash_cdn_order` | 19 / 23 | **只重排内存里的镜像列表变量**，不写盘 |
| `openclash_asn_mmdb_valid` / `openclash_core_runtime_valid` / `openclash_model_file_valid` / `openclash_file_min_size` / `openclash_resolve_storage_path` / `openclash_report_storage_location` | 5–22 | 只读探测/打印 |
| `nradio_print_openclash_brief_summary` / `nradio_hwaccel_openclash_status` | 12 / 14 | 只读状态打印 |
| `run_unified_opkg_openclash_readiness_check` / `unified_opkg_hakimi_warn` / `unified_opkg_hakimi_package_check` / `unified_get_openclash_config_path` / `run_unified_openclash_rule_check` | 5–86 | opkg 源与规则只读检查（被统一体检引用） |
| `hakimi_build_policy_menu` | 57 | 生成策略菜单**文本**，被规则检查引用 |
| `install_openclash_embedded_icon` / `install_adguardhome_embedded_icon` | 24 / 12 | 只写内置 SVG 图标文件 |
| `get_adguard_configpath` / `is_adguard_placeholder_config` | 6 / 12 | 只读判定 |
| `storage_expand_qiyou_service_is_running` | 13 | 只读服务状态 |
| `restore_dnsmasq_system_dns_when_adguard_unready` | 69 | 唯一有写盘的：恢复 dnsmasq 上游。**存活引用只存在于 `write_plugin_uninstall_assets` 的 heredoc 文本里**（即写入设备的卸载脚本素材），顶层无活调用路径 |

> ⚠️ `write_plugin_uninstall_assets` 本身保留（生成的卸载脚本是各插件安装流程的产物），
> 其 heredoc 素材中包含 AGH 卸载代码片段 —— 那是**落盘文本**，不在本脚本进程内执行。

## 7. 验证证据

| 检查 | 方法 | 结果 |
|---|---|---|
| 语法（PC） | `sh -n` | ✅ returncode 0 |
| 语法（设备） | 推送到 `/tmp/maye-lite.sh` 后 `sh -n` | ✅ `DEVICE_SYNTAX_OK` |
| 函数集合 | 原 803 ∪ 精简 663，`新增 0` | ✅ 无意外新函数 |
| 悬挂引用 | 140 个被删名字在存活全文（含 heredoc，从严）中检索 | ✅ **0 命中** |
| 动态拼名残留 | `command_` / `_switch_sim_` / `_command_atcmd_` / `generic_` 前缀扫描 | ✅ 无命中 |
| feature ID 一致性 | 分派表 ID vs 菜单引用 ID | ✅ 菜单引用的 ID 全部存在，无悬空 |
| heredoc 解析 | 自建 heredoc 感知扫描器（49,202 行 = 67% 属 heredoc 内容） | ✅ |
| 入口完整性 | 末行 `main_menu "$@"` | ✅（曾因边界推算吞掉入口，已修） |
| **真机菜单走查** | 推送设备后管道喂编号，逐类进入后返回（不选任何功能项） | ✅ 顶层 + 4 个子菜单全部按设计渲染，`rc=0` |
| **真机 handler 端到端** | 实跑 `4 → 1 统一体检增强版`（feature 13，静态调用闭包 **214 个函数**） | ✅ 25 个检查段全跑通，407 行输出，`rc=0`，30.3 s（见 §7.1） |
| 跑前/跑后对照 | 8 个关键文件 sha256、`pidof`、6 个补丁 marker、opkg 576 包整体哈希、`crontab`、`distfeeds`、`/root` 与 `/etc/kp_store` 清单 | ✅ **10/10 区段同值**；仅 dropbear pid 与 tmpfs 用量因本次会话变化 |
| **rootfs 改动侦测** | 遍历 `find / -xdev` + shell `[ f -nt $marker ]`（⚠️ 此固件 busybox find **无 `-newer`**，见 §9 第 9 条） | ✅ **0 个文件净变动**；仅 3 个目录 mtime 变动，其中 `/overlay` 与 `/mnt/app_data` 由脚本自身的**写探针**造成、`/tmp` 由本次会话写文件造成（见 §7.1 ③） |
| **安装类 handler 端到端** | 实跑 `1 → 2 ttyd / Web SSH`（feature 3，含 `install_ttyd_webssh` 2276 行） | ✅ 5 个阶段全过，`rc=0`，12.8 s；ttyd 1.7.7 落地并监听 `192.168.66.1:7681`（见 §7.1 ④） |
| 脚本锁释放 | `/var/run/nradio-plugin-assistant/` | ✅ 空目录，无残留锁 |
| 上传完整性 | 本机 sha256 vs 设备 `sha256sum` | ✅ 一致（`3c2913f3…1e104`） |

### 7.1 真机端到端验证详情（2026-09-24 · C2000 U）

验证目的：**证明裁剪后的代码不只在语法层自洽，而是能真实跑通 handler**。
分两轮：先跑**只读 handler**（不担风险地把调用链跑穿），再跑**安装类 handler**
（验证「下载 → 落盘 → 起服务」这条最容易因裁剪而断的路径）。

#### ① 只读靶子：`4 → 1 统一体检增强版`（feature 13）

选它是因为**全程只读** —— 静态审查其调用闭包（`reach.py`，**214 个函数**）
确认无持久化写入：`ensure_state_dir` 的目标目录已存在；`optimize_*_cdn_order`
只重排内存里的 URL 变量；`record_*__summary` / `set_last_selfcheck_status`
只写 shell 变量；唯一落盘处是 tmpfs 的 `WORKDIR=/var/run/nradio-plugin-assistant/work.$$`。

```
$ printf '4\n1\n' | sh /tmp/ssh-nradio-plugin-installer-lite.sh
rc=0     耗时 30.3 s     输出 407 行

overall:  安装阶段 = PASS / 系统体检 = PASS / 时间与证书 = PASS
          NROS 出口 = WARN / 网络出口 = PASS / 大包风险 = PASS
          安装前预检 = WARN / 哈基米 安装就绪 = WARN / feed 索引 = PASS
          运行负载 = PASS / 内核存储日志 = PASS / 插件矩阵 = WARN
          应用商店一致性 = WARN / 端口冲突 = PASS / 哈基米 规则 = WARN
          脱敏摘要 = PASS / CDN 六连（哈基米·AGH·OpenList·ZeroTier·EasyTier）= PASS
          OpenVPN CDN = FAIL / 哈基米 = FAIL / OpenVPN = FAIL
          overall: FAIL (pass=17 warn=6 fail=3 skip=9)
```

**3 个 FAIL 全部是设备既有状态，与裁剪无关**，逐条已核实：

| FAIL 段 | 原因 | 是否裁剪引入 |
|---|---|---|
| `OpenVPN CDN` | `luci-app-openvpn` 无法从当前软件源（阿里云 21.02.7）解析 | ❌ 本机未装 OpenVPN |
| `OpenVPN` 自检 | 核心/服务/配置文件全缺（errors=5 warnings=6） | ❌ 本机未装 OpenVPN |
| `哈基米` 自检 | `/etc/openclash/ASN.mmdb` 缺失（errors=1 warnings=2） | ❌ **且为误报**：运行中配置 `e_bbydy.yaml` 里 `ASN,` 规则计数 = **0**，`Country.mmdb` 与 `GeoSite.dat` 均在位 → 无功能影响 |

另有 9 个 SKIP 段（AdGuardHome / ttyd / OpenList / ZeroTier / EasyTier /
eMMC 两段 / LuCI 温度与运营商显示）都是「可选插件未安装」的正常跳过。

#### ② 覆盖到的调用链

菜单分派 → `run_menu_feature` → handler → 深层子函数
（下载辅助、网络探测、opkg 查询、服务状态检查、日志解析）全链路真实执行，
无函数缺失、无 `command not found`、无悬挂引用报错。

#### ③ 副作用复核（**本轮订正过一次**，方法论很重要）

第一轮的结论「零改动」是**错的** —— 当时用的命令是
`find <树> -xdev -newer <marker> 2>/dev/null`，而**此固件的 busybox find
不支持 `-newer`**：它报 `unrecognized: -newer`，错误被 `2>/dev/null` 吞掉，
**静默返回空结果** → 看起来像"零改动"，实为假阴性。

改用可用方法（遍历 + shell `[ f -nt ]`）重做后的**真实**结论：

```
0 个文件净变动；
3 个目录 mtime 变动：
  /overlay        <- 脚本自己的写探针（ensure_dir_writable /overlay，第 23445 行）
  /mnt/app_data   <- 脚本自己的写探针（openlist_dir_is_writable /mnt/app_data，第 1324 行）
  /tmp            <- 本次会话把输出写到了 /tmp
```

写探针的机制：`probe_file="$dir/.nradio-write-test.$$"; : > "$probe_file"; rm -f "$probe_file"`
—— **建完立刻删，净文件为零，但父目录 mtime 会跳**。
对照实验（静置 45 s 不做任何操作）确认：那 45 s 里变的是 `/etc/config/cpecfg`
（固件自己周期写的 5G 模块状态），`/overlay`、`/mnt/app_data` 均未变 →
证明这两个目录确实是被体检的写探针碰的，不是环境噪声。

#### ④ 安装类靶子：`1 → 2 ttyd / Web SSH`（feature 3）

先静态审查 `install_ttyd_webssh`（2276 行，内嵌 ~2500 行 helper 的 heredoc），
确认它会：下载 ttyd 1.7.7 二进制 + LuCI ttyd 资源 → 写 `Web SSH` 包装页 →
**改 `appcenter.htm` 加商店快捷入口** → 重启 ttyd / infocd / appcenter 并 reload uhttpd。
跑前备份 7 个文件（含 `appcenter.htm`、`appcenter.lua`）到 `/tmp/kp-maye-bak-ttyd/`。

```
$ printf '1\n2\ny\n' | sh /tmp/ssh-nradio-plugin-installer-lite.sh
rc=0     耗时 12.8 s     输出 61 行

[20%]  [1/5] 下载或更新 ttyd 二进制        下载完成 100% 1.3MB/1.3MB 0分2秒
[40%]  [2/5] 安装或刷新 LuCI ttyd 文件     1.3KB + 109.1KB
[60%]  [3/5] 写入 Web SSH 包装页
[80%]  [4/5] 写入应用商店快捷入口
[100%] [5/5] 重启 ttyd 与 uhttpd 服务
安装完成 / 直连 ttyd: http://192.168.66.1:7681/ / ttyd 访问认证: 已关闭
```

跑后用同一套 `-nt` 方法实测，**真实改动 19 个文件 + 19 个目录**：

| 类别 | 文件 |
|---|---|
| 新增二进制 / 服务 | `/usr/bin/ttyd`(1,370,112 B)、`/etc/init.d/ttyd`、`/etc/config/ttyd`、`/etc/rc.d/S??ttyd` |
| 新增 LuCI | `controller/ttyd.lua`、`model/cbi/ttyd.lua`、`view/ttyd/overview.htm`、`view/ttyd/nradio_polish.htm`、`view/nradio_adv/webssh.htm`、`controller/nradio_adv/webssh.lua`、`www/luci-static/nradio/images/icon/webssh.svg` |
| ⚠️ **改写了商店文件** | `view/nradio_appcenter/appcenter.htm`、`controller/nradio_adv/appcenter.lua` |
| ⚠️ 改了固件模板 | `usr/lib/lua/luci/nradio.lua`（补 `luci.nradio` 运行接口）、`/etc/skills/oaf-tool/SKILL.md`（加 appfilter 存在性检查） |
| 卸载素材 / 记账 | `controller/nradio_adv/plugin_uninstall.lua`、`/usr/libexec/nradio-plugin-uninstall`、`/usr/libexec/nradio-ai-compat.sh`、`/etc/nradio-plugin-menu/webssh-owned-files.list`、`/root/.nradio-plugin-menu/action-history.log` |

**关键判据：它确实改写了 `appcenter.htm` / `appcenter.lua`，但我们的补丁 marker
（`nradio_appcenter_extra_action` / `_kp_installed_registry` / `aurora_open_app`）
跑前跑后都是 0 —— 本机从未打过我们的商店补丁，所以没有补丁被冲掉。**
这同时**实测验证了 §0 红线 1 的「它会改商店页」不是推测**。
（`Design By MaYe` 计数跑后 = 1，即它自己的产权标识。）

**仍未验证的**：其余安装项（OpenList / DDNS-GO / ZeroTier / EasyTier / MT5700 /
Open-Box / swap / eMMC 扩展 / 封版工具箱 / 风扇控制 / 首页温度切换）未逐个真跑 ——
本次只抽验了 ttyd 一项作为安装路径的代表。网络侧（ZeroTier/EasyTier 会写 `ip rule`）
风险最高，未触碰。
见 §9。

## 8. 复现步骤

```bash
# 1) 取回定点版本（唯一可取回 V3.2.0 的方式）
curl -sL -o maye-v320.sh \
  https://raw.githubusercontent.com/561410590/ssh-nradio-plugin-installer/2daa69d8b4/00-current/ssh-nradio-plugin-installer.sh
sha256sum maye-v320.sh   # 期望 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8

# 2) 裁剪
cd scripts/maye_trim
SRC=maye-v320.sh DST=maye-lite.sh python trim_maye.py

# 3) 硬校验（语法 + 悬挂引用 + ID 一致性 + 家族残留）
SRC=maye-v320.sh LITE=maye-lite.sh python verify_lite.py

# 4) 【真机冒烟前必做】静态调用闭包 + 写盘扫描：判断想跑的那个 handler 是不是"只读"
#    从入口出发沿静态调用图 BFS，列出闭包内所有写盘/删除/服务控制操作及行号
python reach.py maye-lite.sh run_unified_test_mode
#    命中 ≠ 有害（`> /dev/null`、tmpfs 上的 mkdir 都会被命中），要逐条读原行；
#    选出只读 handler 后，真机跑 + 配下面的改动侦测实测副作用，才算验证完成
```

`trim_maye.py` 内的 `DENY_IDS` / `FAMILY` 即为裁剪策略，改这两处即可调整口径。

**真机验证的两步法**（2026-09-24 实战成形，别跳第一步）：
```sh
# ① 纯静态：reach.py 扫闭包 → 挑一个「只读 handler」当冒烟靶子
# ② 纯运行期：设备侧
touch /tmp/kp-marker
printf '4\n1\n' | sh /tmp/ssh-nradio-plugin-installer-lite.sh   # 跑被测 handler

# 改动侦测 —— ⚠️ 此固件的 busybox find **没有 `-newer` / `-mmin` / `-newermt`**，
#    必须用 shell 的 `-nt` 判定（写成 find -newer 且 2>/dev/null 会静默返回空 → 假阴性！）
cd / && find . -xdev -type f | while IFS= read -r f; do [ "$f" -nt /tmp/kp-marker ] && echo "F $f"; done
cd / && find . -xdev -type d | while IFS= read -r f; do [ "$f" -nt /tmp/kp-marker ] && echo "D $f"; done
#    rootfs 只有 6,610 文件 / 523 目录 → 全盘扫一遍 0.6 s，可以每次跑完都扫
#    期望：只读操作 = 0 个 F 行（`D` 行可能因脚本自己的写探针而出现，见 §7.1 ③）
#    这比"静态看着没问题"硬得多 —— 语法通过 + 引用自洽都证明不了"能跑"。
```

> 💡 **别漏了对照实验**：设备上跑着每分钟一次的 crontab（ocspeed），固件自己也会周期写
> `/etc/config/cpecfg`。看到意外改动时，先"静置同样时长什么都不做"再扫一遍，
> 用对照组把环境噪声与操作副作用分开 —— 否则很容易把固件行为误判成脚本行为。

## 9. ⚠️ 未验证与已知限制

1. **只抽验了一个安装项**。2026-09-24 已跑通「只读 handler（统一体检增强版 25 段）」与
   「一个安装类 handler（`ttyd / Web SSH`，5 阶段全过、落地并监听 7681）」，见 §7.1。
   **其余安装项未逐个真跑**（OpenList / DDNS-GO / ZeroTier / EasyTier / MT5700 /
   Open-Box / swap / eMMC 扩展 / 封版工具箱 / 风扇控制 / 首页温度切换）——
   下载源与 ipk 依赖整体可用性已由 CDN 探测 6 段 + ttyd 实测间接证明，
   但**逐项的设备端兼容性仍需自行判断**。网络侧（ZeroTier / EasyTier 会写 `ip rule`）
   **风险最高、本次刻意未触碰**。
2. **仍不产生任何备份**（与上游一致）。跑任何安装项之前，自己备份
   `appcenter.lua` / `appcenter.htm` / `/etc/config/appcenter` / `/etc/opkg/distfeeds.conf`。
   ⚠️ 实测证实它会改写这两个 appcenter 文件（见 §7.1 ④），备份不能省。
3. **依赖上游函数名稳定**。若上游改了函数命名，`FAMILY` 归属需同步调整。
4. **机型分支已移除**：AK68-798 / NRadio_C8-788 的专用菜单分支被删，统一走单一菜单；
   机型级功能门禁仍在，不支持的功能照样会被 `die` 拦下。
5. **动态拼名家族未做任何裁剪**（modem/AT 的 `command_*` 等 81 个函数原样保留），
   因此本版仍完整保留 5G/模组相关的 AT 操作能力。
6. **`install_*` 类流程的卸载脚本素材仍包含 AGH/Docker 片段**（见 §6 末注），
   属落盘文本而非本进程执行。⚠️ 但**卸载素材本身会被写进设备**
   （ttyd 那次写了 `/usr/lib/lua/luci/controller/nradio_adv/plugin_uninstall.lua` +
   `/usr/libexec/nradio-plugin-uninstall`）；内容是文本，**不要去点那些入口**。
7. **会残留一个空的 tmpfs 目录** `/var/run/nradio-plugin-assistant/`（`WORKDIR` 的父目录），
   重启即消失，且**上游同样如此**（非裁剪引入）；锁文件本身会正常释放。
8. **只读操作也会碰目录 mtime**：脚本用「建一个探针文件再立刻删」来判断目录可写
   （`ensure_dir_writable`），净文件为零但**目标目录的 mtime 会跳**。
   实测体检会碰 `/overlay` 与 `/mnt/app_data`。做副作用复核时别把 D 行当故障。
9. 🕳️ **`-newer` 假阴性（本项目真踩过）**：**此固件的 busybox find 不支持
   `-newer` / `-mmin` / `-newermt`**。写成
   `find <树> -xdev -newer <marker> 2>/dev/null` 时，它报 `unrecognized: -newer`
   但错误被 `/dev/null` 吞掉，**静默返回空结果** → 看起来像"零改动"。
   正确做法是遍历 + shell `[ f -nt marker ]`（见 §8）。
   **推论：任何"期望无输出"的校验都别把 stderr 丢掉** —— 静默为空既可能是无问题，
   也可能是命令根本没跑起来。
10. **ttyd 的访问认证默认关闭**（`option credential '0'`，`interface='br-lan'`）。
    仅监听 LAN 网桥，但**同网段任何设备都能拿到 root shell**。
    本机 root 口令本身也弱，所以未额外处理；在意的话自行
    `uci set ttyd.default.credential='1'` 并设 username/password 后
    `/etc/init.d/ttyd restart`。
11. 本版**不是**上游产物，被上游收录的哈希校验对本文件无意义。

## 10. 授权与声明

- 原作版权归 **maye** 所有，上游声明：**免费分享的非商业项目，禁止任何形式的付费传播或倒卖**。
- 本衍生版由 `h910056902/kunpeng-router-ai-skills` 按上述红线规则裁剪生成，
  同样**免费、非商业、禁止付费传播或倒卖**；裁剪目的仅为移除本机不需要的破坏性功能，
  不改变其余功能行为。
- 由于是**修改后的再分发**，使用前请自行判断是否符合上游授权意图；
  文件头部已内嵌完整的来源与衍生声明。
