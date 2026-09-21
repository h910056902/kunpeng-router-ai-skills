#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
与社区脚本「NRadio 官方系统插件安装助手」(maye V3.x) 的兼容适配器。
上游仓库: https://github.com/561410590/ssh-nradio-plugin-installer
社区镜像页: https://nradio.mayebano.shop/

该脚本会修改 /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua 和
appcenter.htm（直接整替/增量改写，**不产生任何备份** —— 上游 backup_file() 是
空实现，见 MAYE_BACKUP_DIR 处注释），可能冲掉我们自己的商店补丁。用法两步：

  python adapt_maye_assistant.py snapshot   # 跑 maye 脚本【之前】拍基线
  python adapt_maye_assistant.py check      # 跑完【之后】检测补丁丢失情况
  python adapt_maye_assistant.py check --fix  # 丢失的补丁自动重放本地 patches 脚本

检测的补丁指纹 = 我们全部商店增强的关键 marker。
"""
import os, sys, json, hashlib, time, subprocess, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')
# 默认取「本脚本所在 scripts/ 的上级目录」下的 patches/，绝不硬编码本机绝对路径
# （本文件会同步进公开仓库）。需要指向别处时用环境变量 KP_PATCHES_DIR 覆盖。
LOCAL_PATCHES = os.environ.get(
    'KP_PATCHES_DIR',
    os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                 'patches'))
BASELINE_LOCAL = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                              'maye-baseline.json')
BASELINE_ROUTER = '/etc/kp_store/patch-baseline.json'

MAYE_STATE_DIR = '/root/.nradio-plugin-menu'      # 跑过 maye（接受免责声明）就会创建
MAYE_PATCH_MARKER = 'Design By MaYe'              # 它给 appcenter.htm 加的产权标识
MAYE_PATCH_TARGET = '/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm'
# ⚠️ 死路径（保留仅为说明上游意图）：上游 backup_file() 是空实现（return 0，注释称
#    「所有安装、修复和页面操作直接写入，不在路由器上生成持久备份」），BACKUP_DIR
#    只在脚本里定义、全脚本没有任何 mkdir/cp 落到它上面。实测该目录**从不创建**、
#    也**从不产生任何备份**（设备上 `ls -ld /root/nradio-plugin-fix` → No such file）。
MAYE_BACKUP_DIR = '/root/nradio-plugin-fix'


def maye_footprint(c):
    """返回 dict(state_dir, patched, note) —— 两个**互不相同**的事实。

    为什么必须分开：`/root/.nradio-plugin-menu/` 在**输入 y 接受免责声明**时就创建，
    跟「装没装插件」无关（2026-09-20 真机实测：只进了 5 个子菜单、一个功能项都没选，
    该目录就出现了，里面只有 27 字节的 disclaimer flag）。

    旧版把「目录存在」直接当「maye 已安装」→ 用户只要在菜单里按过一次 y，
    适配器就报「已安装」，是误判。真正的装过痕迹是它往 appcenter.htm 注入的产权标识。
    """
    st = c.exec_command('[ -d %s ] && echo yes || echo no' % MAYE_STATE_DIR
                        )[1].read().decode('utf-8', 'replace').strip() == 'yes'
    body = read_file(c, MAYE_PATCH_TARGET)
    patched = body is not None and MAYE_PATCH_MARKER in body
    if patched:
        note = '已装过插件（appcenter.htm 有它的产权标识）'
    elif st:
        note = '跑过但未装插件（只有免责声明 flag，页面未被它改过）'
    else:
        note = '从未跑过'
    return {'state_dir': st, 'patched': patched, 'note': note}


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
    """读远端文本；**文件不存在返回 None**。

    ⚠️ 不能用 open_sftp()：鲲鹏精简固件没有 sftp-server 子系统，paramiko 会直接抛
    `SSHException: EOF during negotiation`（同 rtr_lib.py 开头记录的是同一个坑）。
    固件也没有 base64/openssl/xxd，所以唯一可靠通道是 exec_command + cat。

    存在性判定用 `[ -f ]` 的退出码，而不是去捕获 cat 的报错：busybox 各版本 cat 失败
    时的 stderr 文案不固定（`No such file or directory` / `can't open` 等），按文案匹配
    不可靠；`[ -f ]` 的退出码语义是 POSIX 固定的。
    """
    probe = c.exec_command('[ -f %s ] && echo yes || echo no' % path)[1]
    if probe.read().decode('utf-8', 'replace').strip() != 'yes':
        return None
    return c.exec_command('cat %s' % path)[1].read().decode('utf-8', 'replace')


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
    base['maye_state_dir_exists'] = maye_installed == 'yes'
    # 旧字段名保留（历史基线兼容），语义已改为「状态目录存在」而非「已装插件」
    base['maye_installed_at_snapshot'] = maye_installed == 'yes'
    foot = maye_footprint(c)
    base['maye_footprint'] = foot
    c.close()
    json.dump(base, open(BASELINE_LOCAL, 'w'), ensure_ascii=False, indent=2)
    # 基线同时存路由器一份，防止换电脑后丢
    # ⚠️ 同样不能用 open_sftp()（设备无 sftp-server）；heredoc 前先 mkdir -p —— 该目录
    #    不能假定存在（当前设备上 /etc/kp_store 只有 routes.list，是新商店自己建的）。
    c = connect()
    payload = json.dumps(base, ensure_ascii=False)
    # json.dumps 会把真实换行转义成 \n 两字符，故正文里不可能出现行首 KPEOF，heredoc 安全
    c.exec_command("mkdir -p /etc/kp_store\ncat > %s << 'KPEOF'\n%s\nKPEOF\n"
                   % (BASELINE_ROUTER, payload))[1].read()
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
    foot = maye_footprint(c)
    print('maye 助手: %s' % foot['note'])
    print('   状态目录 %s（只代表「跑过并接受免责声明」，不等于装过插件）'
          % MAYE_STATE_DIR)
    print('⚠ maye 助手【不产生任何备份】：%s 从不创建、从不写入。' % MAYE_BACKUP_DIR)

    print('  改动前请自行备份目标文件, 否则冲掉的补丁只能靠本地 patches 重放。')
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
    if not os.path.isdir(LOCAL_PATCHES):
        # 默认值只是「脚本上级目录下找 patches/」的约定；补丁脚本集与技能包仓库
        # 不是同一棵树（通常放在用户自己的私有项目里），找不到是常态而非故障。
        print('! patches 目录不存在: %s' % LOCAL_PATCHES)
        print('  无法自动重放 —— 上面这些指纹请手动修复, 或把 patches 目录指过来后再跑 --fix:')
        print('    cmd:        set KP_PATCHES_DIR=<你的 patches 目录>')
        print("    PowerShell: $env:KP_PATCHES_DIR='<你的 patches 目录>'")
        print('  说明: 补丁脚本与技能包仓库不是同一棵树, 默认值仅约定为「脚本上级目录下的 patches/」。')
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
