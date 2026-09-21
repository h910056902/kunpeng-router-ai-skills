# kunpeng-router-ai-skills

![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png) ![常用插件](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/plugins.png) ![VPN组网](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/network.png) ![游戏加速](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/game.png) ![应用商店](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/store.png) ![设备维护](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maint.png)

**🤔 这是什么？**

把一台**内核无 veth / bridge 不可用**的鲲鹏无限 / NRadio C2000 路由器（OpenWrt 21.02，MT7987，aarch64），不刷机调教到能跑 Docker、1Panel、OpenClash 的全部真机实测经验 —— 沉淀为 **46 个机读任务 + 离线安装素材 + 复盘文档** 的 AI Agent 技能仓库。任何 AI（WorkBuddy / Codex / Cursor / Claude Code…）读它能直接上手干活。

> 🔒 公开脱敏版：所有密码 / token / 入口码均已替换为 `<你的xxx>` 占位符；离线素材经 md5 校验。

**💡 能干什么？**

- 🌐 **一键任务 1**：OpenClash 安装 + Mihomo 内核拉取（离线 ipk / 在线双路径）
- 📊 **一键任务 2**：ocspeed 自动测速插件安装（五件套落盘 + cron 重建）
- 🐋 **一键任务 3**：Docker + 1Panel 安装（含 host 网络默认化，容器建 veth 必死的解法）
- 🧩 **一键任务 4**：第三方 NROS 插件安装器（maye 助手 · **总入口**；红线 + 补丁基线校验，菜单需人工按）
- 🧰 **任务 5 ~ 9**：maye 助手的**五个功能分类直达入口** —— 🔌 常用插件 / 🛡️ VPN 组网 / 🎮 游戏加速器 / 🎨 应用商店与页面美化 / 🔧 设备维护与检测（每个分类有自己的红线与判据，任一分类都**不是**「照 tasks/05 跑一遍」那么简单）
- 📦 另有 34 个机读任务：换源救源、无 SSH 救援、TF 扩容、面板排障、**Docker 环境清空**… 全在 `tasks/index.json`

**🚀 AI 快速接入（一段话，复制即用）**

把下面这一段发给 AI —— **仓库地址与 SSH 连接信息已写在段内**，发送前把 `<SSH密码>` 替换成真实密码（或删掉那句让 AI 向你索要）。它会像带菜单的安装脚本一样工作：
**第一条回复先弹一行软件真实图标、再在代码块里弹出菜单**，然后停下等你输编号。

```text
你现在是「鲲鹏 C2000 U 路由器 · 安装助手」，一切行为只依据仓库 kunpeng-router-ai-skills（https://github.com/h910056902/kunpeng-router-ai-skills；本地没有就先 clone 它；GitHub 访问不了就改用 CDN 直读 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/AGENTS.md 和 https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/tasks/index.json）。
先静默读完仓库里的 AGENTS.md 与 tasks/index.json，读完前一个字都不要输出；之后严格按 AGENTS.md §8「菜单助手协议」工作，协议里已写明的内容（首屏输出、输入解析、四关流程、硬约束等）全部以仓库为准，不要复述、不要重新解释。
连接设备：SSH root@192.168.66.1:22，密码 <SSH密码>（发提示词前把 <SSH密码> 替换成真实密码；没替换就先向我索要，不要猜）；连接方式照 AGENTS.md §6（python3 + paramiko，禁用 open_sftp，传文件用 scripts/rtr_lib.py）；凭据只在本会话内存里使用，不写进任何文件、日志或回复。
连上后先按 AGENTS.md §4 做三项只读检查再动手；然后一直停在菜单等我输入编号；4)~9) 是交互式脚本，到那几步停下等我本人按菜单。
```

菜单长这样（下面是**展示预览**；解析规则、四关、4)~9) 的交互式细则、10 条硬约束全部在
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

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
────────────────────────────────────────────
```

其他入口：[`docs/助手菜单提示词.md`](docs/助手菜单提示词.md)（启动器与维护须知）·
[`docs/仓库维护指南.md`](docs/仓库维护指南.md)（维护者手册）。

## AI 接入点（机器可读）

| 文件 | 用途 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent 约定入口：这个仓库是什么、先读什么、高危禁令、每个任务从哪进 |
| [`llms.txt`](llms.txt) | LLM 索引清单：全部文档一句话摘要，便于检索式加载 |
| [`tasks/index.json`](tasks/index.json) | **46 个机读任务**：每条含 id / title / risk / playbook / preconditions / verify / rollback / offline / refs 等字段 |
| [`SKILL.md`](SKILL.md) | 主技能：设备档案 + A→V 有序任务路由表（含 T1–T5 任务包速查 + maye 分类分册） |

**最小接入方式**：让 Agent 先读 `AGENTS.md`，按 `tasks/index.json` 的任务 id 精确取用 playbook，而不是通读全库。

## 任务包（T1–T5 + maye 分类分册）

| 任务包 | Playbook | 离线素材 |
|---|---|---|
| **T1 · OpenClash 安装 + 内核拉取** | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | `offline/openclash/luci-app-openclash_0.47.156_all.ipk`、`offline/core/mihomo-linux-arm64.gz`、6 个 stub ipk、脱敏 config 模板 |
| **T2 · ocspeed 安装** | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | `offline/ocspeed/` 五件套（speedswitch.sh / ocspeed.lua / ocspeed.htm / nodetest.htm / config.ocspeed）+ 一键装脚本 `kp-ocspeed.sh` |
| **T3 · Docker + 1Panel 安装** | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | `offline/panel/` 六脚本（install / kp-install / kp-storage-init / kp-store-lib / kp-store-check / kp-ui）+ `scripts/payload/` host 网络默认化三件套 |
| **T4 · 清空 Docker 环境（重装前置）** | [`tasks/04-docker-purge.md`](tasks/04-docker-purge.md) | `scripts/payload/kp-docker-purge.sh`（默认 dry-run，双开关才真删，动手前自动备份快照） |
| **T5 · 第三方 NROS 插件安装器（maye 助手）· 总入口** | [`tasks/05-nros-plugin-installer.md`](tasks/05-nros-plugin-installer.md) | 无离线素材（设备侧在线下载 + sha256 校验）；适配器 `scripts/adapt_maye_assistant.py` |
| **T5-a · 分类一 常用插件安装** | [`tasks/06-nros-plugins-common.md`](tasks/06-nros-plugins-common.md) | 同上（红线：哈基米＝装 OpenClash / AGH·MosDNS 抢 53 / ttyd 默认免登录） |
| **T5-b · 分类二 VPN / 组网 / 路由向导** | [`tasks/07-nros-network-route.md`](tasks/07-nros-network-route.md) | 同上（destructive：写 `ip rule`，本机全网出口＝断网风险） |
| **T5-c · 分类三 游戏加速器** | [`tasks/08-nros-game-accel.md`](tasks/08-nros-game-accel.md) | 同上（destructive：明文 HTTP 下载 root 脚本，无校验和） |
| **T5-d · 分类四 应用商店与页面美化** | [`tasks/09-nros-appcenter-polish.md`](tasks/09-nros-appcenter-polish.md) | 同上（会覆盖商店补丁载体 `appcenter.htm` / `appcenter.lua`） |
| **T5-e · 分类五 设备维护与检测** | [`tasks/10-nros-maintenance.md`](tasks/10-nros-maintenance.md) | 同上（红线：`5 › 11` 硬件加速会 `fw3 reload`） |

每个 playbook 都包含：前置条件 → 步骤（含离线/在线两条路径）→ 验证命令 → 回滚方法 → 已知坑。
T5 的五个分类分册另外各自带**本分类专属红线表**与**跑前/跑后对照项**。

## 目录结构

```
├── AGENTS.md / llms.txt / SKILL.md     # AI 入口与路由
├── tasks/                              # index.json(46 任务) + 10 份 playbook（含清空 Docker / maye 助手 + 五个分类分册）
├── references/                         # 23 篇专题文档（含 id/tags/risk frontmatter）
├── docs/                               # 调优经验总览 · 验收清单 · 助手菜单提示词 · 仓库维护指南
├── assets/menu/                        # 菜单软件图标（10 枚 32px PNG，jsdelivr 引用）
├── offline/                            # 离线安装素材 + checksums.md5（21 项）
├── scripts/                            # PC 侧驱动 + payload/（host 网络三件套、回归自测）
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
