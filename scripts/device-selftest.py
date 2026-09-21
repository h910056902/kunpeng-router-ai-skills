#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""device-selftest.py —— 设备状态与环境自检 · PC 侧唯一入口（助手菜单 11 · 纯只读）

做什么：
  1. 把设备侧采集器 scripts/payload/kp-selftest.sh 推到设备 /tmp/kps/；
  2. 先过设备侧语法门禁（`sh -n` 必须拿到 SYNTAX_OK）再采集 —— 不通过不往下走；
  3. 解析 TSV 采集流，按**仓库既有阈值**渲染 [ OK ] / [WARN] / [FAIL] / [ SKIP ] 四态；
  4. 以退出码汇报：0 = 无 FAIL · 1 = 存在 FAIL · 2 = 环境错误。

本任务的边界（与 tasks/11-device-selftest.md §0 一致）：
  · 设备侧零写盘、不启停服务、不改 uci、不发 AT（见 payload 头部声明）
  · PC 侧**不落盘任何报告** —— 只打终端，不产生 JSON / markdown
  · **不执行任何修复**：发现问题只给「建议」，由使用者决定；该真修的走 tasks/03、tasks/06~10

凭据：ROUTER_HOST / ROUTER_USER / ROUTER_PW（环境变量），或 --pw / --cred-file（KEY=VALUE 文本）。
      ⚠️ 与 scripts/kp-clean.py 不同，本脚本**不给默认密码** —— 缺密码直接退出码 2。
      设备档案见 AGENTS.md §1。

用法：
    python scripts/device-selftest.py
    python scripts/device-selftest.py --pw ****
    python scripts/device-selftest.py --skip-docker     # dockerd 半死时降级（docker CLI 会挂住）
"""
from __future__ import annotations

import argparse
import io
import os
import re
import sys
import time
import unicodedata

# ----------------------------------------------------------------- 路径
# ⚠️ 一律用 expanduser 推导，绝不写死宿主机用户名（公开仓红线，_selfcheck.py §7a 会查）
SKILL = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "kunpeng-router-tuning")
PAYLOAD = os.path.join(SKILL, "scripts", "payload", "kp-selftest.sh")
DEFAULT_CRED_FILE = os.path.join(os.path.expanduser("~"), ".workbuddy", "kunpeng-router.env")

REMOTE_DIR = "/tmp/kps"
REMOTE_SH = REMOTE_DIR + "/kp-selftest.sh"
EXPECT_VERSION = "1.0.0"

# ----------------------------------------------------------------- 阈值
# 全部引用仓库既有判据，**不新造**（见 tasks/11-device-selftest.md §3）
MARK = {"ok": "[ OK ]", "warn": "[WARN]", "bad": "[FAIL]", "skip": "[ SKIP ]"}

MEM_FUSE = 30000            # kB  <30MB 熔断线：不再加大清单 / 大镜像
MEM_LIGHT = 40000           # kB  >40MB 轻量插件（ocspeed）
MEM_MEDIUM = 100000         # kB  >100MB 中等（OpenClash / maye 总入口 / 体检）
MEM_HEAVY = 250000          # kB  >250MB 重（Docker + 1Panel）

TEMP_WARN = 70000           # mdegC  CPU >70°C 偏热
TEMP_BAD = 75000            # mdegC  CPU >75°C 已过热
DISK_JELLYFIN = 2 * 1024 ** 3   # 容器级磁盘硬门槛 ≥2 GiB
STORE_HEAD = 1.5            # 安装余量安全系数（对齐商店原生 check_size 的宽裕口径）

# RSRP 分档（>=-80→4 优 · >=-90→3 良 · >=-100→2 中 · >=-110→1 弱 · else 0 无）
RSRP_BANDS = [(-80, 4, "优"), (-90, 3, "良"), (-100, 2, "中"), (-110, 1, "弱")]

# 温度读数里哪些 thermal_zone 算 CPU —— 只有 CPU 才拿 CPU 阈值判 FAIL
CPU_ZONE_RE = re.compile(r"cpu|soc|tsadc|mtk|ap_thermal", re.I)

# 日志里出现这些 = 硬故障（不只是"有痕迹"）
OOM_RE = re.compile(r"out of memory|oom.kill|killed process", re.I)


# ----------------------------------------------------------------- 小工具

def _blank(s):
    """设备侧 kv 把空值写成 (空)；两者都算「没采到」。"""
    return s is None or str(s).strip() in ("", "(空)")


def _first_int(s):
    """从 '-85dBm' / 'RSRP -85' / '20.5' 里抽第一个整数；没有则 None。"""
    m = re.search(r"-?\d+", str(s or ""))
    return int(m.group(0)) if m else None


def _strict_int(s):
    """只在「整串就是数字」时返回 int —— (空)/MISSING/脏值一律 None。"""
    t = str(s or "").strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    return None


def _hkb(kb):
    if kb is None:
        return "未知"
    mib = kb / 1024.0
    if mib >= 1024:
        return "%.2f GB" % (mib / 1024.0)
    if mib >= 10:
        return "%.0f MB" % mib
    return "%.1f MB" % mib


def _hsz(b):
    """字节 → 人话（商店 option size 的单位是字节）。"""
    if b is None:
        return "?"
    if b >= 1024 ** 3:
        return "%.2f GB" % (b / 1024.0 ** 3)
    if b >= 1024 ** 2:
        return "%.1f MB" % (b / 1024.0 ** 2)
    if b >= 1024:
        return "%.0f KB" % (b / 1024.0)
    return "%d B" % b


def _hup(sec):
    try:
        sec = int(sec)
    except (TypeError, ValueError):
        return "?"
    d, r = divmod(sec, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    if d:
        return "%d 天 %d 小时 %d 分" % (d, h, m)
    if h:
        return "%d 小时 %d 分" % (h, m)
    return "%d 分" % m


def _clip(s, n=150):
    s = " ".join(str(s or "").split())
    return s if len(s) <= n else s[:n - 1] + "…"


def _df(line):
    """`df -P` 的一行 → (总kB, 已用kB, 可用kB, 挂载点)；解析不了返回 None。"""
    p = str(line or "").split()
    if len(p) < 6:
        return None
    try:
        return int(p[1]), int(p[2]), int(p[3]), p[5]
    except ValueError:
        return None


def _dw(s):
    """显示宽度（中文占 2 列），仅用于对齐，不参与判定。"""
    return sum(2 if unicodedata.east_asian_width(ch) in ("W", "F") else 1 for ch in s)


def _pad(s, w):
    n = w - _dw(s)
    return s + " " * n if n > 0 else s


# ----------------------------------------------------------------- 凭据

def load_creds(path):
    """凭据文件（KEY=VALUE）→ dict；环境变量优先级更高。"""
    vals = {}
    if path and os.path.isfile(path):
        with io.open(path, "r", encoding="utf-8-sig") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#") or "=" not in ln:
                    continue
                k, v = ln.split("=", 1)
                vals[k.strip()] = v.strip().strip('"').strip("'")
    for k in ("ROUTER_HOST", "ROUTER_USER", "ROUTER_PW"):
        if os.environ.get(k):
            vals[k] = os.environ[k]
    return vals


# ----------------------------------------------------------------- 解析

def parse_stream(txt):
    """TSV 采集流 → 结构化 dict。

    V 握手 / S 板块 / K 键值 / L 列表 / E 采集失败 / N 备注 / Z 结束哨兵。
    末行是否为 Z 是本协议唯一能诚实区分「跑完了但没数据」与「被 dropbear 截断」的手段。
    """
    d = {"V": None, "sections": [], "K": {}, "L": {}, "E": {}, "N": [],
         "Z": False, "lines": 0, "last": ""}
    for ln in (txt or "").splitlines():
        d["lines"] += 1
        d["last"] = ln
        p = ln.split("\t")
        tag = p[0]
        if tag == "V" and len(p) >= 3:
            d["V"] = (p[1], p[2])
        elif tag == "S" and len(p) >= 3:
            d["sections"].append((p[1], p[2]))
        elif tag == "K" and len(p) >= 3:
            d["K"][p[1]] = p[2]
        elif tag == "L" and len(p) >= 3:
            d["L"].setdefault(p[1], []).append(p[2])
        elif tag == "E" and len(p) >= 3:
            d["E"][p[1]] = p[2]
        elif tag == "N" and len(p) >= 2:
            d["N"].append(p[1])
        elif tag == "Z" and len(p) >= 2 and p[1] == "END":
            d["Z"] = True
    return d


# ----------------------------------------------------------------- 判定（纯函数）

def _rsrp_level(v):
    for edge, lvl, desc in RSRP_BANDS:
        if v >= edge:
            return ("ok" if lvl >= 3 else "warn"), "档 %d · %s" % (lvl, desc)
    return "bad", "档 0 · 无信号"


def verdicts(d):
    """数据结构 → (rows, apps)。

    rows = [(板块号, level, text)]  ·  apps = [(名称, 字节, 已装, level, 附注)]
    纯函数：不碰网络、不读文件 → 可被离线夹具单测覆盖全部阈值分支。
    """
    K, L, E, N = d["K"], d["L"], d["E"], d["N"]
    rows, apps = [], []

    def add(sec, lvl, txt):
        rows.append((sec, lvl, txt))

    # ================= 1 · 系统资源与环境 =================
    if "board" in E:
        add(1, "bad", "采集失败: ubus call system board —— %s" % E["board"])

    mn, mr = K.get("model_norm", ""), K.get("model_raw", "")
    if mn == "NRadio_C2000Ultra":
        add(1, "ok", "机型 %s（/tmp/sysinfo/model = %s，已归一化）" % (mn, mr or "(空)"))
    elif mn in ("", "(空)", "unknown"):
        add(1, "bad", "机型无法识别（/tmp/sysinfo/model = %s）—— 任务包适用性未知" % (mr or "(空)"))
    else:
        add(1, "warn", "机型 %s 不在本仓已验证清单内（raw = %s）" % (mn, mr or "(空)"))

    rev = K.get("board_release_rev", "")
    if re.match(r"^2\.", rev or ""):
        add(1, "ok", "固件版本 %s（ubus call system board → release.revision，匹配 2.*）" % rev)
    else:
        add(1, "warn", "固件版本 %s 不匹配 2.* —— 请先确认机型与任务包适用性" % (rev or "(空)"))
    add(1, "ok", "OpenWrt %s · 内核 %s" % (K.get("openwrt_release") or "?", K.get("kernel") or "?"))

    la3 = " ".join((K.get("loadavg") or "").split()[:3])
    add(1, "ok", "CPU %s 核 · 负载 %s · 已运行 %s"
        % (K.get("cpu_count") or "?", la3 or "?", _hup(K.get("uptime_s"))))

    mt = _strict_int(K.get("mem_total_kb"))
    ma = _strict_int(K.get("mem_avail_kb"))
    st = _strict_int(K.get("swap_total_kb"))
    sf = _strict_int(K.get("swap_free_kb"))
    if ma is None:
        add(1, "bad", "可用内存采集失败（mem_avail_kb = %s）" % K.get("mem_avail_kb"))
    else:
        head = "可用内存 %s / %s" % (_hkb(ma), _hkb(mt))
        if ma < MEM_FUSE:
            add(1, "bad", "%s —— 低于 30 MB 熔断线：先释放内存，别装大插件" % head)
        elif ma < MEM_LIGHT:
            add(1, "warn", "%s —— 低于轻量插件门槛 40 MB" % head)
        elif ma < MEM_MEDIUM:
            add(1, "warn", "%s —— 属「轻量」档：够 ocspeed 级，不够 OpenClash / maye 全量" % head)
        elif ma < MEM_HEAVY:
            add(1, "ok", "%s —— 属「中等」档：够 OpenClash / maye 总入口 / 体检" % head)
        else:
            add(1, "ok", "%s —— 属「重载」档：够 Docker + 1Panel" % head)
    if st is None:
        add(1, "skip", "swap 读数未采到")
    elif st == 0:
        add(1, "ok", "无 swap（SwapTotal=0，符合本机档案；内存即硬上限）")
    else:
        add(1, "ok", "swap 总 %s / 空闲 %s" % (_hkb(st), _hkb(sf or 0)))
    for r in L.get("SWAP_TOP", []):
        p = (r.split("|") + ["", "", ""])[:3]
        add(1, "warn", "有进程吃 swap：pid %s（%s）%s kB —— 本机无 swap 时应为 0" % (p[0], p[1] or "?", p[2]))

    temps = L.get("TEMP", [])
    if not temps:
        add(1, "skip", "无温度传感器（/sys/class/thermal 未提供）")
    for r in temps:
        p = (r.split("|") + ["", "", ""])[:3]
        zone, typ, val = p
        v = _strict_int(val)
        deg = (v / 1000.0) if v is not None else None
        if deg is None:
            add(1, "warn", "温度读数不可解析：%s" % _clip(r, 80))
        elif CPU_ZONE_RE.search(typ or ""):
            if deg > TEMP_BAD / 1000.0:
                add(1, "bad", "CPU 温度 %.1f °C（%s）—— 已过热，先降负载再谈装插件" % (deg, typ))
            elif deg > TEMP_WARN / 1000.0:
                add(1, "warn", "CPU 温度 %.1f °C（%s）—— >70 偏热，看负载与散热" % (deg, typ))
            else:
                add(1, "ok", "CPU 温度 %.1f °C（%s）" % (deg, typ))
        else:
            add(1, "ok", "温度 %s = %.1f °C（%s，非 CPU，不按 CPU 阈值判定）" % (typ or "?", deg, zone))

    cc = _strict_int(K.get("conntrack_count"))
    cm = _strict_int(K.get("conntrack_max"))
    if cc is not None and cm:
        pct = cc * 100.0 / cm
        add(1, "warn" if pct >= 80 else "ok", "conntrack 连接跟踪 %d / %d（%.0f%%）" % (cc, cm, pct))

    ovd = K.get("overlay_dev", "")
    if ovd == "/dev/mmcblk0p1":
        add(1, "ok", "overlay 载体 %s（TF 卡第 1 分区，正常）" % ovd)
    elif _blank(ovd):
        add(1, "bad", "overlay 载体为空 —— overlay 未挂载，只剩只读固件 + 2 MB ramdisk")
    else:
        add(1, "bad", "overlay 载体 %s（期望 /dev/mmcblk0p1）—— overlay 可能落到 mtd / ramdisk" % ovd)

    mmc = K.get("mmc_present", "")
    if _blank(mmc):
        add(1, "bad", "TF 卡未挂载（/proc/mounts 无 /dev/mmcblk* → /tmp/storage）—— 存储扩展失效")
    else:
        add(1, "ok", "TF 卡在场：%s（%s GB）" % (_clip(mmc, 60), K.get("mmc_size_gb") or "?"))

    for key, label in (("df_overlay", "overlay"), ("df_data", "data"), ("df_tmp", "tmp")):
        df = _df(K.get(key))
        if df:
            add(1, "ok", "%s 挂载 %s：总量 %s / 已用 %s / 可用 %s"
                % (label, df[3], _hkb(df[0]), _hkb(df[1]), _hkb(df[2])))

    dmn = _strict_int(K.get("DMESG_HITS")) or 0
    lrn = _strict_int(K.get("LOGREAD_HITS")) or 0
    dm_rows = L.get("DMESG_HITS", [])
    if any(OOM_RE.search(r) for r in dm_rows):
        add(1, "bad", "内核日志出现 OOM 击杀（dmesg）—— 内存曾被打穿，见下方明细")
    elif dmn or lrn:
        add(1, "warn", "内核 / 系统日志有异常痕迹：dmesg %d 条 · logread %d 条" % (dmn, lrn))
    else:
        add(1, "ok", "内核与系统日志无 OOM / f2fs / mmc / segfault 异常痕迹")
    for r in dm_rows[:8]:
        add(1, "warn", "   dmesg: %s" % _clip(r, 140))
    for r in L.get("LOGREAD_HITS", [])[:5]:
        add(1, "warn", "   logread: %s" % _clip(r, 140))

    rv = K.get("resolv", "")
    add(1, "ok" if not _blank(rv) else "warn", "/etc/resolv.conf: %s" % (_clip(rv, 120) or "(空)"))

    # ================= 2 · 容器梳理 =================
    dpid = K.get("dockerd_pid", "")
    if _blank(dpid):
        add(2, "skip", "dockerd 未运行（未装 / 未启用）—— 容器与镜像清单跳过")
        if K.get("dockerd_init") == "yes":
            add(2, "warn", "但 /etc/init.d/dockerd 在位（enabled=%s）—— 装了却起不来，值得查"
                % K.get("dockerd_enabled"))
    else:
        add(2, "ok", "dockerd 运行中（pid %s）· enabled=%s · data_root=%s · daemon.json=%s"
            % (dpid, K.get("dockerd_enabled"), K.get("dockerd_data_root") or "默认",
               K.get("daemon_json")))
        if "docker_info" in E:
            add(2, "bad", "采集失败: docker info —— %s（dockerd 半死？可加 --skip-docker）" % E["docker_info"])
        else:
            add(2, "ok", "docker %s · 存储驱动 %s（backing %s）· root %s"
                % (K.get("docker_version") or "?", K.get("docker_storage_driver") or "?",
                   K.get("docker_backing_fs") or "?", K.get("docker_root_dir") or "?"))
            rm = K.get("registry_mirrors", "")
            add(2, "ok", "镜像加速: %s" % (_clip(rm, 120) if not _blank(rm) else "未配置"))
        for r in L.get("CONTAINER", []):
            p = (r.split("|") + ["", "", "", ""])[:4]
            nm, stat, img, nets = p
            nz = (nets or "").strip()
            if nz != "host":
                add(2, "bad", "容器 %s 网络=%s（非 host）—— 本机内核无 veth，bridge 网络必然起不来"
                    % (nm, nz or "(空)"))
            elif re.search(r"Exited|Dead|Created", stat, re.I):
                m = re.search(r"\((\d+)\)", stat)
                if m and m.group(1) == "137":
                    add(2, "warn", "容器 %s 已退出 %s —— exit 137（SIGKILL）疑似被 OOM 击杀" % (nm, stat))
                else:
                    add(2, "warn", "容器 %s 未在运行：%s" % (nm, stat))
            else:
                add(2, "ok", "容器 %s %s · %s · net=%s" % (nm, stat, img, nz))
        imgs = L.get("IMAGE", [])
        if imgs:
            shown = ", ".join(imgs[:10]) + (" …共 %d 个" % len(imgs) if len(imgs) > 10 else "")
            add(2, "ok", "镜像清单（%d 个）: %s" % (len(imgs), shown))
        else:
            add(2, "skip", "无本地镜像")

    ppid = K.get("panel_pid", "")
    if _blank(ppid):
        add(2, "skip", "1Panel 未运行（未装 / 已停）")
    else:
        port = _strict_int(K.get("panel_port_listen")) or 0
        db = K.get("panel_db_bytes", "")
        if db == "MISSING":
            add(2, "bad", "1Panel 运行中（pid %s）但面板库 1Panel.db 缺失" % ppid)
        else:
            add(2, "ok", "1Panel 运行中（pid %s）· 面板库 %s · 端口 10090 监听=%s"
                % (ppid, _hsz(_strict_int(db)), "是" if port else "否"))
        if not port:
            add(2, "warn", "10090 未监听 —— 面板可能只起了内层进程，或端口被改")

    # ================= 3 · 网络与信号 =================
    # ---- 出口判定：接口列表 + 默认路由 + 真 HTTP 三者综合 ----
    # 真机教训：不能只看 network.interface.wan。本机那个接口 up=false，但默认路由走 eth3、
    # HTTP 三次全 200、境外 204、5G 已驻网 —— 写死接口名会把「能上网」判成「上不了网」。
    netif = [(r.split("|") + ["", "", "", ""])[:4] for r in L.get("NETIF", [])]
    ups = [p for p in netif if p[1] == "true" and not _blank(p[3])]
    _dr = K.get("defroute4", "")
    _codes = [K.get("http_baidu_%d" % i) for i in (1, 2, 3)]
    _okn = sum(1 for n in (_strict_int(c) for c in _codes) if n == 200)

    if netif:
        det = " · ".join("%s=%s/%s" % (p[0], p[1] or "?", p[2] or "?") for p in netif)
        if ups:
            add(3, "ok", "已连接出口 %d 个：%s"
                % (len(ups), "、".join("%s(%s)" % (p[0], p[2] or "?") for p in ups)))
            add(3, "ok", "接口状态（up/proto）：%s" % _clip(det, 160))
        elif not _blank(_dr) and _okn == 3:
            add(3, "warn", "无接口报告 up=true，但默认路由与真 HTTP 都正常（接口状态上报可能滞后）")
            add(3, "ok", "接口状态（up/proto）：%s" % _clip(det, 160))
        else:
            add(3, "bad", "无接口报告 up=true，且默认路由/HTTP 也不正常 —— 设备当前上不了网")
            add(3, "ok", "接口状态（up/proto）：%s" % _clip(det, 160))
    elif "wan" in E:
        add(3, "bad", "采集失败: ubus network.interface.* status —— %s" % E["wan"])
    else:
        up = K.get("wan_up", "")
        if up == "true":
            add(3, "ok", "WAN 已拨号（proto=%s · IP=%s）" % (K.get("wan_proto") or "?", K.get("wan_ipv4") or "?"))
        elif _blank(_dr):
            add(3, "bad", "无接口状态、也无默认路由 —— 设备当前上不了网")
        else:
            add(3, "warn", "无接口状态可读（默认路由 %s）" % _clip(_dr, 60))
    if not _blank(K.get("lan_ipv4")):
        add(3, "ok", "LAN IP %s" % K["lan_ipv4"])
    dr = K.get("defroute4", "")
    if _blank(dr):
        add(3, "bad", "无 IPv4 默认路由 —— 出不了网")
    else:
        add(3, "ok", "默认路由 %s" % _clip(dr, 100))
    if not _blank(K.get("defroute6")):
        add(3, "ok", "IPv6 默认路由 %s" % _clip(K["defroute6"], 80))
    add(3, "ok", "策略路由规则 %s 条（ip -4 rule）" % (K.get("ip_rule_n") or "?"))

    if _blank(K.get("clash_pid")):
        add(3, "skip", "OpenClash 未运行（未装 / 已停）—— 代理端口与 DNS 判定按现状展示")
    else:
        add(3, "ok", "OpenClash 内核运行中（pid %s）· core 文件 %s"
            % (K["clash_pid"], K.get("openclash_core")))
    for r in L.get("PROXY_PORT", []):
        add(3, "ok", "代理端口监听 %s" % r.replace("|", " · "))
    # DNS 监听按端口聚合 —— 本机多网卡 × tcp/udp 会输出 20 条，逐条渲染纯噪音
    _byport = {}
    for r in L.get("DNS_LISTEN", []):
        p = (r.split("|") + ["", "", ""])[:3]
        proto, addr, proc = p
        port = addr.rsplit(":", 1)[-1] if ":" in addr else "?"
        d = _byport.setdefault(port, {"n": 0, "procs": set()})
        d["n"] += 1
        if proc and proc != "LISTEN":
            d["procs"].add(proc)
    if _byport:
        parts = ["%s ×%d 地址（%s）" % (port, _byport[port]["n"],
                                     "/".join(sorted(_byport[port]["procs"])) or "?")
                 for port in sorted(_byport, key=lambda x: -_byport[x]["n"])]
        add(3, "ok", "DNS 监听端口：%s（共 %d 条监听，按端口聚合）"
            % (" · ".join(parts), len(L.get("DNS_LISTEN", []))))
    if not _blank(K.get("iwinfo_summary")):
        add(3, "ok", "无线摘要 %s" % _clip(K["iwinfo_summary"], 150))

    codes = [K.get("http_baidu_%d" % i) for i in (1, 2, 3)]
    nums = [_strict_int(c) for c in codes]
    ok_n = sum(1 for n in nums if n == 200)
    shown = "/".join(c if not _blank(c) else "-" for c in codes)
    if ok_n == 3:
        add(3, "ok", "HTTP 连通 http://www.baidu.com 三次均 200（%s）" % shown)
    elif ok_n == 0:
        add(3, "bad", "HTTP 连通三次全非 200（%s）—— 出网或 DNS 有问题" % shown)
    else:
        add(3, "warn", "HTTP 连通不稳定：三次中 %d 次 200（%s）" % (ok_n, shown))
    gs = _strict_int(K.get("http_gstatic"))
    if gs == 204:
        add(3, "ok", "境外连通 gstatic generate_204 = 204")
    elif gs is None:
        add(3, "skip", "境外连通未采到（gstatic 无返回）")
    else:
        add(3, "warn", "境外连通 gstatic = %s（期望 204）—— 代理不通时属预期" % K.get("http_gstatic"))

    # ---- 5G / CPE：无数据 = SKIP（本机走有线 WAN 未拨号是正常态，不是故障）----
    ch = K.get("cpe_channel", "")
    if _blank(ch):
        add(3, "skip", "5G / CPE 无数据（本机走有线 WAN，未拨号属正常；本任务不发 AT）")
    else:
        add(3, "ok", "5G 通道 %s · 运营商 %s · 模式 %s · 频段 %s · PCI %s · EARFCN %s · Cell %s · TAC %s"
            % (ch, K.get("cpe_isp") or "?", K.get("cpe_mode") or "?", K.get("cpe_band") or "?",
               K.get("cpe_pci") or "?", K.get("cpe_earfcn") or "?", K.get("cpe_cell") or "?",
               K.get("cpe_tac") or "?"))
        rs = _first_int(K.get("cpe_rsrp"))
        if rs is None:
            add(3, "skip", "RSRP 未采到（cpestatus 未给该字段）")
        else:
            lvl, desc = _rsrp_level(rs)
            add(3, lvl, "RSRP %s dBm → %s" % (rs, desc))
        for label, key, unit in (("SINR", "cpe_sinr", "dB"), ("RSRQ", "cpe_rsrq", "dB")):
            if not _blank(K.get(key)):
                add(3, "ok", "%s %s %s" % (label, K[key], unit))
        add(3, "ok", "5G 模块 %s · 固件 %s · 模块温度 %s"
            % (K.get("cpe_model") or "?", K.get("cpe_revision") or "?",
               K.get("cpe_model_temp") or "?"))
        add(3, "ok", "身份（仅末 4 位）: IMSI %s · ICCID %s · IMEI %s"
            % (K.get("cpe_imsi_tail") or "(无)", K.get("cpe_iccid_tail") or "(无)",
               K.get("cpe_imei_tail") or "(无)"))

    parts = []
    for label, key in (("主板", "dev_temp"), ("Wi-Fi", "wifi_temp"),
                       ("CPU 占用", "cpu_percent"), ("内存占用", "mem_percent")):
        if not _blank(K.get(key)):
            parts.append("%s %s%s" % (label, K[key], "%" if "percent" in key else "°C"))
    if parts:
        add(3, "ok", "运行时读数（ubus infocd runtime）: %s" % " · ".join(parts))
    _smap = K.get("sim_name_map_n")
    add(3, "ok", "5G 串口 /dev/ttyUSB* %s 个 · 当前 SIM 选择 %s · SIM 名映射 %s"
        % (K.get("cpe_uart_n") or "?", K.get("cpe_sim_cur") or "?",
           "无（未装 /etc/nradio-sim-name.map）" if _blank(_smap) else "%s 条" % _smap))

    # ================= 4 · 服务与补丁状态 =================
    for r in L.get("SVC_CORE", []):
        p = (r.split("|") + ["", "", ""])[:3]
        svc, al, en = p
        if al != "yes":
            add(4, "bad", "出厂核心服务 %s 未运行（pidof 空）—— 这不该发生" % svc)
        elif en != "yes":
            add(4, "warn", "出厂核心服务 %s 运行中但未 enable（重启后不会自启）" % svc)
        else:
            add(4, "ok", "出厂核心服务 %s 运行中且已 enable" % svc)
    ses = L.get("SVC_ENABLED", [])
    if ses:
        add(4, "ok", "已 enable 的 init.d 服务 %d 个：%s%s"
            % (len(ses), ", ".join(ses[:14]), " …" if len(ses) > 14 else ""))

    for k in ("patch_lua", "patch_htm", "opkg"):
        if k in E:
            add(4, "bad", "采集失败: %s —— %s" % (k, E[k]))
    if "patch_lua" not in E:
        marks = [("nradio_appcenter_extra_action", "patch_extra_action"),
                 ("_kp_installed_registry", "patch_registry"),
                 ("nradio_appcenter_extra_installed_merge", "patch_extra_merge"),
                 ("_online_install_percent", "patch_install_percent")]
        miss = [lab for lab, key in marks if _strict_int(K.get(key)) == 0]
        seen = [lab for lab, key in marks if _strict_int(K.get(key)) is not None]
        _lp = K.get("patch_lua_path") or "?"
        _lb = K.get("patch_lua_bytes") or "?"
        if not seen:
            add(4, "skip", "商店补丁 marker 未采到（载体 %s）" % _lp)
        elif miss:
            add(4, "warn", "商店补丁 marker 缺失 %d 个：%s —— 载体 %s（%s 字节），"
                           "可能从未打过补丁或被固件升级覆盖"
                % (len(miss), ", ".join(miss), _lp, _lb))
        else:
            add(4, "ok", "商店补丁 4 个 marker 全在（载体 %s，%s 字节）" % (_lp, _lb))
    ao = _strict_int(K.get("patch_aurora_open_app"))
    if ao == 0:
        add(4, "warn", "appcenter.htm 的 aurora_open_app 缺失 —— 商店「打开应用」入口会失效")
    elif ao is not None:
        add(4, "ok", "appcenter.htm 的 aurora_open_app 在位（%s 字节）" % K.get("patch_htm_bytes"))

    if "opkg" not in E:
        sn = _strict_int(K.get("opkg_snapshot_n"))
        al = _strict_int(K.get("opkg_aliyun_n"))
        if sn is None or al is None:
            add(4, "skip", "opkg 源计数未采到")
        else:
            if sn != 0:
                add(4, "bad", "distfeeds 仍含 %d 行 21.02-SNAPSHOT（期望 0）—— opkg update 会失败" % sn)
            if al != 3:
                add(4, "bad", "distfeeds 的 aliyun 21.02.7 行 = %d（期望 3）" % al)
            if sn == 0 and al == 3:
                add(4, "ok", "opkg 源已修好：0 行 snapshot · 3 行 aliyun 21.02.7（共 %s 行）"
                    % K.get("opkg_lines"))

    add(4, "ok", "crontab %s 行（ocspeed-auto %s · ocspeed-failover %s）"
        % (K.get("cron_lines") or "?", K.get("cron_ocspeed") or "?", K.get("cron_ocspeed_failover") or "?"))
    ri, s9 = K.get("rc_local_initd"), K.get("s95done")
    if ri == "no" and s9 == "yes":
        add(4, "ok", "开机自启链：/etc/init.d/rc.local 不在（本机固件如此），执行者是 /etc/rc.d/S95done")
    elif ri == "yes":
        add(4, "ok", "开机自启链：/etc/init.d/rc.local 在位 · S95done=%s" % s9)
    else:
        add(4, "warn", "开机自启链异常：/etc/init.d/rc.local=%s · S95done=%s —— 重启后自定义启动项可能不跑"
            % (ri, s9))
    if not _blank(K.get("rc_local_tail")):
        add(4, "ok", "rc.local 末尾 %s" % _clip(K["rc_local_tail"], 150))

    sp = _strict_int(K.get("store_pkg_n"))
    if K.get("store_uci") == "yes":
        add(4, "ok", "应用商店索引 /etc/config/appcenter 在位 · config package %s 条"
            % (sp if sp is not None else "?"))
    else:
        add(4, "bad", "/etc/config/appcenter 缺失 —— 商店无法做可装性判定")
    kf = K.get("kp_store_files", "")
    if _blank(kf):
        add(4, "warn", "/etc/kp_store 不存在 —— 商店路由表缺失")
    else:
        # 只有这两个是「另一台机器（A 机）的遗留」；patch-baseline.json 反而是**本机**的补丁基线快照，
        # 早先一律标成「遗留」是错的（真机实测纠正）。
        _legacy = {"installed.list", "plugins.json"}
        files = [x for x in kf.split(",") if x]
        got_legacy = [x for x in files if x in _legacy]
        line = "/etc/kp_store: %s" % ", ".join(files)
        if got_legacy:
            line += "（其中 %s 属另一台机器的遗留，不是本机缺陷）" % ", ".join(got_legacy)
        add(4, "ok", line)
    if K.get("maye_state_dir") == "yes":
        add(4, "ok", "maye 助手状态目录 /root/.nradio-plugin-menu 在位")

    # ================= 5 · 装载余量探测（可装性对照） =================
    ova = _strict_int(K.get("overlay_avail_kb"))
    dva = _strict_int(K.get("data_avail_kb"))
    tva = _strict_int(K.get("tmp_avail_kb"))
    ovd = K.get("overlay_dev", "")
    usable = (ovd == "/dev/mmcblk0p1")

    if usable:
        add(5, "ok", "商店判据基准：overlay 可用 %s（载体 %s）" % (_hkb(ova), ovd))
    else:
        add(5, "bad", "overlay 载体 %s ≠ /dev/mmcblk0p1 —— 商店装不下任何东西，可装性判定作废"
            % (ovd or "(空)"))
    add(5, "ok", "数据区可用 %s（/mnt/storage/data）· /tmp 可用 %s" % (_hkb(dva), _hkb(tva)))
    if dva is not None and dva * 1024 < DISK_JELLYFIN:
        add(5, "warn", "数据区 %s < 2 GiB —— 不够 Jellyfin 级容器（硬门槛 ≥2GiB）" % _hkb(dva))
    if "store_apps" in E:
        add(5, "bad", "采集失败: %s" % E["store_apps"])

    raw = L.get("STORE_APP", [])
    for r in raw:
        p = r.split("|")
        name = p[0] if p else "?"
        size = _strict_int(p[1]) if len(p) > 1 else None
        ins = p[3] if len(p) > 3 else "no"
        if not name:
            continue
        if ins == "yes":
            apps.append((name, size, True, "ok", "（已装）"))
            continue
        if not usable:
            apps.append((name, size, False, "bad", "overlay 不可用，装不下"))
            continue
        if size is None or size < 1024 or not ova:
            apps.append((name, size, False, "skip", "体积未知或可疑，无法对照"))
            continue
        ratio = ova * 1024.0 / size
        if ratio >= STORE_HEAD:
            apps.append((name, size, False, "ok", "装得下（余量 %.1fx）" % ratio))
        elif ratio >= 1.0:
            apps.append((name, size, False, "warn", "余量偏紧（%.2fx < %.1fx）" % (ratio, STORE_HEAD)))
        else:
            apps.append((name, size, False, "bad", "装不下（overlay 剩余 %s < %s）" % (_hkb(ova), _hsz(size))))
    if not raw and "store_apps" not in E:
        add(5, "skip", "商店无 config package 条目 —— 无应用可对照")

    if ma is not None:
        if ma >= MEM_HEAVY:
            add(5, "ok", "可用内存 %s —— 重载档：够 Docker + 1Panel" % _hkb(ma))
        elif ma >= MEM_MEDIUM:
            add(5, "ok", "可用内存 %s —— 中等档：够 OpenClash / maye 总入口；不够再起大容器" % _hkb(ma))
        elif ma >= MEM_LIGHT:
            add(5, "warn", "可用内存 %s —— 轻量档：只够 ocspeed 级插件" % _hkb(ma))
        else:
            add(5, "bad", "可用内存 %s —— 低于熔断线，装插件前先释放内存" % _hkb(ma))

    return rows, apps


# ----------------------------------------------------------------- 渲染

def _title(d):
    mn = d["K"].get("model_norm", "")
    if mn == "NRadio_C2000Ultra":
        return "鲲鹏 C2000 U"
    if mn == "NRadio_C2000MAX":
        return "鲲鹏 C2000 Max"
    return mn or "鲲鹏路由器"


def evaluate(raw):
    """采集流 → (code, reason, d, rows, apps)。

    reason ∈ ok / no_sentinel / no_handshake / precheck / bad。不含任何 IO，
    这样「缺哨兵必须判环境错误」这类分支能被离线夹具单测覆盖（见 tasks §8③）。
    """
    d = parse_stream(raw)
    # 哨兵优先级最高：缺它就无从判断后面收到的记录是否完整
    if not d["Z"]:
        return 2, "no_sentinel", d, None, None
    if d["V"] is None:
        return 2, "no_handshake", d, None, None
    if d["E"].get("precheck"):
        return 2, "precheck", d, None, None
    rows, apps = verdicts(d)
    bad = any(l == "bad" for _, l, _ in rows) or any(a[3] == "bad" for a in apps)
    return (1 if bad else 0), ("bad" if bad else "ok"), d, rows, apps


def render(d, rows, apps, host, elapsed):
    """唯一输出形态：终端人类可读。不落盘、不产 JSON。"""
    W = 72
    out = ["=" * W,
           "  %s · 设备状态与环境自检     %s   %s" % (_title(d), host, elapsed),
           "=" * W]

    if d["V"] and d["V"][1] != EXPECT_VERSION:
        out.append("  [WARN] 设备侧采集器版本 %s ≠ 期望 %s —— 建议重新推送" % (d["V"][1], EXPECT_VERSION))

    secs = {}
    for no, nm in d["sections"]:
        secs[int(no)] = nm
    for no in sorted(secs):
        out.append("")
        out.append("  %d · %s" % (no, secs[no]))
        out.append("-" * W)
        mine = [(lvl, txt) for (s, lvl, txt) in rows if s == no]
        for lvl, txt in mine:
            out.append("  %s %s" % (MARK[lvl], txt))
        if no == 5 and apps:
            out.append("    应用商店可装性（共 %d 条 · option size ↔ overlay 剩余）：" % len(apps))
            for name, size, ins, lvl, note in apps:
                out.append("      %s %10s   %s %s"
                           % (_pad(_clip(name, 26), 26), _hsz(size), MARK[lvl], note))
            out.append("      （体积取自 /etc/config/appcenter 的 option size；语言包等附属包也在列，"
                       "倍数仅供横向参考）")
        if not mine and not (no == 5 and apps):
            out.append("  (空)")

    cnt = {"ok": 0, "warn": 0, "bad": 0, "skip": 0}
    for _, lvl, _t in rows:
        cnt[lvl] += 1
    for _n, _s, _i, lvl, _no in apps:
        cnt[lvl] += 1

    out.append("")
    out.append("-" * W)
    if cnt["bad"]:
        tail = "需要处理（%d 项必须处理）" % cnt["bad"]
    elif cnt["warn"]:
        tail = "可用（有 %d 项建议）" % cnt["warn"]
    else:
        tail = "可用（无建议）"
    out.append("  汇总：OK %d · WARN %d · FAIL %d · SKIP %d   →  设备状态：%s"
               % (cnt["ok"], cnt["warn"], cnt["bad"], cnt["skip"], tail))

    if d["N"]:
        out.append("")
        out.append("  备注")
        out.append("-" * W)
        for n in d["N"]:
            out.append("  · %s" % _clip(n, 190))

    out.append("")
    out.append("  本任务纯只读：设备侧零写盘、不启停服务、不发 AT；PC 侧不落盘报告。")
    out.append("  发现问题只给建议，不自动修复；需真修的请走 tasks/03、tasks/06~10。")
    return "\n".join(out), cnt


# ----------------------------------------------------------------- 执行

def push_and_run(host, user, pw, timeout, skip_docker):
    """推送 → 语法门禁 → 采集。返回 (raw_stdout, err_dict)。"""
    sys.path.insert(0, os.path.join(SKILL, "scripts"))
    from rtr_lib import Rtr  # noqa: E402

    r = Rtr(host=host, user=user, pw=pw)
    r.run("mkdir -p %s" % REMOTE_DIR, t=30)

    text = io.open(PAYLOAD, "r", encoding="utf-8").read()
    ok, md5 = r.put_text_verified(REMOTE_SH, text)
    if not ok:
        return None, {"error": "推送失败：远端 md5 与本地不一致（got %s）" % md5}
    r.p("  已推送 %s（md5 %s，%d 字节）" % (REMOTE_SH, md5, len(text.encode("utf-8"))))

    # 第二道语法门禁：设备侧 sh -n 拿不到 SYNTAX_OK 就绝不下发执行
    if "SYNTAX_OK" not in r.run("sh -n %s && echo SYNTAX_OK" % REMOTE_SH, t=60):
        return None, {"error": "设备侧语法门禁未通过（sh -n 未输出 SYNTAX_OK）"}

    prefix = "KP_SKIP_DOCKER=1 " if skip_docker else ""
    # ⚠️ Rtr.run() 丢 stderr、不检查退出码、不打印 → 判定只能靠哨兵与记录本身
    return r.run("%ssh %s" % (prefix, REMOTE_SH), t=timeout), {}


def main():
    for s in (sys.stdout, sys.stderr):
        try:
            s.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    ap = argparse.ArgumentParser(
        description="设备状态与环境自检（助手菜单 11 · 纯只读）")
    ap.add_argument("--host")
    ap.add_argument("--user")
    ap.add_argument("--pw", help="SSH 密码；也可用 ROUTER_PW 环境变量或 --cred-file")
    ap.add_argument("--cred-file", default=DEFAULT_CRED_FILE,
                    help="KEY=VALUE 凭据文件（默认 ~/.workbuddy/kunpeng-router.env）")
    ap.add_argument("--timeout", type=int, default=300, help="设备侧采集总超时秒数（默认 300）")
    ap.add_argument("--skip-docker", action="store_true",
                    help="跳过第 2 板块（dockerd 半死时 docker CLI 会挂住）")
    args = ap.parse_args()

    creds = load_creds(args.cred_file)
    host = args.host or creds.get("ROUTER_HOST") or "192.168.66.1"
    user = args.user or creds.get("ROUTER_USER") or "root"
    # ⚠️ 不给默认密码：不要把真密码写进已公开发布的脚本。
    #    （kp-clean.py:153 的「密码缺失即回退到某个常量」是既有隐患，勿复制到本脚本。）
    pw = args.pw or creds.get("ROUTER_PW")
    if not pw:
        print("[FAIL] 缺少密码：请设置 ROUTER_PW 环境变量，或用 --pw / --cred-file 传入。")
        print("       设备档案见 AGENTS.md §1（本脚本不保存任何凭据，也不提供默认密码）。")
        return 2

    if not os.path.isfile(PAYLOAD):
        print("[FAIL] 找不到设备侧采集器：%s" % PAYLOAD)
        return 2

    print("连接 %s@%s ..." % (user, host))
    t0 = time.time()
    try:
        raw, err = push_and_run(host, user, pw, args.timeout, args.skip_docker)
    except Exception as ex:
        print("[FAIL] 连接或执行失败：%s: %s" % (type(ex).__name__, ex))
        print("       连不上请见 references/no-ssh-recovery.md")
        return 2
    if err:
        print("[FAIL] %s" % err["error"])
        return 2
    if not raw:
        print("[FAIL] 设备侧无任何输出 —— 命令未执行或 SSH 被 reset")
        return 2

    elapsed = "用时 %.1f s" % (time.time() - t0)
    code, reason, d, rows, apps = evaluate(raw)
    if reason == "no_sentinel":
        print("[FAIL] 采集输出缺 Z<TAB>END 哨兵 —— 输出被 dropbear 截断，结论不可信")
        print("       已收到 %d 行；末行：%s" % (d["lines"], _clip(d["last"], 120)))
        print("       建议：重跑一次；若仍截断，用 --skip-docker 缩小输出量。")
        return 2
    if reason == "no_handshake":
        print("[FAIL] 无版本握手（V 记录）—— 执行的可能不是本脚本")
        return 2
    if reason == "precheck":
        print("[FAIL] 设备侧前置检查未通过：%s" % d["E"]["precheck"])
        return 2

    text, _cnt = render(d, rows, apps, host, elapsed)
    print("")
    print(text)

    return code


if __name__ == "__main__":
    sys.exit(main())
