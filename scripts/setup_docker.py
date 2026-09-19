# -*- coding: utf-8 -*-
"""鲲鹏/NRadio 官方系统 Docker 适配一键脚本 (host 网络模式)

背景: 固件 OpenWrt 21.02-SNAPSHOT, 内核 5.4.281 (mediatek/mt7987 定制, HC-WT9303)。
- 内核缺 veth/kmod 系列模块且无匹配源 → 桥接网络不可用, daemon.json 设 bridge=none, 容器一律 --network=host
- dockerd 的 kmod 依赖(kmod-veth 等 6 个)用"stub 空包"满足依赖检查(纯登记, 不含模块)
- eMMC(f2fs) 27G overlay 空闲, 数据目录 /opt/docker, 存储驱动 vfs(overlay2 在此环境不可用)
- 1G swap 落在 eMMC, 兜底内存(整机 493MB)

用法: python setup_docker.py   (可重复执行, 已装则跳过)
"""
import paramiko, os, io, tarfile, gzip, json, time, sys

HOST, USER = '192.168.66.1', 'root'
PW = os.environ.get('ROUTER_PW', '')
ALIYUN_PKGS = 'https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages'
STUBS = ["kmod-veth", "kmod-br-netfilter", "kmod-ikconfig", "kmod-nf-ipvs", "kmod-fs-btrfs", "kmod-dm"]

# ---------- 本地生成老式 ipk(tar.gz 嵌套格式, 注意不是 ar!) ----------
def gz(b):
    bio = io.BytesIO()
    with gzip.GzipFile(fileobj=bio, mode='wb', mtime=0) as g:
        g.write(b)
    return bio.getvalue()

def tar_gz(entries):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.GNU_FORMAT) as t:
        for name, data, typ in entries:
            ti = tarfile.TarInfo(name)
            ti.size = len(data); ti.mtime = 0; ti.mode = 0o644; ti.type = typ
            t.addfile(ti, io.BytesIO(data))
    return gz(buf.getvalue())

def make_stub(pkgname):
    control = ("Package: %s\nVersion: 5.4.281-1\nArchitecture: aarch64_cortex-a53\n"
               "Priority: optional\nMaintainer: kp-stub\nSection: kernel\n"
               "Description: STUB - satisfies dep; module built-in or not required\n" % pkgname).encode()
    ctargz = tar_gz([('./', b'', tarfile.DIRTYPE), ('./control', control, tarfile.REGTYPE)])
    dtargz = tar_gz([('./', b'', tarfile.DIRTYPE)])
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode='w', format=tarfile.GNU_FORMAT) as t:
        for name, data in (('./debian-binary', b'2.0\n'),
                           ('./control.tar.gz', ctargz),
                           ('./data.tar.gz', dtargz)):
            ti = tarfile.TarInfo(name)
            ti.size = len(data); ti.mtime = 0; ti.mode = 0o644
            t.addfile(ti, io.BytesIO(data))
    return gz(buf.getvalue())

def main():
    c = paramiko.SSHClient(); c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PW, timeout=10)
    sftp = c.open_sftp()

    def sh(cmd, t=600):
        _, o, e = c.exec_command(cmd, timeout=t)
        return o.read().decode('utf-8', 'replace').strip()

    # 0) 已装检测
    if 'dockerd - ' in sh('opkg list-installed'):
        print('dockerd 已安装, 跳过安装流程(如需重装先 opkg remove dockerd)')
        sftp.close(); c.close(); return

    # 1) swap 1GB + rc.local 持久化
    if sh('test -f /overlay/.docker-swap && echo yes') != 'yes':
        print(sh('dd if=/dev/zero of=/overlay/.docker-swap bs=1M count=1024 2>&1 | tail -1', t=600))
        sh('chmod 600 /overlay/.docker-swap && mkswap /overlay/.docker-swap >/dev/null 2>&1')
    sh('swapon /overlay/.docker-swap 2>/dev/null')
    rc = sh('cat /etc/rc.local 2>/dev/null')
    if '.docker-swap' not in rc:
        line = 'swapon /overlay/.docker-swap 2>/dev/null'
        newrc = rc.replace('exit 0', line + '\n\nexit 0') if 'exit 0' in rc else rc + '\n' + line + '\nexit 0\n'
        with sftp.open('/etc/rc.local', 'w') as f:
            f.write(newrc)
        print('swap: 已创建并加入 rc.local')
    else:
        print('swap: 已就绪')

    # 2) 添加 packages feed
    feeds = sh('cat /etc/opkg/customfeeds.conf')
    if 'aarch64_cortex-a53/packages' not in feeds:
        with sftp.open('/etc/opkg/customfeeds.conf', 'a') as f:
            f.write('\nsrc/gz owrt21027_pkgs ' + ALIYUN_PKGS + '\n')
        print('feed: 已添加')
    sh('opkg update >/dev/null 2>&1', t=300)

    # 3) 上传并安装 stub
    sh('mkdir -p /tmp/dockerstubs')
    for s in STUBS:
        fn = '/tmp/dockerstubs/%s_5.4.281-1_aarch64_cortex-a53.ipk' % s
        with sftp.open(fn, 'w+b') as f:
            f.write(make_stub(s))
        sh('opkg install %s >/dev/null 2>&1' % fn)
    ok = sum(1 for s in STUBS if sh('opkg list-installed | grep -cE "^%s "' % s) not in ('', '0'))
    print('stub: %d/%d 已登记' % (ok, len(STUBS)))
    if ok < len(STUBS):
        sys.exit('stub 安装不全, 中止')

    # 4) 安装 dockerd + CLI + compose
    sh('rm -f /var/lock/opkg.lock 2>/dev/null')
    print(sh('opkg install dockerd docker docker-compose 2>&1 | grep -viE "python3" | tail -4', t=900))
    for p in ('dockerd', 'docker', 'docker-compose'):
        if sh('opkg list-installed | grep -cE "^%s "' % p) in ('', '0'):
            sys.exit('%s 安装失败' % p)
    print('安装: dockerd/docker/compose 完成')

    # 5) daemon.json: 无 bridge, vfs, /opt/docker, 日志限 10m*3
    cfg = ('{\n  "bridge": "none",\n  "storage-driver": "vfs",\n  "data-root": "/opt/docker",\n'
           '  "log-level": "warn",\n  "log-driver": "json-file",\n'
           '  "log-opts": {"max-size": "10m", "max-file": "3"}\n}\n')
    sh('mkdir -p /etc/docker /opt/docker')
    with sftp.open('/etc/docker/daemon.json', 'w') as f:
        f.write(cfg)

    # 6) 启动 + 自启
    sh('/etc/init.d/dockerd enable >/dev/null 2>&1')
    sh('/etc/init.d/dockerd start >/dev/null 2>&1; sleep 6')
    print('daemon:', sh('docker info 2>/dev/null | grep -E "Server Version|Storage Driver"').replace('\n', ' | '))

    # 7) 商店注册(清单 + 已安装)
    d = json.loads(sh('cat /etc/kp_store/plugins.json'))
    lst = d if isinstance(d, list) else d.get('plugins', d.get('list', []))
    if not any(x.get('id') == 'docker' for x in lst):
        lst.append({"id": "docker", "name": "Docker 容器", "pkg": "dockerd", "source": "opkg",
                    "tags": ["system", "net"],
                    "des": "Docker 引擎 20.10（host 网络模式；docker / docker-compose 可用，镜像数据在 /opt/docker）"})
        with sftp.open('/etc/kp_store/plugins.json', 'w') as f:
            f.write(json.dumps(d if isinstance(d, list) else {'plugins': lst}, ensure_ascii=False, indent=1))
    print('商店注册:', sh('kp-store-register dockerd 2>&1 | tail -1'))
    sh('rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache')

    # 8) 冒烟测试
    print('冒烟测试:', sh('docker run --rm --network=host alpine:latest echo CONTAINER_OK 2>&1 | tail -1', t=560))
    sftp.close(); c.close()

if __name__ == '__main__':
    main()
