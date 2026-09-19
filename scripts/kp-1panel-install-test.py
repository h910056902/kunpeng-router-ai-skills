#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""kp-1panel-install-test.py —— 「1Panel 到底能不能装容器」测试驱动（PC 侧）

背景：鲲鹏 C2000 U 内核无 veth，docker 桥接网络物理不可用，而 1Panel 应用商店的
compose 模板**一律**引用外部 bridge 网络 1panel-network + ports:，所以面板装应用必失败。
本脚本端到端验证两件事：
  ① 拉取能力：能不能把应用镜像拉下来（走 UCI 里的加速源）
  ② 安装能力：把 1Panel 的 `docker-compose -f <file> up -d` 调用**默认 host 化**之后，
     应用能不能真的跑起来并对外可访问

用法：
    python kp-1panel-install-test.py                     # 全流程（默认到 control 停，除非 --yes）
    python kp-1panel-install-test.py --yes               # 授权改 /usr/bin/docker-compose，跑完整链
    python kp-1panel-install-test.py --stage probe       # 只跑一个阶段（可重复/逗号分隔）
    python kp-1panel-install-test.py --stage panelcheck --stage verify   # 面板点完后收尾取证
    python kp-1panel-install-test.py --restore           # 一键回滚 wrapper
    python kp-1panel-install-test.py --uninstall --yes   # 卸载测试实例（数据目录保留）

凭据：只从环境变量或本地凭据文件读，**绝不落盘、绝不进报告**。
    环境变量优先：ROUTER_HOST / ROUTER_USER / ROUTER_PW
    凭据文件默认：C:\\Users\\91005\\.workbuddy\\kunpeng-router.env（KEY=VALUE 一行一条）

阶段：probe pull control hostnet-install hostnet-restore install panel panelcheck verify uninstall
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
import tarfile
import time
import urllib.error
import urllib.request
import zipfile

# ---------------------------------------------------------------- 常量

CRED_FILE = r"%USERPROFILE%\.workbuddy\kunpeng-router.env"
SKILL_DIR = r"%USERPROFILE%\.workbuddy\skills\kunpeng-router-tuning"
SCRIPTS_DIR = os.path.join(SKILL_DIR, "scripts")
PAYLOAD_DIR = os.path.join(SCRIPTS_DIR, "payload")
OUT_ROOT = r"%USERPROFILE%\WorkBuddy\2026-09-19-02-21-37\1panel-install-test"

STORE_INDEX = "https://apps-assets.fit2cloud.com/stable/1panel.json.zip"
REMOTE_WORK = "/tmp/kp1pt"

# 需要推到设备去的 payload（相对 PAYLOAD_DIR 的路径 -> 远端同名路径，子目录需先建）
# ⚠️ 2026-09-19：fixtures 是**转换器回归样本**，必须一起推 —— 面板实际落盘的 compose
#    是 4 空格缩进（商店 tarball 是 2 空格），漏了它就会重演"只测商店模板→真机翻车"。
PAYLOAD_FILES = [
    "kp-1panel-test.sh",
    "install-hostnet-default.sh",
    "kp-compose-host.sh",
    "docker-compose.wrapper",
    "kp-compose-selftest.sh",
    "fixtures/compose.store2sp.yml",
    "fixtures/compose.panel4sp.yml",
    "fixtures/compose.weird3sp.yml",
]
# 需要先 mkdir 的远端子目录（按 PAYLOAD_FILES 里的目录部分自动推）
PAYLOAD_SUBDIRS = ["fixtures"]

ALL_STAGES = ["probe", "pull", "control", "hostnet-install",
              "install", "panel", "panelcheck", "verify"]

# 只在显式指定 / --restore / --uninstall 时才跑的阶段。
# ⚠️ 必须并进校验表，否则 --restore 会被自己的参数校验拒掉（rc=2）—— 这是实测踩到的 bug。
EXTRA_STAGES = ["hostnet-restore", "uninstall"]
VALID_STAGES = ALL_STAGES + EXTRA_STAGES

# 默认流程；hostnet-install 之后的阶段需要 --yes 才放行
DEFAULT_STAGES = ALL_STAGES

# 每个阶段的 SSH 超时（秒）
STAGE_TIMEOUT = {
    "probe": 180,
    "pull": 900,          # TF 卡 + 加速源，慢
    "control": 300,
    "hostnet-install": 180,
    "hostnet-restore": 120,
    "install": 600,
    "panel": 60,          # 只在 PC 侧发 HTTP，不连设备；留个值保持阶段表完整
    "panelcheck": 120,
    "verify": 120,
    "uninstall": 180,
}

GATED = {"hostnet-install"}   # 出现在这里之后的阶段都要 --yes


# ---------------------------------------------------------------- 输出工具

class C:
    OK = "\033[32m"
    BAD = "\033[31m"
    WARN = "\033[33m"
    DIM = "\033[2m"
    BOLD = "\033[1m"
    END = "\033[0m"


def _tty() -> bool:
    try:
        return sys.stdout.isatty()
    except Exception:
        return False


def paint(s, c):
    return ("%s%s%s" % (c, s, C.END)) if _tty() else s


def log(msg=""):
    print(msg)
    REPORT_LINES.append(msg)


REPORT_LINES = []


def step(msg):
    print("\n%s %s" % (paint("==", C.BOLD), paint(msg, C.BOLD)))
    REPORT_LINES.append("\n## " + msg)


# ---------------------------------------------------------------- 凭据

def load_creds(path=CRED_FILE):
    """环境变量优先，其次读文件。返回 dict 并把值灌进 os.environ（rtr_lib 只认环境变量）。"""
    vals = {}
    if os.path.isfile(path):
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
    for k, v in vals.items():
        os.environ[k] = v
    return vals


def scrub(text):
    """报告里出现的密码一律打码。"""
    pw = os.environ.get("ROUTER_PW") or ""
    if pw and len(pw) >= 3:
        text = text.replace(pw, "***")
    return text


# ---------------------------------------------------------------- 1Panel 商店模板

def _fetch(url, timeout=90):
    # 显式禁用代理：目标可能是局域网地址（192.168.x.x），走代理必失败
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req = urllib.request.Request(url, headers={"User-Agent": "kp-1panel-test/1.0"})
    with opener.open(req, timeout=timeout) as r:
        return r.read()


def fetch_app_index():
    """下载并解析 1Panel 应用商店索引（一个 zip，内含 1panel.json）。"""
    raw = _fetch(STORE_INDEX)
    z = zipfile.ZipFile(io.BytesIO(raw))
    name = z.namelist()[0]
    return json.loads(z.read(name).decode("utf-8", "replace")), len(raw)


def pick_app(data, key):
    for a in data.get("apps", []):
        if a.get("id") == key:
            return a
    raise SystemExit("商店索引里找不到应用 key=%s" % key)


def pick_version(app, want=None):
    vers = app.get("versions") or []
    if not vers:
        raise SystemExit("应用 %s 没有任何版本" % app.get("id"))
    if want:
        for v in vers:
            if v.get("name") == want:
                return v
        raise SystemExit("应用 %s 没有版本 %s" % (app.get("id"), want))
    return vers[0]        # 索引按新到旧排，第一条即最新


def fetch_template(app, ver):
    """下载应用 tarball，取出真正的 docker-compose.yml 文本。"""
    url = ver.get("downloadUrl")
    if not url:
        raise SystemExit("版本 %s 没有 downloadUrl" % ver.get("name"))
    raw = _fetch(url)
    tf = tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz")
    cands = [m for m in tf.getmembers() if m.isfile() and m.name.endswith("docker-compose.yml")]
    if not cands:
        raise SystemExit("tarball 里没有 docker-compose.yml: %s" % url)
    cands.sort(key=lambda m: len(m.name))          # 路径最深的那个是应用版本目录下的
    f = tf.extractfile(cands[-1])
    return f.read().decode("utf-8", "replace"), url, len(raw), cands[-1].name


def build_env(app, ver, instname):
    """1Panel 装应用时会按版本 data.yml 的 formFields 生成 .env（包内并不带 .env）。
    缺了它 compose 里的 ${CONTAINER_NAME} 之类变量会解析失败，必须自己补。"""
    lines = ["# 由 kp-1panel-install-test.py 按 1Panel data.yml formFields 合成",
             "CONTAINER_NAME=%s" % instname]
    ap = ver.get("additionalProperties") or {}
    for f in ap.get("formFields") or []:
        k = f.get("envKey")
        if not k or k == "CONTAINER_NAME":
            continue
        d = f.get("default")
        if d is None:
            d = ""
        lines.append("%s=%s" % (k, d))
    return "\n".join(lines) + "\n", len(ap.get("formFields") or [])


# ---------------------------------------------------------------- 面板 HTTP（A1）
#
# 2026-09-19 对 192.168.66.1:10090 实测定型，推翻了先前"必须 RSA+AES 加密登录"的猜测：
#   · API 直接可达，**不需要安全入口码**（不带 entranceCode 也走到凭据校验）
#   · 变量是**明文**提交的，不需要加密 —— 发假密码拿到的是 {"code":406,"message":"ErrAuth"}，
#     而不是解密失败
#   · 必填字段恰好 4 个：name / password / authMethod / language（少一个就 code=400 参数错误）
#   · **一律返回 HTTP 200**，真实结果在 body 的 code 字段里 ——
#     只看 HTTP 状态码会把"参数错误"误判成"登录成功"

def _panel_opener():
    # 显式禁用代理：目标是局域网地址，走代理必失败
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def _panel_post(host, port, path, body, token=None, timeout=10):
    """发一个 JSON POST。返回 (http_status, raw_text, parsed_json)。"""
    url = "http://%s:%s%s" % (host, port, path)
    hdr = {"Content-Type": "application/json"}
    if token:
        hdr["1Panel-Token"] = token
    req = urllib.request.Request(url, data=json.dumps(body).encode("utf-8"),
                                 method="POST", headers=hdr)
    status, raw = None, ""
    try:
        with _panel_opener().open(req, timeout=timeout) as r:
            status = r.status
            raw = r.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        status = e.code
        try:
            raw = e.read().decode("utf-8", "replace")
        except Exception:
            pass
    except Exception as e:
        return None, "%s: %s" % (type(e).__name__, e), {}
    try:
        return status, raw, json.loads(raw)
    except Exception:
        return status, raw, {}


def panel_api_ready(host, port, timeout=8):
    """只读判断面板 API 是否可达，并回报它要什么必填字段。"""
    status, raw, js = _panel_post(host, port, "/api/v1/auth/login", {}, timeout=timeout)
    if status is None:
        return False, raw
    msg = js.get("message") or ""
    needed = re.findall(r"Key: 'Login\.(\w+)'", msg)
    if needed:
        return True, "可达；空请求回报必填字段: %s" % ", ".join(needed)
    return True, "可达；返回 code=%s message=%s" % (js.get("code"), msg[:120])


def panel_api_login(host, port, user, pw, entrance="", timeout=15):
    """返回 (token|None, 说明)。"""
    status, raw, js = _panel_post(host, port, "/api/v1/auth/login", {
        "name": user,
        "password": pw,          # 实测明文即可，无需 RSA+AES
        "authMethod": "session",
        "language": "zh",
        "ignoreCaptcha": True,
        "entranceCode": entrance or "",
    }, timeout=timeout)
    if status is None:
        return None, raw
    if js.get("code") == 200 and isinstance(js.get("data"), dict):
        return js["data"].get("token"), "code=200 登录成功"
    return None, "code=%s message=%s" % (js.get("code"), (js.get("message") or "")[:180])


def panel_api_installed(host, port, token, timeout=10):
    """带 token 的只读调用：证明会话真的可用，并列出面板记账的已安装应用。"""
    status, raw, js = _panel_post(host, port, "/api/v1/apps/installed/search",
                                  {"page": 1, "pageSize": 50}, token=token, timeout=timeout)
    if status is None:
        return None, raw
    if js.get("code") == 200:
        items = (js.get("data") or {}).get("items") or []
        return items, "已安装 %d 个" % len(items)
    return None, "code=%s message=%s" % (js.get("code"), (js.get("message") or "")[:180])


def panel_api_install(host, port, token, app_key, instname, version, params, timeout=60):
    """尽力而成的一次安装尝试。
    ⚠️ 这个请求体的精确形状**还没从真实浏览器抓过**，所以它失败是预期内的：
    失败时把面板返回的原文**原样带回来**，那就是下一次改进的依据。"""
    body = {
        "appKey": app_key,
        "name": instname,
        "version": version,
        "params": params,
        "type": "install",
        "advanced": False,
        "pullImage": True,
        "editCompose": False,
        "allowPort": False,
        "containerName": instname,
    }
    status, raw, js = _panel_post(host, port, "/api/v1/apps/install", body,
                                  token=token, timeout=timeout)
    if status is None:
        return False, raw
    if js.get("code") == 200:
        return True, "code=200 安装请求已被接受"
    return False, "code=%s message=%s" % (js.get("code"), (js.get("message") or "")[:300])



# ---------------------------------------------------------------- 设备端输出解析

class StageResult:
    def __init__(self, name):
        self.name = name
        self.kv = {}
        self.ok = []
        self.fail = []
        self.info = []
        self.sections = []
        self.raw = ""
        self.rc = None

    def feed(self, text):
        self.raw = text
        for ln in text.splitlines():
            if ln.startswith("@@KV "):
                rest = ln[5:]
                k, _, v = rest.partition(" ")
                self.kv[k] = v.strip()
            elif ln.startswith("@@OK "):
                self.ok.append(ln[5:].strip())
            elif ln.startswith("@@FAIL "):
                self.fail.append(ln[7:].strip())
            elif ln.startswith("@@INFO "):
                self.info.append(ln[7:].strip())
            elif ln.startswith("@@SECTION "):
                self.sections.append(ln[10:].strip())

    @property
    def verdict(self):
        if self.fail:
            return "FAIL"
        if self.ok:
            return "PASS"
        return "N/A"


# ---------------------------------------------------------------- 主流程

def main():
    ap = argparse.ArgumentParser(
        description="1Panel 装容器能力测试（PC 侧驱动）",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--stage", action="append", default=[],
                    help="只跑指定阶段，可重复或用逗号分隔；all = 全跑")
    ap.add_argument("--yes", action="store_true",
                    help="授权改 /usr/bin/docker-compose（wrapper 默认化）。不加则跑到 control 就停")
    ap.add_argument("--restore", action="store_true", help="一键回滚 wrapper")
    ap.add_argument("--uninstall", action="store_true", help="卸载测试实例（数据目录保留）")
    ap.add_argument("--app", default="alist", help="应用 key（默认 alist）")
    ap.add_argument("--app-version", default=None, help="指定应用版本（默认最新）")
    ap.add_argument("--instname", default="alist-test", help="安装实例名（默认 alist-test）")
    ap.add_argument("--panel-pw", default=None,
                    help="直接给 1Panel 面板密码（默认从设备 1pctl 读；与 ROUTER_PW 不是一回事）")
    ap.add_argument("--panel-user", default=None, help="面板账号（默认从 1pctl 读）")
    ap.add_argument("--panel-port", default=None, help="面板端口（默认从 1pctl 读）")
    ap.add_argument("--template-file", default=None,
                    help="跳过下载，直接用本地的 docker-compose.yml 作为被测模板")
    ap.add_argument("--keep", action="store_true", help="结束后不提示卸载")
    ap.add_argument("--no-report", action="store_true", help="不写报告文件")
    args = ap.parse_args()

    # ---- 凭据 ----
    creds = load_creds()
    if not creds.get("ROUTER_PW"):
        print(paint("缺少 ROUTER_PW。", C.BAD))
        print("请创建凭据文件：%s" % CRED_FILE)
        print("内容一行：ROUTER_PW=<路由器 root 密码>")
        print("（也可直接设环境变量 ROUTER_HOST / ROUTER_USER / ROUTER_PW）")
        return 2
    host = creds.get("ROUTER_HOST") or "192.168.66.1"

    # ---- 阶段表 ----
    if args.restore:
        stages = ["hostnet-restore", "verify"]
    elif args.uninstall:
        stages = ["uninstall"]
    elif args.stage:
        if "all" in args.stage:
            stages = list(DEFAULT_STAGES)
        else:
            stages = []
            for s in args.stage:
                stages.extend([x.strip() for x in s.split(",") if x.strip()])
    else:
        stages = list(DEFAULT_STAGES)

    bad = [s for s in stages if s not in VALID_STAGES]
    if bad:
        print(paint("未知阶段: %s" % ", ".join(bad), C.BAD))
        print("可用阶段: %s" % ", ".join(VALID_STAGES))
        return 2

    # ---- GATE：没有 --yes 就不许动系统命令 ----
    gated_out = []
    if not args.yes and "hostnet-install" in stages:
        idx = stages.index("hostnet-install")
        gated_out = stages[idx:]
        stages = stages[:idx]

    results = []

    try:
        sys.path.insert(0, SCRIPTS_DIR)
        from rtr_lib import Rtr            # noqa: E402
    except Exception as e:
        print(paint("导入 rtr_lib 失败（需要 paramiko）: %s" % e, C.BAD))
        return 2

    step("连接设备 %s" % host)
    try:
        r = Rtr()
    except Exception as e:
        print(paint("SSH 连接失败: %s" % e, C.BAD))
        return 2
    log("已连接 %s@%s" % (os.environ.get("ROUTER_USER", "root"), host))

    try:
        # ============================================================ 取模板
        if args.template_file:
            step("使用本地模板 %s" % args.template_file)
            with io.open(args.template_file, "r", encoding="utf-8") as f:
                tmpl = f.read()
            tmpl_src = args.template_file
            ver_name = "local"
            env_text = ("CONTAINER_NAME=%s\n" % args.instname)
            nfields = 0
        else:
            step("从 1Panel 官方应用商店取 %s 的真模板" % args.app)
            try:
                data, isz = fetch_app_index()
                app = pick_app(data, args.app)
                ver = pick_version(app, args.app_version)
                tmpl, url, tsz, member = fetch_template(app, ver)
                ver_name = ver.get("name")
                tmpl_src = url
                log("  索引 %.0fKB，应用包 %.1fKB，成员 %s" % (isz / 1024.0, tsz / 1024.0, member))
                log("  应用 %s（%s）版本 %s" % (app.get("name"), app.get("id"), ver_name))
                arches = (app.get("additionalProperties") or {}).get("architectures") or []
                log("  声明架构: %s" % (", ".join(arches) or "未声明"))
                if arches and not any("arm64" in str(a) or "aarch64" in str(a) for a in arches):
                    log(paint("  警告：应用未声明 arm64 支持，可能拉不到镜像", C.WARN))
                env_text, nfields = build_env(app, ver, args.instname)
                log("  由 data.yml 合成 .env（%d 个 formField + CONTAINER_NAME）" % nfields)
                # 供 panel 阶段调安装接口用
                args.__dict__["_app_version"] = ver_name
                args.__dict__["_app_params"] = {
                    f.get("envKey"): str(f.get("default"))
                    for f in ((ver.get("additionalProperties") or {}).get("formFields") or [])
                    if f.get("envKey")
                }
            except SystemExit as e:
                print(paint(str(e), C.BAD))
                return 2

        # 模板指纹（本地先看一眼，确认它确实是 bridge 模板）
        img = ""
        for ln in tmpl.splitlines():
            m = re.match(r"^\s+image:\s*(\S+)", ln)
            if m:
                img = m.group(1).strip('"\'')
                break
        has_net = "1panel-network" in tmpl
        has_ports = bool(re.search(r"^[ \t]+ports:", tmpl, re.M))
        log("  模板指纹：image=%s  external-network=%s  ports段=%s" % (img, has_net, has_ports))
        if not (has_net or has_ports):
            log(paint("  警告：模板没有 bridge 特征 —— 它可能本来就是 host，测不出对照效果", C.WARN))

        # ============================================================ 推 payload
        step("推送 payload 到设备 %s" % REMOTE_WORK)
        r.sh("mkdir -p %s && chmod 700 %s" % (REMOTE_WORK, REMOTE_WORK), silent=True)
        for sub in PAYLOAD_SUBDIRS:
            r.sh("mkdir -p %s/%s" % (REMOTE_WORK, sub), silent=True)
        for fn in PAYLOAD_FILES:
            lp = os.path.join(PAYLOAD_DIR, fn)
            if not os.path.isfile(lp):
                print(paint("缺少 payload %s" % lp, C.BAD))
                return 2
            with io.open(lp, "r", encoding="utf-8", newline="\n") as f:
                txt = f.read()
            ok, md5 = r.put_text_verified("%s/%s" % (REMOTE_WORK, fn), txt, t=90)
            log("  %-30s %s  md5=%s" % (fn, "OK" if ok else "MD5 不一致!!", md5))
            if not ok:
                print(paint("  %s 上传校验失败，中止（历史上出现过只写了一半的静默失败）" % fn, C.BAD))
                return 2

        ok, md5 = r.put_text_verified("%s/compose.orig.yml" % REMOTE_WORK, tmpl, t=90)
        log("  %-30s %s  md5=%s" % ("compose.orig.yml", "OK" if ok else "MD5 不一致!!", md5))
        if not ok:
            return 2
        ok2, md52 = r.put_text_verified("%s/app.env" % REMOTE_WORK, env_text, t=60)
        log("  %-30s %s  md5=%s" % ("app.env", "OK" if ok2 else "MD5 不一致!!", md52))
        if not ok2:
            return 2

        # 远端做一次 bash -n 语法闸门（绝不上未通过语法检查的脚本）
        step("设备端语法闸门 sh -n")
        for fn in PAYLOAD_FILES:
            if not fn.endswith(".sh"):
                continue          # fixtures 是 YAML 样本，不做 sh -n
            out = r.sh("sh -n %s/%s 2>&1 && echo SYNTAX_OK" % (REMOTE_WORK, fn), silent=True)
            flag = "SYNTAX_OK" in out
            log("  %-30s %s %s" % (fn, "PASS" if flag else "FAIL", out if not flag else ""))
            if not flag:
                print(paint("  语法检查未通过，中止（不会把坏脚本放到系统里）", C.BAD))
                return 2

        # ============================================================ 逐阶段跑
        for st in stages:
            step("阶段 %s" % st)
            res = run_stage(r, st, args, host)
            results.append(res)

            # panel 阶段的特殊处理：A1 没能真的把应用装起来 → 降级为操作卡
            if st == "panel" and res.kv.get("a1_install") != "yes":
                print_panel_card(res, host, args)
                log(paint("  → 请按上面的操作卡在浏览器点一次，然后跑：", C.WARN))
                cmd = ("python %s --stage panelcheck --stage verify"
                       % os.path.basename(__file__))
                log("     %s" % cmd)
                break

        # ---- GATE 提示 ----
        if gated_out:
            step("已停在授权闸门（未加 --yes）")
            log("以下阶段被拦住，因为它们会修改系统命令：")
            for s in gated_out:
                log("  - %s" % s)
            log("")
            log("将要做的改动：")
            log("  1. /usr/bin/docker-compose  →  /usr/bin/docker-compose.real（改名保留，不删除）")
            log("  2. 写入 wrapper 到 /usr/bin/docker-compose（拦截 -f 指向的 compose 并自动 host 化）")
            log("  3. 安装转换器 /usr/sbin/kp-compose-host")
            log("  4. 扫描并转换已有应用 $PANEL_ROOT/apps/*/*/docker-compose.yml")
            log("")
            log("一条命令回滚：  --restore")
            log("确认可跑：      --yes")

        # ============================================================ 报告
        if not args.no_report:
            write_report(results, args, host, tmpl_src, ver_name, img)

    finally:
        try:
            r.close()
        except Exception:
            pass

    # ---- 收尾摘要 ----
    print()
    print(paint("========== 汇总 ==========", C.BOLD))
    for res in results:
        tag = {"PASS": paint("PASS", C.OK),
               "FAIL": paint("FAIL", C.BAD),
               "N/A": paint("N/A ", C.DIM)}[res.verdict]
        print("  [%s] %-16s ok=%d fail=%d" % (tag, res.name, len(res.ok), len(res.fail)))
        for f in res.fail:
            print("        %s %s" % (paint("x", C.BAD), f))
    print()
    return 0


def run_stage(r, stage, args, host):
    res = StageResult(stage)

    if stage == "panel":
        # A1：PC 侧直连面板 API。实测可达 + 明文登录，所以这条路是真能走通的，
        # 但**装应用**那个请求体的精确形状还没从真实浏览器抓过 —— 失败不阻塞。
        port = args.panel_port or args.__dict__.get("_panel_port") or "10090"
        user = args.panel_user or args.__dict__.get("_panel_user") or "admin"
        pw = args.panel_pw or args.__dict__.get("_panel_pw") or ""
        ent = args.__dict__.get("_panel_entrance") or ""

        print("  A1：PC 侧直连面板 API http://%s:%s" % (host, port))
        ready, detail = panel_api_ready(host, port)
        print("    %-4s 可达性: %s" % ("OK" if ready else "FAIL", detail[:200]))
        res.info.append("A1 可达性 %s: %s" % ("OK" if ready else "FAIL", detail[:200]))
        res.kv["panel_api_reachable"] = "yes" if ready else "no"
        res.kv["a1_login"] = "no"
        res.kv["a1_install"] = "no"
        if not ready:
            res.fail.append("A1 不可用（面板 API 连不上）: %s" % detail[:140])
            return res
        res.ok.append("面板 API 可达（无需安全入口码）")

        if not pw:
            res.fail.append("A1 不可用（拿不到面板密码 —— ROUTER_PW 没设，或 1pctl 里读不到；"
                            "可用 --panel-pw 直接给）")
            return res

        print("    登录中（账号 %s，密码 %d 字符）…" % (user, len(pw)))
        token, detail = panel_api_login(host, port, user, pw, ent)
        res.info.append("A1 登录 %s: %s" % ("OK" if token else "FAIL", detail[:200]))
        if not token:
            print("    FAIL 登录失败: %s" % detail[:200])
            if "aptcha" in detail:
                res.fail.append("A1 被图形验证码拦住（ErrCaptchaCode）—— 这是纯脚本自动化的硬阻断，"
                                "只能人工在浏览器点一次；见下方操作卡")
            else:
                res.fail.append("A1 登录失败: %s" % detail[:200])
            return res
        print("    OK   登录成功，token %d 字符（明文提交即可，无需 RSA+AES）" % len(token))
        res.ok.append("A1 自动登录面板成功（明文提交，无需入口码）")
        res.kv["a1_login"] = "yes"

        items, detail = panel_api_installed(host, port, token)
        if items is not None:
            print("    OK   面板记账的已安装应用: %s" % detail)
            res.ok.append("A1 会话可用；面板记账 %s" % detail)
            for it in items[:10]:
                res.info.append("面板已装应用: %s"
                                % (it.get("name") if isinstance(it, dict) else it))
        else:
            print("    警告 读已安装列表失败: %s" % detail[:200])
            res.info.append("A1 读已安装列表失败: %s" % detail[:200])

        params = args.__dict__.get("_app_params") or {}
        ver = args.__dict__.get("_app_version") or ""
        print("    尝试调安装接口（appKey=%s name=%s version=%s params=%d 项）…"
              % (args.app, args.instname, ver or "?", len(params)))
        ok, detail = panel_api_install(host, port, token, args.app, args.instname,
                                       ver, params)
        print("    %-4s 安装请求: %s" % ("OK" if ok else "FAIL", detail[:250]))
        res.info.append("A1 install %s: %s" % ("OK" if ok else "FAIL", detail[:300]))
        if ok:
            res.kv["a1_install"] = "yes"
            res.ok.append("A1 面板 API 安装请求已被接受（等 15s 后别忘跑 panelcheck 取证）")
        else:
            res.fail.append("A1 安装请求被拒（请求体形状需从真实浏览器抓包比对）: %s"
                            % detail[:220])
        return res


    # 普通阶段：远端执行
    cmd = "sh %s/kp-1panel-test.sh %s 2>&1" % (REMOTE_WORK, stage)
    t = STAGE_TIMEOUT.get(stage, 300)
    try:
        out = r.safe(cmd, t=t, silent=True)
    except Exception as e:
        res.fail.append("执行异常: %s: %s" % (type(e).__name__, e))
        print(paint("  执行异常: %s" % e, C.BAD))
        return res

    res.feed(out)

    # 回填关键 KV 给 panel 阶段用
    if stage == "probe":
        args.__dict__["_panel_port"] = res.kv.get("panel_port") or "10090"
        args.__dict__["_panel_user"] = res.kv.get("panel_user") or "admin"
        args.__dict__["_panel_entrance"] = res.kv.get("panel_entrance") or ""
        # 面板密码只在设备上，PC 拿不到明文长度之外的东西 —— 由 probe 里单独取一次
        pw = r.run("sed -n 's/^ORIGINAL_PASSWORD=//p' /usr/local/bin/1pctl 2>/dev/null | head -n1", t=30)
        args.__dict__["_panel_pw"] = pw.strip()

    for ln in res.sections:
        print("  %s" % paint("-- %s" % ln, C.DIM))
    for k, v in res.kv.items():
        print("    %-32s %s" % (k, v[:150]))
    for i in res.info[:40]:
        print("    %s %s" % (paint(".", C.DIM), i[:200]))
    if len(res.info) > 40:
        print("    %s …还有 %d 条（详见报告）" % (paint(".", C.DIM), len(res.info) - 40))
    for f in res.fail:
        print("    %s %s" % (paint("FAIL", C.BAD), f))
    for o in res.ok:
        print("    %s %s" % (paint("OK", C.OK), o))
    return res


def print_panel_card(res, host, args):
    port = args.__dict__.get("_panel_port") or "10090"
    ent = args.__dict__.get("_panel_entrance") or ""
    url = "http://%s:%s/%s" % (host, port, ent) if ent else "http://%s:%s/" % (host, port)
    print()
    print(paint("  ── 需要你手动点一次（脚本走不完全自动） ──", C.WARN))
    print(paint("     原因：1Panel v1.10 的登录接口要图形验证码（ErrCaptchaCode），", C.WARN))
    print(paint("     纯脚本登录过不去。（但 API 本身既不需要安全入口码、也不需要加密）", C.WARN))
    print("")
    print("    1. 浏览器打开： %s" % url)
    if not ent:
        print(paint("       ⚠ 没能从 1pctl 读到安全入口码，请自行补上（1pctl user-info 可看）", C.WARN))
    print("    2. 登录（账号密码在设备 /root/1panel-credentials.txt，或 1pctl user-info）")
    print("    3. 应用商店 → 搜索 %s → 点「安装」" % args.app)
    print("       · 端口随便填（host 模式下端口映射会失效，以镜像默认 5244 为准）")
    print("    4. 装完回到这里跑收尾取证：")
    print("       python %s --stage panelcheck --stage verify" % os.path.basename(__file__))
    print("    取证会读 /tmp/kp-compose.log —— 那是唯一能回答")
    print("    「面板到底调了什么」的证据源。")


# ---------------------------------------------------------------- 报告

def write_report(results, args, host, tmpl_src, ver_name, img):
    os.makedirs(OUT_ROOT, exist_ok=True)
    ts = time.strftime("%Y%m%d-%H%M%S")
    path = os.path.join(OUT_ROOT, "report-%s.md" % ts)

    L = []
    L.append("# 1Panel 装容器能力测试报告")
    L.append("")
    L.append("- 设备：`%s`（root，凭据只从环境/本地文件读，报告内已打码）" % host)
    L.append("- 时间：%s" % time.strftime("%Y-%m-%d %H:%M:%S"))
    L.append("- 被测应用：`%s` @ `%s`" % (args.app, ver_name))
    L.append("- 模板来源：`%s`" % tmpl_src)
    L.append("- 镜像：`%s`" % img)
    L.append("")

    L.append("## 结论汇总")
    L.append("")
    L.append("| 阶段 | 结论 | OK | FAIL |")
    L.append("|---|---|---|---|")
    for res in results:
        L.append("| %s | %s | %d | %d |" % (res.name, res.verdict, len(res.ok), len(res.fail)))
    L.append("")

    for res in results:
        L.append("## 阶段：%s → %s" % (res.name, res.verdict))
        L.append("")
        if res.fail:
            L.append("**失败项**")
            L.append("")
            for f in res.fail:
                L.append("- %s" % f)
            L.append("")
        if res.ok:
            L.append("**通过项**")
            L.append("")
            for o in res.ok:
                L.append("- %s" % o)
            L.append("")
        if res.kv:
            L.append("**键值**")
            L.append("")
            L.append("| 键 | 值 |")
            L.append("|---|---|")
            for k, v in res.kv.items():
                L.append("| `%s` | %s |" % (k, v[:400].replace("|", "\\|")))
            L.append("")
        if res.info:
            L.append("<details><summary>原始信息 %d 条</summary>" % len(res.info))
            L.append("")
            L.append("```")
            for i in res.info:
                L.append(i)
            L.append("```")
            L.append("</details>")
            L.append("")
        L.append("<details><summary>原始输出</summary>")
        L.append("")
        L.append("```")
        L.append(scrub(res.raw))
        L.append("```")
        L.append("</details>")
        L.append("")

    L.append("## 已知代价（要写进面板说明，别以为坏了）")
    L.append("")
    L.append("- **端口映射失效**：host 网络下应用直接占宿主机端口，以**镜像默认端口**为准，"
             "面板里选的端口不再生效；同一端口不能被两个应用同时用。")
    L.append("- 装完后不要在面板里「改端口」——会被转换器再抹掉。")
    L.append("- 回滚：`--restore`（真件一直在 `/usr/bin/docker-compose.real`）。")
    L.append("")

    text = scrub("\n".join(L))
    with io.open(path, "w", encoding="utf-8", newline="\n") as f:
        f.write(text)
    print()
    print(paint("报告已写入：%s" % path, C.OK))
    return path


if __name__ == "__main__":
    sys.exit(main())
