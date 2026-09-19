# 路由器运维脚本的终端界面（kp-ui.sh）

**什么时候用**：给设备写/改运维脚本，用户要求「界面要好看、要能维护」时。
不要在每个脚本里各写一套 printf —— 抽成独立界面库，脚本只调用 `ui_*` 函数。

**落地位置**：`kp-docker1panel/kp-ui.sh`（库）+ `kp-ui-preview.sh`（预览，改完跑它看效果）。
三个脚本（`kp-install.sh` / `kp-storage-init.sh`）里已经不出现任何 printf。

## API

| 函数 | 用途 |
|---|---|
| `ui_init "标题" "副标题"` | 脚本头（上下各一条分隔线） |
| `ui_meta 标签 值` | 头部信息行，**标签统一写 2 个汉字**才能上下对齐 |
| `ui_stage 序号 总数 "标题"` | 阶段头：自动画进度条 + 开始计时 |
| `ui_stage_end` | 阶段尾：自动打印本阶段耗时（`↳ 12s`） |
| `ui_ok` / `ui_info` / `ui_warn` / `ui_err` | 四态：绿 `✓` / 灰 `·` / 黄 `!` / 红 `✗` |
| `ui_note "说明"` | 条目下的缩进补充说明（4 空格） |
| `ui_kv 键 值` | 汇总区键值对 |
| `ui_fail "原因" "怎么办"` | 原因 + 解决办法 + 幂等提示，然后 `exit 1` |
| `ui_done` / `ui_hr` / `ui_hr2` / `ui_gap` | 收尾 / 细灰线 / 粗绿线 / 空行 |

## 三条硬约束（踩坑得来，改界面时不能破）

1. **只用 busybox sh + printf** —— 路由器上没有 `tput`，也不保证能装 bash 数组，
   所以全部用最朴素的 `while` 循环和 `printf` 实现（`_rep` 铺分隔线、`ui_bar` 画进度条）。
2. **中文在终端占 2 列，但 `${#s}` 按字节算**，两者不一致
   → **一律左对齐，绝不做右边框、右对齐**。一旦按字符数补空格对齐，中文一多就全歪。
   连 banner 都不画右边框，就是这个原因。
3. **输出被重定向时自动关色**（`[ -t 1 ]` 判断），免得日志里全是 `\033` 乱码；
   `UI_COLOR=always|never` 可强制，`UI_W=48` 改分隔线宽度。

## 其他约定

- **取脚本目录不能用 `dirname`** —— 本机 PortableGit 的 PATH 里没有它。用纯参数扩展：
  ```sh
  KP_DIR=${0%/*}; [ "$KP_DIR" = "$0" ] && KP_DIR=.
  . "$KP_DIR/kp-ui.sh"
  ```
- **界面库必须和主脚本同目录**：主脚本靠 `$0` 找它。
  所以 `remote-install.sh` 这类引导器要**连界面库一起下载**；手动 pscp 也要两个都传。
- **阶段编号只给真阶段**。汇总/收尾不算阶段，不占编号，否则进度条永远到不了 100%。
  例：预检 → OpenClash → Docker → 1Panel 是 `[1/4]`…`[4/4]`，最后 `ui_done` 汇总。

## 本机验证（不要试图开真终端）

Bash 工具缺命令、PowerShell 起 shell 会被沙箱拦（`Spawning a non-PowerShell shell ... bypasses command validation`）。
**唯一可靠路径**：用 node 的 `execFileSync` 调 PortableGit 的 bash，输出由 **node 自己写文件**：

```js
const { execFileSync } = require('child_process');
const BASH = 'C:/Users/91005/.workbuddy/binaries/PortableGit/versions/1.2.0/bin/bash.exe';
// 语法检查
execFileSync(BASH, ['-n', 'kp-install.sh'], { stdio: 'pipe' });
// 试跑（必须显式 export PATH，否则 date/dirname/cat 全找不到）
const out = execFileSync(BASH, ['-c',
  "export PATH=/usr/bin:/bin; cd '<目录>'; UI_COLOR=never bash kp-install.sh"], { stdio: 'pipe' });
fs.writeFileSync('render.txt', out.toString(), 'utf8');
```

**两个编码陷阱**：

- 经 PowerShell 中转，UTF-8 中文会变 `鈹€鈹€` 之类，ESC 颜色序列也会坏掉 ——
  **看起来像脚本输出错乱，其实是中转毁的**。必须让 bash/node 直接写文件再读。
- `Out-File -Encoding utf8` 会写 BOM。

**试跑能验到哪一步**：本机不是 OpenWrt，`uci`/`opkg` 都没有，脚本会在第一条 root 检查处
停下 —— 但这足够验证 banner、阶段头、进度条、条目、失败提示全部渲染正确。
