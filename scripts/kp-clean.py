# -*- coding: utf-8 -*-
"""kp-clean.py —— 写盘足迹「双向对账」PC 侧驱动（期 1-B / 1-C）

做什么：
  1. 从 tasks/footprint.json 生成审计用例（每个功能声称写过的对象）；
  2. 把 payload/kp-clean.sh + 用例表推到设备 /tmp/kpc/；
  3. 跑 `--audit`（足迹 → 设备：声称写过的，本机到底有没有）
     和 `--list`（设备 → 足迹：本机有的，有没有功能认领）；
  4. 对账，把 UNKNOWN 清到 0，产出报告。

凭据：一律从环境变量读（ROUTER_HOST / ROUTER_USER / ROUTER_PW），不落盘。
用法：
    python kp-clean.py --audit              # 完整双向对账
    python kp-clean.py --audit --no-push    # 复用设备上已有的脚本，只重跑
    python kp-clean.py --push-only          # 只推脚本
"""
import argparse
import json
import os
import re
import sys
import time

WS = r"%USERPROFILE%\WorkBuddy\2026-09-19-12-19-57"
SKILL = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills", "kunpeng-router-tuning")
FOOTPRINT = os.path.join(SKILL, "tasks", "footprint.json")
PAYLOAD = os.path.join(SKILL, "scripts", "payload", "kp-clean.sh")
REPORT = os.path.join(WS, "_audit_report.md")
RECON = os.path.join(WS, "_audit_recon.json")
CASES_LOCAL = os.path.join(WS, "_audit_cases.tsv")

REMOTE_DIR = "/tmp/kpc"
REMOTE_SH = REMOTE_DIR + "/kp-clean.sh"
REMOTE_CASES = REMOTE_DIR + "/cases.tsv"

UCI_KEY_RE = re.compile(r"uci\s+(?:-q\s+)?set\s+([A-Za-z0-9_@\[\].\"$*-]+)")
PKG_RE = re.compile(r"opkg\s+(?:install|remove|download)\s+([^\s;|&)]+)")
SVC_RE = re.compile(r"/etc/init\.d/([A-Za-z0-9._-]+)")
RCD_RE = re.compile(r"/etc/rc\.d/([SK][0-9]*[A-Za-z0-9._-]*)")
NOISE_RE = re.compile(r"^(?:/dev/|/proc/|/sys/|/tmp|/var/run|/var/lock|/var/log|/run/|/)$|"
                      r"^[\s,]*$|CDATA|^\$|^//")

# 与足迹抽取器一致的禁区（绝不下发设备去查，环保且无意义）
FORBIDDEN_PREFIX = ("/bin/", "/sbin/", "/lib/", "/proc/", "/sys/", "/dev/")


def build_cases(fp):
    """从 footprint.json 生成 {kind: {value: set(features)}}"""
    cases = {}
    cls2kind = {"initd": "service", "rcd": "rcdir", "uci": "uci", "marker": "marker",
                "cron": "cron", "net": "net", "store": "store"}

    def add(kind, value, feat, tag):
        value = value.strip()
        if not value or len(value) > 120:
            return
        if "$" in value or NOISE_RE.match(value):
            return
        if value.startswith(FORBIDDEN_PREFIX):
            return
        d = cases.setdefault(kind + "\t" + value, {"kind": kind, "value": value,
                                                   "features": set(), "tags": set(),
                                                   "feats_unique": set(),
                                                   "feats_shared": set()})
        d["features"].add(feat)
        d["tags"].add(tag)
        (d["feats_unique"] if tag == "unique" else d["feats_shared"]).add(feat)

    for f in fp["features"]:
        feat = str(f["feature"])
        for bucket, tag in (("writes_unique", "unique"), ("writes_shared", "shared")):
            w = f.get(bucket) or {}
            for cls, kind in cls2kind.items():
                for seg in w.get(cls) or []:
                    if cls == "initd":
                        for m in SVC_RE.finditer(seg):
                            add("service", m.group(1), feat, tag)
                    elif cls == "rcd":
                        for m in RCD_RE.finditer(seg):
                            v = m.group(1)
                            if not re.search(r"[SK][0-9]*$", v) and len(v) > 3:
                                add("rcdir", v, feat, tag)
                    elif cls == "uci":
                        m = UCI_KEY_RE.search(seg)
                        if m and "$" not in m.group(1):
                            v = m.group(1).strip('"')
                            if v.count(".") >= 1 and not v.endswith("."):
                                add("uci", v, feat, tag)
                    elif cls in ("marker", "store"):
                        add(kind, seg.split()[0], feat, tag)
                    elif cls == "cron":
                        for tok in re.split(r"[;\s]+", seg):
                            if tok and tok not in ("/etc/crontabs/root", "crontab") and len(tok) > 5:
                                add("cron", tok, feat, tag)
                    elif cls == "net":
                        if "ip rule" in seg or "ip -4 rule" in seg:
                            add("net", "rule", feat, tag)
                        elif "mtkhnat" in seg or "flow_offloading" in seg:
                            add("net", "offload", feat, tag)
                        elif seg.strip() in ("iptables", "nft"):
                            continue
                        else:
                            add("net", seg.split()[0][:40], feat, tag)
            # 路径类
            for cls in ("dirs", "targets", "vars"):
                for seg in w.get(cls) or []:
                    for one in re.split(r"[;\s]+", seg.strip().strip("\"'")):
                        if one.startswith("/") and one.count("/") >= 2:
                            add("path", one, feat, tag)
            # opkg → 包名
            for seg in w.get("opkg") or []:
                for m in PKG_RE.finditer(seg):
                    tok = m.group(1).strip("\"'")
                    if not tok.startswith("$"):
                        add("pkg", tok, feat, tag)
    return cases


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true")
    ap.add_argument("--push-only", action="store_true")
    ap.add_argument("--no-push", action="store_true")
    ap.add_argument("--max-cases", type=int, default=0)
    args = ap.parse_args()

    fp = json.loads(open(FOOTPRINT, "rb").read().decode("utf-8"))
    cases = build_cases(fp)
    items = sorted(cases.values(), key=lambda d: (d["kind"], d["value"]))
    if args.max_cases:
        items = items[:args.max_cases]

    lines = ["# KIND\tVALUE\tFEATURES\tTAG"]
    for d in items:
        lines.append("%s\t%s\t%s\t%s" % (d["kind"], d["value"],
                                         ",".join(sorted(d["features"], key=int)),
                                         ",".join(sorted(d["tags"]))))
    blob = "\n".join(lines) + "\n"
    open(CASES_LOCAL, "wb").write(blob.encode("utf-8"))

    by_kind = {}
    for d in items:
        by_kind[d["kind"]] = by_kind.get(d["kind"], 0) + 1

    print("用例 %d 条 / %.1f KB：%s" % (len(items), len(blob) / 1024.0, by_kind))

    if args.push_only or args.audit:
        import paramiko  # noqa
        sys.path.insert(0, os.path.join(SKILL, "scripts"))
        from rtr_lib import Rtr  # noqa
        host = os.environ.get("ROUTER_HOST") or "192.168.66.1"
        user = os.environ.get("ROUTER_USER") or "root"
        pw = os.environ.get("ROUTER_PW") or "admin"
        r = Rtr(host=host, user=user, pw=pw)
        print("连接 %s@%s OK" % (user, host))
        r.run("mkdir -p %s" % REMOTE_DIR)
        sh_text = open(PAYLOAD, "rb").read().decode("utf-8")
        ok, md5 = r.put_text_verified(REMOTE_SH, sh_text)
        print("推 kp-clean.sh: %s (md5 %s)" % ("OK" if ok else "FAIL", md5))
        ok2, md52 = r.put_text_verified(REMOTE_CASES, blob)
        print("推 cases.tsv: %s (md5 %s)" % ("OK" if ok2 else "FAIL", md52))

    if not args.audit:
        return 0

    t0 = time.time()
    shrc = r.run("sh -n %s && echo SYNTAX_OK" % REMOTE_SH)
    print("设备侧语法: %s" % shrc)

    raw_audit = r.run("sh %s --audit %s" % (REMOTE_SH, REMOTE_CASES), t=600)
    print("--audit 用时 %.1fs，输出 %d 行" % (time.time() - t0, len(raw_audit.splitlines())))

    t1 = time.time()
    raw_list = r.run("sh %s --list" % REMOTE_SH, t=600)
    print("--list 用时 %.1fs，输出 %d 行" % (time.time() - t1, len(raw_list.splitlines())))

    open(os.path.join(WS, "_audit_raw_audit.txt"), "wb").write(raw_audit.encode("utf-8"))
    open(os.path.join(WS, "_audit_raw_list.txt"), "wb").write(raw_list.encode("utf-8"))

    results = {}
    rommap = {}
    for ln in raw_audit.splitlines():
        p = ln.split("\t")
        if len(p) >= 4 and p[0] == "R":
            extra = p[4] if len(p) > 4 else ""
            results[(p[1], p[2])] = {"state": p[3], "extra": extra}
            m = re.search(r"rom=(yes|no)", extra)
            if m:
                rommap[(p[1], p[2])] = m.group(1)

    # --list：kind -> [(值, rom)]
    listed = {}
    for ln in raw_list.splitlines():
        p = ln.split("\t")
        if len(p) < 3 or p[0] != "L":
            continue
        kind, v = p[1], p[2]
        extra = p[3] if len(p) > 3 else ""
        m = re.search(r"rom=(yes|no)", extra)
        listed.setdefault(kind, []).append((v, m.group(1) if m else "?"))

    # ---------- 对象级冲突判定
    # 逐功能标「独有」不等于全局独有：同一个 /etc/openclash 对功能 2 是「独有（该清）」、
    # 对功能 19 是「共用（该留）」—— 这种对象就是**必须先人工裁定**的，不能自动删。
    # 首跑就踩到过：/etc/rc.local、/etc/opkg/distfeeds.conf 这些系统关键文件
    # 一度混进「独有 = 该清」的桶里。
    for d in items:
        d["n_features"] = len(d["features"])
        d["conflict"] = bool(d["feats_unique"] and d["feats_shared"])

    # ---------- 正向：足迹 → 设备
    buckets = {"present_clean": [], "present_keep": [], "present_conflict": [],
               "present_firmware": [], "absent": [], "unknown": [], "missing_result": []}
    for d in items:
        key = (d["kind"], d["value"])
        res = results.get(key)
        if res is None:
            buckets["missing_result"].append(d)
            continue
        st = res["state"]
        if st == "unknown":
            buckets["unknown"].append((d, res))
        elif st == "absent":
            buckets["absent"].append((d, res))
        elif rommap.get(key) == "yes":
            # 出厂就有 → 插件**不可能**是它的创建者，最多是改过它。
            # 所以既不能「删」（删了就破坏固件功能），也不能当残留 ——只能「重置」。
            buckets["present_firmware"].append((d, res))
        elif d["conflict"]:
            buckets["present_conflict"].append((d, res))
        elif d["feats_unique"]:
            buckets["present_clean"].append((d, res))
        else:
            buckets["present_keep"].append((d, res))

    # ---------- 反向：设备 → 足迹（只看「出厂没有」的，否则全是固件预装噪声）
    claimed_all = {}
    for d in items:
        claimed_all.setdefault(d["kind"], set()).add(d["value"])
    claimed_paths = claimed_all.get("path", set())
    claimed_svc = claimed_all.get("service", set())
    claimed_rcd = claimed_all.get("rcdir", set())
    claimed_uci = claimed_all.get("uci", set())
    claimed_misc = set()
    for k in ("pkg", "cron", "net", "marker"):
        claimed_misc |= claimed_all.get(k, set())

    unclaimed, unclaimed_fw = [], []
    for kind, vals in listed.items():
        if kind in ("header", "info", "footer", "scan_dir"):
            continue
        for v, rom in vals:
            if kind == "scan_entry":
                # 父目录已被认领 → 其子项天然被覆盖，不再单列
                parent = v.rsplit("/", 1)[0]
                if parent in claimed_paths or any(v.startswith(c + "/") for c in claimed_paths):
                    continue
                claimed = v in claimed_paths
            elif kind == "service":
                claimed = v in claimed_svc
            elif kind == "rcdir":
                claimed = any(v.endswith(c) or c in v for c in claimed_rcd) if claimed_rcd else False
            elif kind == "uci_config":
                claimed = any(c.startswith(v + ".") for c in claimed_uci)
            elif kind == "pkg":
                claimed = v in claimed_misc
            elif kind in ("cron", "netrule", "marker"):
                claimed = any(v in c or c in v for c in claimed_misc)
            else:
                claimed = False
            if claimed:
                continue
            (unclaimed if rom == "no" else unclaimed_fw).append((kind, v, rom))

    recon = {
        "generated": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "cases": len(items),
        "by_kind": by_kind,
        "audit_lines": len(raw_audit.splitlines()),
        "list_lines": len(raw_list.splitlines()),
        "present_clean": len(buckets["present_clean"]),
        "present_keep": len(buckets["present_keep"]),
        "present_conflict": len(buckets["present_conflict"]),
        "present_firmware_reset_only": len(buckets["present_firmware"]),
        "absent": len(buckets["absent"]),
        "unknown": len(buckets["unknown"]),
        "missing_result": len(buckets["missing_result"]),
        "unclaimed_post_factory": len(unclaimed),
        "unclaimed_firmware": len(unclaimed_fw),
    }
    open(RECON, "wb").write(json.dumps(recon, ensure_ascii=False, indent=1).encode("utf-8"))

    md = []
    md.append("# 写盘足迹双向对账报告")
    md.append("")
    md.append("设备 %s@%s ｜ %s" % (user, host, time.strftime("%Y-%m-%d %H:%M:%S")))
    md.append("")
    md.append("| 指标 | 值 |")
    md.append("|---|---|")
    for k, v in recon.items():
        md.append("| %s | %s |" % (k, v))
    md.append("")
    md.append("## 正向：足迹声称写过 → 本机实际有")
    md.append("")
    md.append("### ① 该清（固件没有 + 仅被独有认领）%d 条" % len(buckets["present_clean"]))
    md.append("")
    md.append("判定：本机存在、**固件里没有**（rom=no）、且只出现在某些功能的「独有」桶里")
    md.append("→ 对应功能卸载时应当清除。")
    md.append("")
    md.append("| 类 | 对象 | 状态 | 应清除的功能 |")
    md.append("|---|---|---|---|")
    for d, res in sorted(buckets["present_clean"], key=lambda x: x[0]["value"]):
        md.append("| %s | `%s` | %s | %s |"
                  % (d["kind"], d["value"], res["extra"][:30],
                     ",".join(sorted(d["feats_unique"], key=int))))
    md.append("")
    md.append("### ④ 只能重置、**不能删**（固件自带 rom=yes）%d 条" % len(buckets["present_firmware"]))
    md.append("")
    md.append("关键判据：出厂就有 → 插件**不可能是它的创建者**，最多是改过它。")
    md.append("删了就破坏固件功能（`/etc/rc.local`、`/etc/resolv.conf`、`uhttpd`…），")
    md.append("所以只能「改回原值 / 停掉插件加的那一段」，绝不能 `rm`。")
    md.append("")
    md.append("| 类 | 对象 | 状态 | 被认领为独有（提示：这里应是「重置」而非「删除」） |")
    md.append("|---|---|---|---|")
    for d, res in sorted(buckets["present_firmware"], key=lambda x: x[0]["value"]):
        md.append("| %s | `%s` | %s | %s |"
                  % (d["kind"], d["value"], res["extra"][:30],
                     ",".join(sorted(d["feats_unique"], key=int)) or "—"))
    md.append("")
    md.append("### ② 保留（仅被共用认领）%d 条" % len(buckets["present_keep"]))
    md.append("")
    md.append("判定：本机存在，只出现在「共用」桶里（公共设施 / 系统关键文件）→ **绝不随单插件删**。")
    md.append("")
    md.append("| 类 | 对象 | 状态 | 共用它的功能数 |")
    md.append("|---|---|---|---|")
    for d, res in sorted(buckets["present_keep"], key=lambda x: -x[0]["n_features"]):
        md.append("| %s | `%s` | %s | %d |"
                  % (d["kind"], d["value"], res["extra"][:30], len(d["feats_shared"])))
    md.append("")
    md.append("### ③ ★冲突：既被独有认领又被共用认领 %d 条 —— **必须人工裁定**"
              % len(buckets["present_conflict"]))
    md.append("")
    md.append("同一个对象，有的功能说「这是我装的、该清」，有的功能说「这是公用的、该留」。")
    md.append("自动删会误伤，自动留会残留 —— 只能按「卸载谁」来决定，故单列为人工裁定项。")
    md.append("")
    md.append("| 类 | 对象 | 状态 | 独有认领（该清） | 共用认领（该留） |")
    md.append("|---|---|---|---|---|")
    for d, res in sorted(buckets["present_conflict"],
                         key=lambda x: (-len(x[0]["feats_unique"]), x[0]["value"])):
        md.append("| %s | `%s` | %s | %s | 共%d个 |"
                  % (d["kind"], d["value"], res["extra"][:30],
                     ",".join(sorted(d["feats_unique"], key=int)), len(d["feats_shared"])))
    md.append("")
    md.append("### unknown %d 条 / 无结果 %d 条"
              % (len(buckets["unknown"]), len(buckets["missing_result"])))
    md.append("")
    for d, res in buckets["unknown"][:60]:
        md.append("- `%s` %s -> %s" % (d["kind"], d["value"], res["extra"]))
    for d in buckets["missing_result"][:60]:
        md.append("- (设备没回结果) `%s` %s" % (d["kind"], d["value"]))
    md.append("")
    md.append("## 反向：本机有、但没有任何功能认领")
    md.append("")
    md.append("关键：OpenWrt 的 `/rom` 是只读出厂根，`/rom<path>` 存在即「出厂就有」。")
    md.append("用它当**不需要重刷机就能拿到的原始基线**，把固件预装从「未认领」里剔出去 ——")
    md.append("否则本机 500+ 个固件对象全会涌进来，反向对账毫无信号（首跑就是这么废掉的）。")
    md.append("")
    md.append("### 出厂后新增且未认领（**真信号**，需逐条定性）%d 条" % len(unclaimed))
    md.append("")
    for k, v, _rom in unclaimed[:200]:
        md.append("- `%s` %s" % (k, v))
    md.append("")
    md.append("### 固件自带（rom=yes，与本项目无关，已剔除）%d 条" % len(unclaimed_fw))
    md.append("")
    kinds = {}
    for k, _v, _r in unclaimed_fw:
        kinds[k] = kinds.get(k, 0) + 1
    md.append("按类：%s" % kinds)

    open(REPORT, "wb").write("\n".join(md).encode("utf-8"))
    print(json.dumps(recon, ensure_ascii=False, indent=1))
    print("报告 -> %s" % REPORT)
    return 0


if __name__ == "__main__":
    sys.exit(main())
