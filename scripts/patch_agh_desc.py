#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
优化已安装注册表中 AdGuard Home 的简介 (installed.list 第 8 字段 des):
  旧: AdGuard Home 去广告 DNS（Docker host 模式；管理页 :3000，全网 DNS :53）
  新: 更完整、面向用户的介绍 (含规则量/管理页/端口/账号提示)
先时间戳备份 installed.list, 再原位改写该行, 其余行不动。
"""
import os, time, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')
REG = '/etc/kp_store/installed.list'

NEW_DES = ('DNS 级全网去广告：拦截国内外广告、 trackers 与恶意域名，'
           '内置 49 万+ 条规则（AdRules / anti-AD / EasyList China 等），'
           '支持自定义过滤、查询日志与设备级管控。'
           '管理页 :3000（账号见 AGH 配置），全网 DNS 走 :53，'
           '上游经 OpenClash 分流，容器为 Docker host 模式。')


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, 'root', PW, timeout=12)
    sftp = c.open_sftp()

    bak = REG + '.bak-desc-' + time.strftime('%Y%m%d_%H%M%S')
    c.exec_command('cp %s %s' % (REG, bak))
    time.sleep(0.5)
    print('备份:', bak)

    with sftp.open(REG, 'r') as f:
        raw = f.read().decode('utf-8')

    out_lines = []
    changed = False
    for line in raw.splitlines():
        f = line.split('|')
        if len(f) >= 8 and f[2] == 'adguardhome':
            print('旧简介:', f[7])
            f[7] = NEW_DES
            # 保持行尾结构与原文件一致: 非末行带换行由 join 处理
            out_lines.append('|'.join(f))
            changed = True
            print('新简介:', f[7])
        else:
            out_lines.append(line)

    if not changed:
        print('! 未找到 adguardhome 行, 未做修改')
    else:
        with sftp.open(REG, 'w') as f:
            f.write('\n'.join(out_lines) + '\n')
        print('installed.list 已更新')
        # 立即验证
        _, o, _ = c.exec_command("grep adguardhome %s" % REG, timeout=15)
        print('验证:', o.read().decode('utf-8', 'replace').strip())

    sftp.close()
    c.close()


if __name__ == '__main__':
    main()
