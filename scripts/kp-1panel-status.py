#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""kp-1panel-status.py —— 只读盘点 1Panel 上的容器/应用/端口/资源（不写任何东西）。

用途：回答"现在设备上到底有哪些 1Panel 容器在跑？面板记账和实际对不对得上？"
适用：鲲鹏 C2000 U 等 OpenWrt + 1Panel v1.10 设备。

凭据：环境变量 ROUTER_HOST / ROUTER_USER / ROUTER_PW，或凭据文件（KEY=VALUE）。
      默认凭据文件 %USERPROFILE%\\.workbuddy\\kunpeng-router.env
      凭据绝不落盘、绝不进输出。

用法：
    python kp-1panel-status.py                  # 人类可读
    python kp-1panel-status.py --json out.json  # 额外落一份 JSON
    python kp-1panel-status.py --host 192.168.66.1 --pw xxx

覆盖的判据（每条都能回答一个真实排障问题）：
  1 容器清单 + 运行态 + 退出码 + OOMKilled + NetworkMode + restart 策略
    → "面板说运行中，为什么打不开？"（看里层 state / exit / oom）
  2 面板库 app_installs.status 对照
    → "面板记账和我看到的对不上吗？"（Running 但容器已退出 = 典型 OOM/被杀）
  3 应用实例目录 + compose 是否已 host 化
    → "还有没有漏转换的 compose？"
  4 宿主端口监听 → "host 模式下应用真的在听吗？"
  5 host 默认化装置是否在位（wrapper / .real / 转换器）
    → "重建 overlay 之后装置还在不在？"
  6 dmesg OOM 事件 + memcg 归属
    → "容器是被谁杀死的？"（关键：memcg 目录名 = 容器 ID 前缀）

⚠️ 全部只读。绝不 stop/start/rm 任何东西。
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys

DEFAULT_CRED_FILE = r"%USERPROFILE%\.workbuddy\kunpeng-router.env"


# ---------------------------------------------------------------- 凭据

def load_creds(path):
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


# ---------------------------------------------------------------- SSH

class Dev:
    def __init__(self, host, user, pw, timeout=20):
        import paramiko
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(host, 22, user, pw, timeout=timeout)

    def sh(self, cmd, t=60):
        try:
            _i, o, e = self.c.exec_command(cmd, timeout=t)
            return (o.read().decode("utf-8", "replace").strip(),
                    e.read().decode("utf-8", "replace").strip())
        except Exception as ex:
            return "", "%s: %s" % (type(ex).__name__, ex)

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass


# 注意：设备是 busybox ash + dropbear，没有 jq / timeout / sqlite3 CLI，
#       但**有 python3** —— 所以面板库直接用 python3 sqlite3 只读打开。
CMDS = {
    "containers":
        "docker ps -a --format '{{.Names}}\t{{.Image}}\t{{.Status}}' 2>&1",
    "inspect":
        "for n in $(docker ps -aq); do "
        "docker inspect -f '{{.Name}}|{{.Id}}|{{.State.Status}}|{{.State.ExitCode}}|"
        "{{.State.OOMKilled}}|{{.HostConfig.NetworkMode}}|{{.HostConfig.RestartPolicy.Name}}|"
        "{{.RestartCount}}|{{.State.StartedAt}}|{{.State.FinishedAt}}' $n; "
        "done 2>&1",
    "appdirs":
        "ls -1 /mnt/storage/data/1panel/apps/ 2>&1; echo '@@INST'; "
        "for d in /mnt/storage/data/1panel/apps/*/*/; do "
        "[ -f \"$d/docker-compose.yml\" ] && { "
        "nm=$(grep -c 'network_mode: host' \"$d/docker-compose.yml\" 2>/dev/null); "
        "ports=$(grep -c '^[ ]*ports:' \"$d/docker-compose.yml\" 2>/dev/null); "
        "bak=$([ -f \"$d/docker-compose.yml.bridge.bak\" ] && echo yes || echo no); "
        "echo \"$d|nm=$nm|ports=$ports|bak=$bak\"; }; done 2>&1",
    "db":
        "python3 - <<'PYEOF' 2>&1\n"
        "import sqlite3\n"
        "db='/mnt/storage/data/1panel/db/1Panel.db'\n"
        "try:\n"
        "    con=sqlite3.connect('file:%s?mode=ro'%db, uri=True)\n"
        "    for r in con.execute('select id,name,status,version,container_name,http_port,https_port,message'\n"
        "                         ' from app_installs order by id'):\n"
        "        print('|'.join('' if x is None else str(x).replace('\\n',' ') for x in r))\n"
        "    con.close()\n"
        "except Exception as e:\n"
        "    print('ERR', e)\n"
        "PYEOF",
    "ports":
        "netstat -lntp 2>/dev/null | grep LISTEN | awk '{print $4, $7}' 2>&1",
    "hostnet":
        "echo -n 'compose_file='; ls -l /usr/bin/docker-compose 2>&1 | awk '{print $5}'; "
        "echo -n 'wrapper_marker='; grep -c 'kp-compose-host\\|net_mode\\|host\\.bak' /usr/bin/docker-compose 2>/dev/null; "
        "echo -n 'real_present='; [ -x /usr/bin/docker-compose.real ] && echo yes || echo no; "
        "echo -n 'converter_present='; [ -x /usr/sbin/kp-compose-host ] && echo yes || echo no; "
        "echo '@@LOG'; tail -n 8 /tmp/kp-compose.log 2>&1",
    "oom":
        "dmesg 2>/dev/null | grep -i 'Out of memory' | tail -n 5; "
        "echo '@@UPTIME'; awk '{print $1}' /proc/uptime",
    "res":
        # ⚠️ busybox 的 `free -m` 在这个固件上**不认 -m**，照样输出 kB ——
        #    直接用 /proc/meminfo（永远是 kB）最可靠，不用猜单位。
        "awk '/^MemTotal:/{t=$2} /^MemAvailable:/{a=$2} END"
        "{printf \"mem_kb=%d avail_kb=%d\\n\", t, a}' /proc/meminfo 2>&1; "
        "echo '@@DF'; df -h /mnt/storage/data 2>/dev/null | tail -n 1",
    "installed":
        "cat /usr/local/bin/1pctl 2>/dev/null | sed -n 's/^BASE_DIR=//p' | head -n1; "
        "echo '@@VER'; 1pctl version 2>&1 | head -n 3",
}

# 1Panel 认为"活着"的状态
LIVE_DB = {"Running", "Starting"}
# docker 认为"活着"的状态
LIVE_DOCKER = {"running", "restarting"}


def collect(dev):
    out = {}
    for k, cmd in CMDS.items():
        out[k], err = dev.sh(cmd, 90)
        if err:
            out.setdefault("_err", []).append("%s: %s" % (k, err))
    return out


def parse(raw):
    d = {}

    cs = []
    for ln in raw["containers"].splitlines():
        parts = ln.split("\t")
        if len(parts) >= 3:
            cs.append({"name": parts[0], "image": parts[1], "status": parts[2]})
    d["containers"] = cs

    insp = []
    for ln in raw["inspect"].splitlines():
        p = ln.split("|")
        if len(p) >= 10 and p[1]:
            insp.append({
                "name": p[0].lstrip("/"), "id": p[1], "state": p[2], "exit": p[3],
                "oom_killed": p[4].lower() == "true", "network": p[5],
                "restart_policy": p[6], "restarts": p[7],
                "started": p[8], "finished": p[9],
            })
    d["inspect"] = insp

    # 应用实例
    inst = []
    for ln in raw["appdirs"].split("@@INST", 1)[-1].splitlines():
        p = [x for x in ln.split("|")]
        if len(p) >= 4 and p[0].startswith("/"):
            inst.append({"dir": p[0], "nm_host": p[1].split("=")[-1],
                         "ports": p[2].split("=")[-1], "bridge_bak": p[3].split("=")[-1]})
    d["instances"] = inst

    # 面板记账
    # ⚠️ 列名坑：app_installs 里 `name` 才是应用 key（alist/siyuan…），
    #    `app_id` / `app_detail_id` 是商店里的数字 id，别拿来当标签。
    apps = []
    for ln in raw["db"].splitlines():
        p = ln.split("|")
        if len(p) >= 7 and p[0].isdigit():
            apps.append({"id": p[0], "app_key": p[1], "status": p[2], "version": p[3],
                         "container": p[4], "http_port": p[5], "https_port": p[6],
                         "message": p[7] if len(p) > 7 else ""})
    d["panel_apps"] = apps

    # 端口
    pl = []
    for ln in raw["ports"].splitlines():
        m = re.match(r"^(\S+)\s+(.*)$", ln)
        if m:
            pl.append({"listen": m.group(1), "proc": m.group(2)})
    d["listen"] = pl

    # hostnet
    h = {}
    for ln in raw["hostnet"].split("@@LOG")[0].splitlines():
        if "=" in ln:
            k, v = ln.split("=", 1)
            h[k.strip()] = v.strip()
    h["log_tail"] = raw["hostnet"].split("@@LOG")[-1].strip().splitlines() if "@@LOG" in raw["hostnet"] else []
    d["hostnet"] = h

    # OOM
    oom_lines = [l for l in raw["oom"].split("@@UPTIME")[0].splitlines() if l.strip()]
    d["oom"] = oom_lines
    up = raw["oom"].split("@@UPTIME")[-1].strip()
    d["uptime_s"] = float(up) if up.replace(".", "").isdigit() else None

    # 资源（/proc/meminfo 单位恒为 kB）
    # ⚠️ awk 把 mem_kb=… 和 avail_kb=… 打在同一行（空格分隔），
    #    逐个 token 拆，不能整行 split("=",1)。
    rmem = {}
    for ln in raw["res"].split("@@DF")[0].splitlines():
        for tok in ln.strip().split():
            if "=" in tok:
                k, vv = tok.split("=", 1)
                if vv.isdigit():
                    rmem[k] = int(vv)
    d["mem_kb"] = rmem.get("mem_kb")
    d["avail_kb"] = rmem.get("avail_kb")
    d["disk"] = raw["res"].split("@@DF")[-1].strip() if "@@DF" in raw["res"] else ""
    d["panel_ver"] = raw["installed"].split("@@VER")[-1].strip().splitlines()[0] if "@@VER" in raw["installed"] else ""
    d["base_dir"] = raw["installed"].split("@@VER")[0].strip()
    return d


def verdicts(d):
    """把原始数据翻成"人话 + 告警"，这是本脚本存在的意义。"""
    v = []
    byname = {c["name"]: c for c in d["inspect"]}

    for c in d["inspect"]:
        alive = c["state"] in LIVE_DOCKER
        if alive:
            v.append(("ok", "%s 运行中（nm=%s, restarts=%s）" % (c["name"], c["network"], c["restarts"])))
        else:
            tag = "被 OOM 杀死" if c["oom_killed"] else ("手动/正常停止" if c["exit"] == "0" else "异常退出")
            v.append(("bad" if c["oom_killed"] or c["exit"] not in ("0",) else "warn",
                      "%s 已停止 → exit=%s %s（nm=%s, restarts=%s）"
                      % (c["name"], c["exit"], tag, c["network"], c["restarts"])))
        if c["network"] != "host":
            v.append(("bad", "%s 不是 host 网络（nm=%s）—— 本机无 veth，bridge 必挂" % (c["name"], c["network"])))

    # 面板记账 vs 实际
    for a in d["panel_apps"]:
        c = byname.get(a["container"])
        db_live = a["status"] in LIVE_DB
        real_live = bool(c) and c["state"] in LIVE_DOCKER
        if db_live and not real_live:
            v.append(("bad", "面板记 %s=Running，但容器实际%s → 面板状态是错的"
                      % (a["app_key"], "不存在" if not c else c["state"])))
        elif a["status"] in ("Error", "UpErr"):
            v.append(("warn", "%s 面板状态 %s：%s" % (a["app_key"], a["status"], a["message"][:70])))

    # OOM 归属
    for ln in d["oom"]:
        m = re.search(r"task_memcg=/docker/([0-9a-f]{12,})", ln)
        m2 = re.search(r"Killed process \d+ \((\S+?)\).*?anon-rss:(\d+)kB", ln)
        if m:
            wid = m.group(1)
            owner = [c["name"] for c in d["inspect"] if c["id"].startswith(wid)]
            victim = m2.group(1) if m2 else "?"
            rss = ("%.0f MB" % (int(m2.group(2)) / 1024.0)) if m2 else "?"
            v.append(("bad", "OOM 受害者 = %s（进程 %s, RSS %s）—— memcg %s 就是该容器"
                      % (owner[0] if owner else "已删除的容器", victim, rss, wid[:12])))

    # compose 是否都 host 化
    notconv = [i for i in d["instances"] if i["nm_host"] != "1"]
    if notconv:
        for i in notconv:
            v.append(("bad", "未 host 化：%s" % i["dir"]))
    elif d["instances"]:
        v.append(("ok", "%d 个应用实例的 compose 全部已 host 化" % len(d["instances"])))

    resid = [i for i in d["instances"] if i["ports"] not in ("0", "")]
    if resid:
        for i in resid:
            v.append(("warn", "%s 仍残留 ports: 段（host 模式下无效）" % i["dir"]))

    # hostnet 装置
    hn = d["hostnet"]
    if hn.get("real_present") == "yes" and hn.get("converter_present") == "yes":
        v.append(("ok", "host 默认化装置在位（wrapper + .real + kp-compose-host）"))
    else:
        v.append(("bad", "host 默认化装置不完整：real=%s converter=%s"
                  % (hn.get("real_present"), hn.get("converter_present"))))
    if not hn.get("log_tail"):
        v.append(("warn", "/tmp/kp-compose.log 为空 —— 没有 wrapper 调用记录（面板可能没走 /usr/bin/docker-compose）"))

    # 内存红线（kB → MB）
    if d.get("mem_kb"):
        total_mb = d["mem_kb"] / 1024.0
        avail_mb = (d.get("avail_kb") or 0) / 1024.0
        if avail_mb < 300:
            v.append(("bad", "可用内存仅 %.0f MB / %.0f MB —— 再起大容器很可能二次 OOM"
                      % (avail_mb, total_mb)))
        else:
            v.append(("ok", "可用内存 %.0f MB / %.0f MB" % (avail_mb, total_mb)))
    return v


def main():
    ap = argparse.ArgumentParser(description="只读盘点 1Panel 容器/应用/端口（不写任何东西）")
    ap.add_argument("--host")
    ap.add_argument("--user")
    ap.add_argument("--pw")
    ap.add_argument("--cred-file", default=DEFAULT_CRED_FILE)
    ap.add_argument("--json", help="额外把结构化结果写到这个文件")
    args = ap.parse_args()

    creds = load_creds(args.cred_file)
    host = args.host or creds.get("ROUTER_HOST") or "192.168.66.1"
    user = args.user or creds.get("ROUTER_USER") or "root"
    pw = args.pw or creds.get("ROUTER_PW")
    if not pw:
        print("缺少凭据：请设 ROUTER_PW 环境变量，或写 %s" % args.cred_file, file=sys.stderr)
        return 2

    try:
        import paramiko  # noqa: F401
    except ImportError:
        print("需要 paramiko：pip install paramiko", file=sys.stderr)
        return 2

    print("只读盘点 %s（不做任何写操作）…" % host)
    dev = Dev(host, user, pw)
    try:
        raw = collect(dev)
    finally:
        dev.close()

    d = parse(raw)
    d["host"] = host
    d["_err"] = raw.get("_err", [])
    vs = verdicts(d)

    print()
    print("=" * 68)
    print("容器（docker ps -a）")
    print("-" * 68)
    if not d["inspect"]:
        print("  （没有任何容器）")
    for c in d["inspect"]:
        print("  %-34s %-10s exit=%-4s oom=%-5s nm=%s" %
              (c["name"], c["state"], c["exit"], c["oom_killed"], c["network"]))

    print()
    print("=" * 68)
    print("面板记账（app_installs）")
    print("-" * 68)
    for a in d["panel_apps"]:
        print("  id=%-3s %-18s %-9s v%-12s %s" %
              (a["id"], a["app_key"], a["status"], a["version"], a["container"]))

    print()
    print("=" * 68)
    print("磁盘上的应用实例")
    print("-" * 68)
    for i in d["instances"]:
        print("  %-58s nm_host=%s ports=%s bak=%s" % (i["dir"], i["nm_host"], i["ports"], i["bridge_bak"]))

    print()
    print("=" * 68)
    print("判读")
    print("-" * 68)
    for lvl, msg in vs:
        mark = {"ok": "[ OK ]", "warn": "[WARN]", "bad": "[FAIL]"}[lvl]
        print("  %s %s" % (mark, msg))

    if d.get("mem_kb"):
        print()
        print("  资源: 内存 可用 %.0f MB / 共 %.0f MB" %
              ((d.get("avail_kb") or 0) / 1024.0, d["mem_kb"] / 1024.0))
        if d.get("disk"):
            print("        %s" % d["disk"])

    if args.json:
        with io.open(args.json, "w", encoding="utf-8") as f:
            f.write(json.dumps(d, ensure_ascii=False, indent=2))
        print("\nJSON -> %s" % args.json)

    return 0 if not any(l == "bad" for l, _ in vs) else 1


if __name__ == "__main__":
    sys.exit(main())
