#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
与社区脚本「NRadio 官方系统插件安装助手」(maye, nradio.mayebano.shop V3.x) 的兼容适配器。

该脚本会修改 /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua 和
appcenter.htm（备份到 /root/nradio-plugin-fix 后做增量/整替），可能冲掉
我们自己的商店补丁。用法两步：

  python adapt_maye_assistant.py snapshot   # 跑 maye 脚本【之前】拍基线
  python adapt_maye_assistant.py check      # 跑完【之后】检测补丁丢失情况
  python adapt_maye_assistant.py check --fix  # 丢失的补丁自动重放本地 patches 脚本

检测的补丁指纹 = 我们全部商店增强的关键 marker。
"""
import os, sys, json, hashlib, time, subprocess, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')
LOCAL_PATCHES = os.environ.get(
    'KP_PATCHES_DIR',
    'C:/Users/91005/Desktop/鲲鹏无限路由器美化/patches')
BASELINE_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'maye-baseline.json')
BASELINE_ROUTER = '/etc/kp_store/patch-baseline.json'

MAYE_STATE_DIR = '/root/.nradio-plugin-menu'      # maye 脚本安装后存在
MAYE_BACKUP_DIR = '/root/nradio-plugin-fix'

# 文件 → [(marker, 补丁名, 用于重放的本地脚本), ...]
MARKERS = {
    '/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua': [
        ('nradio_appcenter_extra_installed_merge', '已安装注册表合并',
         'patch_extra_installed.py'),
        ('nradio_appcenter_extra_action',           '卸载/Docker 分发',
         'patch_extra_installed.py'),
        ('_kp_installed_registry',                  '注册表读取函数',
         'patch_extra_installed.py'),
        ('_online_install_percent',                 '安装百分比',
         'patch_install_percent.py'),
        ('&& kp-store-register',                    '安装后自动注册',
         'patch_extra_installed.py'),
    ],
    '/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm': [
        ('aurora_open_app',                         '打开按钮助手',
         'patch_online_ui.py'),
    ],
}


def connect():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, 'root', PW, timeout=12)
    return c


def read_file(c, path):
    try:
        with c.open_sftp().open(path, 'r') as f:
            return f.read().decode('utf-8', 'replace')
    except IOError:
        return None


def snapshot():
    c = connect()
    base = {'time': time.strftime('%Y-%m-%d %H:%M:%S'), 'files': {}}
    for path, marks in MARKERS.items():
        body = read_file(c, path)
        base['files'][path] = {
            'sha256': hashlib.sha256(body.encode()).hexdigest() if body else None,
            'markers': {m: (body is not None and key in body)
                        for key, m, _ in marks},
        }
    maye_installed = c.exec_command(
        '[ -d %s ] && echo yes || echo no' % MAYE_STATE_DIR)[1].read().decode().strip()
    base['maye_installed_at_snapshot'] = maye_installed == 'yes'
    c.close()
    json.dump(base, open(BASELINE_LOCAL, 'w'), ensure_ascii=False, indent=2)
    # 基线同时存路由器一份，防止换电脑后丢
    c = connect()
    with c.open_sftp().open(BASELINE_ROUTER, 'w') as f:
        f.write(json.dumps(base, ensure_ascii=False))
    c.close()
    print('基线已保存:', BASELINE_LOCAL, '和', BASELINE_ROUTER)
    for path, info in base['files'].items():
        lost = [m for m, ok in info['markers'].items() if not ok]
        print('%s: %s' % (path.split("/")[-1],
                          '全部指纹在位' if not lost else '缺失! ' + str(lost)))


def check(fix=False):
    if not os.path.exists(BASELINE_LOCAL):
        print('! 没有基线, 先跑: python adapt_maye_assistant.py snapshot')
        return
    base = json.load(open(BASELINE_LOCAL))
    c = connect()
    print('== maye 脚本状态 ==')
    maye = c.exec_command('[ -d %s ] && echo yes || echo no' % MAYE_STATE_DIR
                          )[1].read().decode().strip() == 'yes'
    print('maye 助手 %s (备份目录 %s)' % (
        '已安装' if maye else '未安装', MAYE_BACKUP_DIR))
    missing = []
    for path, marks in MARKERS.items():
        body = read_file(c, path)
        if body is None:
            print('!! 文件不存在: %s' % path)
            missing.extend(marks)
            continue
        for key, name, script in marks:
            if key not in body:
                print('✗ 丢失: [%s] %s (%s)' % (path.split("/")[-1], name, script))
                missing.append((key, name, script))
            else:
                print('✓ 在位: [%s] %s' % (path.split("/")[-1], name))
    if not missing:
        print('\n结论: 我们的全部补丁完好, 无需处理。')
        c.close()
        return
    print('\n共 %d 个补丁指纹丢失。' % len(missing))
    if not fix:
        print('自动修复请加参数: python adapt_maye_assistant.py check --fix')
        print('⚠ 注意: 不要在 maye 菜单里安装它的 AdGuardHome/mosdns 插件,')
        print('  那是 native 版(端口554/uci配置), 会与我们的 Docker 版 AGH(:53) 打架。')
        c.close()
        return
    # 自动重放: 各 patches 脚本自身幂等(marker 检查后才插入)
    to_run = sorted({s for _, _, s in missing})
    for script in to_run:
        p = os.path.join(LOCAL_PATCHES, script)
        if not os.path.exists(p):
            print('! 找不到重放脚本: %s' % p)
            continue
        print('>> 重放 %s ...' % script)
        r = subprocess.run([sys.executable, p], cwd=LOCAL_PATCHES,
                           capture_output=True, text=True)
        tail = (r.stdout + r.stderr).strip().splitlines()[-3:]
        print('   ' + ' | '.join(tail))
    c.close()
    print('\n重放完成, 再跑一次 check 复核: python adapt_maye_assistant.py check')


if __name__ == '__main__':
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    if mode == 'snapshot':
        snapshot()
    elif mode == 'check':
        check(fix='--fix' in sys.argv)
    else:
        print(__doc__)
