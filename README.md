# kunpeng-router-ai-skills

**🤔 这是什么？**

把一台**内核无 veth / bridge 不可用**的鲲鹏无限 / NRadio C2000 路由器（OpenWrt 21.02，MT7987，aarch64），不刷机调教到能跑 Docker、1Panel、OpenClash 的全部真机实测经验 —— 沉淀为 **39 个机读任务 + 离线安装素材 + 复盘文档** 的 AI Agent 技能仓库。任何 AI（WorkBuddy / Codex / Cursor / Claude Code…）读它能直接上手干活。

> 🔒 公开脱敏版：所有密码 / token / 入口码均已替换为 `<你的xxx>` 占位符；离线素材经 md5 校验。

**💡 能干什么？**

- 🌐 **一键任务 1**：OpenClash 安装 + Mihomo 内核拉取（离线 ipk / 在线双路径）
- 📊 **一键任务 2**：ocspeed 自动测速插件安装（五件套落盘 + cron 重建）
- 🐋 **一键任务 3**：Docker + 1Panel 安装（含 host 网络默认化，容器建 veth 必死的解法）
- 📦 另有 36 个机读任务：换源救源、无 SSH 救援、TF 扩容、面板排障… 全在 `tasks/index.json`

**🚀 AI 快速接入（复制即用）**

把下面这段发给任何能联网读 GitHub 的 AI，它就会像带菜单的安装脚本一样工作：

```text
你现在是「鲲鹏 C2000 U 路由器安装助手」，运行在仓库 kunpeng-router-ai-skills 之上
（https://github.com/h910056902/kunpeng-router-ai-skills）。
你的行为要像一个带菜单的安装脚本：先显示功能列表 → 等我输入编号 → 执行对应任务 → 回到菜单等我下一步。

【第 0 步 · 加载索引】先读仓库根的 AGENTS.md，再读 tasks/index.json 建立任务索引，
不要通读 SKILL.md。读不到就直接告诉我，不要凭记忆猜。

【第 1 步 · 显示菜单】把下面这张表原样打印出来，然后停下来等我输入，不要自己先跑：

  === 鲲鹏路由器安装助手 ===
  请选择要执行的功能（可多选，用空格或逗号分隔，例如：1 3）
    1) OpenClash 安装 + Mihomo 内核拉取            [openclash.install → tasks/01-openclash-install.md]
    2) ocspeed 自动测速插件安装                     [ocspeed.install → tasks/02-ocspeed-install.md]
    3) 1Panel + Docker 安装（含 host 网络默认化）   [docker.install → tasks/03-docker-1panel-install.md]
    0) 退出

【第 2 步 · 解析我的输入】1/2/3 只跑对应功能；「1 3」或「1,3」按 1→3 固定顺序；
all/全部 三个都跑（1→2→3）；0 结束；输入菜单外内容就重新显示菜单。没被选中的一律不碰。

【第 3 步 · 执行（每个功能固定四关，失败即停）】
① 前置——逐条实测 playbook 的 preconditions，有一条不满足就停下报告；
② 执行——按 playbook 分步做，写操作前先备份，报错先查 SKILL.md 末尾「踩坑速查」；
③ 验证——跑完 verify 判据，拿到期望结果才算通过，拿不到就如实说哪条没过；
④ 收尾——报告改了什么 / 备份在哪 / 怎么回滚。
每跑完一个功能打印一行：[OK] 1) OpenClash 安装 —— 通过（判据…） 或 [FAIL] 2) ocspeed —— 卡在 ③ cron 未建。

【第 4 步 · 回到菜单】全部跑完后重新打印菜单，问我还要不要继续，只有输入 0 才结束。

【硬约束】只做菜单里的 1/2/3，不做商店增强（store.*）/AdGuard/NAS 等未点名任务；
容器只能 host 网络；凭据只从环境变量读；报结论前必须跑 verify。

现在开始：读 AGENTS.md 和 tasks/index.json，然后显示菜单。
```

（完整版含执行四关与素材对应关系，见 [`docs/助手菜单提示词.md`](docs/助手菜单提示词.md)。）

## AI 接入点（机器可读）

| 文件 | 用途 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent 约定入口：这个仓库是什么、先读什么、高危禁令、每个任务从哪进 |
| [`llms.txt`](llms.txt) | LLM 索引清单：全部文档一句话摘要，便于检索式加载 |
| [`tasks/index.json`](tasks/index.json) | **39 个机读任务**：每条含 id / title / risk / playbook / preconditions / verify / rollback / offline / refs 等字段 |
| [`SKILL.md`](SKILL.md) | 主技能：设备档案 + A→V 有序任务路由表（含 T1/T2/T3 任务包速查） |

**最小接入方式**：让 Agent 先读 `AGENTS.md`，按 `tasks/index.json` 的任务 id 精确取用 playbook，而不是通读全库。

## 三大任务包

| 任务包 | Playbook | 离线素材 |
|---|---|---|
| **T1 · OpenClash 安装 + 内核拉取** | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | `offline/openclash/luci-app-openclash_0.47.156_all.ipk`、`offline/core/mihomo-linux-arm64.gz`、6 个 stub ipk、脱敏 config 模板 |
| **T2 · ocspeed 安装** | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | `offline/ocspeed/` 五件套（speedswitch.sh / ocspeed.lua / ocspeed.htm / nodetest.htm / config.ocspeed）+ 一键装脚本 `kp-ocspeed.sh` |
| **T3 · Docker + 1Panel 安装** | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | `offline/panel/` 六脚本（install / kp-install / kp-storage-init / kp-store-lib / kp-store-check / kp-ui）+ `scripts/payload/` host 网络默认化三件套 |

每个 playbook 都包含：前置条件 → 步骤（含离线/在线两条路径）→ 验证命令 → 回滚方法 → 已知坑。

## 目录结构

```
├── AGENTS.md / llms.txt / SKILL.md     # AI 入口与路由
├── tasks/                              # index.json(39 任务) + 3 份 playbook
├── references/                         # 23 篇专题文档（含 id/tags/risk frontmatter）
├── docs/                               # 调优经验总览（12 领域）· 新会话验收清单 · 助手菜单提示词
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
