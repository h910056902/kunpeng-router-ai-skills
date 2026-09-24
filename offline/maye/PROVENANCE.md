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
| **真机菜单走查** | 推送设备后用 PTY 启动，逐类进入后 Ctrl-C 中止，不选任何安装项 | ✅ 顶层 + 4 个子菜单全部按设计渲染 |
| 跑前/跑后对照 | `pidof` clash/dockerd/dnsmasq、5 个文件 sha256、补丁 marker、`distfeeds` 行数 | ✅ 全部同值，零副作用 |
| 上传完整性 | 本机 sha256 vs 设备 `sha256sum` | ✅ 一致 |

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
```

`trim_maye.py` 内的 `DENY_IDS` / `FAMILY` 即为裁剪策略，改这两处即可调整口径。

## 9. ⚠️ 未验证与已知限制

1. **没有执行过任何安装动作**。本版只验证到"能启动、菜单渲染正确、语法与引用自洽"。
   每个具体安装流程（下载源可用性、ipk 依赖、设备端兼容性）**均未在真机跑过** ——
   跑它们会真实改动设备，越出了只读验证的边界。
2. **依赖上游函数名稳定**。若上游改了函数命名，`FAMILY` 归属需同步调整。
3. **机型分支已移除**：AK68-798 / NRadio_C8-788 的专用菜单分支被删，统一走单一菜单；
   机型级功能门禁仍在，不支持的功能照样会被 `die` 拦下。
4. **动态拼名家族未做任何裁剪**（modem/AT 的 `command_*` 等 81 个函数原样保留），
   因此本版仍完整保留 5G/模组相关的 AT 操作能力。
5. **`install_*` 类流程的卸载脚本素材仍包含 AGH/Docker 片段**（见 §6 末注），
   属落盘文本而非本进程执行。
6. 本版**不是**上游产物，被上游收录的哈希校验对本文件无意义。

## 10. 授权与声明

- 原作版权归 **maye** 所有，上游声明：**免费分享的非商业项目，禁止任何形式的付费传播或倒卖**。
- 本衍生版由 `h910056902/kunpeng-router-ai-skills` 按上述红线规则裁剪生成，
  同样**免费、非商业、禁止付费传播或倒卖**；裁剪目的仅为移除本机不需要的破坏性功能，
  不改变其余功能行为。
- 由于是**修改后的再分发**，使用前请自行判断是否符合上游授权意图；
  文件头部已内嵌完整的来源与衍生声明。
