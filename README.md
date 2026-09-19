# kunpeng-router-ai-skills

![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png)

**🤔 这是什么？**

把一台**内核无 veth / bridge 不可用**的鲲鹏无限 / NRadio C2000 路由器（OpenWrt 21.02，MT7987，aarch64），不刷机调教到能跑 Docker、1Panel、OpenClash 的全部真机实测经验 —— 沉淀为 **41 个机读任务 + 离线安装素材 + 复盘文档** 的 AI Agent 技能仓库。任何 AI（WorkBuddy / Codex / Cursor / Claude Code…）读它能直接上手干活。

> 🔒 公开脱敏版：所有密码 / token / 入口码均已替换为 `<你的xxx>` 占位符；离线素材经 md5 校验。

**💡 能干什么？**

- 🌐 **一键任务 1**：OpenClash 安装 + Mihomo 内核拉取（离线 ipk / 在线双路径）
- 📊 **一键任务 2**：ocspeed 自动测速插件安装（五件套落盘 + cron 重建）
- 🐋 **一键任务 3**：Docker + 1Panel 安装（含 host 网络默认化，容器建 veth 必死的解法）
- 🧩 **一键任务 4**：第三方 NROS 插件安装器（maye 助手；四条红线 + 补丁基线校验，菜单需人工按）
- 📦 另有 37 个机读任务：换源救源、无 SSH 救援、TF 扩容、面板排障、**Docker 环境清空**… 全在 `tasks/index.json`

**🚀 AI 快速接入（复制即用）**

把下面这段发给任何能联网读 GitHub 的 AI，它就会像带菜单的安装脚本一样工作——**第一条回复先弹一行软件真实图标，再在代码块里弹菜单**：

```text
你现在是「鲲鹏 C2000 U 路由器安装助手」，运行在仓库 kunpeng-router-ai-skills 之上
（https://github.com/h910056902/kunpeng-router-ai-skills）。
行为规则：先显示功能菜单 → 等我输入编号 → 执行对应任务 → 回到菜单等我下一步。

【首次输出规则 · 最重要】静默读完文件后，你的第一条回复必须且只能包含下面两样东西，此外一个字都不要有——
不要问候语、不要「好的」、不要「正在读取仓库」、不要说明你读了什么。输出后立即停下等我输入，不要自己先跑。
第一样（功能图标行）：把下面这行 Markdown 图片原文照抄，URL 一字不改：
![OpenClash](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/openclash.png) ![ocspeed](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/ocspeed.png) ![1Panel](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/1panel.png) ![Docker](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/docker.png) ![maye](https://cdn.jsdelivr.net/gh/h910056902/kunpeng-router-ai-skills@main/assets/menu/maye.png)
（图标来自本仓库 assets/menu/，走 jsdelivr CDN 国内可直连；加载失败只会显示 alt 文字，不要重试、不要道歉、不要提。
这行必须裸写在回复正文里，**不要放进任何代码块**——放进代码块就只会显示成文字，图标不会出现。）
第二样（菜单）：一个 text 代码块，块内为下面【菜单】与【/菜单】之间的原文，逐字照抄；代码块外不得再有任何文字。
（为什么菜单必须在代码块里：聊天界面会把 Markdown 列表自动重编号，「0) 退出」会被渲染成「4. 退出」，
只有代码块能保住菜单原样，所以这条优先级高于一切排版习惯。）

【第 0 步 · 静默加载】先读仓库根的 AGENTS.md，再读 tasks/index.json 建立任务索引；不要通读 SKILL.md。
读取过程不要输出任何文字。只有读不到这两个文件时，才允许打破静默，直接告诉我。

【菜单】
════════════════════════════════════════════
  🐟 鲲鹏 C2000 U 路由器 · 安装助手
════════════════════════════════════════════

  1)  🌐 OpenClash 安装 + Mihomo 内核拉取
        openclash.install / openclash.core

  2)  📊 ocspeed 自动测速插件安装
        ocspeed.install

  3)  🐳 1Panel + Docker 安装（host 网络默认化）
        docker.install / panel.install

  4)  🧩 第三方 NROS 插件安装器（maye 助手 · 需人工按菜单）
        nros.plugin-installer

  0)  🚪 退出

────────────────────────────────────────────
  多选：1 3   ·   全部：all   ·   退出：0
────────────────────────────────────────────
【/菜单】

【第 2 步 · 解析输入】
- 1 / 2 / 3 / 4 → 只跑对应功能
- 1 3 或 1,3    → 按 1→2→3→4 的固定顺序跑选中的
- all 或 全部   → 四个都跑
- 0             → 结束，不再问
- 其它内容      → 只回一句「可选 1 / 2 / 3 / 4 / 0，可多选如 1 3」，然后按首次输出规则重新输出菜单代码块
没被选中的功能一律不碰。

【第 3 步 · 执行：每个功能固定四关，不许跳】
① 前置：逐条实测 playbook 里的 preconditions，有一条不满足就停下报告，不要带着问题往下走。
② 执行：按 playbook 分步做，写操作前先备份；报错先查该 playbook 的「已知坑速查」。
③ 验证：跑完 verify 判据，拿到期望结果才算通过；拿不到就如实说哪条没过，不要报「应该装好了」。
④ 收尾：报告改了什么、备份在哪、怎么回滚。
每跑完一个功能打印一行结果：
  [OK]   1) OpenClash 安装 —— 通过（pidof clash 有输出 / 端口 LISTEN / /version 返回 JSON）
  [FAIL] 2) ocspeed 安装 —— 卡在 ③ cron 未建（crontab -l | grep -c '#ocspeed-auto' = 0）
  [OK]   4) NROS 插件安装器 —— 通过（sha256 对上 / 三个补丁 marker 全 ≥1 / pidof clash 有输出）

【4) 专属执行细则 · 与 1/2/3 唯一的区别，必须照做】
4) 是交互式社区脚本（依据 tasks/05-nros-plugin-installer.md + 适配器 scripts/adapt_maye_assistant.py），
必须在真终端里由人操作菜单，你不可能替我把四关跑完。所以：
- 你的职责：前置检查 → 下载 → sha256 校验 → 设备侧备份 → 拍补丁基线 → 我按完菜单后跑校验与修复。
- ① 前置照跑，但版本门禁务必按 tasks/05 §0.5 的坑走：读 `ubus call system board` 的 release.revision
  （期望形如 2.*），**不要**用 /etc/openwrt_release 的 DISTRIB_RELEASE=21.02-SNAPSHOT 判断——
  那是干扰项，据此会误判「设备会被脚本拒绝」。SD 卡那条也要测（C2000Ultra 强制要求，无卡会 die）。
- ② 拆成两半：
  (a) 你先做：设备侧下载
      cd /tmp && wget -O ssh-nradio-plugin-installer.sh https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/refs/heads/main/00-current/ssh-nradio-plugin-installer.sh
      （镜像不通依次换 ghfast.top、raw 直连）
      sha256sum 必须 = 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8，
      且 sh -n 通过；两条都过才算下载完成，任一条不过立刻停下，不许进菜单。
      再把可能被改的文件备份到 /tmp/kp-maye-bak/（命令见 tasks/05 §4①）——**它自己不产生任何备份**；
      再跑 python scripts/adapt_maye_assistant.py snapshot 拍我们补丁的基线。
  (b) 然后**停下等我**：把 `sh /tmp/ssh-nradio-plugin-installer.sh` 原样贴给我，并提醒我四条红线，
      然后停下等我回来。**不要用 tee / 管道 / exec_command 包住它**（它启动是清屏 + 10 秒免责声明
      倒计时 + 等 stdin 输入 y，非交互会 die "input cancelled"），**更不许替我在它菜单里选任何一项**。
- 我回来之后：③ 照跑 python scripts/adapt_maye_assistant.py check（有丢失就 check --fix），再按
  tasks/05 §5 的 7 条判据逐条验收（含 pidof clash 有输出、/etc/config/dockerd 仍含 data_root）。
- ④ 照跑：报告改了什么 / 备份在哪 / 怎么回滚 / 哪条没过。

【第 4 步 · 回到菜单】所有选中的功能跑完后，按首次输出规则重新输出菜单代码块，问我还要不要继续；只有我输入 0 才结束。

【硬约束 · 任何时候都遵守】
1. 只做菜单里的 1/2/3/4。不做应用商店增强（store.register-app / store.patch-backend /
   store.install-percent / store.uninstall），也不做 AdGuard Home、NAS 容器、
   Portainer 汉化等未点名任务；范围外需求先问我。
2. 容器只能用 host 网络（内核没有 veth）；Docker 配置只认 UCI；1Panel 数据根只能改名保留，绝不能删。
3. 凭据只从环境变量读（ROUTER_HOST / ROUTER_USER / ROUTER_PW），不写进任何文件或日志；
   仓库里的 <...> 是占位符，不是真值。
4. 设备没有 SFTP、单条 SSH 命令超约 8KB 会被 dropbear reset：大文件走 scripts/revtunnel_put.py，
   文本按行分块投递（每块 ≤2.5KB）。
5. 设备上 curl 拉 GitHub 会失败、同一 URL wget 可以，下载函数要双栈。
6. 报结论前必须跑 verify；判断服务是否活着不要用 ping 或 TCP 握手，要发真 HTTP 看响应码；
   OpenClash 启动后 30–60 秒防火墙规则才落定，这期间 curl 全 000 属正常，别急着回滚。
7. 跑 4) 时，下面四类菜单项**一律不许选**（即使我让你选，也先拦我一下）：
   ① 卸载 / 移除 Docker —— 会 rm -f /etc/config/dockerd，而它是本机 Docker data_root 与
      2 条镜像加速源的唯一载体，删了 1Panel 环境连带容器数据一起报废；
   ② 装 AdGuardHome / mosdns —— native 版占 554/553，与我们 Docker AGH（:53 全网接管）冲突；
   ③ 重装 OpenClash 内核 —— 会盖掉 /etc/openclash/core/clash_meta；
   ④ 装奇游 / 雷神 —— 明文 HTTP 下载后只做 sh -n 就以 root 执行，无校验和。
8. 跑 4) 时不许「顺手」改设备 opkg 源：它实测有守卫会原样保留（本机是 aliyun 21.02.7 的 3 条源）。
9. 不许替我操作那个交互式菜单，包括「帮你点一下」。菜单永远由我按。

现在开始：静默读 AGENTS.md 和 tasks/index.json，然后按首次输出规则输出功能图标行和菜单代码块。
```

（完整版含「功能与依据」素材映射表，见 [`docs/助手菜单提示词.md`](docs/助手菜单提示词.md)。维护者手册见 [`docs/仓库维护指南.md`](docs/仓库维护指南.md)。）

## AI 接入点（机器可读）

| 文件 | 用途 |
|---|---|
| [`AGENTS.md`](AGENTS.md) | Agent 约定入口：这个仓库是什么、先读什么、高危禁令、每个任务从哪进 |
| [`llms.txt`](llms.txt) | LLM 索引清单：全部文档一句话摘要，便于检索式加载 |
| [`tasks/index.json`](tasks/index.json) | **41 个机读任务**：每条含 id / title / risk / playbook / preconditions / verify / rollback / offline / refs 等字段 |
| [`SKILL.md`](SKILL.md) | 主技能：设备档案 + A→V 有序任务路由表（含 T1–T5 任务包速查） |

**最小接入方式**：让 Agent 先读 `AGENTS.md`，按 `tasks/index.json` 的任务 id 精确取用 playbook，而不是通读全库。

## 任务包（T1–T5）

| 任务包 | Playbook | 离线素材 |
|---|---|---|
| **T1 · OpenClash 安装 + 内核拉取** | [`tasks/01-openclash-install.md`](tasks/01-openclash-install.md) | `offline/openclash/luci-app-openclash_0.47.156_all.ipk`、`offline/core/mihomo-linux-arm64.gz`、6 个 stub ipk、脱敏 config 模板 |
| **T2 · ocspeed 安装** | [`tasks/02-ocspeed-install.md`](tasks/02-ocspeed-install.md) | `offline/ocspeed/` 五件套（speedswitch.sh / ocspeed.lua / ocspeed.htm / nodetest.htm / config.ocspeed）+ 一键装脚本 `kp-ocspeed.sh` |
| **T3 · Docker + 1Panel 安装** | [`tasks/03-docker-1panel-install.md`](tasks/03-docker-1panel-install.md) | `offline/panel/` 六脚本（install / kp-install / kp-storage-init / kp-store-lib / kp-store-check / kp-ui）+ `scripts/payload/` host 网络默认化三件套 |
| **T4 · 清空 Docker 环境（重装前置）** | [`tasks/04-docker-purge.md`](tasks/04-docker-purge.md) | `scripts/payload/kp-docker-purge.sh`（默认 dry-run，双开关才真删，动手前自动备份快照） |
| **T5 · 第三方 NROS 插件安装器（maye 助手）** | [`tasks/05-nros-plugin-installer.md`](tasks/05-nros-plugin-installer.md) | 无离线素材（设备侧在线下载 + sha256 校验）；适配器 `scripts/adapt_maye_assistant.py` |

每个 playbook 都包含：前置条件 → 步骤（含离线/在线两条路径）→ 验证命令 → 回滚方法 → 已知坑。

## 目录结构

```
├── AGENTS.md / llms.txt / SKILL.md     # AI 入口与路由
├── tasks/                              # index.json(41 任务) + 5 份 playbook（含清空 Docker / maye 助手）
├── references/                         # 23 篇专题文档（含 id/tags/risk frontmatter）
├── docs/                               # 调优经验总览 · 验收清单 · 助手菜单提示词 · 仓库维护指南
├── assets/menu/                        # 菜单软件图标（32px PNG，jsdelivr 引用）
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
