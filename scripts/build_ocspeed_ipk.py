# -*- coding: utf-8 -*-
"""
把 ocspeed（OpenClash 自动测速 LuCI 插件）打包成 opkg 可装的 .ipk
源：kunpeng-router-tuning/offline/ocspeed/ 五件套
产物：luci-app-ocspeed_3.5-1_all.ipk（架构无关，21.02 / 24.10 通用）
"""
import hashlib, io, tarfile, time, sys, os

SRC = r"C:\Users\91005\.workbuddy\skills\kunpeng-router-tuning\offline\ocspeed"
OUT = r"C:\Users\91005\WorkBuddy\2026-09-23-10-56-49\luci-app-ocspeed_3.5-1_all.ipk"

# 与 tasks/02-ocspeed-install.md 的 md5 表对账（LF 归一化后）
EXPECT_MD5 = {
    "speedswitch.sh": "9544e0b38b29bb146690535466913f00",
    "ocspeed.lua":    "ea0fc06440268c99a91f705887889228",
    "ocspeed.htm":    "0f512a333d139a4b58945bf7a2c67397",
    "nodetest.htm":   "e857abd6577c4094f1bec743745193ec",
    "config.ocspeed": "22ac5f0fe2c6ea32bdd7a2fabc86f384",
}
# data.tar.gz 里的路径与权限（唯一权威表）
DATA_FILES = [
    ("speedswitch.sh", "/usr/libexec/openclash-helper/speedswitch.sh", 0o755),
    ("ocspeed.lua",    "/usr/lib/lua/luci/controller/ocspeed.lua",     0o644),
    ("ocspeed.htm",    "/usr/lib/lua/luci/view/ocspeed.htm",           0o644),
    ("nodetest.htm",   "/usr/lib/lua/luci/view/nodetest.htm",          0o644),
    ("config.ocspeed", "/etc/config/ocspeed",                          0o644),
]
MTIME = int(time.time())

def load_lf(name):
    raw = open(os.path.join(SRC, name), "rb").read()
    if b"\r\n" in raw:
        print("[warn] %s 含 CRLF，打包时归一化为 LF" % name)
    return raw.replace(b"\r\n", b"\n")

def md5(b): return hashlib.md5(b).hexdigest()

# ---------- 1. 校验 ----------
content = {}
for name, expect in EXPECT_MD5.items():
    b = load_lf(name)
    content[name] = b
    got = md5(b)
    flag = "OK " if got == expect else "*** MISMATCH"
    print("%s %-16s md5=%s (期望 %s)" % (flag, name, got, expect))
    if got != expect:
        print("   !! 与技能档案不符，中止打包，先核对源文件")
        sys.exit(1)

# ---------- 2. control ----------
CONTROL = """Package: luci-app-ocspeed
Version: 3.5-1
Depends: luci-app-openclash
Architecture: all
Maintainer: kp <local>
Section: luci
Description: OpenClash auto speedtest & node-switch LuCI plugin (self-built, v3.4)
 LuCI page: Services -> OpenClash -> ocspeed.
 Enable cron via: /usr/libexec/openclash-helper/speedswitch.sh enable
Installed-Size: %d
""" % sum(len(v) for v in content.values())

CONFFILES = "/etc/config/ocspeed\n"

# ⚠️ 没有 ACL 文件 → 新版客户端 LuCI（21.02+）会把菜单项隐藏（2026-09-24 实测）
ACL_JSON = """{
\t"luci-app-ocspeed": {
\t\t"description": "Grant UCI access for luci-app-ocspeed",
\t\t"read": { "uci": [ "ocspeed" ] },
\t\t"write": { "uci": [ "ocspeed" ] }
\t}
}
"""

POSTINST = """#!/bin/sh
mkdir -p /etc/openclash-helper /tmp/ocspeed
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.* 2>/dev/null
rm -rf /tmp/luci-modulecache 2>/dev/null
/etc/init.d/rpcd restart >/dev/null 2>&1    # 重载 acl.d，否则菜单被 ACL 过滤隐藏
[ -x /etc/init.d/uhttpd ] && /etc/init.d/uhttpd restart >/dev/null 2>&1
echo
echo "ocspeed v3.5 installed (OpenClash native color scheme)."
echo "  1) LuCI -> Services -> OpenClash -> ocspeed  (set target group)"
echo "  2) /usr/libexec/openclash-helper/speedswitch.sh enable   # build cron"
echo "  3) logs: /var/log/ocspeed.log"
echo "  Note: LuCI needs re-login to refresh session ACLs."
exit 0
"""

POSTRM = """#!/bin/sh
rm -f /usr/share/rpcd/acl.d/luci-app-ocspeed.json
rm -f /tmp/luci-indexcache /tmp/luci-indexcache.* 2>/dev/null
rm -rf /tmp/luci-modulecache 2>/dev/null
/etc/init.d/rpcd restart >/dev/null 2>&1
[ -x /etc/init.d/uhttpd ] && /etc/init.d/uhttpd restart >/dev/null 2>&1
echo "ocspeed removed. data dir /etc/openclash-helper kept."
exit 0
"""

# ---------- 3. tar.gz 打包工具 ----------
def add_bytes(tar, arcname, data, mode):
    ti = tarfile.TarInfo(arcname)
    ti.size = len(data); ti.mtime = MTIME; ti.mode = mode
    ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
    ti.type = tarfile.REGTYPE
    tar.addfile(ti, io.BytesIO(data))

def add_dir(tar, arcname):
    ti = tarfile.TarInfo(arcname)
    ti.type = tarfile.DIRTYPE; ti.mode = 0o755
    ti.mtime = MTIME; ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
    tar.addfile(ti)

def make_targz(members):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz", format=tarfile.GNU_FORMAT) as t:
        for arcname, data, mode in members:
            if arcname.endswith("/"):          # 目录条目：必须 DIRTYPE，否则会变成空文件
                ti = tarfile.TarInfo(arcname)
                ti.type = tarfile.DIRTYPE; ti.mode = mode
                ti.mtime = MTIME; ti.uid = ti.gid = 0; ti.uname = ti.gname = ""
                t.addfile(ti)
            else:
                add_bytes(t, arcname, data, mode)
    return buf.getvalue()

ctrl_members = [
    ("./control",   CONTROL.encode(),   0o644),
    ("./conffiles", CONFFILES.encode(), 0o644),
    ("./postinst",  POSTINST.encode(),  0o755),
    ("./postrm",    POSTRM.encode(),    0o755),
]
# 父目录条目必须显式给出（目标设备不一定有 /usr/libexec/openclash-helper/）
DIRS = ["./usr/", "./usr/lib/", "./usr/libexec/", "./usr/lib/lua/", "./usr/lib/lua/luci/",
        "./usr/lib/lua/luci/controller/", "./usr/lib/lua/luci/view/",
        "./usr/libexec/openclash-helper/", "./etc/",
        "./usr/share/", "./usr/share/rpcd/", "./usr/share/rpcd/acl.d/"]
data_members = [(d, b"", 0o755) for d in DIRS]
for src_name, dest, mode in DATA_FILES:
    data_members.append(("." + dest, content[src_name], mode))
data_members.append(("./usr/share/rpcd/acl.d/luci-app-ocspeed.json", ACL_JSON.encode(), 0o644))

control_tgz = make_targz(ctrl_members)
data_tgz = make_targz(data_members)

# ---------- 4. 外层 tar.gz（现代 OpenWrt ipk 格式：tar 包 debian-binary/control.tar.gz/data.tar.gz） ----------
def ar_member(name, data):
    hdr = "{:<16}{:<12}{:<6}{:<6}{:<8}{:<10}".format(
        name if name.endswith("/") else name + "/",
        str(MTIME), "0", "0", "100644", str(len(data)))
    hdr += "`\n"                       # 60 字节头 + magic
    assert len(hdr) == 60, len(hdr)
    out = hdr.encode() + data
    if len(data) % 2: out += b"\n"     # 2 字节对齐
    return out

outer = io.BytesIO()
with tarfile.open(fileobj=outer, mode="w:gz", format=tarfile.GNU_FORMAT) as t:
    add_bytes(t, "./debian-binary", b"2.0\n", 0o644)
    add_bytes(t, "./control.tar.gz", control_tgz, 0o644)
    add_bytes(t, "./data.tar.gz", data_tgz, 0o644)

with open(OUT, "wb") as f:
    f.write(outer.getvalue())
print()
print("打包完成: %s (%.1f KB)" % (OUT, len(outer.getvalue())/1024))
