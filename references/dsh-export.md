---
id: REF-dsh-export
title: "把 WorkBuddy 技能导出成 DeepSeek Harness (DSH) 技能"
tags: [dsh, deepseek-harness, skill-export]
risk: low
preconditions:
  - "本机已装 DSH（npm 全局 @deepseek-ai/dsh）"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# 把 WorkBuddy 技能导出成 DeepSeek Harness (DSH) 技能

> 2026-09-12 实测落地。用途：把本技能包（以及其它 WorkBuddy 技能）搬到 DSH 里复用。

## 一、DSH 的技能加载规则（来自 `dsh-skill-filesystem` README）

**扫描根（按 rank，数字小者优先）**

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | `project-dsh` | `<项目根>/.dsh/skills` |
| 200 | `project-agents` | `<项目根>/.agents/skills` |
| 300 | `custom` | 配置项 `customSkillDirs` |
| 400 | `user-dsh` | **`~/.dsh/skills`** ← 全局生效，最省事 |
| 500 | `user-agents` | `~/.agents/skills` |

- 项目根 = 最近的含 `.git` 的祖先目录；没有则用当前 cwd
- 用户根会跳过其 `.system` 子目录
- **该插件已默认挂在 `dsh-base` 的 bundle 里**（`cordis.patch.yml` 第 276 行 `id: skill-filesystem`），**不需要改配置**

**技能形态**

- 目录束 `<name>/SKILL.md`，或平铺文件 `<name>.md`
- **只扫一层**：`**/SKILL.md` 这种深层嵌套**不会被发现**
- YAML frontmatter **必填 `name` + `description`**
- 可选：`whenToUse`、`metadata`、`disable-model-invocation`、`user-invocable`
- 布尔键写错拼法或给非布尔值 → **整个技能被丢弃并打警告**，不是静默放行
- **目录 / 正文分离**：发现阶段只解析 frontmatter 建目录；每次加载都重读文件 → **改正文不用清缓存 / 不用版本号**
- 文件监听（chokidar）：新增 / 改名 / 删除技能、或**改 frontmatter** 会触发目录刷新；**只改 `references/` `scripts/` 等资源不触发**（本来也不需要）
- 缺失的根会用 `fs.watchFile` 轮询一个路径段，直到 chokidar 能挂上

## 二、转换要点（WorkBuddy → DSH）

| WorkBuddy | DSH | 处理 |
|---|---|---|
| `name` | `name` | 保留 |
| `description` | `description` | 保留（DSH 靠它做触发判断，别删） |
| `agent_created: true` | — | **删掉**（DSH 不认这个键） |
| — | `whenToUse` | **新增**，写"什么时候用我" |
| — | `metadata` | 新增，存 `source` / `exportedAt` 等溯源信息 |

**踩坑**：`description` 里的中文冒号必须是**全角 `：`**。若写成 ASCII `: `，
在 YAML plain scalar 里会被解析成键值分隔符，**frontmatter 直接坏掉**。

## 三、一键脚本

`C:\Users\91005\WorkBuddy\2026-09-06-00-21-37\_build_dsh_export.py`

它做三件事：① 按 `PLAN` 字典复制技能目录树；② 转换根 `SKILL.md` 的 frontmatter；
③ 自检 `name` / `description` / `whenToUse` 存在且无 `agent_created` 残留。

配套校验脚本 `_verify_dsh_skills.py`（**要用装了 PyYAML 的解释器跑**）：

```
# 建隔离 venv 并装 pyyaml（只需一次）
& "C:\Users\91005\.workbuddy\binaries\python\versions\3.13.12\python.exe" `
    -m venv "C:\Users\91005\.workbuddy\binaries\python\envs\default"
& "...\envs\default\Scripts\python.exe" -m pip install pyyaml

# 校验装到 ~/.dsh/skills 的技能
& "...\envs\default\Scripts\python.exe" "C:\...\_verify_dsh_skills.py"
```

校验项：**无 BOM**、合法 UTF-8、frontmatter 可被 YAML 解析、键集合 ⊆ DSH 允许集、
`name` 与目录名一致、正文 CJK 字符数达标、无控制字符污染。

## 四、坑

| 症状 | 原因 | 修法 |
|---|---|---|
| 导出脚本重跑后**手工新增的技能没了** | 脚本开头 `shutil.rmtree(EXPORT)` 整目录清空，只重建 `PLAN` 里的技能 | 改成**只删 `PLAN` 里的子目录**；或先备份手工技能 |
| 导入后 DSH 里看不到技能 | 路径嵌套超一层；或 frontmatter 缺 `name`/`description`；或布尔键拼错 | 确认是 `<root>/<name>/SKILL.md`；用第三节脚本逐项核 |
| 用 PowerShell 看 `SKILL.md` 显示乱码 | **PowerShell 控制台回显问题**，不是文件损坏 | 走**字节层**核对（Python 解码 + CJK 计数），别信回显 |
| 改 <code>references/</code> 后 DSH 没刷新 | 资源文件变更**不触发**目录刷新 | 正常行为。要么等下次 frontmatter 变动，要么重启 DSH |

## 五、文件落点

- 源（WorkBuddy）：`C:\Users\91005\.workbuddy\skills\`
- 导出中间产物：`C:\Users\91005\WorkBuddy\2026-09-06-00-21-37\dsh-skills-export\`
- 目标（DSH）：`C:\Users\91005\.dsh\skills\`
