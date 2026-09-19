# -*- coding: utf-8 -*-
"""鲲鹏 C2000 U（C2000-798 / HC-WT9500 / MT7987 / 992MB / TF 卡）Docker 一键实装。

2026-09-11 实机验证通过。相对老 C2000 Max 的差异与本脚本的关键点：
  1. 出厂源全指向 21.02-SNAPSHOT（上游已 404）→ 必须换阿里云 21.02.7
  2. 本机 **无 sftp-server** → 传文件走 heredoc（文本）/ printf 八进制（二进制），见 rtr_lib.py
  3. dockerd 的 kmod 依赖无源可装 → 造 6 个 stub 空 ipk
  4. **opkg 会被 feed 同名包截胡** → 装 stub 前临时移走 /var/opkg-lists
  5. **UCI 生成器不支持 storage-driver / bridge** → 唯一正路是 alt_config_file 指向自写 daemon.json
  6. `/mnt/storage/data` 是**裸 f2fs 挂载**（不在 overlayfs 之上）→ **overlay2 可用**（老 Max 只能 vfs）

用法：
    export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<设备密码>
    python setup_docker_c2000u.py            # 全流程
    python setup_docker_c2000u.py --only 1   # 只跑第 N 步

⚠️ data-root 放在 /mnt/storage/data/docker（厂商数据分区，恢复出厂可能被清空）。
   想改回 /opt/docker 则只能退回 vfs —— 两者是绑定的，详见 references/c2000u-docker.md
"""
import io
import gzip
import json
import os
import sys
import tarfile
import time
import hashlib

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from rtr_lib import Rtr  # noqa: E402

ARCH = 'aarch64_cortex-a53'
KVER = '5.4.281'
ALIYUN = 'https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/' + ARCH
DATA_ROOT = '/mnt/storage/data/docker'
STUB_DIR = '/tmp/dockerstubs'

NEW_DISTFEEDS = (
    "src/gz openwrt_base {a}/base\n"
    "src/gz openwrt_packages {a}/packages\n"
    "src/gz openwrt_routing {a}/routing\n"
).format(a=ALIYUN)

# 与 feed 同名的包必须先屏蔽 feed 再装，否则 opkg 用 feed 候选（依赖对它不成立）
STUBS = [
    ('kmod-veth',        KVER + '-1', 'kernel', 'STUB - CONFIG_VETH unset; only satisfies dockerd dep'),
    ('kmod-br-netfilter', KVER + '-1', 'kernel', 'STUB - CONFIG_BRIDGE_NETFILTER is built-in; only satisfies dep'),
    ('kmod-ikconfig',    KVER + '-1', 'kernel', 'STUB - only satisfies dep'),
    ('kmod-nf-ipvs',     KVER + '-1', 'kernel', 'STUB - IPVS unused (no swarm); only satisfies dep'),
    ('btrfs-progs',      '5.11-1',    'utils',  'STUB - btrfs driver unused; only satisfies dep'),
    ('libdevmapper',     '2.03.16-1', 'libs',   'STUB - devicemapper driver unused; only satisfies dep'),
]

REAL_PKGS = ['libseccomp', 'libnetwork', 'tini', 'runc', 'containerd', 'dockerd', 'docker']

DAEMON_JSON = {
    "data-root": DATA_ROOT,
    "storage-driver": "overlay2",
    "bridge": "none",
    "iptables": False,
    "log-level": "warn",
    "log-driver": "json-file",
    "log-opts": {"max-size": "10m", "max-file": "3"},
    "registry-mirrors": [
        "https://docker.1ms.run",
        "https://docker.m.daocloud.io",
    ],
}


# ---------------- 老式 ipk 构造（tar.gz 嵌套，**不能**用 PAX） ----------------
def _gz(b):
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode='wb', mtime=0) as g:
        g.write(b)
    return bio.getvalue()


def _tar_gz(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.GNU_FORMAT) as t:
        for name, data, typ in entries:
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            ti.type = typ
            ti.uname = 'root'
            ti.gname = 'root'
            t.addfile(ti, io.BytesIO(data))
    return _gz(buf.getvalue())


def make_stub(pkg, ver, section, desc):
    control = ("Package: %s\nVersion: %s\nArchitecture: %s\n"
               "Priority: optional\nMaintainer: kp-stub <stub@local>\nSection: %s\n"
               "Installed-Size: 1\nDescription: %s\n"
               % (pkg, ver, ARCH, section, desc)).encode()
    ctargz = _tar_gz([('./', b'', tarfile.DIRTYPE), ('./control', control, tarfile.REGTYPE)])
    dtargz = _tar_gz([('./', b'', tarfile.DIRTYPE)])
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.GNU_FORMAT) as t:
        for name, data in (('./debian-binary', b'2.0\n'),
                           ('./control.tar.gz', ctargz),
                           ('./data.tar.gz', dtargz)):
            ti = tarfile.TarInfo(name)
            ti.size = len(data)
            ti.mtime = 0
            ti.mode = 0o644
            ti.uname = 'root'
            ti.gname = 'root'
            t.addfile(ti, io.BytesIO(data))
    return _gz(buf.getvalue())


# ---------------- 各步骤 ----------------
def step1_sources(r):
    r.p("\n===== [1/6] 备份出厂源并换阿里云 21.02.7 =====")
    cur = r.run("cat /etc/opkg/distfeeds.conf")
    if '21.02-SNAPSHOT' not in cur and 'mirrors.aliyun.com' in cur:
        r.p("  已是阿里云源，跳过换源")
    else:
        ts = r.run("date +%Y%m%d_%H%M%S")
        bak = "/etc/opkg/distfeeds.conf.bak-c2000u-%s" % ts
        r.p("  备份 → %s" % r.run("cp -f /etc/opkg/distfeeds.conf %s && echo OK:%s" % (bak, bak)))
        ok, md5 = r.put_text_verified("/etc/opkg/distfeeds.conf", NEW_DISTFEEDS)
        r.p("  写入新源 ok=%s" % ok)
    t0 = time.time()
    r.p(r.run("opkg update 2>&1 | tail -8", t=300))
    r.p("  opkg update 用时 %.1fs" % (time.time() - t0))


def step2_stubs(r):
    r.p("\n===== [2/6] 造并安装 6 个 stub 空 ipk =====")
    r.p(r.run("mkdir -p %s && echo ok" % STUB_DIR))
    paths = []
    for name, ver, sec, desc in STUBS:
        data = make_stub(name, ver, sec, desc)
        path = "%s/%s_%s_%s.ipk" % (STUB_DIR, name, ver, ARCH)
        ok, md5 = r.put_bin(path, data)
        r.p("  %-20s %4dB transfer=%s" % (name, len(data), "OK" if ok else "FAIL"))
        if not ok:
            raise SystemExit("传输失败: " + name)
        paths.append((name, path))

    # 关键：屏蔽 feed，避免同名包被 feed 候选截胡
    r.p("  临时移走 /var/opkg-lists（规避 feed 同名包截胡）")
    r.run("if [ -d /var/opkg-lists ]; then mv /var/opkg-lists /var/opkg-lists.off; fi")
    for name, path in paths:
        out = r.run("opkg install --force-reinstall %s 2>&1 | tail -2" % path, t=180)
        r.p("  %-20s %s" % (name, out.replace('\n', ' | ')))
    r.run("rm -rf /var/opkg-lists; if [ -d /var/opkg-lists.off ]; then mv /var/opkg-lists.off /var/opkg-lists; fi")
    miss = [n for n, _ in paths if not r.run("opkg list-installed | grep -E '^%s '" % n)]
    if miss:
        raise SystemExit("stub 未登记: %s" % miss)
    r.p("  6/6 stub 全部登记")


def step3_install(r):
    r.p("\n===== [3/6] 安装 docker 全家 =====")
    for pkg in REAL_PKGS:
        if r.run("opkg list-installed | grep -cE '^%s '" % pkg).strip() not in ('', '0'):
            r.p("  %-12s 已安装，跳过" % pkg)
            continue
        t0 = time.time()
        r.run("rm -f /var/lock/opkg.lock; opkg install %s > /tmp/opkg_%s.log 2>&1" % (pkg, pkg), t=900)
        got = r.run("opkg list-installed | grep -E '^%s '" % pkg)
        r.p("  %-12s %6.1fs  %s" % (pkg, time.time() - t0, got if got else "!!! 失败，看 /tmp/opkg_%s.log" % pkg))
        if not got:
            raise SystemExit("安装失败: " + pkg)
    r.p(r.run("dockerd --version; docker --version"))


def step4_config(r):
    r.p("\n===== [4/6] 配置 daemon.json 与 UCI =====")
    cfg = json.dumps(DAEMON_JSON, indent=2, ensure_ascii=False) + "\n"
    r.p(r.run("mkdir -p %s" % DATA_ROOT))
    ok, md5 = r.put_text_verified("/etc/docker/daemon.json", cfg)
    r.p("  daemon.json ok=%s" % ok)
    # 关键：只有 alt_config_file 才能让 storage-driver / bridge 生效
    r.p(r.run("uci set dockerd.globals.alt_config_file='/etc/docker/daemon.json'; uci commit dockerd && echo UCI_OK"))
    r.safe("/etc/init.d/dockerd restart >/dev/null 2>&1; echo RESTARTED", t=180)
    for _ in range(12):
        time.sleep(3)
        if 'UP' in r.run("test -S /var/run/docker.sock && echo UP || echo down"):
            break
    r.p(r.run("ls -l /tmp/dockerd/daemon.json"))
    r.p(r.run("docker info 2>&1 | grep -iE 'storage driver|backing filesystem|docker root dir|registry mirrors' -A2 | head -14", t=180))


def step5_enable(r):
    r.p("\n===== [5/6] 开机自启 =====")
    r.p(r.run("/etc/init.d/dockerd enable 2>&1; ls -l /etc/rc.d/ | grep -i docker"))


def step6_smoke(r, image='alpine:3.19'):
    r.p("\n===== [6/6] 冒烟测试（后台化拉取，遵守铁律）=====")
    r.run("rm -f /tmp/pull.log; nohup docker pull %s > /tmp/pull.log 2>&1 & echo STARTED" % image, t=60)
    for _ in range(50):
        time.sleep(8)
        if 'Status:' in r.run("tail -3 /tmp/pull.log 2>/dev/null"):
            break
    r.p(r.run("tail -6 /tmp/pull.log"))
    r.p(r.run("docker images"))
    r.p("-- host 网络跑容器 --")
    r.p(r.run("docker run --rm --network=host %s sh -c 'echo CONTAINER_OK; cat /etc/os-release|head -1' " % image, t=300))
    r.p("-- 后台生命周期 --")
    r.p(r.run("docker run -d --name kp_smoke --network=host %s sleep 60 >/dev/null 2>&1; sleep 2; "
              "docker ps --format '{{.Names}} {{.Status}}'; docker stop kp_smoke >/dev/null 2>&1; "
              "docker rm kp_smoke >/dev/null 2>&1; echo LIFE_OK", t=300))
    r.p(r.run("docker system df"))
    r.run("rm -rf %s /tmp/pull.log" % STUB_DIR)


def main():
    only = None
    if '--only' in sys.argv:
        only = int(sys.argv[sys.argv.index('--only') + 1])
    steps = [(1, step1_sources), (2, step2_stubs), (3, step3_install),
             (4, step4_config), (5, step5_enable), (6, step6_smoke)]
    r = Rtr()
    try:
        r.p("### 目标设备 %s  内存: %s" % (r.host, r.mem().replace('\n', ' / ')))
        for n, fn in steps:
            if only and n != only:
                continue
            fn(r)
        r.p("\n### 全部完成。最终状态")
        r.p(r.run("docker info 2>&1 | grep -iE 'server version|storage driver|docker root dir'"))
        r.p(r.run("free -k | head -2"))
    finally:
        r.close()
        r.save(os.path.join(os.path.dirname(os.path.abspath(__file__)), "setup_docker_c2000u.log"))


if __name__ == '__main__':
    main()
