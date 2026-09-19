# kunpeng-router-ai-skills

**AI Agent Skill for 鲲鹏无限 / NRadio C2000 Max / C2000 U (OpenWrt 21.02, aarch64) router deep-tuning.**

这是一个面向 AI Agent（WorkBuddy / Codex / Cursor / Claude Code 等）的技能仓库：把一台**内核无 veth、 bridge 不可用**的 MT7987 OpenWrt 路由器调教到能跑 Docker、1Panel、OpenClash、AdGuard Home、NAS 容器的全部经验，沉淀为**机器可读的任务清单 + 离线安装素材 + 复盘文档**。

> 安全说明：本仓库为公开脱敏版。所有密码 / token / 入口码均已替换为 `<你的xxx>` 占位符；离线素材经 md5 校验，与私有档案仓库逐字节一致。

---

## AI 接入点（机器可读）

| 文件 | 用途 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent 约定入口：这个仓库是什么、先读什么、高危禁令、每个任务从哪进 |
| [`llms.txt`](llms.txt) | LLM 索引清单：全部文档一句话摘要，便于检索式加载 |
| [`tasks/index.json`](tasks/index.json) | **39 个机读任务**：`id / title / group / risk / playbook / refs / preconditions / verify / rollback` |
| [`SKILL.md`](SKILL.md) | 主技能：设备档案 + A→V 有序任务路由表（含 T1/T2/T3 任务包速查） |

**最小接入方式**：把本仓库目录投喂给 Agent，让它先读 `AGENTS.md`，按 `tasks/index.json` 的任务 id 精确取用 playbook，而不是通读全库。

## 三大任务包（本次核心交付）

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
├── docs/                               # 调优经验总览（12 领域）· 新会话验收清单
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
