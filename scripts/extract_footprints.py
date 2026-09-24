# -*- coding: utf-8 -*-
"""从上游 maye 安装器（ssh-nradio-plugin-installer.sh）里抽出「每个功能写了哪些盘」。

为什么要它：本项目要求「清除逻辑全部自写、不依赖上游 cleanup_*」，
而自写的前提是**精确知道每个功能都写了什么**（包、uci 键、服务、rc.d 软链、
hotplug、cron、rc.local 段、数据目录、商店注册项、网络规则、补丁 marker）。
人肉读 72,458 行不现实，所以这里半自动抽取，并把「抽不出来但看着像写盘」的行
单独塞进 unclassified 桶，交给真机只读审计（kp-clean.sh --audit）反向对账。

四趟解析：
  1. 函数地图：`^name() {` 到下一个行首 `}` —— 本脚本风格规整（4 空格缩进，
     函数收尾 `}` 一律顶格），故用「下一个顶格 }」比大括号配平更稳（后者会被
     字符串里的花括号带偏）。同时用「顶格 } 数 == 函数定义数」自校验。
  2. 分派：解析 run_menu_feature() 的 `case "$feature_choice"`，
     取「feature 号 → 菜单路径 / 标题 / 处理函数」。
  3. 菜单：解析所有含 print_menu_item 的函数，取「菜单号 → 标签」，
     以及 `case "$UI_READ_RESULT"` 里「菜单号 → feature 号」的映射。
  4. 写盘足迹：对处理函数做**传递闭包**（≤MAX_DEPTH 层）得到行区间集合，
     在区间内跑十一类正则；未命中任何类的 IO 行进 unclassified。

用法：
    python extract_footprints.py [--installer <路径>] [--out <footprint.json>] [--report <txt>]
默认从 <工作区>/_third/installer.sh 读，写到私有仓 tasks/footprint.json。
"""
import argparse
import hashlib
import io
import json
import os
import re
import sys
from collections import OrderedDict

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace", write_through=True)

WORKSPACE = r"C:\Users\91005\WorkBuddy\2026-09-19-12-19-57"
PRIVATE = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "kunpeng-router-tuning")
DEFAULT_INSTALLER = os.path.join(WORKSPACE, "_third", "installer.sh")
DEFAULT_OUT = os.path.join(PRIVATE, "tasks", "footprint.json")
DEFAULT_REPORT = os.path.join(WORKSPACE, "_footprint_report.txt")

MAX_DEPTH = 3           # 传递闭包层数
MAX_CLOSURE = 120       # 单个功能最多纳入多少个函数（防爆）
# 单个函数的行区间上限（防把整个脚本吞进来）。别调小：上游有 4 个「大文件写入器」
# 天然就是几千行 —— write_openvpn_custom_ui_files 13,582 行、extract_nradio_cpeopt_payload
# 8,199、write_adguard_wrapper_files 5,880、patch_appcenter_card_polish_legacy 5,133。
# 原来设 4000 会把它们的尾巴切掉，导致 L14419 那批写盘语句掉进「闭包外」。
MAX_RANGE = 20000

# 被 ≥SHARED_MIN 个功能共用的函数 = 公共设施（删单个插件时不能动）
SHARED_MIN = 3

# ---------------------------------------------------------------- 十一类写盘模式
# 每项：(类名, 正则, 说明)。正则在「已去掉行首缩进」的原始行上匹配。
WRITE_PATTERNS = [
    ("opkg", re.compile(r"\bopkg\s+(?:install|remove|download)\b[^\n]*")),
    ("uci", re.compile(r"\buci\s+(?:-q\s+)?(?:set|add_list|add|delete|rename|commit)\b[^\n]*")),
    ("initd", re.compile(r"/etc/init\.d/[A-Za-z0-9._-]+")),
    ("rcd", re.compile(r"/etc/rc\.d/[SK][0-9]*[A-Za-z0-9._-]*")),
    ("hotplug", re.compile(r"/etc/hotplug\.d/[A-Za-z0-9._/-]+")),
    ("cron", re.compile(r"(?:/etc/crontabs/root|\bcrontab\b|nradio-smart-band)")),
    ("rclocal", re.compile(r"(?:/etc/rc\.local|EASYTIER_ROUTE_WIZARD|OPENVPN_ROUTE_WIZARD)")),
    ("dirs", re.compile(
        r"(?:/etc/openclash|/etc/openlist|/etc/docker|/etc/qy(?:plug)?|/etc/acc\b|"
        r"/etc/config/accelerator|/opt/[A-Za-z0-9._-]+|/mnt/storage/[A-Za-z0-9._/-]+|"
        r"/overlay/[A-Za-z0-9._-]+|/usr/libexec/[A-Za-z0-9._-]+|/etc/kp_store)")),
    ("store", re.compile(r"(?:appcenter|plugin_uninstall|kp-store|installed\.list|routes\.list)")),
    ("net", re.compile(
        r"(?:\bip\s+rule\s+(?:add|del)|ip\s+-4\s+rule|\bip\s+route\s+(?:add|del|replace)|"
        r"uci\s+set\s+firewall|uci\s+set\s+mtkhnat|fw3\s+reload|mtkhnat|"
        r"\biptables\b|\bnft\b)")),
    ("marker", re.compile(
        r"(?:nradio_appcenter_extra_action|_kp_installed_registry|aurora_open_app|"
        r"Design By MaYe)")),
]

# 「看着像写盘但没被上面归类」的行 → 强制人工过目
IO_HINT = re.compile(
    r"(?:\brm\s+-[rf]+|\bmv\s+|\bcp\s+|\btar\s+|\bsed\s+-i\b|>\s*/(?!dev/null)|"
    r"\bmkdir\s+-p\b|\bchmod\b|\bln\s+-s\b|>>\s*/|\bswapon\b|\bswapoff\b|\btruncate\b)")

# 数据目录前缀白名单（用于把 dirs 类里的值归一成「目录」而非具体文件）
# ⚠️ 2026-09-21 收窄（B3）：这里**只允许放插件自建的业务目录**。原先混进了
#    /opt /mnt/storage /overlay /usr/libexec /usr/bin /usr/lib/lua/luci /usr/share ——
#    全是红线容器/固件目录。norm_dir 会把 `/usr/libexec/qy_acc` 折叠成 `/usr/libexec`，
#    「改某个文件」被放大成「占整个目录」，而 /usr/libexec 正是固件 7 个文件的所在目录。
#    收窄后这类路径保持**具体子路径**，由 CONTAINER_DIRS / path_is_forbidden 的
#    前缀匹配继续兜底 —— 精度更高，也不再误伤。
DIR_PREFIXES = [
    "/etc/openclash", "/etc/openlist", "/etc/docker", "/etc/qy", "/etc/acc",
    "/etc/config/accelerator", "/etc/kp_store",
]

# ---- /rom 出厂基线清单（B1/B2 的判据）----
# 真机只读采集：find /rom -type f（2026-09-21，C2000 U / NRadio_C2000Ultra，4121 条）。
# 「/rom<path> 存在 = 出厂就有，插件不可能是创建者，只能重置不能删」是本项目铁律。
# 因此 matches_baseline（与 /rom 逐字节比对）**只对出厂件成立**；对插件自建文件，
# /rom 无原件、cmp 恒假 —— 那是假谓词（/etc/config/accelerator 曾被 19 个 feature
# 这样误判，真机对账才揪出来）。⚠️ 换机型 / 升级固件后**必须重采**本清单。
ROM_MANIFEST = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "rom_baseline_c2000u.txt")
try:
    with open(ROM_MANIFEST, "r", encoding="utf-8") as _fh:
        ROM_FILES = set(l.strip() for l in _fh if l.strip().startswith("/rom/"))
except OSError:
    ROM_FILES = set()
if not ROM_FILES:
    # 清单缺失 = 无法判定「出厂件 vs 插件件」= 会批量生成假谓词。宁可失败也不产出。
    raise SystemExit("FATAL: 读不到 /rom 基线清单 %s —— 没有它就无法区分出厂件与插件件，"
                     "拒绝生成 footprint.json（先在真机上重采：find /rom -type f）" % ROM_MANIFEST)


def rom_has(p):
    """/rom 下是否存在 p（出厂件判定）。"""
    return ("/rom" + p) in ROM_FILES


def is_pseudo_fs(p):
    """/sys|/proc|/dev 出厂无原件、还原值由上游运行时决定 —— 不可能比对基线。"""
    return p.startswith("/sys/") or p.startswith("/proc/") or p.startswith("/dev/")

FUNC_RE = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*\(\)\s*\{")
CALL_RE = re.compile(r"(?<![\w./-])([a-z_][a-z0-9_]{2,})\b")


def read_lines(path):
    with open(path, "rb") as fh:
        raw = fh.read()
    txt = raw.decode("utf-8", "replace")
    return raw, txt.split("\n")


HEREDOC_RE = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1")


def compute_heredocs(lines):
    """标出所有 heredoc 正文行，并返回 (正文行集合, 区间清单)。

    上游脚本大量用 heredoc 往设备写文件（/etc/rc.local、/etc/crontabs/root、
    Lua 补丁、初始化脚本…），而 **heredoc 正文里经常出现顶格 `}`**（写进去的
    本身可能就是 ash 函数或 Lua 表）。这会被「下一个顶格 }」的函数边界法误判成
    函数收尾，把函数区间截断 —— 第一次跑就踩到了（1244 函数 vs 1305 个顶格 }）。

    所以：函数地图**跳过** heredoc 正文；但写盘抽取**不能跳过** ——
    正文本身就是被写进设备的内容，marker（如 EASYTIER_ROUTE_WIZARD）
    往往就藏在里面。

    返回的区间清单用来**自查「未闭合 heredoc」**：如果某个区间一直延伸到 EOF，
    说明分隔符没被识别（比如用了变量作分隔符），会把后面整段误判成正文 ——
    那是必须人工过目的信号。
    """
    body = set()
    regions = []
    i, n = 0, len(lines)
    while i < n:
        m = HEREDOC_RE.search(lines[i])
        if m:
            delim = m.group(2)
            j = i + 1
            closed = False
            while j < n:
                cand = lines[j]
                body.add(j)                       # 先当正文，命中分隔符再剔除
                if cand == delim or cand.strip() == delim or cand.lstrip("\t") == delim:
                    body.discard(j)
                    closed = True
                    break
                j += 1
            regions.append({"start": i + 1, "end": min(j + 1, n), "delim": delim,
                            "closed": closed})
            i = j + 1
            continue
        i += 1
    return body, regions


def classify_heredocs(lines, heredoc, regions):
    """把 heredoc 正文分成「脚本式」和「数据式」，返回两个行集合。

    **为什么必须分**（2026-09-20 发现，比「只抽 marker」的原设计严重得多）：

    上游有整整一类功能是「先用 heredoc 生成一个嵌入式安装脚本，再执行它」——
    ttyd / MosDNS / Open-Box / eFanCtrl / MT5700 / 5G 连接监听都是这个路数。
    真正写盘的动作（`uci -q set ttyd.default.port='7681'`、`printf > /etc/config/ttyd`）
    **全在正文里**。而 extract_writes 原本对**所有** heredoc 正文只抽 marker 一类，
    于是这些功能的写盘足迹被判成 0：

        feature 3「ttyd / Web SSH 安装」→ remove_paths 0 / stop_services 0 / uci_reset 0
        而它自己的 heredoc 正文（L54400~L56654，2253 行）里写着
        `/etc/init.d/ttyd`、`/etc/config/ttyd`、`webssh.lua`、`nradio_polish.htm` …

    另一类是「数据式」：写进设备的模板内容（LuCI 的 .htm、Lua 补丁、JSON 配置）。
    正文里的路径是**文件内容**，不是这个脚本要动的目标 —— 只能抽 marker。

    判据：正文首行是 shebang（`#!`）→ 脚本式。
    """
    script_lines, data_lines = set(), set()
    for r in regions:
        b0 = r["start"]          # 0-based 首行正文
        b1 = r["end"] - 1
        if b1 < b0 or b0 >= len(lines):
            continue
        is_script = lines[b0].strip().startswith("#!")
        for k in range(b0, b1 + 1):
            if k in heredoc:
                (script_lines if is_script else data_lines).add(k)
    return script_lines, data_lines


ASSIGN_RE = re.compile(r"^\s*(?:export\s+|local\s+)?([A-Za-z_][A-Za-z0-9_]*)=(?:\"([^\"]*)\"|'([^']*)'|(\S+))")
VARREF_RE = re.compile(r"\$\{?([A-Za-z_][A-Za-z0-9_]*)\}?")
REDIR_RE = re.compile(r"(?:>>?|\btee\b)\s*\"?([^\s\"';|&()]+)\"?")


def collect_var_paths(lines):
    """收集「变量 → 绝对路径」的赋值。

    上游把大量写盘目标存在变量里（`TPL=` 应用商店模板、`APPCENTER_CONTROLLER=`、
    `rc_file=` 等），所以只按正则扫字面路径会漏掉一大半 —— 第一次跑时
    unclassified 里 `cp "$tmp_css" "$TPL"` 成片出现就是这个原因。
    这里把 `VAR=/abs/path` 形式的赋值收起来，抽取时把 `$VAR` 还原成真实路径。
    """
    vp = {}
    for ln in lines:
        m = ASSIGN_RE.match(ln)
        if not m:
            continue
        val = m.group(2) or m.group(3) or m.group(4) or ""
        if val.startswith("/") and "$" not in val and len(val) > 3:
            vp.setdefault(m.group(1), val)
    return vp


def collect_var_literals(lines):
    """收集「变量 → 字面值」，**不限于是路径**。

    比 collect_var_paths 多出来的东西正是本轮缺的那块：
      · 注入标记常量 —— `NRADIO_OPERATOR_FIX_MARKER_BEGIN="<!-- nradio-operator-display-fix:start -->"`
      · 备份目录    —— `BACKUP_DIR="/root/nradio-plugin-fix"`
    没有它就只能靠「文件不存在」判卸载是否干净；有了它才能用
    `no_marker:<标记原文>` 这种**与上游 selfcheck 同源**的强判据。
    含 `$` 的值一律丢弃（无法静态求值，宁可退回人工）。
    """
    vl = {}
    for ln in lines:
        m = ASSIGN_RE.match(ln)
        if not m:
            continue
        val = m.group(2) or m.group(3) or m.group(4) or ""
        if val and "$" not in val and len(val) > 1:
            vl.setdefault(m.group(1), val)
    return vl


def resolve_ref(tok, var_paths):
    """把 `$VAR` / `${VAR}` / 字面路径 解析成绝对路径；解析不出就返回 None。"""
    if not tok:
        return None
    m = VARREF_RE.fullmatch(tok) or VARREF_RE.fullmatch(tok.strip('"'))
    if m:
        return var_paths.get(m.group(1))
    return tok if tok.startswith("/") else None


def menu_item_features(md):
    """把 `md['items']` 与 `md['maps']` 配成 [(item, feature|None), ...]。

    为什么不能直接用 (菜单号, cond) 配对：**两边的 cond 语义不同**。
      · items 的 cond  = 它被 `if 机型条件` 包住的层次
      · maps 的 cond   = 分派 `case`/`elif` 所在那一支的条件
    对字面编号分支两者恰好一致（`is_current_model_c8_788` == `is_current_model_c8_788`），
    但变量比较式分派那一支就不一样了：
        item cond = ""（在 case 之前打印）
        map  cond = `[ "$UI_READ_RESULT" = "$maintenance_health_choice" ]`
    于是 default 分支的 8 项全都配不上 → 报出来 `-> feature -`。
    解法：这种情况改用**变量名**配 —— item 的 expr 是 `$maintenance_health_choice`，
    map 的 cond 里正好含 `$maintenance_health_choice`。
    """
    by_nc = {(mp["no"], mp["cond"]): mp["feature"] for mp in md["maps"]}
    cand = {}
    for mp in md["maps"]:
        cand.setdefault(mp["no"], []).append(mp)
    out = []
    for it in md["items"]:
        f = by_nc.get((it["no"], it["cond"]))
        if f is None and it.get("expr"):
            var = re.sub(r"[^A-Za-z0-9_]", "", it["expr"])
            if var:
                for mp in cand.get(it["no"], []):
                    if var in mp["cond"]:
                        f = mp["feature"]
                        break
        if f is None:
            c = cand.get(it["no"], [])
            if len(c) == 1:
                f = c[0]["feature"]
        out.append((it, f))
    return out


def build_function_map(lines, heredoc):
    """返回 (name -> (start_idx, end_idx))，0-based、闭区间。

    本脚本风格规整（4 空格缩进、函数收尾一律顶格 `}`），故用「下一个**非 heredoc**
    的顶格 }」定位函数结尾 —— 比大括号配平稳，后者会被字符串与 `${...}` 带偏。
    """
    fmap = OrderedDict()
    n = len(lines)
    starts = []
    for i, ln in enumerate(lines):
        if i in heredoc:
            continue
        m = FUNC_RE.match(ln)
        if m:
            starts.append((m.group(1), i))
    for name, s in starts:
        e = None
        for j in range(s + 1, n):
            if j in heredoc:
                continue
            if lines[j] == "}":
                e = j
                break
        if e is None:
            e = min(s + MAX_RANGE, n - 1)
        fmap[name] = (s, e)
    # 自校验：非 heredoc 的顶格 } 数量应等于函数定义数
    top_close = sum(1 for i, ln in enumerate(lines) if ln == "}" and i not in heredoc)
    return fmap, len(starts), top_close


def nested_pairs(fmap):
    """找出「在别的函数体里定义」的函数（上游有 2 对，如 install_openclash_smart_core
    定义在 get_openclash_core_arch 内部）。它们与宿主共用同一个收尾 `}`，
    所以「函数数 == 顶格 } 数」这个校验必须先把它们扣掉才成立。"""
    spans = sorted((s, e, n) for n, (s, e) in fmap.items())
    out = []
    for k in range(1, len(spans)):
        if spans[k][0] <= spans[k - 1][1]:
            out.append((spans[k - 1][2], spans[k][2], spans[k - 1][0] + 1, spans[k][0] + 1))
    return out


def count_nested(fmap):
    return len(nested_pairs(fmap))


def parse_dispatch(lines, fmap, report):
    """解析 run_menu_feature() → {feature: {path, title, handler}}"""
    if "run_menu_feature" not in fmap:
        report.append("[FATAL] 找不到 run_menu_feature 函数")
        return {}
    s, e = fmap["run_menu_feature"]
    body = lines[s:e + 1]
    # 找 `case "$feature_choice" in` 块
    ci = None
    for i, ln in enumerate(body):
        if "case" in ln and "feature_choice" in ln:
            ci = i
            break
    if ci is None:
        report.append("[FATAL] run_menu_feature 里找不到 case $feature_choice")
        return {}
    out = OrderedDict()
    cur = None
    for ln in body[ci + 1:]:
        st = ln.strip()
        if st == "esac":
            break
        m = re.match(r"^(\d+(?:\|\d+)*)\)\s*$", st)
        if m:
            for f in m.group(1).split("|"):
                cur = int(f)
                # src_line 留空，后面第二趟扫描再填真实行号（这里 body.index 会取到首次出现位置）
                out[cur] = {"feature": cur, "path": None, "title": None,
                            "handler": None, "src_line": None}
            continue
        if cur is None:
            continue
        rm = re.search(r'run_recorded_menu_feature\s+"([^"]*)"\s+"([^"]*)"\s+([A-Za-z_][A-Za-z0-9_]*)', st)
        if rm and out[cur]["handler"] is None:
            out[cur]["path"] = rm.group(1)
            out[cur]["title"] = rm.group(2)
            out[cur]["handler"] = rm.group(3)
            continue
        cm = re.match(r"^([a-z_][a-z0-9_]*)\s*(?:\|\||;|$)", st)
        if cm and out[cur]["handler"] is None and cm.group(1) not in ("die_menu_input_issue",):
            out[cur]["handler"] = cm.group(1)
    # 记录真实行号
    for f, d in out.items():
        d["src_line"] = None
    for i, ln in enumerate(body):
        st = ln.strip()
        m = re.match(r"^(\d+(?:\|\d+)*)\)\s*$", st)
        if m:
            for f in m.group(1).split("|"):
                if f.isdigit() and int(f) in out:
                    out[int(f)]["src_line"] = s + 1 + i + 1

    # ---- 第二种来源：前导子菜单（分类 3 的 `3 > 1` 奇游 / `3 > 2` 雷神）
    #
    # 上游有**第五种分派写法**：子菜单自己 `case` 里**直接调处理函数**，
    # 完全不经 `run_menu_feature`、也没有 feature 编号：
    #     qiyou_integrated_menu() { ... print_menu_item 1 '安装奇游并接入应用商店'
    #         case "$UI_READ_RESULT" in
    #             1) qiyou_install_integrated
    #                record_action_history "3 > 1 > 1" "安装奇游联机宝" "PASS" "$BACKUP_DIR"
    #             3) qiyou_uninstall_integrated ...
    #
    # 不补这一趟的后果：分类 3 的 8 个动作（含**「卸载奇游」「卸载雷神」**这两个
    # 现成的权威卸载实现）一条写盘足迹都没有 —— 菜单核对却照样 3/3 命中，
    # 因为核对的是「菜单项打印出来没有」，不是「这些项背后有没有被解析」。
    # 这类功能上不了清除清单 = 违背「所有脚本功能都能清干净」的目标。
    nxt = max(out) if out else 0
    subs = []
    for fn, rng in fmap.items():
        if not fn.endswith("_menu") or fn == "run_menu_feature":
            continue
        fs, fe = rng
        fbody = lines[fs:fe + 1]
        labels = {}
        for ln in fbody:
            m = re.search(r"print_menu_item\s+(\S+)\s+'([^']*)'", ln)
            if m and m.group(1).isdigit():
                labels[int(m.group(1))] = m.group(2)
        if not labels:
            continue
        ci = next((i for i, ln in enumerate(fbody)
                   if "case" in ln and "UI_READ_RESULT" in ln), None)
        if ci is None:
            continue
        cur, seen = None, set()
        for i in range(ci + 1, len(fbody)):
            st = fbody[i].strip()
            if st == "esac":
                break
            # `2)` 单独一行、或 `2) qiyou_show_status; return 0 ;;` 挤在同一行
            tail = ""
            m = re.match(r"^(\d+)\)\s*(.*)$", st)
            if m:
                cur = int(m.group(1))
                tail = m.group(2).strip()
                if not tail:
                    continue
            elif cur is not None:
                tail = st
            if cur in (None, 0) or not tail:
                continue
            hm = re.match(r"^([a-z_][a-z0-9_]*)\s*(?:;|$)", tail)
            if not hm or hm.group(1) not in fmap:
                continue
            h = hm.group(1)
            if h in ("die_menu_input_issue", "record_action_history") or h in seen:
                continue
            # 跳转到**另一个菜单**不算动作（`game_accelerator_menu` 的 `1) qiyou_integrated_menu`）
            if h.endswith("_menu"):
                continue
            seen.add(h)
            # 紧随其后的 record_action_history 给出**权威**菜单路径与标题。
            # ⚠️ 搜索必须**止于本 case 分支末尾** —— 否则会把下一个分支的
            # record_action_history 借来用（`2) qiyou_show_status` 拿不到自己的，
            # 就会误取 `3) -> qiyou_uninstall_integrated` 的 "3 > 1 > 3" 和
            # 「卸载奇游联机宝」当标题，看着像正常解析，实际张冠李戴）。
            path, title = None, labels.get(cur)
            for j in range(i, min(i + 4, len(fbody))):
                sj = fbody[j].strip()
                if j > i and (sj == "esac" or re.match(r"^\d+\)", sj)):
                    break
                rm2 = re.search(r'record_action_history\s+"([^"]*)"\s+"([^"]*)"', sj)
                if rm2:
                    path, title = rm2.group(1), rm2.group(2)
                    break
            nxt += 1
            out[nxt] = {"feature": nxt, "path": path, "title": title,
                        "handler": h, "src_line": fs + 1 + i + 1,
                        "key": "submenu:%s:%d" % (fn, cur)}
            subs.append((nxt, fn, cur, h, path))
    if subs:
        report.append("前导子菜单（case 直接调处理函数，无 feature 编号）: %d 个动作"
                      % len(subs))
        for n, fn, no, h, p in subs:
            report.append("    submenu feature %-3d %-28s %s) -> %-34s path=%s"
                          % (n, fn, "%d" % no, h, p or "(无 record_action_history)"))
    return out


MENU_ASSIGN_RE = re.compile(r"^\s*(?:local\s+)?([A-Za-z_][A-Za-z0-9_]*)=(.*?)\s*$")
ARITH_INC_RE = re.compile(r"^\$\(\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*([+-])\s*(\d+)\s*\)\)$")


def _menu_int_expr(expr, ints):
    """解析菜单编号表达式 → int；解析不出（或该机型不打印）返回 None。

    支持：`1` / `$var` / `$((var + 1))` / `$((var - 1))` / `''`（显式置空 = 条件项未启用）
    """
    e = (expr or "").strip()
    if e in ("''", '""'):
        return None
    if len(e) >= 2 and e[0] == e[-1] and e[0] in "'\"":
        e = e[1:-1].strip()
    if not e:
        return None
    if e.isdigit():
        return int(e)
    if e.startswith("$"):
        e = e[1:]
    if e.startswith("((") and e.endswith("))"):
        m = ARITH_INC_RE.match("$((" + e[2:-2].strip() + "))")
        if not m:
            return None
        base = ints.get(m.group(1))
        if base is None:
            return None
        n = int(m.group(3))
        return base + n if m.group(2) == "+" else base - n
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", e):
        return ints.get(e)
    return None


def _menu_cond_of(st, kw):
    """从 `if <cond>; then` / `elif <cond>; then` 里剥出条件原文。"""
    t = st[len(kw):].strip()
    for tail in (";then", "; then", " then", ";"):
        if t.endswith(tail):
            return t[: -len(tail)].strip()
    return t


def _cond_taken(cond, false_conds):
    """把菜单条件**粗略**求值，用于「按机型投影」。

    只处理两种形态：单谓词 `X`、取反 `!X`。其余（`[ ... ]`、复合条件）一律当 True ——
    **保守方向是「保留该项」**：多列一项只是编号偏后，漏列一项会让菜单号整体错位。

    这一步的存在意义：菜单编号是**顺序推进**的（`next=$((next+1))`），
    所以「某条件项不打印」会让它之后所有项的编号各减 1。
    真机分类 5 就是这样：两个 5G 相关项在本机型上不打印，
    于是真机的 8 = 解析里的 9（首页 CPU / 5G 温度切换）。
    """
    c = (cond or "").strip()
    if not c:
        return True
    if c.startswith("else(") and c.endswith(")"):
        return not _cond_taken(c[5:-1], false_conds)
    neg = False
    while c.startswith("!"):
        neg = not neg
        c = c[1:].strip()
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", c):
        return True
    t = c not in false_conds
    return (not t) if neg else t


def parse_menus(lines, fmap, false_conds=None):
    """返回 {menu_func: {'headers': [...], 'items': [...], 'map': {...}, 'prompt': str}}

    `false_conds`：在这个机型上**为假**的谓词名集合。
      · 传 None（默认）→ **并集视图**：不求和，所有条件块照收，每项带 cond。
      · 传集合          → **投影视图**：按「条件项不打印」重新推进编号，
                          得到「该机型实际看到的菜单」。
    注意 `false_conds=None` 与 `false_conds=set()` 语义**不同**：
    后者是「投影、且没有已知为假的谓词」——此时 `!X` 仍会被求值成 False。
    （踩过：把两者当同一件事，并集视图里 `if ! lightweight_...` 包住的
      「1 美化应用商店 / 2 还原应用商店」被整块吃掉，菜单项 90 → 82。）

    两个**只有真机才能发现**的坑，本函数专门处理：

    ① 变量编号。上游菜单有两种写法：
         字面：print_menu_item 3 'ttyd / Web SSH'
         变量：next=1; health=$next; print_menu_item "$health" '统一体检增强版'
       只认字面数字会把整个 default 分支丢掉 —— 真机分类 5 打印 1~8 + 11/12，
       而静态解析只抽到 5 项（AK68-798 与 C8-788 两个老分支），default 分支全没了。

    ② 机型条件。菜单项常被 `if is_current_model_ak798; then ... fi` 之类的条件包裹，
       静态解析**不做条件求值**，把各分支并集当成「该机型看到的」是错的：
         分类 1：真机 10 项（default 分支），并集 12 项（多出 C8-788 分支）
         分类 4：真机  3 项，并集 4 项（排除 lightweight 机型的第 4 项）
         分类 5：真机 10 项（default），并集 11 项（含 AK68-798 / C8-788 分支）
    """
    project = false_conds is not None
    false_conds = set(false_conds or ())
    menus = OrderedDict()
    for name, (s, e) in fmap.items():
        body = lines[s:e + 1]
        if not any("print_menu_item" in ln for ln in body):
            continue
        headers = []
        items = []
        maps = []           # [{'no','feature','cond','src'}]，与 items 同粒度
        ints = {}
        stack = []          # [{'raw': cond原文, 'taken': bool}]
        prompt = None
        vm_pending = None   # 变量比较式分派的中间状态
        pending_nos = []    # 「N) 单独一行」的中间状态
        pending_win = 0

        for off, ln in enumerate(body):
            st = ln.strip()
            # ---- 条件栈维护
            # 只跟踪 if/fi/elif/else；while/for/case 不参与。
            # 坑：上游有「一行里既 if 又 fi」的写法 ——
            #     `if nradio_hwaccel_set 1; then result=PASS; fi`
            # 只看行首会把栈永久推高，之后所有项的 cond 全错。
            # 自校验就是这样抓到 manage_nradio_hardware_acceleration 不平衡的。
            n_close = len(re.findall(r"(?<![\w.-])fi(?![\w.-])", st))
            if st == "fi" or st.startswith(("fi ", "fi;", "fi#")):
                if stack:
                    stack.pop()
                n_close -= 1
            elif st.startswith("elif "):
                if stack:
                    stack.pop()
                raw = _menu_cond_of(st, "elif")
                stack.append({"raw": raw,
                              "taken": _cond_taken(raw, false_conds) if project else True})
            elif st == "else" or st.startswith(("else ", "else;")):
                if stack:
                    top = stack[-1]
                    base = top["raw"]
                    base = base[5:-1] if base.startswith("else(") and base.endswith(")") else base
                    stack[-1] = {"raw": "else(%s)" % base,
                                 "taken": (not _cond_taken(base, false_conds))
                                 if project else True}
            elif st.startswith("if ") or st.startswith("if["):
                raw = _menu_cond_of(st, "if")
                stack.append({"raw": raw,
                              "taken": _cond_taken(raw, false_conds) if project else True})
            while n_close > 0:
                if stack:
                    stack.pop()
                n_close -= 1
            cond = " && ".join(en["raw"] for en in stack)
            active = all(en["taken"] for en in stack)
            # 变量比较式分派的两半：条件行给变量名，紧邻的下一行给 feature 号
            vm_cond = re.search(r'UI_READ_RESULT"?\s*=\s*"\$([A-Za-z_][A-Za-z0-9_]*)', st)
            vm2 = re.search(r"submenu_feature=['\"]?(\d+)", st)

            # ---- 整型变量（菜单编号）。条件不成立的块**不推进编号**，这正是投影的关键
            am = MENU_ASSIGN_RE.match(ln)
            if am and active and not st.startswith(
                    ("if", "elif", "else", "fi", "case", "for", "while")):
                v = _menu_int_expr(am.group(2), ints)
                if v is None:
                    ints.pop(am.group(1), None)
                else:
                    ints[am.group(1)] = v

            # ---- header / prompt（可能多套，各带自己的条件）
            hm = re.search(r"print_menu_header\s+'?([^'\n]*)'?", ln)
            if hm and active:
                headers.append({"header": hm.group(1).strip(), "cond": cond,
                                "src": s + off + 1})
            pm = re.search(r"print_menu_prompt\s+'([^']*)'", ln)
            if pm and active:
                prompt = pm.group(1)

            # ---- 菜单项
            im = re.search(r"print_menu_item\s+(\S+)\s+'([^']*)'", ln)
            if im and active:
                raw = im.group(1)
                no = int(raw) if raw.isdigit() else _menu_int_expr(raw, ints)
                items.append({
                    "no": no, "label": im.group(2), "cond": cond,
                    "expr": None if raw.isdigit() else raw,
                    "src": s + off + 1,
                })

            # ---- 菜单号 -> feature 号。
            # ⚠️ **不能**用扁平 `{菜单号: feature}` 字典：同一个菜单号在不同机型分支里
            # 指向不同 feature（分类 5 的 `4`：C8-788 分支 →23「哈基米依赖检查修复」，
            # default 分支 →20「eMMC 存储扩展」）。第一版用 setdefault 写扁平 dict，
            # 结果 C8-788 分支先写进去，default 分支的 4→20 / 5→21 被静默挡掉，
            # 报出来的是**错的映射**。所以改成条目列表，每条都带 cond，与 items 一一对应。
            mm = re.match(r"^\s*(\d+)\)\s*submenu_feature=['\"]?(\d+)['\"]?", ln)
            if mm:
                maps.append({"no": int(mm.group(1)), "feature": int(mm.group(2)),
                             "cond": cond, "src": s + off + 1})
            mm2 = re.match(r"^\s*(\d+)\)\s*run_menu_feature\s+(\d+)\b", ln)
            if mm2:
                maps.append({"no": int(mm2.group(1)), "feature": int(mm2.group(2)),
                             "cond": cond, "src": s + off + 1})

            # 还有第三种写法：`3)` 单独一行，隔几行才出现 `run_menu_feature 28`
            # （appcenter_polish_menu 的 LuCI-8080 分支，中间夹着一个 if）。
            # 给一个 4 行窗口，超时就作废，避免把别的分支的 run_menu_feature 张冠李戴。
            bm = re.match(r"^\s*(\d+(?:\|\d+)*)\)\s*$", st)
            if bm:
                pending_nos = [int(x) for x in bm.group(1).split("|")]
                pending_win = 4
            if pending_nos:
                fm2 = re.search(r"run_menu_feature\s+(\d+)\b", st)
                if fm2:
                    for pn in pending_nos:
                        maps.append({"no": pn, "feature": int(fm2.group(1)),
                                     "cond": cond, "src": s + off + 1})
                    pending_nos = []
                    pending_win = 0
                elif pending_win > 0:
                    pending_win -= 1
                if pending_win <= 0:
                    pending_nos = []

            # ---- 变量比较式分派（分类 5 default 分支专用）：
            #     elif [ "$UI_READ_RESULT" = "$maintenance_operator_choice" ]; then
            #         submenu_feature='26'
            # 菜单号藏在变量里，必须回填它的整型值，否则**8 个菜单项全进不了映射**
            # （只有 AK68-798 / C8-788 两个字面编号分支进得去）。
            # 连带后果：feature 20/21/24/26/27/29 的标题也回填不上。
            # 只认**紧邻的下一行**，避免把后面无关的 submenu_feature 张冠李戴。
            if vm2:
                if vm_pending:
                    mv = ints.get(vm_pending)
                    if mv is not None:
                        maps.append({"no": mv, "feature": int(vm2.group(1)),
                                     "cond": cond, "src": s + off + 1})
                vm_pending = None
            if vm_cond:
                vm_pending = vm_cond.group(1)
            elif vm_pending and st and not st.startswith("#"):
                vm_pending = None

        if items:
            seen = set()
            uniq_maps = []
            for mp in maps:
                k = (mp["no"], mp["feature"], mp["cond"])
                if k not in seen:
                    seen.add(k)
                    uniq_maps.append(mp)
            menus[name] = {"headers": headers, "items": items, "maps": uniq_maps,
                           "prompt": prompt,
                           # 走到函数末尾 if 栈没空 → 说明有 if 的 then 跨行或写法特殊，
                           # 这份 cond 不可信，必须人工看（自校验）
                           "unbalanced": bool(stack)}
    return menus


def closure(handler, fmap, lines, heredoc=None):
    """处理函数的传递闭包 → (函数名集合, 行号集合)

    heredoc 正文**不参与调用扫描**：那些正文是「要写进设备的文件」的内容，
    里面出现的标识符是字面文本，不是本脚本的调用点。第一次跑时
    install_ttyd_webssh 的闭包被一路污染到 OpenVPN/AdGuard 的清理函数
    （write_plugin_uninstall_assets 的 heredoc 里成片出现这些名字），
    把别的插件的写盘操作算进了 ttyd 的足迹 —— 装卸时会误删。
    """
    heredoc = heredoc or set()
    seen = OrderedDict()
    stack = [(handler, 0)]
    while stack and len(seen) < MAX_CLOSURE:
        fn, depth = stack.pop()
        if fn in seen or fn not in fmap:
            continue
        s, e = fmap[fn]
        seen[fn] = (s, e)
        if depth >= MAX_DEPTH:
            continue
        for i in range(s + 1, min(e, len(lines))):
            if i in heredoc:
                continue
            ln = lines[i]
            if ln.lstrip().startswith("#"):
                continue
            for cm in CALL_RE.finditer(ln):
                callee = cm.group(1)
                if callee in fmap and callee not in seen:
                    stack.append((callee, depth + 1))
    lines_set = set()
    for _fn, (s, e) in seen.items():
        if e - s > MAX_RANGE:
            e = s + MAX_RANGE
        lines_set.update(range(s, e + 1))
    return list(seen.keys()), sorted(lines_set)


# ---------------------------------------------------------------- 写动词判定
#
# **为什么需要**（2026-09-20 发现）：
# WRITE_PATTERNS 里的 initd / rcd / hotplug / dirs 是**纯路径正则，不判动词**。
# 于是 `[ -f /etc/openclash/x ] && log "存在"`（读）和 `rm -rf /etc/openclash/x`（写）
# 被等价对待。实测受害：
#   · feature 24「封版工具箱」只是打印一份诊断摘要，经
#     nradio_print_openclash_brief_summary → openclash_report_storage_location
#     **读到** /etc/openclash 与 /etc/init.d/openclash，就被判成
#     「要删 openclash 配置目录、要停 openclash 服务」—— 直接踩到「先别动 openclash」的红线
#   · feature 41「查看雷神状态」里唯一的 `/etc/init.d/acc` 是
#     `/etc/init.d/acc enabled`（查是否开机自启），被判成「要停 acc 服务」
#     → 谓词 `not_running:acc`。一个「查看状态」动作不可能停服务。
#
# 判据落在**函数**而不是**行**上：同一个函数体内的路径引用会互相牵连
# （`for oc_path in /etc/openclash ...; do oc_real="$(readlink -f "$oc_path")"; rm -rf "$oc_real"`），
# 逐行判会漏。函数级判定的漏判面则可以用不动点传播补回来。
WRITE_VERB_RE = re.compile(
    r"(?:^|[;&|(\s])(?:rm|mv|cp|mkdir|touch|ln|chmod|chown|tee|truncate|dd|"
    r"swapon|swapoff|unzip|gzip|gunzip|install|tar)\b"
    r"|sed\s+-[A-Za-z]*i"
    r"|/etc/init\.d/\S+\s+(?:start|stop|restart|reload|enable|disable)\b"
    r"|\bopkg\s+(?:install|remove|upgrade|download)\b"
    r"|\buci\s+(?:-q\s+)?(?:set|add|add_list|delete|rename|commit)\b"
    r"|\bubus\s+call\b|\beval\b|\bcat\s*>")
_REDIR_TGT_RE = re.compile(r">>?\s*([^\s;|&]*)")


def has_write_redir(line):
    """`> x` / `>> x` 是写；`>&1`、`2>/dev/null`、`>/dev/null` 不算。"""
    for m in _REDIR_TGT_RE.finditer(line):
        tgt = m.group(1).strip("'\"")
        if not tgt or tgt.startswith("&") or tgt.startswith("/dev/"):
            continue
        return True
    return False


def compute_write_funcs(fmap, lines, heredoc=None):
    """返回「函数体内**直接**含写动词」的函数名集合。

    ⚠️ **刻意不做不动点传播**（2026-09-20 实测结论）。

    试过加传播（「调用了写函数的函数也算写函数」，理由是 `foo() { install_bar; }`
    这种纯转发函数），结果灾难性：

        nradio_print_openclash_brief_summary    一行写盘都没有
          └─ 调用了 selfcheck_print_header / openclash_report_storage_location …
             └─ 链上某处是写函数 → 不动点把 print_* 也标成写函数
                → 它体内 `openclash_report_storage_location "..." /etc/openclash`
                  这种**纯传参行**被当成写盘
                → feature 24「封版工具箱」凭空要删 /etc/openclash、停 openclash

    不传播的代价：`foo() { install_bar; }` 判不出来。但这类纯转发函数**体内没有
    路径引用**，抽不到东西，所以对足迹没有任何影响 —— 代价约等于零。
    """
    heredoc = heredoc or set()
    wf = set()
    for fn, (s, e) in fmap.items():
        for i in range(s + 1, min(e + 1, len(lines))):
            if i in heredoc:
                continue
            ln = lines[i]
            if ln.lstrip().startswith("#"):
                continue
            if WRITE_VERB_RE.search(ln) or has_write_redir(ln):
                wf.add(fn)
                break
    return wf


def readonly_lines_of(fmap, lines, line_owner, write_funcs, script_hd_lines,
                      data_hd_lines=None):
    """「所有归属函数都不是写函数」的行 —— 这些行里的路径引用只是**读**。

    **为什么是函数级而不是行级**（2026-09-20 实测两轮）：

      · 行级（「这一行不含写动词就不算写」）看起来更精确，实测**漏判灾难性**：
        上游大量用「封装函数 + 变量实参」写盘 ——
        `stop_disable /etc/init.d/openvpn`、`$LEIGOD_INIT enable`、
        `unified_apply_fix "$target"` —— 这些行本身没有写动词，
        路径全靠被调函数或变量承载。行级闸门直接把它们全滤掉：
        feature 13「统一体检增强版」从 medium/7 条谓词掉成 low/1 条，
        feature 2/5/6/7 的 stop_services 全部归零。

      · 函数级（本文）会**过度包含**：不动点传播把
        `nradio_print_openclash_brief_summary` 标成写函数 → feature 24 误判。
        这一半已经用「`compute_write_funcs` 不做传播」修掉了。

    两害相权：函数级的残余误差是「少量假阳性」（会进 needs_manual 或由人工核），
    行级的误差是「成片假阴性」（清除不完整且看不出来）。取函数级。
    """
    ro = set()
    script_hd_lines = script_hd_lines or set()
    for i in range(len(lines)):
        if i in script_hd_lines:
            continue
        owners = line_owner.get(i)
        if owners and all(o not in write_funcs for o in owners):
            ro.add(i)
    return ro


CLEANUP_FUNC_RE = re.compile(
    r"^(?:uninstall|remove|cleanup|purge|restore|disable|delete)_[a-z0-9_]+$|"
    r"^_(?:uninstall|remove|cleanup|purge)_[a-z0-9_]+$")
# 带**命名空间前缀**的卸载动作：`qiyou_uninstall_integrated` / `leigod_uninstall_integrated`。
# 不能直接把 CLEANUP_FUNC_RE 放宽成「允许任意前缀」—— 那样 `write_plugin_uninstall_assets`
# （生成那份通用卸载脚本的「写手」）、`ui_restore_echo`（UI 回显）、
# `patch_appcenter_docker_uninstall_key`（改商店卸载键）都会混进来，
# 共 28 个假阳性、波及 24 个 feature。
# 只对「**feature 自己的 handler** 就是一个卸载动作」这一种情形开口子，
# 影响面精确锁定（命中 `qiyou_uninstall_integrated` / `leigod_uninstall_integrated` 两个）。
OWN_UNINSTALL_RE = re.compile(r"^[a-z][a-z0-9_]*uninstall_[a-z0-9_]+$")


def upstream_cleanup_funcs(fns):
    """闭包里哪些函数是上游自己的「卸载/清理/还原」实现。

    本项目明确**不依赖**它们（全部自写），但必须知道它们存在、以及它们
    是否真的被装->卸路径调用 —— 这是判断「上游卸载是否彻底」的依据。
    """
    return [f for f in fns if CLEANUP_FUNC_RE.match(f)]


RM_TARGET_RE = re.compile(r"\brm\s+((?:-[A-Za-z]+\s+)*)(.+)$")
VIEW_SUFFIXES = (".htm", ".html", ".lua", ".js", ".css")
# `rewrite_nradio_operator_display_view` / `rewrite_nradio_home_temperature_view`
REWRITE_VIEW_RE = re.compile(r"^(?:rewrite|restore|patch)_[a-z0-9_]*view[a-z0-9_]*$")
ABS_PATH_RE = re.compile(r"(?<![\w./-])(/[A-Za-z0-9._/-]{3,})")
# 生成「卸载助手脚本」的函数：`qiyou_write_uninstall_helper` / `leigod_write_uninstall_helper` /
# `write_plugin_uninstall_assets`
GEN_UNINSTALL_HELPER_RE = re.compile(r"^[a-z][a-z0-9_]*write_[a-z0-9_]*uninstall[a-z0-9_]*$")
# `cat > /usr/libexec/nradio-qiyou-uninstall <<'EOF_QIYOU_UNINSTALL'`
HEREDOC_HDR_RE = re.compile(
    r">\s*(\S+)\s*<<-?\s*['\"]?([A-Za-z_][A-Za-z0-9_]*)['\"]?")
# 上游卸载脚本**自己写明的验收断言**：`[ ! -e /etc/qy ] && ... || exit 1`
ASSERT_ABSENT_RE = re.compile(r"\[\s*!\s*-e\s+(/[A-Za-z0-9._/-]+)\s*\]")
PROC_RE = re.compile(r"\b(?:pidof|killall)\b[^\n;|&]*")
# 只认「像设备文件系统」的绝对路径。必须是白名单前缀，否则会把 awk 里的
# **URL 路径**（`script_src="/luci-static/nradio/js/xxx.js"` —— 相对 /www，
# 补上前缀才是真路径）误当成固件文件，生成 `matches_baseline:/luci-static/...`
# 这种永远不可能成立、也永远不可能失败的假谓词。
FW_ROOTS = ("/usr/lib/lua/luci/", "/www/", "/etc/", "/usr/share/", "/root/",
            "/opt/", "/overlay/", "/mnt/", "/lib/", "/usr/bin/", "/usr/sbin/",
            "/sbin/", "/bin/")


def _looks_like_device_path(p):
    return p.startswith(FW_ROOTS)


def _view_paths_of(seg, varlit):
    """从一段脚本文本里挑出「固件 LuCI 模板/静态资源」路径。

    坑：调用点那一行**不一定含变量** ——
        `if [ -f "$NRADIO_OPERATOR_FIX_VIEW" ]; then`
        `    rewrite_nradio_operator_display_view remove`
    真正决定 view 的是**被调用函数自己的函数体**（里面引用 `$NRADIO_..._VIEW`）。
    早期只扫调用点那一行 → VARREF 为空 → views 恒空，index.htm 被误判成
    「上游有意保留」，等于给「卸载后首页必须回基线」这条最重要的验收判据挖了坑。
    """
    found = []
    for var in VARREF_RE.findall(seg):
        v = varlit.get(var)
        if (v and v.startswith("/") and v.endswith(VIEW_SUFFIXES)
                and _looks_like_device_path(v) and v not in found):
            found.append(v)
    for p in ABS_PATH_RE.findall(seg):
        if (p.endswith(VIEW_SUFFIXES) and _looks_like_device_path(p)
                and p not in found):
            found.append(p)
    return found


def _heredoc_bodies(seg_lines):
    """从一段函数体里抽出所有 heredoc 正文 → [(目标路径, 分隔符, 正文行)]。

    正文是**要写到设备上的那份脚本**的内容，不是本脚本的语句 —— 但对奇游/雷神
    这类「代码生成器」模式，正文恰恰才是真正的卸载逻辑。
    """
    out = []
    i = 0
    while i < len(seg_lines):
        m = HEREDOC_HDR_RE.search(seg_lines[i])
        if not m:
            i += 1
            continue
        tgt, delim = m.group(1), m.group(2)
        body, j = [], i + 1
        while j < len(seg_lines) and seg_lines[j].strip() != delim:
            body.append(seg_lines[j])
            j += 1
        out.append((tgt, delim, body))
        i = j + 1
    return out


def _scan_generated_uninstall(body, varlit):
    """解析一份「上游生成出来的卸载脚本」的正文 → 删除清单 / 进程 / 自带验收断言。

    `rm -f "$APP_CONTROLLER"` 里的变量是在**这份脚本内部**赋值的
    （`APP_CONTROLLER="/usr/lib/lua/luci/controller/nradio_adv/qiyou.lua"`），
    所以要用「正文自己的变量表」覆盖全局表，否则一个目标都解析不出来。
    """
    local = {}
    for ln in body:
        m = ASSIGN_RE.match(ln)
        if m:
            val = m.group(2) or m.group(3) or m.group(4) or ""
            if val and "$" not in val:
                local.setdefault(m.group(1), val)
    merged = dict(varlit)
    merged.update(local)

    rm, procs, asserts = [], [], []
    for ln in body:
        if ln.lstrip().startswith("#"):
            continue
        m = RM_TARGET_RE.search(ln)
        if m:
            for tok in re.split(r"[;\s|&()]+", m.group(2).split("2>", 1)[0]):
                tok = tok.strip().strip("\"'")
                if not tok:
                    continue
                p = resolve_ref(tok, merged) if "$" in tok else (
                    tok if tok.startswith("/") else None)
                if p and not NOISE_PATH.match(p) and p not in rm:
                    rm.append(p)
        for pm in PROC_RE.finditer(ln):
            for tok in re.split(r"[\s;|&]+", pm.group(0)):
                tok = tok.strip("-9")
                if (re.fullmatch(r"[a-z][a-z0-9_.-]+", tok or "")
                        and tok not in ("pidof", "killall") and tok not in procs):
                    procs.append(tok)
        for am in ASSERT_ABSENT_RE.finditer(ln):
            p = resolve_ref(am.group(1), merged) or am.group(1)
            if not NOISE_PATH.match(p) and p not in asserts:
                asserts.append(p)
    return rm, procs, asserts


def parse_upstream_uninstall(entry, lines, fmap, varlit, closure_text):
    """解析上游自带的 `uninstall_*` 函数 —— 它是「该删什么」的**权威答案**。

    为什么需要它：有一类功能**不改配置、不建包、不建目录**，只往固件自带的
    LuCI 首页模板里插一段带 marker 的 `<script>`，外加一两个自己的 JS。
    静态扫描只能看到「一堆变量指向的路径」，既判不出哪些是「插件新增」、
    哪些是「固件原文不能删」，于是全部落进 `_weak` → needs_manual →
    post_condition 为空（feature 26/27 就是这样：33 个功能里只有这 2 个没有
    任何验收谓词）。

    上游自己的 uninstall 把这件事说得很清楚（installer.sh L57420 / L58420）：

        rewrite_nradio_operator_display_view remove   # awk 按 marker 摘掉注入段
        rm -f "$NRADIO_OPERATOR_FIX_JS" "$NRADIO_SIM_NAME_MAP_JS"
        refresh_nradio_operator_display_fix           # 清 LuCI 缓存 + uhttpd reload
        # 注释原文：「卡名配置已保留」→ /etc/nradio-sim-name.map 卸载后必须还在

    三个结论直接改成谓词：
      1. `rewrite_*_view remove` 的目标 view → **不能删**，只能「回到基线」
         → `matches_baseline:<view>` + `no_marker:<标记>`
         （摘掉 marker 段后逐字节等于 /rom 原文，这条是可达的）
      2. `rm -f` 的目标 → 真删 → `absent:<path>`
      3. 既不在 rm、也不在 view 的持久路径 → 上游**有意保留**（如卡名 map）
         → `keeps:<path>`，同时进 keep_shared，并留一条人工复核提示

    返回 {rm, views, keeps, markers, funcs}。
    """
    out = {"rm": [], "views": [], "keeps": [], "markers": [], "funcs": [],
           "procs": [], "assert_absent": [], "helpers": []}
    funcs = entry.get("upstream_cleanup") or []
    if not funcs:
        return out

    # ---- 1) 注入标记：标记常量在闭包里被引用（`$NRADIO_*_MARKER_BEGIN`），
    #         值形如 `<!-- xxx:start -->`，从字面值表还原。
    markers = []
    for name in VARREF_RE.findall(closure_text):
        if "MARKER" not in name:
            continue
        v = varlit.get(name)
        if v and (v.startswith("<!--") or v.startswith("/*") or v.startswith("#")):
            if v not in markers:
                markers.append(v)
    out["markers"] = markers

    for fn in funcs:
        info = fmap.get(fn)
        if not info:
            continue
        out["funcs"].append(fn)
        s, e = info[0], info[1]
        seg_lines = lines[s:min(e + 1, len(lines))]
        seg = "\n".join(seg_lines)

        # ---- 2) rm 目标（`rm -f a b c 2>/dev/null || true`）
        for ln in seg_lines:
            m = RM_TARGET_RE.search(ln)
            if not m:
                continue
            body = m.group(2).split("2>", 1)[0]
            for tok in re.split(r"[;\s|&()]+", body):
                tok = tok.strip().strip("\"'")
                if not tok:
                    continue
                p = resolve_ref(tok, varlit) if "$" in tok else (
                    tok if tok.startswith("/") else None)
                if p and not NOISE_PATH.match(p) and p not in out["rm"]:
                    out["rm"].append(p)

        # ---- 3) view 重写：`rewrite_xxx_view remove` → 摘注入段，**不删文件**。
        #         变量在「重写器自己的函数体」里，所以两处都要扫。
        for v in _view_paths_of(seg, varlit):
            if v not in out["views"]:
                out["views"].append(v)

    # 3b) 卸载函数只是「调一下重写器」——把重写器本体也扫一遍
    for fn in (entry.get("src") or {}).get("funcs") or []:
        if not REWRITE_VIEW_RE.match(fn):
            continue
        info = fmap.get(fn)
        if not info:
            continue
        s, e = info[0], info[1]
        seg = "\n".join(lines[s:min(e + 1, len(lines))])
        for v in _view_paths_of(seg, varlit):
            if v not in out["views"]:
                out["views"].append(v)

    # ---- 3c) 生成式卸载助手 —— 奇游/雷神这类「代码生成器」功能的正解在这里。
    #
    # 结构（真机源码 installer.sh:71825 / 71862）：
    #     qiyou_uninstall_integrated() {            # handler 自己什么都不删
    #         [ -x /usr/libexec/nradio-qiyou-uninstall ] || qiyou_write_uninstall_helper
    #         /usr/libexec/nradio-qiyou-uninstall   # ← 真正干活的是**生成出来的那份脚本**
    #     }
    #     qiyou_write_uninstall_helper() {          # 正文藏在 heredoc 里
    #         cat > /usr/libexec/nradio-qiyou-uninstall <<'EOF_QIYOU_UNINSTALL'
    #             rm -rf /tmp/qy /etc/qy ...
    #             rm -f "$APP_CONTROLLER" ...
    #             [ ! -e /etc/qy ] && [ ! -e /tmp/qy ] || { echo "...残留" >&2; exit 1; }
    #             pidof qy_proxy qy_mosq qy_acc && { echo "...仍有进程" >&2; exit 1; }
    #         EOF_QIYOU_UNINSTALL
    #     }
    # 只解析 `uninstall_*` 函数的话这两个功能是「零谓词」，和 26/27 一样没验收标准；
    # 而正文里连**上游自己的验收断言**都写好了，是最硬的依据。
    for fn in (entry.get("src") or {}).get("funcs") or []:
        if not GEN_UNINSTALL_HELPER_RE.match(fn):
            continue
        info = fmap.get(fn)
        if not info:
            continue
        for tgt, delim, body in _heredoc_bodies(lines[info[0]:min(info[1] + 1, len(lines))]):
            # 只认「写到 *uninstall* 目标」的那份脚本
            if "uninstall" not in tgt.lower() and "UNINSTALL" not in delim:
                continue
            out["helpers"].append("%s -> %s" % (fn, tgt))
            brm, bproc, bassert = _scan_generated_uninstall(body, varlit)
            for x in brm:
                if x not in out["rm"]:
                    out["rm"].append(x)
            for x in bproc:
                if x not in out["procs"]:
                    out["procs"].append(x)
            for x in bassert:
                if x not in out["assert_absent"]:
                    out["assert_absent"].append(x)

    # ---- 3d) 收集卸载函数正文，供「有意保留」判定用
    un_bodies = []
    for fn in out["funcs"]:
        info = fmap.get(fn)
        if info:
            un_bodies.append("\n".join(lines[info[0]:min(info[1] + 1, len(lines))]))
    un_text = "\n".join(un_bodies)

    # ---- 4) rm 优先于 view：同一个路径不可能既「删掉」又「回到基线」。
    #         不收敛的话 `/www/.../xxx.js`（在 rm 里）会同时进 views，
    #         碰巧因 build_cleanup 先判 rm 而结果正确 —— 这种「靠调用顺序兜底」
    #         的隐式正确必须消掉，否则以后一调顺序就静默错。
    out["views"] = [v for v in out["views"] if v not in out["rm"]]

    # ---- 5) 「上游有意保留」——**必须有显式文字证据**，不能靠「上游没 rm」推。
    #
    # 第一版就是靠「没 rm ⇒ 保留」推的，结果 66 条谓词里绝大多数是错的：
    # feature 5（OpenList）把 `/usr/bin/openlist`、`/etc/init.d/openlist`、
    # `openlist.lua` 全判成「卸载后必须仍在」—— 那些明明**必须删**。
    # 真实原因是上游的 cleanup 函数只管「运行时态/路由/缓存」这类需要特别处理
    # 的东西，插件自己的文件另有机制（.lua 控制器、init.d 自带 stop、商店注册项）
    # 负责，没出现在 rm 里 ≠ 不删。
    #
    # 唯一站得住的证据是**源码里把话说出来了**。feature 26 就是范例：
    #     log "结果:   LuCI 运营商与卡名显示修复已移除（卡名配置已保留）"
    # 配合「路径是数据/配置文件形态」，才敢断言它卸载后必须仍在。
    # 拿不准的一律退回 needs_manual —— 宁缺勿错。
    keep_hint = bool(KEEP_HINT_RE.search(un_text))
    for one in entry["writes_unique"].get("vars", []):
        for p in re.split(r"[;\s]+", one.strip().strip("\"'")):
            if not p.startswith("/") or NOISE_PATH.match(p):
                continue
            if p in out["rm"] or p in out["views"]:
                continue
            if (keep_hint and p.endswith(DATA_SUFFIXES)
                    and not EXCLUDE_KEEP_RE.match(p)):
                if p not in out["keeps"]:
                    out["keeps"].append(p)
    return out


# 上游把「卸载时保留」写在日志/注释里的措辞（feature 26「卡名配置已保留」）
KEEP_HINT_RE = re.compile(r"保留|不删|勿删|keep|preserve|do not (?:remove|delete)", re.I)
# 只有「数据/配置」形态的路径才谈得上「保留」（用户数据必须活下来）；
# 可执行文件、LuCI 控制器/视图、init.d 脚本一律不是保留对象。
DATA_SUFFIXES = (".map", ".conf", ".cfg", ".json", ".toml", ".yaml", ".yml",
                 ".list", ".txt", ".ini", ".csv", ".db", ".sqlite", ".db")
EXCLUDE_KEEP_RE = re.compile(
    r"^(?:/etc/init\.d/|/etc/rc\.d/|/etc/hotplug\.d/|/bin/|/sbin/|/lib/|"
    r"/usr/bin/|/usr/sbin/|/usr/libexec/|"
    r"/usr/lib/lua/luci/(?:controller|model|cbi|view|model/cbi)/|"
    r"/www/|/usr/share/|/mnt/|/opt/)")


# ------------------------------------------------ cleanup / post_condition 草稿
# 这些正则把一个「写盘值」拆成可执行动作的素材
PKG_RE = re.compile(r"opkg\s+(?:install|remove|download)\s+([^\s;|&)]+)")
SVC_RE = re.compile(r"/etc/init\.d/([A-Za-z0-9._-]+)")
RCD_SVC_RE = re.compile(r"/etc/rc\.d/[SK][0-9]*([A-Za-z0-9._-]+)\.?(?:boot|start|stop|enable|disable)?$")
UCI_HINT_RE = re.compile(r"uci\s+(?:-q\s+)?set\s+([A-Za-z0-9_@\[\].\"$*-]+)")
UCI_CFG_RE = re.compile(
    r"uci\s+(?:-q\s+)?(?:set|add|add_list|delete|rename|commit|revert)\s+([A-Za-z0-9_-]+)")

# 明显是「噪声/运行期」的路径，不作为删除候选
NOISE_PATH = re.compile(
    r"^(?:/dev/|/proc/|/sys/|/tmp|/var/run|/var/lock|/var/log|/run/|/)$|"
    r"^/[\s,]*$|CDATA|^\$\{|^//|^-\s*$")
# 运行期状态而非持久配置：记录但不建议删（重启即清）
RUNTIME_PATH = re.compile(r"^/(?:tmp|var/run|var/lock|var/log|run)/")


# 绝对不能进删除候选的系统路径。命中一律改判 needs_manual / forbidden。
# 第一次生成草稿时 /bin/sh、/mnt/rootfs_2nd_data 混进了删除列表 —— 删了就是砖。
FORBIDDEN_EXACT = {
    "/", "/bin", "/sbin", "/lib", "/usr", "/usr/bin", "/usr/sbin", "/usr/lib", "/etc",
    "/etc/rc.local", "/etc/crontabs/root", "/etc/profile", "/etc/passwd", "/etc/shadow",
    "/etc/group", "/etc/fstab", "/etc/config/fstab", "/etc/config/network",
    "/etc/config/wireless", "/etc/config/firewall", "/etc/config/dhcp",
    "/etc/config/system", "/etc/config/dropbear", "/etc/config/uhttpd", "/etc/config/luci",
    "/etc/opkg/distfeeds.conf", "/mnt/rootfs_2nd_data", "/mnt/storage", "/mnt/storage/data",
    "/overlay", "/root", "/home", "/www", "/tmp", "/bin/sh", "/bin/ash", "/bin/busybox",
}
FORBIDDEN_PREFIX = [
    "/bin/", "/sbin/", "/lib/", "/mnt/", "/dev/", "/proc/", "/sys/", "/usr/lib/opkg/",
    "/etc/config/uhttpd", "/etc/config/dropbear", "/etc/opkg/",
]

# 出厂自带的 /etc/init.d 服务（真机实测 `ls -1 /rom/etc/init.d/` 的 72 个，
# 设备 NRadio_C2000Ultra / NROS 2.3.0.n0.c1 / 2026-09-20）。
#
# 判据：`/rom` 是只读的出厂根 → 这些服务**不可能是插件引入的**，卸载时绝不能
# stop / disable，最多只能「重置它们被改过的配置」。
#
# 为什么是硬黑名单而不是「靠共用度推断」：首跑时 uhttpd 被 20 个功能标成「该清」、
# dnsmasq / firewall / odhcpd / mtkhnat / cpesel / dropbear 也进了删除候选 ——
# 因为上游到处 `restart` 公共 Web 服务，那些行落在各功能**自己的**函数里，
# 按「共用度」判不出来。照那份清单卸载会直接把路由器的网断掉。
#
# 注：设备侧 kp-clean.sh 用 /rom 做**权威**判定（rom=yes/no），
# 这个列表只是让 PC 侧草稿一开始就干净、不用等审计回灌。
FIRMWARE_SERVICES = set("""
access_ctl appcenter atsd atserver-sniffer boot cellular_init cellular_power
cellular_record cimd cloudd combo conn_detect cpesel cpeselgpio cron dnsmasq
done dropbear factory_siminfo fanctrl firewall fota_upgrade fstab fwdd
gpio_switch guest htpdate igmpproxy infocd kpcped kpsh led ledctrl logservice
miniupnpd mosquitto mqttagent msad mtk_dut mtkhnat network nrswitch odhcpd
pppq-ebl.init report_proactively reset_boot_count rpcd rsyslog simcom_http smsd
softapd sysctl sysfixtime sysntpd system system_power telnetd terminal_trackd
uhttpd umount urandom_seed urngd wanchk wanswd wifi_e2p wifi_fw_path wifi_msp
wifi_testmode wifidogx wm wpad xl2tpd
""".split())

# 只当「容器」用的大目录。`norm_dir` 会把 `/usr/libexec/qy_acc` 归一成 `/usr/libexec`，
# 于是 remove_paths 里出现 `/usr/libexec` 本身 —— 那是**固件 7 个文件的所在目录**，
# 删它等于删固件（真机审计：`/usr/libexec` 判 rom=yes，却落进「该清」）。
# 这类「只知前缀、不知具体文件」的条目一律退回人工，不进删除候选。
CONTAINER_DIRS = {
    "/usr/libexec", "/usr/lib/lua/luci", "/usr/lib/lua", "/usr/lib", "/usr/share",
    "/usr/bin", "/usr/sbin", "/www", "/etc/config", "/opt", "/mnt/storage", "/overlay",
}


def path_is_forbidden(p):
    return p in FORBIDDEN_EXACT or any(p.startswith(pre) for pre in FORBIDDEN_PREFIX)


def build_cleanup(entry, lines=None, fmap=None, varlit=None, closure_text=""):
    """从「独有写盘」推导卸载动作与验收谓词（草稿）。

    设计原则（来自计划 §4）：
      · 删除候选**只取独有写盘**；共用设施一律进 keep_shared，绝不随单插件删。
      · post_condition 用「谓词」而不是「文件不存在」—— /etc/config/fstab、
        /etc/rc.local、/etc/crontabs/root 这些**必须存在**，用文件不存在判定会误判成失败。
      · 拿不准的一律进 needs_manual，宁缺勿错。
      · 有上游 `uninstall_*` 函数时，以它为准解歧（见 parse_upstream_uninstall）——
        这是把 `_weak` 路径从「一律人工」升级成「可判定谓词」的唯一可靠依据。
    """
    u = entry["writes_unique"]
    remove_paths, stop_services, disable_rc, uci_reset = [], [], [], []
    keep_shared, needs_manual, packages, forbidden = [], [], [], []
    baseline_paths = []          # 固件文件：不能删，只能回基线
    weak = set(u.get("_weak") or [])
    partial = set(u.get("_partial") or [])
    un = (parse_upstream_uninstall(entry, lines, fmap, varlit, closure_text)
          if (lines is not None and fmap is not None) else
          {"rm": [], "views": [], "keeps": [], "markers": [], "funcs": []})

    for seg in u["dirs"] + u["targets"] + u["vars"]:
        for one in re.split(r"[;\s]+", seg):
            one = one.strip().strip("\"'")
            if not one or NOISE_PATH.match(one):
                continue
            # ---- 上游卸载函数解歧（优先于一切启发式判据）
            if one in un["rm"]:
                if one not in remove_paths:
                    remove_paths.append(one)
                continue
            if one in un["views"]:
                # 固件自带的 LuCI 模板：删了首页就没了 → 只能「摘注入段、回基线」
                if one not in baseline_paths:
                    baseline_paths.append(one)
                continue
            if one in un["keeps"]:
                if one not in keep_shared:
                    keep_shared.append(one)
                needs_manual.append(
                    "上游 uninstall 未删它 → 现判为「有意保留」（须人工确认不是上游漏删）: " + one)
                continue
            if one in weak:
                needs_manual.append("弱证据（变量指向，未必真写入）: " + one)
                continue
            if one in partial:
                needs_manual.append("被变量截断的半截路径，须回原文核: " + one)
                continue
            if path_is_forbidden(one):
                forbidden.append(one)
                continue
            if one in CONTAINER_DIRS:
                needs_manual.append(
                    "只知目录前缀、不知具体文件（norm_dir 归一所致，删它等于删固件），须回原文核: " + one)
                continue
            if RUNTIME_PATH.match(one):
                needs_manual.append("运行期路径（重启即清，通常不用删）: " + one)
                continue
            if one not in remove_paths:
                remove_paths.append(one)

    for seg in u["initd"]:
        m = SVC_RE.search(seg)
        if not m:
            continue
        svc = m.group(1)
        if svc in FIRMWARE_SERVICES:
            # 出厂服务：只能重置配置，绝不能停/禁。记进 forbidden 让人看见。
            tag = "service:%s" % svc
            if tag not in forbidden:
                forbidden.append(tag)
            continue
        if svc not in stop_services:
            stop_services.append(svc)

    # ---- 上游卸载脚本里**写明要删**的目标（最硬的一手证据）
    #
    # 必须单独走一遍：卸载动作的 rm 目标往往是**安装动作**写的路径。
    # 例 feature 42「卸载雷神加速器」要删 `/usr/sbin/leigod`、`/etc/init.d/acc`、
    # `/etc/config/accelerator` —— 那些是 feature 39 装的，卸载动作自己一条都没写过，
    # 所以上面那个「遍历本功能写盘」的循环永远看不到它们，remove_paths 恒为 0。
    rm_derived = set()
    for one in un["rm"]:
        if NOISE_PATH.match(one) or one in CONTAINER_DIRS:
            continue
        if path_is_forbidden(one):
            if one not in forbidden:
                forbidden.append(one)
            continue
        rm_derived.add(one)
        if one not in remove_paths:
            remove_paths.append(one)

    # 上游卸载脚本里显式 `killall` 的第三方插件进程（奇游 `qy_proxy qy_mosq qy_acc`）。
    # 走**同一道固件服务黑名单** —— 出厂服务绝不能被 kill。
    for p in un["procs"]:
        if p in FIRMWARE_SERVICES:
            tag = "service:%s" % p
            if tag not in forbidden:
                forbidden.append(tag)
            continue
        if p not in stop_services:
            stop_services.append(p)

    for seg in u["rcd"]:
        # `/etc/rc.d/S` 这种半截（真身是 `/etc/rc.d/S99xxx` 拼了变量）不能当删除目标
        if re.search(r"/[SK][0-9]*$", seg) or seg.endswith("/"):
            needs_manual.append("rc.d 路径被变量截断，须回原文核: " + seg)
            continue
        if seg and seg not in disable_rc:
            disable_rc.append(seg)

    for seg in u["opkg"]:
        found = False
        for m in PKG_RE.finditer(seg):
            tok = m.group(1).strip("\"'")
            if tok.startswith("$"):
                needs_manual.append("包名含变量，需人工确认: " + seg[:120])
                found = True
                continue
            if tok not in packages:
                packages.append(tok)
            found = True
        if not found:
            needs_manual.append("opkg 行未解析出包名: " + seg[:120])

    for seg in u["uci"]:
        m = UCI_HINT_RE.search(seg)
        if m:
            tgt = m.group(1).strip('"')
            if "$" in tgt:
                needs_manual.append("uci 键含变量（可能是共用注册项）: " + seg[:120])
            elif tgt not in uci_reset:
                uci_reset.append(tgt)
        else:
            needs_manual.append("uci 行未解析出配置键: " + seg[:120])

    for kind, tag in (("cron", "cron 条目"), ("rclocal", "rc.local / 向导块"),
                      ("marker", "补丁 marker"),
                      ("store", "应用商店注册项")):
        for seg in u[kind]:
            needs_manual.append("%s: %s" % (tag, seg[:120]))

    # 网络规则**一律只给人工提示，不给自动谓词**（理由见下方 post_condition 处）。
    # 提示里点名核对命令 —— 否则「网络规则: iptables」这种信息量约等于零，
    # 拿到手不知道要去哪里看什么。
    for seg in u["net"]:
        needs_manual.append(
            "网络规则（不自动判定；请人工核对 iptables-save / ip rule show / ip route show）: "
            + seg[:120])

    # 共用设施里那些「必须保持完好」的系统文件 → 用基线比对谓词收口。
    # 不能写 absent：/etc/config/fstab、/etc/rc.local、/etc/crontabs/root 卸载后**必须还在**。
    shared_paths = []
    for kind in ("targets", "dirs", "vars"):
        for seg in entry["writes_shared"][kind]:
            for one in re.split(r"[;\s]+", seg.strip().strip("\"'")):
                if one.startswith("/etc/config/") or one in ("/etc/rc.local",
                                                             "/etc/crontabs/root",
                                                             "/etc/opkg/distfeeds.conf"):
                    if one not in shared_paths:
                        shared_paths.append(one)
    # uci 写法（`uci set fstab.xxx`、`uci commit dhcp`）不出现文件路径，
    # 但对应的 `/etc/config/<cfg>` 同样是「卸载后必须还在」的基线文件
    for seg in entry["writes_shared"]["uci"]:
        m = UCI_CFG_RE.search(seg)
        if m and "$" not in m.group(1):
            p = "/etc/config/%s" % m.group(1)
            if p not in shared_paths:
                shared_paths.append(p)

    for kind in ALL_CLASSES:
        for seg in entry["writes_shared"][kind]:
            if seg not in keep_shared:
                keep_shared.append(seg)

    # ---- post_condition：卸载后用来判定「真的清干净了」的谓词
    pc = []
    for p in remove_paths:
        # 上游卸载脚本**点名要删**的一律判「文件不存在」—— 哪怕落在 /etc/config/：
        # `/etc/config/accelerator` 是插件建的整份配置（雷神），该整份消失，
        # 不是「文件还在但少了个 section」。只有「卸载后必须还在」的基线配置
        # （/etc/config/fstab、network…）才用 lacks_section。
        if is_pseudo_fs(p):
            # /sys|/proc|/dev：出厂无原件，还原值是上游运行时保存的动态值
            # （installer.sh:69781 写回 $saved_hook）—— 既不能 absent 也不能比对基线。
            needs_manual.append("伪文件系统路径，无法自动断言（出厂无原件；"
                                "还原值由上游运行时决定，须人工 cat 核对）: " + p)
            continue
        if rom_has(p):
            # 铁律：/rom 存在 = 出厂就有，插件不可能是创建者 → 只能重置不能删。
            # 上游却把它列进删除候选 —— 这本身就是必须人工裁定的红灯。
            needs_manual.append("★/rom 存在此出厂件，插件不可能是创建者，只能重置不能删"
                                "（上游却要求删）: " + p)
            continue
        if p.startswith("/etc/config/") and p not in rm_derived:
            pc.append("lacks_section:%s" % p)
        else:
            pc.append("absent:%s" % p)
    for svc in stop_services:
        pc.append("not_running:%s" % svc)
    for path in disable_rc:
        pc.append("no_symlink:%s" % path)
    for key in uci_reset:
        pc.append("lacks_key:%s" % key)
    for seg in u["marker"]:
        pc.append("no_marker:%s" % seg[:60])
    # 🚫 刻意**不**产出 `no_net_rule:` 谓词。
    #    它的参数是「命令片段」而不是「规则特征」：引擎执行 `no_net_rule:fw3 reload`
    #    时会去 iptables 里找一条叫 "fw3 reload" 的规则 —— 恒真。**假谓词比没有谓词
    #    更坏**，它让人以为「验收过了」。而且 `fw3 reload` / `mtkhnat` 根本不是规则，
    #    是动作与服务。
    #    唯一看似可抽的「表/链/目标」三元组同样不安全：上游规则的动作对象几乎全是
    #    shell 变量（`ip rule del to "$remote_subnet"`、
    #    `iptables -s "$local_subnet" -j MASQUERADE`），而 `nat/POSTROUTING/MASQUERADE`
    #    出厂固件自身就在用 —— 拿它判「没清干净」会在干净机器上失败。
    #    → 降级为 needs_manual 人工提示（见上）。
    #    回归守卫：_selfcheck.py §10 已把 no_net_rule 移出谓词白名单，
    #    一旦重新出现即报「白名单外的谓词」+ 专门的计数断言。
    for seg in u["cron"]:
        pc.append("no_cron:%s" % seg[:60])
    for seg in u["rclocal"]:
        pc.append("no_block:%s" % seg[:60])
    for seg in u["store"]:
        pc.append("no_store_entry:%s" % seg[:60])
    for p in shared_paths:
        # matches_baseline 的真实语义 = 「与 /rom 逐字节一致」→ 只对**出厂件**成立。
        # 实测反例：/etc/config/accelerator 是雷神自建配置，/rom 无原件，却被 19 个
        # feature 断言「必须等于出厂原件」—— 引擎执行时 cmp 恒假，健康机也会报「没清干净」。
        if is_pseudo_fs(p):
            needs_manual.append("伪文件系统路径，无法自动断言（出厂无原件；"
                                "还原值由上游运行时决定，须人工 cat 核对）: " + p)
            continue
        if rom_has(p):
            pc.append("matches_baseline:%s" % p)
        else:
            needs_manual.append("插件自建文件（/rom 无原件），逐字节比对必假 → 不自动断言: " + p)
    # 命中禁区（系统关键文件/目录）的路径**不能删**，但卸载后**必须回到基线** ——
    # 否则像 feature 26/27（运营商显示修复、首页温度切换）这种「只改固件文件、
    # 不装包不建目录」的功能会一条验收谓词都没有，等于没有验收标准。
    for p in forbidden:
        if p.startswith("/") and not any(p.startswith(x) for x in CONTAINER_DIRS):
            if is_pseudo_fs(p) or not rom_has(p):
                needs_manual.append("禁区路径但 /rom 无原件，比对基线必假 → 人工核对: " + p)
                continue
            tag = "matches_baseline:%s" % p
            if tag not in pc:
                pc.append(tag)
    # ---- 上游卸载函数解歧产出的谓词（最可靠的一批）
    # 固件 LuCI 模板：卸载后必须与 /rom 逐字节一致（上游 rewrite_*_view remove
    # 就是「按 marker 摘掉注入段」，摘干净了自然等于原文）
    for p in baseline_paths:
        if is_pseudo_fs(p) or not rom_has(p):
            needs_manual.append("判定为固件文件但 /rom 清单里没有 —— 判定或清单有误，须人工: " + p)
            continue
        tag = "matches_baseline:%s" % p
        if tag not in pc:
            pc.append(tag)
    # 注入残留：与上游 selfcheck 同源的强判据（它自己也是 grep -Fc marker == 1）
    for mv in un["markers"]:
        tag = "no_marker:%s" % mv
        if tag not in pc:
            pc.append(tag)
    # 出厂服务（uhttpd/dnsmasq/firewall…）：我们拒绝停/禁它们。
    # 那么验收标准就是**它们必须还活着** —— 否则「修运营商显示」把 LuCI 弄挂了也没人发现。
    for f in forbidden:
        if f.startswith("service:"):
            tag = "keeps_service:%s" % f.split(":", 1)[1]
            if tag not in pc:
                pc.append(tag)
    # 上游卸载脚本**自己写明的**验收断言：`[ ! -e /etc/qy ] || { echo "残留"; exit 1; }`
    # —— 这是上游亲口定义的「卸载干净」标准，比任何推断都硬。
    for p in un["assert_absent"]:
        if rom_has(p):
            needs_manual.append("★/rom 存在此出厂件，插件不可能是创建者，只能重置不能删"
                                "（上游却断言它必须消失）: " + p)
            continue
        if is_pseudo_fs(p):
            needs_manual.append("伪文件系统路径，无法自动断言: " + p)
            continue
        tag = "absent:%s" % p
        if tag not in pc:
            pc.append(tag)
    # 上游有意保留的持久路径（卡名 map、备份目录…）：卸载后**必须仍在**
    for p in un["keeps"]:
        tag = "keeps:%s" % p
        if tag not in pc:
            pc.append(tag)
    pc = list(OrderedDict.fromkeys(pc))

    needs_manual = list(OrderedDict.fromkeys(needs_manual))
    if forbidden:
        needs_manual.insert(0, "★曾命中系统关键路径，已剔除并需人工裁定: %s" % forbidden)

    # ---- 安全档位（计划 §6 风险三档）
    hot = any(x.startswith(("/etc/config/firewall", "/etc/config/dhcp", "/etc/config/mtkhnat"))
              for x in remove_paths) or any("ip rule" in x for x in u["net"])
    if hot:
        safety, why = "high", "触及防火墙 / DHCP / 硬件加速 / 路由规则 —— 会断网，必须人工在旁"
    elif remove_paths or stop_services or packages or uci_reset:
        safety, why = "medium", "动服务或写配置；断开自身管理通道的风险存在"
    else:
        safety, why = "low", "只有文件/注册项层面的增删（或写盘全在共用设施里）"

    # ---- 零写盘（`查看奇游状态` 这类纯查询动作）：本来就没什么可清。
    # 显式打 read_only，而不是让它带着空的 post_condition 混过去 ——
    # 守卫据此区分「只读 ⇒ 无需谓词（正确）」与「该有谓词却没有（缺陷）」。
    read_only = not (packages or stop_services or disable_rc or uci_reset
                     or remove_paths or baseline_paths or un["rm"] or un["views"]
                     or un["markers"] or un["procs"] or un["assert_absent"]
                     or shared_paths
                     or u["marker"] or u["cron"] or u["rclocal"] or u["net"] or u["store"])
    if read_only:
        safety, why = "low", "只读查询类动作：无任何写盘足迹，无需清除谓词"

    return {
        "status": "draft-需真机对账",
        "safety": safety,
        "safety_reason": why,
        "read_only": read_only,
        # 只读行里提到、但**没被当成写盘证据**的路径型引用（白名单表、状态检查清单里的）。
        # 典型：ttyd 的 `ttyd_path_is_allowlisted()` 列出 /etc/config/ttyd、/etc/init.d/ttyd …
        # 那是它**确实拥有**的文件，只是没写在写命令的实参位置 → 被只读闸门滤掉。
        # 单列出来供人工核「是不是漏了」，**不参与自动删除**。
        "readonly_refs": list(u.get("_ro_skipped") or []),
        "remove_packages": packages,
        "stop_services": stop_services,
        "disable_rc": disable_rc,
        "uci_reset": uci_reset,
        "remove_paths": remove_paths,
        # 固件文件：不能删，只能在卸载时「摘掉注入段还原成 /rom 原文」
        "restore_baseline": baseline_paths,
        # 注入标记原文：用来判「注入段是否摘干净」（与上游 selfcheck 同源）
        "inject_markers": un["markers"],
        # 上游有意保留的持久路径（卸载后必须仍在）
        "keeps": un["keeps"],
        # 上游卸载脚本里显式 kill 的进程 / 自己写明的 `[ ! -e ]` 断言
        "kill_procs": un["procs"],
        "upstream_assert_absent": un["assert_absent"],
        # 生成式卸载助手（`X_write_uninstall_helper -> /usr/libexec/xxx-uninstall`）
        "generated_uninstall_helpers": un["helpers"],
        # 解歧依据：上游自己的卸载函数名（空 = 本轮没有权威依据，谓词靠启发式）
        "upstream_uninstall_funcs": un["funcs"],
        "forbidden": forbidden,
        "keep_shared": keep_shared,
        "post_condition": pc,
        "needs_manual": needs_manual,
    }


def norm_dir(p):
    for pre in sorted(DIR_PREFIXES, key=len, reverse=True):
        if p.startswith(pre):
            return pre
    return p


EXTRA_CLASSES = ["vars", "targets"]      # 需要变量解析，不能纯靠正则
ALL_CLASSES = [k for k, _ in WRITE_PATTERNS] + EXTRA_CLASSES
# 辅助键：不作为「写盘类别」报告，只标证据强度
AUX_KEYS = ["_weak", "_partial", "_ro_skipped"]

# 变量命中要「这一行确实在写盘」才算证据。否则 `uci set x.shell='/bin/sh'` 里的
# /bin/sh 会被当成我们写过的文件 —— 第一次生成清除草稿时它就进了删除候选。
WRITEISH_RE = re.compile(
    r"(?:>>?|\btee\b|\bcp\b|\bmv\b|\binstall\b|\bln\s+-s\b|\bmkdir\b|"
    r"\bsed\s+-i\b|\btouch\b|\bchmod\b|\bchown\b|\bcat\b|\bdd\b|\bunzip\b|\btar\b)")


def empty_writes():
    w = OrderedDict((k, []) for k, _ in WRITE_PATTERNS)
    for k in EXTRA_CLASSES + AUX_KEYS:
        w[k] = []
    return w


def is_partial(raw, end):
    """p 之后紧跟变量 → 抽到的路径是被变量截断的半截（如 `/etc/rc.d/S` + `${n}`）。"""
    tail = raw[end:end + 3]
    return tail.startswith("$") or tail.startswith('"$')


# heredoc 正文里**仍然要抽**的类别。
#
# 为什么限制：上游那个公共卸载助手（write_plugin_uninstall_assets）用一个几千行的
# heredoc 写出一份「所有插件通用」的卸载脚本，载荷里成片出现别人的路径
# （/etc/openclash、/etc/openlist…）。不限的话每个功能的「共用写盘」里都会有全部
# 插件的路径 —— 真机对账时就表现为 /etc/openclash 被 19 个功能认领成「共用、该保留」，
# 将来卸载 OpenClash 反而不敢删它。
#
# marker 例外：补丁指纹（Design By MaYe 之类）恰恰藏在正文里，是「装没装过」的证据。
#
# ⚠️ 2026-09-20 修正：这个限制**只适用于数据式 heredoc**。
# 脚本式 heredoc（正文首行是 `#!`）是「嵌入式安装脚本」，正文本身就是可执行代码，
# 必须按普通代码抽全类别 —— 否则 ttyd / MosDNS / Open-Box / eFanCtrl / MT5700 /
# 5G 连接监听这一整类功能的写盘足迹会被判成 0。见 classify_heredocs。
IN_HEREDOC_CLASSES = ("marker",)


def extract_writes(lines, line_idx_set, heredoc=None, var_paths=None,
                   readonly_lines=None, script_heredoc=None):
    """在给定行集合内跑十一类正则 + 两类变量解析，返回 (writes, unclassified)

    `heredoc`：传**数据式** heredoc 的正文行（见 classify_heredocs）。这些行只抽
        IN_HEREDOC_CLASSES（marker），其余类别跳过。**脚本式 heredoc 的行不要传进来**，
        它们要按普通代码抽全类别。

    `readonly_lines`：传「所有归属函数都不是写函数」的行。这些行里的路径只是被**读**
        （`[ -f /etc/openclash/x ]`、`readlink -f`、`log "... /etc/openclash ..."`），
        除 marker 外一律不抽 —— 否则会凭空生出「要删 /etc/openclash」这种假条目。

    `script_heredoc`：仅用于给 unclassified 打 `in_heredoc` 标记。
    """
    w = empty_writes()
    unclassified = []
    heredoc = heredoc or set()
    var_paths = var_paths or {}
    readonly_lines = readonly_lines or set()
    script_heredoc = script_heredoc or set()
    for i in line_idx_set:
        if i >= len(lines):
            continue
        raw = lines[i]
        st = raw.strip()
        if not st or st.startswith("#"):
            continue
        if st in ("{", "}", "esac", "fi", "then", "do", "done", "else"):
            continue
        in_hd = i in heredoc
        is_ro = (not in_hd) and (i in readonly_lines)
        # 数据式 heredoc 与只读行同一处理：只留 marker
        marker_only = in_hd or is_ro
        hit_any = False
        for kind, pat in WRITE_PATTERNS:
            if marker_only and kind not in IN_HEREDOC_CLASSES:
                # 只读闸门滤掉的**路径型**证据单独留档：它们往往是「白名单 / 状态检查」
                # 里列出的、本插件确实拥有的文件（ttyd 的
                # `ttyd_path_is_allowlisted() { case ... /etc/config/ttyd|/etc/init.d/ttyd ... }`
                # 就是），只是没有写在写命令的实参位置。不暴露出来就会静默漏删。
                # 只记**只读行**的；数据式 heredoc 里的路径是「文件内容」，记了全是噪声。
                if is_ro and kind in ("dirs", "initd", "rcd", "hotplug"):
                    for m in pat.finditer(raw):
                        seg = norm_dir(m.group(0).strip()) if kind == "dirs" else m.group(0).strip()
                        if seg not in w["_ro_skipped"]:
                            w["_ro_skipped"].append(seg)
                continue
            for m in pat.finditer(raw):
                seg = m.group(0).strip()
                if kind == "dirs":
                    seg = norm_dir(seg)
                if kind == "opkg" and "$" in seg:
                    seg += "   # 含变量，需人工确认包名"
                if seg not in w[kind]:
                    w[kind].append(seg)
                if is_partial(raw, m.end()) and seg not in w["_partial"]:
                    w["_partial"].append(seg)
                hit_any = True
        if in_hd or i in script_heredoc:
            if not hit_any and IO_HINT.search(raw):
                unclassified.append({"line": i + 1, "snippet": st[:160], "in_heredoc": True})
            continue
        # 变量路径：`$TPL`、`"$APPCENTER_CONTROLLER"` 之类还原成绝对路径。
        # 但只有这一行确实在写盘时才收（见 WRITEISH_RE），且一律标为**弱证据**：
        # 我们知道这个变量指向哪儿，但「指向」不等于「写入」，不能作为删除依据。
        if not is_ro and WRITEISH_RE.search(raw):
            for vm in VARREF_RE.finditer(raw):
                p = var_paths.get(vm.group(1))
                if p:
                    if p not in w["vars"]:
                        w["vars"].append(p)
                    if p not in w["_weak"]:
                        w["_weak"].append(p)
                    hit_any = True
        # 重定向目标：`> /etc/rc.local`、`>>"$rc_file"`、`tee "$f"` —— 最直接的写盘证据
        for rm in (() if is_ro else REDIR_RE.finditer(raw)):
            p = resolve_ref(rm.group(1), var_paths)
            if p and p != "/dev/null" and not p.startswith("/dev/"):
                if p not in w["targets"]:
                    w["targets"].append(p)
                if is_partial(raw, rm.end()) and p not in w["_partial"]:
                    w["_partial"].append(p)
                hit_any = True
        if not hit_any and IO_HINT.search(raw):
            unclassified.append({"line": i + 1, "snippet": st[:160], "in_heredoc": False})
    return w, unclassified


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", default=DEFAULT_INSTALLER)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--report", default=DEFAULT_REPORT)
    args = ap.parse_args()

    if not os.path.isfile(args.installer):
        print("[FATAL] 找不到上游脚本: %s" % args.installer)
        return 2

    raw, lines = read_lines(args.installer)
    sha = hashlib.sha256(raw).hexdigest()
    heredoc, hregions = compute_heredocs(lines)
    var_paths = collect_var_paths(lines)
    var_literals = collect_var_literals(lines)
    unclosed = [r for r in hregions if not r["closed"]]
    report = []
    report.append("上游脚本: %s" % args.installer)
    report.append("字节 %d / 行 %d / sha256 %s" % (len(raw), len(lines), sha))
    report.append("heredoc 正文行: %d 行（占全文 %.1f%%）—— 函数地图跳过它们，写盘抽取保留"
                  % (len(heredoc), 100.0 * len(heredoc) / max(1, len(lines))))
    report.append("heredoc 区间: %d 个；未闭合 %d 个%s"
                  % (len(hregions), len(unclosed),
                     "  ★未闭合会把后面整段误判成正文，必须人工看" if unclosed else "（全部正常闭合）"))
    for r in unclosed[:20]:
        report.append("    未闭合 L%d~L%d delim=%r" % (r["start"], r["end"], r["delim"]))
    report.append("变量路径表: %d 条（`VAR=/abs/path` → 写盘抽取时把 $VAR 还原成真路径）"
                  % len(var_paths))
    report.append("变量字面值表: %d 条（不限路径；注入 marker 常量、备份目录靠它还原）"
                  % len(var_literals))

    fmap, n_funcs, n_topclose = build_function_map(lines, heredoc)
    nested = count_nested(fmap)
    ok = (n_funcs - nested) == n_topclose
    report.append("函数地图: %d 个函数；非 heredoc 的顶格 '}' 共 %d 个；嵌套定义的函数 %d 对"
                  " → 风格自校验 %s"
                  % (n_funcs, n_topclose, nested,
                     "一致（%d-%d=%d）" % (n_funcs, nested, n_topclose) if ok
                     else "★不一致，需人工看"))
    for a, b, la, lb in nested_pairs(fmap)[:10]:
        report.append("    嵌套: %s (L%d) 里定义了 %s (L%d)" % (a, la, b, lb))

    dispatch = parse_dispatch(lines, fmap, report)
    report.append("分派解析: 共 %d 个 feature" % len(dispatch))

    menus = parse_menus(lines, fmap)
    # 参考机型画像：这台 NRadio_C2000Ultra 上**为假**的菜单谓词。
    # 来源是真机菜单实测（_maye_probe_report.md / 2026-09-20）：
    #   · 分类 1 打印的是 default 分支（无机型后缀）→ 非 AK68-798、非 C8-788
    #   · 分类 4 没有「4. 轻量应用商店」     → 不支持 lightweight_appcenter
    #   · 分类 5 没有「5G 聚合修复检查」      → 不支持 5G 聚合
    #   · 分类 5 没有「5G 连接监听」          → 不支持 CPE 监控
    #   · 分类 5 的 prompt 收成 `0-8 / 11-12`（而非 `0-10 / 11-12`），与上面两条吻合
    REFERENCE_FALSE_CONDS = [
        "is_current_model_ak798",
        "is_current_model_c8_788",
        "lightweight_appcenter_model_supported",
        "nradio_5g_aggregation_model_supported",
        "nradio_cpe_monitoring_model_supported",
    ]
    menus_proj = parse_menus(lines, fmap, false_conds=REFERENCE_FALSE_CONDS)
    report.append("菜单函数: %d 个（含 print_menu_item 的函数）" % len(menus))
    _mi = sum(len(m["items"]) for m in menus.values())
    _mc = sum(1 for m in menus.values() for it in m["items"] if it["cond"])
    _md_ = sum(1 for m in menus.values() for it in m["items"] if it["expr"])
    _unbal = [k for k, m in menus.items() if m.get("unbalanced")]
    report.append("菜单项: %d 条；其中带机型条件 %d 条、用变量编号 %d 条" % (_mi, _mc, _md_))
    report.append("菜单条件栈自校验: %s"
                  % ("全部平衡" if not _unbal
                     else "★%d 个菜单函数 if 栈未平衡（cond 不可信，须人工看）: %s"
                          % (len(_unbal), ", ".join(_unbal))))
    # 投影自校验：参考机型上，投影后的每个分类应与真机实测条数一致
    _REAL_EXPECT = {"common_plugin_menu": 11, "network_route_menu": 8,
                    "game_accelerator_menu": 3, "appcenter_polish_menu": 4,
                    "maintenance_test_menu": 10}
    report.append("菜单投影（参考机型 %s，%d 个谓词为假）自校验:"
                  % ("NRadio_C2000Ultra", len(REFERENCE_FALSE_CONDS)))
    for _mn, _exp in _REAL_EXPECT.items():
        _got = len(menus_proj.get(_mn, {}).get("items") or [])
        report.append("    %-24s 投影 %-3d 真机 %-3d %s"
                      % (_mn, _got, _exp, "✓" if _got == _exp else "★不一致"))
    _mapped = set()
    _proj_mapped = set()
    for _md in menus.values():
        for _mp in _md["maps"]:
            _mapped.add(_mp["feature"])
    for _md in menus_proj.values():
        for _mp in _md["maps"]:
            _proj_mapped.add(_mp["feature"])
    report.append("菜单号→feature 映射覆盖: 并集 %d 个 / 投影 %d 个（共 %d 个 feature）"
                  % (len(_mapped), len(_proj_mapped), len(dispatch)))
    report.append("    投影下仍不在任何分类菜单里的 feature: %s"
                  % sorted(set(dispatch) - _proj_mapped))

    # ---- 先算全部闭包（两趟：先闭包 → 再统计共用度 → 再分「独有 / 共用」）
    fclos = OrderedDict()
    for fno in sorted(dispatch):
        h = dispatch[fno].get("handler")
        if h and h in fmap:
            fclos[fno] = closure(h, fmap, lines, heredoc)
        else:
            fclos[fno] = ([], [])

    # 函数 → 被多少个功能共用。上游有个「装完必备」的公共块
    # （set_appcenter_entry / write_plugin_uninstall_assets / patch_common_template），
    # 17 处安装流程都会调它 —— 它们写的是**所有插件共用**的应用商店注册项
    # 与统一卸载助手。删除单个插件时绝不该动这些，否则会把别的插件一起废掉。
    func_feat_count = OrderedDict()
    for _fno, (fns, _l) in fclos.items():
        for fn in fns:
            func_feat_count[fn] = func_feat_count.get(fn, 0) + 1
    common_funcs = set(fn for fn, c in func_feat_count.items() if c >= SHARED_MIN)
    common_rank = sorted(func_feat_count.items(), key=lambda kv: (-kv[1], kv[0]))

    # 行 → 归属函数（嵌套时一个行可属多个函数）
    line_owner = {}
    for fn, (s, e) in fmap.items():
        for i in range(s, min(e, len(lines) - 1) + 1):
            line_owner.setdefault(i, []).append(fn)

    # ---- 两道新闸门（2026-09-20）
    #   A. heredoc 分型：脚本式正文要按普通代码抽全类别；数据式只抽 marker。
    #      不做的后果：ttyd / MosDNS / Open-Box / eFanCtrl / MT5700 / 5G 连接监听
    #      这一整类「生成嵌入式安装脚本」的功能，写盘足迹被判成 0。
    #   B. 只读闸门：只出现在「非写函数」体内的路径引用一律不抽。
    #      不做的后果：feature 24「封版工具箱」只打印诊断摘要，却被判成
    #      「要删 /etc/openclash、要停 openclash」（踩红线）。
    write_funcs = compute_write_funcs(fmap, lines, heredoc)
    script_hd_lines, data_hd_lines = classify_heredocs(lines, heredoc, hregions)
    ro_lines = readonly_lines_of(fmap, lines, line_owner, write_funcs,
                                 script_hd_lines, data_hd_lines)
    report.append("写函数判定: %d / %d 个函数含写动词（不动点后）—— 只作 src.funcs 的参考"
                  % (len(write_funcs), len(fmap)))
    report.append("行级只读闸门: %d 行不含写动词（其中的路径引用一律不当写盘证据）"
                  % len(ro_lines))
    report.append("heredoc 分型: 脚本式 %d 行（纳入写盘抽取）/ 数据式 %d 行（只抽 marker）"
                  % (len(script_hd_lines), len(data_hd_lines)))

    report.append("公共设施函数（被 ≥%d 个功能共用）: %d 个"
                  % (SHARED_MIN, len(common_funcs)))
    for fn, c in common_rank[:15]:
        if c >= SHARED_MIN:
            report.append("    共用 %2d 个功能  %s" % (c, fn))

    # ---- 组装 features
    features = []
    closure_lines_all = set()
    for fno in sorted(dispatch):
        d = dispatch[fno]
        h = d.get("handler")
        fns, lidx = fclos[fno]
        entry = {
            "key": d.get("key"), "feature": fno, "menu_path": d.get("path"),
            "title": d.get("title"), "handler": h,
            "src": {"line": d.get("src_line"), "funcs": fns, "span": None},
            "writes": None, "writes_unique": None, "writes_shared": None,
            "cleanup": None, "upstream_cleanup": [], "shared_funcs": [],
        }
        if lidx:
            entry["src"]["span"] = [min(lidx) + 1, max(lidx) + 1]
            entry["upstream_cleanup"] = upstream_cleanup_funcs(fns)
            # feature 自己的 handler 就是卸载动作时（奇游 `3 > 1 > 3`、雷神 `3 > 2 > 4`），
            # 它自己就是权威 —— 它的 `rm -rf` 列表写明该删什么。
            # 不补这一条：这两个功能会是「零谓词」，和 26/27 一样等于没有验收标准。
            if (h and OWN_UNINSTALL_RE.match(h)
                    and h not in entry["upstream_cleanup"]):
                entry["upstream_cleanup"].insert(0, h)
            entry["shared_funcs"] = sorted(f for f in fns if f in common_funcs)
            # 按「行归属函数是否属公共设施」切开两桶
            shared_lines, uniq_lines = [], []
            for i in lidx:
                owners = line_owner.get(i)
                if owners and any(o in common_funcs for o in owners):
                    shared_lines.append(i)
                else:
                    uniq_lines.append(i)
            w_all, unc = extract_writes(lines, lidx, data_hd_lines, var_paths,
                                        ro_lines, script_hd_lines)
            w_uniq, _ = extract_writes(lines, uniq_lines, data_hd_lines, var_paths,
                                       ro_lines, script_hd_lines)
            w_shr, _ = extract_writes(lines, shared_lines, data_hd_lines, var_paths,
                                      ro_lines, script_hd_lines)
            entry["writes"] = w_all
            entry["writes_unique"] = w_uniq
            entry["writes_shared"] = w_shr
            entry["unclassified_in_closure"] = unc
            entry["cleanup"] = build_cleanup(
                entry, lines, fmap, var_literals,
                "\n".join(lines[i] for i in lidx if 0 <= i < len(lines)))
            closure_lines_all.update(lidx)
        else:
            entry["writes"] = empty_writes()
            entry["writes_unique"] = empty_writes()
            entry["writes_shared"] = empty_writes()
            entry["unclassified_in_closure"] = []
            entry["cleanup"] = {"status": "no-handler", "safety": "unknown",
                                "post_condition": []}
        features.append(entry)

    # ---- 标题/路径回填
    # 有些 feature 的 case 分支是「裸函数调用」而不是
    # `run_recorded_menu_feature "路径" "标题" 函数`（如 26/27:
    # `26) manage_nradio_operator_display_fix ;;`），于是 title/path 抓不到。
    # 这些功能的处理函数本身往往有子菜单（`manage_xxx`），从菜单 label 回填标题最稳。
    feat2label = {}
    for _mn, _md in menus.items():
        for _it, _f in menu_item_features(_md):
            if _f is not None:
                feat2label.setdefault(_f, _it["label"])
    filled = []
    for f in features:
        if not f.get("title") and f["feature"] in feat2label:
            f["title"] = feat2label[f["feature"]]
            filled.append(f["feature"])
    report.append("标题回填（裸函数调用分支，从菜单 label 取）: %d 个 → %s"
                  % (len(filled), filled))
    no_title = [f["feature"] for f in features if not f.get("title")]
    report.append("仍无标题的 feature: %d 个 %s" % (len(no_title), no_title))
    no_path = [f["feature"] for f in features if not f.get("menu_path")]
    report.append("仍无菜单路径的 feature: %d 个 %s" % (len(no_path), no_path))

    all_lines = set(range(len(lines)))
    rest = sorted(all_lines - closure_lines_all)
    w_rest, unc_rest = extract_writes(lines, rest, data_hd_lines, var_paths,
                                      ro_lines, script_hd_lines)
    unc_rest_real = [x for x in unc_rest if not x["in_heredoc"]]
    unc_rest_hd = [x for x in unc_rest if x["in_heredoc"]]
    report.append("")
    report.append("=== 闭包外仍出现写盘语句（可能是漏掉的公共函数，也可能是菜单/提示类噪声）===")
    for kind in ALL_CLASSES:
        if w_rest[kind]:
            report.append("  [%s] %d 条，示例: %s" % (kind, len(w_rest[kind]), w_rest[kind][:4]))
    report.append("  闭包外 unclassified: %d 条（其中 heredoc 正文 %d 条 —— 那些是「被写进设备的"
                  "文件」里自己的代码，属正常；真正要看的是剩下 %d 条）"
                  % (len(unc_rest), len(unc_rest_hd), len(unc_rest_real)))
    for x in unc_rest_real[:60]:
        report.append("    L%-6d %s" % (x["line"], x["snippet"][:120]))

    # ---- 菜单 → feature 对照（人读用）
    report.append("")
    report.append("=== 菜单号 → feature 号（含机型条件；并集 ≠ 单机型所见，须按 cond 判）===")
    for mname, md in menus.items():
        report.append("  %s" % mname)
        for h in (md.get("headers") or []):
            report.append("    header %r   cond=%s   L%s"
                          % (h["header"], h["cond"] or "(无条件)", h["src"]))
        if md.get("prompt"):
            report.append("    prompt %r" % md["prompt"])
        for it, f in menu_item_features(md):
            report.append("    %-3s) %-40s -> feature %-4s expr=%-30s cond=%s"
                          % (it["no"] if it["no"] is not None else "??",
                             it["label"][:40], f if f is not None else "-",
                             it["expr"] or "-", it["cond"] or "(无条件)"))

    # ---- 每个 feature 的写盘摘要
    report.append("")
    report.append("=== 每个 feature 的写盘足迹（供人工核）===")
    for f in features:
        report.append("- feature %s  %s  handler=%s  span=%s"
                      % (f["feature"], f["title"], f["handler"], f["src"]["span"]))
        for kind in ALL_CLASSES:
            u = f["writes_unique"][kind]
            s_ = f["writes_shared"][kind]
            if u or s_:
                report.append("    %-9s 独有 %d: %s" % (kind, len(u), "; ".join(u[:5])))
                if s_:
                    report.append("    %-9s 共用 %d: %s" % ("", len(s_), "; ".join(s_[:5])))
        if f["shared_funcs"]:
            report.append("    共用实现（勿随单插件删除）: %s" % ", ".join(f["shared_funcs"][:6]))
        c = f["cleanup"]
        report.append("    清除草稿[%s/%s] 删包%d 停服务%d 关rc%d uci%d 删路径%d 谓词%d 待人工%d 禁区%d"
                      % (c["status"], c.get("safety", "?"), len(c.get("remove_packages", [])),
                         len(c.get("stop_services", [])), len(c.get("disable_rc", [])),
                         len(c.get("uci_reset", [])), len(c.get("remove_paths", [])),
                         len(c.get("post_condition", [])), len(c.get("needs_manual", [])),
                         len(c.get("forbidden", []))))
        if c.get("forbidden"):
            report.append("    ★曾命中系统关键路径（已剔除，待人工裁定）: %s" % c["forbidden"])
        if f["unclassified_in_closure"]:
            report.append("    ★unclassified %d 条: %s"
                          % (len(f["unclassified_in_closure"]),
                             "; ".join(x["snippet"][:60] for x in f["unclassified_in_closure"][:4])))
        if f["upstream_cleanup"]:
            report.append("    上游自带卸载/清理函数 %d 个: %s"
                          % (len(f["upstream_cleanup"]), ", ".join(f["upstream_cleanup"])))
        if c.get("restore_baseline"):
            report.append("    ↺ 固件文件（不删，改回 /rom 基线）: %s" % c["restore_baseline"])
        if c.get("inject_markers"):
            report.append("    ⌫ 注入标记（须摘干净）: %s" % c["inject_markers"])
        if c.get("keeps"):
            report.append("    ✋ 有意保留（卸载后必须仍在）: %s" % c["keeps"])
        if c.get("generated_uninstall_helpers"):
            report.append("    ⚙ 上游生成式卸载脚本: %s" % c["generated_uninstall_helpers"])
        if c.get("upstream_assert_absent"):
            report.append("    ✅ 上游自己写明的验收断言（`[ ! -e ]`）: %s"
                          % c["upstream_assert_absent"])
        if c.get("kill_procs"):
            report.append("    ☠ 上游显式 kill 的进程: %s" % c["kill_procs"])

    # ---- 验收谓词覆盖率：本轮的目标是「每个有写盘的功能至少一条谓词」
    pc_nonempty = [f for f in features if (f["cleanup"].get("post_condition") or [])]
    pc_empty = [f for f in features
                if not (f["cleanup"].get("post_condition") or [])
                and not f["cleanup"].get("read_only")]
    ro = [f for f in features if f["cleanup"].get("read_only")]
    resolved = [f for f in features if (f["cleanup"].get("upstream_uninstall_funcs") or [])]
    report.append("")
    report.append("=== 验收谓词覆盖（post_condition 非空）: %d / %d ==="
                  % (len(pc_nonempty), len(features)))
    report.append("    只读查询类（零写盘，本就无需谓词）: %d 个 → %s"
                  % (len(ro), [f["feature"] for f in ro]))
    report.append("    靠上游 uninstall 函数解歧的 feature: %d 个 → %s"
                  % (len(resolved), [f["feature"] for f in resolved]))
    if pc_empty:
        report.append("    ★仍有 %d 个**有写盘**但无验收谓词的 feature（须人工定性）:" % len(pc_empty))
        for f in pc_empty:
            c_ = f["cleanup"]
            report.append("      feature %s `%s` 删路径%d 停服务%d 禁区%d 待人工%d"
                          % (f["feature"], f["title"], len(c_.get("remove_paths") or []),
                             len(c_.get("stop_services") or []),
                             len(c_.get("forbidden") or []),
                             len(c_.get("needs_manual") or [])))
    else:
        report.append("    所有**有写盘**的 feature 都有验收谓词 ✓")
    _pred_kind = {}
    for f in features:
        for _p in (f["cleanup"].get("post_condition") or []):
            _pred_kind[_p.split(":", 1)[0]] = _pred_kind.get(_p.split(":", 1)[0], 0) + 1
    report.append("    谓词种类分布: %s" % dict(sorted(_pred_kind.items(), key=lambda kv: -kv[1])))

    # ---- 全文范围内上游自己的卸载/清理函数（我们不用，但要知道有哪些）
    all_cleanup = sorted(n for n in fmap if CLEANUP_FUNC_RE.match(n))
    report.append("")
    report.append("=== 上游全文的卸载/清理/还原函数（共 %d 个；本项目不依赖，仅作对照）===" % len(all_cleanup))
    for k in range(0, len(all_cleanup), 4):
        report.append("    " + "  ".join("%-44s" % x for x in all_cleanup[k:k + 4]))

    payload = {
        "schema": "kunpeng-router-footprint/1",
        "generated_by": "scripts/extract_footprints.py",
        "source": {
            "file": os.path.basename(args.installer),
            "bytes": len(raw), "lines": len(lines), "sha256": sha,
        },
        "stats": {
            "functions": n_funcs,
            "top_level_close_braces": n_topclose,
            "nested_functions": nested,
            "style_selfcheck_ok": ok,
            "heredoc_body_lines": len(heredoc),
            "heredoc_regions": len(hregions),
            "heredoc_unclosed": len(unclosed),
            "var_paths": len(var_paths),
            "var_literals": len(var_literals),
            "features": len(features),
            "features_read_only": len(ro),
            "features_with_post_condition": len(pc_nonempty),
            "features_without_post_condition_and_writable": len(pc_empty),
            "features_resolved_by_upstream_uninstall": len(resolved),
            "menus": len(menus),
            "menu_items": sum(len(m["items"]) for m in menus.values()),
            "menu_items_conditional": sum(1 for m in menus.values()
                                          for it in m["items"] if it["cond"]),
            "menu_items_dynamic_number": sum(1 for m in menus.values()
                                             for it in m["items"] if it["expr"]),
            "menu_functions_unbalanced": len(_unbal),
            "firmware_services": len(FIRMWARE_SERVICES),
            "upstream_cleanup_functions": len(all_cleanup),
            "common_functions": len(common_funcs),
            "shared_min": SHARED_MIN,
        },
        "common_functions": [{"func": fn, "used_by_features": c}
                             for fn, c in common_rank if c >= SHARED_MIN],
        "dispatch": {str(k): {kk: vv for kk, vv in v.items()} for k, v in dispatch.items()},
        "menus": {k: {"headers": v["headers"], "items": v["items"],
                      "maps": v["maps"], "prompt": v["prompt"]}
                  for k, v in menus.items()},
        # 参考机型投影：把 menus 里「本机型为假」的条件块剔掉、编号重排后的结果。
        # 这是**唯一**能直接对着真机屏幕核对的一层 —— 真机实测已逐项吻合。
        "reference_device": {
            "model": "NRadio_C2000Ultra",
            "nros": "2.3.0.n0.c1",
            "assumed_false_conds": REFERENCE_FALSE_CONDS,
            "verified_by": "真机菜单实测 2026-09-20（只进子菜单、只按返回键，未选任何功能项）",
        },
        "menus_reference_projection": {
            k: {"headers": v["headers"], "items": v["items"],
                "maps": v["maps"], "prompt": v["prompt"]}
            for k, v in menus_proj.items()},
        "upstream_cleanup_functions": all_cleanup,
        "features": features,
        "writes_outside_closures": {k: v for k, v in w_rest.items() if v},
        "unclassified_outside_closures": unc_rest,
        "heredoc_unclosed_regions": unclosed,
    }
    os.makedirs(os.path.dirname(args.out), exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=1)
    report.append("")
    report.append("→ 已写出 %s（%.1f KB）" % (args.out, os.path.getsize(args.out) / 1024.0))

    with open(args.report, "w", encoding="utf-8", newline="") as fh:
        fh.write("\n".join(report))
    print("\n".join(report[:40]))
    print("... (完整报告见 %s)" % args.report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
