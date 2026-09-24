# kunpeng-router-ai-skills

![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png) ![常用插件](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/plugins.png) ![VPN组网](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/network.png) ![游戏加速](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/game.png) ![应用商店](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/store.png) ![设备维护](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maint.png) ![设备自检](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/selftest.png)

**🤔 这是什么？**

把一台**内核无 veth / bridge 不可用**的鲲鹏无限 / NRadio C2000 路由器（OpenWrt 21.02，MT7987，aarch64），不刷机调教到能跑 Docker、1Panel、OpenClash 的全部真机实测经验 —— 沉淀为 **47 个机读任务 + 离线安装素材 + 复盘文档** 的 AI Agent 技能仓库。任何 AI（WorkBuddy / Codex / Cursor / Claude Code…）读它能直接上手干活。

> 🔒 公开脱敏版：所有密码 / token / 入口码均已替换为 `<你的xxx>` 占位符；离线素材经 md5 校验。

**💡 能干什么？**

- 🌐 **一键任务 1**：OpenClash 安装 + Mihomo 内核拉取（离线 ipk / 在线双路径）
- 📊 **一键任务 2**：ocspeed 自动测速插件安装（五件套落盘 + cron 重建）
- 🐋 **一键任务 3**：Docker + 1Panel 安装（含 host 网络默认化，容器建 veth 必死的解法）
- 🧩 **一键任务 4**：第三方 NROS 插件安装器（maye 助手 · **总入口**；红线 + 补丁基线校验，菜单需人工按）
- 🧰 **任务 5 ~ 9**：maye 助手的**五个功能分类直达入口** —— 🔌 常用插件 / 🛡️ VPN 组网 / 🎮 游戏加速器 / 🎨 应用商店与页面美化 / 🔧 设备维护与检测（每个分类有自己的红线与判据，任一分类都**不是**「照 tasks/05 跑一遍」那么简单）
- 🩺 **任务 11**：设备状态与环境自检（**纯只读**全机体检 —— 系统资源与环境 / 容器梳理 / 网络与信号含 5G·CPE / 服务与补丁状态 / 装载余量与可装性对照；只报不修、零写盘、不用真终端）
- 📦 另有 34 个机读任务：换源救源、无 SSH 救援、TF 扩容、面板排障、**Docker 环境清空**… 全在 `tasks/index.json`

**🚀 AI 快速接入（一段话，复制即用）**

把下面这一段发给 AI —— 仓库地址、SSH 登录信息（在 `AGENTS.md` §1 设备档案里）都在仓库内，
提示词只负责「你是谁、去哪读、读完弹菜单」。它会像带菜单的安装脚本一样工作：
**第一条回复先弹一行软件真实图标、再说一句用法提示、然后在代码块里弹出菜单（块尾含致谢与版权声明）**，
然后停下等你输编号。

```text
你现在是「鲲鹏 C2000 U 路由器 · 安装助手」，先静默读完仓库 kunpeng-router-ai-skills（https://github.com/h910056902/kunpeng-router-ai-skills；GitHub 访问不了就改用 CDN 直读 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/AGENTS.md 和 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/tasks/index.json）里的 AGENTS.md 与 tasks/index.json，读完前不要输出任何内容。
之后一切都按仓库 AGENTS.md 的指引来：先按 AGENTS.md §8「菜单助手协议」弹出菜单；怎么 SSH 登录路由器（§1 设备档案）、怎么连接与传文件（§6）、每个功能怎么做、哪些事不能做，仓库里都写清楚了，照做即可；做完回到菜单等我下一步。
若 GitHub 与 CDN 都读不到：如实回一句「仓库地址打不开，读不到助手协议」就停下等用户，不要自己编一个菜单、不要凭记忆复述菜单、不要碰路由器。
若只读到 AGENTS.md、读不到 tasks/index.json：仍可按 §8 弹菜单，但在执行任何编号功能之前必须先声明「任务库缺失，无法核对前置与验证判据」，等用户明确确认后才继续。
转发 §8.1 首屏（图标行 + 一句人话 + 菜单代码块）时必须逐字原样：三样东西之间和内部都不得夹带任何解释性文字，不得增删改任何一行。
```

菜单长这样（下面是**展示预览**；解析规则、四关、4)~9) 的交互式细则、10 条硬约束、以及 `11)` 只读自检的特别说明全部在
[`AGENTS.md`](AGENTS.md) §8「菜单助手协议」—— 那是唯一真源，随仓库走、不用你贴）：

```text
════════════════════════════════════════════
  🐟 鲲鹏 C2000 U 路由器 · 安装助手
════════════════════════════════════════════

  1)  🌐 OpenClash 安装 + Mihomo 内核拉取
        openclash.install / openclash.core

  2)  📊 ocspeed 自动测速插件安装
        ocspeed.install

  3)  🐳 1Panel + Docker 安装（host 网络默认化）
        docker.install / panel.install

  4)  🧩 第三方 NROS 插件安装器（maye 助手 · 总入口）
        nros.plugin-installer

  ── 5~9 是 maye 助手的五个功能分类，跑法同 4)：AI 做前置与校验，菜单由你按 ──

  5)  🔌 常用插件（swap · OpenList · DDNS-GO · WebSSH）
        nros.plugins-common

  6)  🛡️ VPN / 组网 / 路由向导（ZeroTier · EasyTier · OpenVPN）
        nros.network-route

  7)  🎮 游戏加速器（奇游 · 雷神 · 明文 HTTP 风险）
        nros.game-accel

  8)  🎨 应用商店与页面美化（美化 · 还原 · LuCI 8080）
        nros.appcenter-polish

  9)  🔧 设备维护与检测（体检 · 工具箱 · 硬件加速）
        nros.maintenance

  ── 10 预留给「清除 / 卸载」引擎（尚未开放），本表从 11 续号 ──

  11)  🩺 设备状态与环境自检（资源 · 容器 · 5G · 服务 · 装载余量）
        device.selftest

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
  菜单交互借鉴自 maye 助手（Design By MaYe）· 特此致谢
  本助手协议 / 任务库 / 清除引擎为自研 · © 2026 h910056902
────────────────────────────────────────────
```

其他入口：[`docs/助手菜单提示词.md`](docs/助手菜单提示词.md)（启动器与维护须知）·
[`docs/仓库维护指南.md`](docs/仓库维护指南.md)（维护者手册）。

## AI 接入点（机器可读）

| 文件 | 用途 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent 约定入口：这个仓库是什么、先读什么、高危禁令、每个任务从哪进 |
| [`llms.txt`](llms.txt) | LLM 索引清单：全部文档一句话摘要，便于检索式加载 |
| [`tasks/index.json`](tasks/index.json) | **47 个机读任务**：每条含 id / title / risk / playbook / preconditions / verify / rollback / offline / refs 等字段 |
| [`SKILL.md`](SKILL.md) | 主技能：设备档案 + A→V 有序任务路由表（含 T1–T6 任务包速查 + maye 分类分册） |

**最小接入方式**：让 Agent 先读 `AGENTS.md`，按 `tasks/index.json` 的任务 id 精确取用 playbook，而不是通读全库。

## 任务包（T1–T6 + maye 分类分册）

| 任务包 | Playbook | 离线素材 |
|---|---|---|
| **T1 · OpenClash 安装 + 内核拉取** | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | `offline/openclash/luci-app-openclash_0.47.156_all.ipk`、`offline/core/mihomo-linux-arm64.gz`、6 个 stub ipk、脱敏 config 模板 |
| **T2 · ocspeed 安装** | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | `offline/ocspeed/` 五件套（speedswitch.sh / ocspeed.lua / ocspeed.htm / nodetest.htm / config.ocspeed）+ 一键装脚本 `kp-ocspeed.sh` |
| **T3 · Docker + 1Panel 安装** | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | `offline/panel/` 六脚本（install / kp-install / kp-storage-init / kp-store-lib / kp-store-check / kp-ui）+ `scripts/payload/` host 网络默认化三件套 |
| **T4 · 清空 Docker 环境（重装前置）** | [`tasks/04-docker-purge.md`](tasks/04-docker-purge.md) | `scripts/payload/kp-docker-purge.sh`（默认 dry-run，双开关才真删，动手前自动备份快照） |
| **T5 · 第三方 NROS 插件安装器（maye 助手）· 总入口** | [`tasks/05-nros-plugin-installer.md`](tasks/05-nros-plugin-installer.md) | `offline/maye/ssh-nradio-plugin-installer-lite.sh`（**精简版**：红线功能已物理删除，60,590 行）+ `PROVENANCE.md` / `SHA256SUMS`；适配器 `scripts/adapt_maye_assistant.py` |
| **T5-a · 分类一 常用插件安装** | [`tasks/06-nros-plugins-common.md`](tasks/06-nros-plugins-common.md) | 同上（红线：哈基米＝装 OpenClash / AGH·MosDNS 抢 53 / ttyd 默认免登录） |
| **T5-b · 分类二 VPN / 组网 / 路由向导** | [`tasks/07-nros-network-route.md`](tasks/07-nros-network-route.md) | 同上（destructive：写 `ip rule`，本机全网出口＝断网风险） |
| **T5-c · 分类三 游戏加速器** | [`tasks/08-nros-game-accel.md`](tasks/08-nros-game-accel.md) | 同上（destructive：明文 HTTP 下载 root 脚本，无校验和） |
| **T5-d · 分类四 应用商店与页面美化** | [`tasks/09-nros-appcenter-polish.md`](tasks/09-nros-appcenter-polish.md) | 同上（会覆盖商店补丁载体 `appcenter.htm` / `appcenter.lua`） |
| **T5-e · 分类五 设备维护与检测** | [`tasks/10-nros-maintenance.md`](tasks/10-nros-maintenance.md) | 同上（红线：`5 › 11` 硬件加速会 `fw3 reload`） |
| **T6 · 设备状态与环境自检（助手菜单 11 · 纯只读）** | [`tasks/11-device-selftest.md`](tasks/11-device-selftest.md) | 无离线素材；`scripts/device-selftest.py`（PC 侧入口）+ `scripts/payload/kp-selftest.sh`（设备侧采集器） |

每个 playbook 都包含：前置条件 → 步骤（含离线/在线两条路径）→ 验证命令 → 回滚方法 → 已知坑。
T5 的五个分类分册另外各自带**本分类专属红线表**与**跑前/跑后对照项**。

## 目录结构

```
├── AGENTS.md / llms.txt / SKILL.md     # AI 入口与路由
├── tasks/                              # index.json(47 任务) + 11 份 playbook（含清空 Docker / maye 助手 + 五个分类分册 + 设备自检）
├── references/                         # 23 篇专题文档（含 id/tags/risk frontmatter）
├── docs/                               # 调优经验总览 · 验收清单 · 助手菜单提示词 · 仓库维护指南
├── assets/menu/                        # 菜单软件图标（11 枚 32px PNG，jsdelivr 引用）
├── offline/                            # 离线安装素材 + checksums.md5（23 项，含 maye 精简版）
├── scripts/                            # PC 侧驱动 + payload/（host 网络三件套、回归自测）+ maye_trim/（源码裁剪工具链）
└── C2000U-Docker-assessment.md         # C2000 U Docker 适配评估与实装记录
```

## TL;DR（8 条铁律）

1. **内核无 veth → bridge 永远起不来**。容器一律 `network_mode: host`；1Panel 应用靠替换 `/usr/bin/docker-compose` 为 wrapper 实现全局 host 化（真件保留 `.real`，一条命令可回滚）。
2. **商店模板 ≠ 面板落盘**：1Panel 会把 2 空格模板重渲染成 4 空格 + `deploy:` 段——任何按缩进硬编码的转换器都会「半转换」（教训见 `references/1panel-hostnet-default.md`）。
3. **busybox ash 三坑**：字符类别写 `\t`；`sed` 无 `-i` 备份后缀；`grep -o` 行为差异。所有设备端脚本必须过 busybox 兼容回归。
4. **dropbear 单命令 ~8KB 上限**：超长文件必须分块 heredoc 写入，且失败要能降级重连（`scripts/rtr_lib.py` 已实现）。
5. **TF 卡数据分区独立挂载**（`/mnt/storage/data`），overlay 重建不丢数据；卡损坏的判死与救援见 `references/`。
6. **DNS 被 fake-ip 劫持时**，真实解析用 `Resolve-DnsName -Server 223.5.5.5` 或 DoH。
7. **GitHub 直推被污染时**（rc=128 且 stderr 空），用 `scripts/gh_proxy_push.py` 走中转。
8. **改任何 UCI / 面板数据库前先备份**：1Panel 参数存 `db/1Panel.db` 的 `app_installs.env`（JSON 列），设备有 python3 无 sqlite3。

## 相关仓库

- **私有完整档案**：`h910056902/kunpeng-router-tuning`（含 `src/` 源码树、`memory/` 日志、`HANDOFF/PROGRESS`，未脱敏）
- 参照项目：`wukongdaily/gl-inet-onescript`（仅作 iStoreOS 风格化对照，本仓库不含其代码）
