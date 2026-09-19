#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""探测: 路由器内存余量 + 各候选去广告规则从路由器侧的可达性/行数 (只读)"""
import os, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')

URLS = {
    'AWAvenue-AdGuard(秋风)': 'https://raw.githubusercontent.com/AWAvenue/Adblock-Rule/main/AWAvenue-Ads-Rule-AdGuard.txt',
    'AWAvenue-ABP(秋风)':     'https://raw.githubusercontent.com/AWAvenue/Adblock-Rule/main/AWAvenue-Ads-Rule.txt',
    'Hagezi-Pro':             'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/pro.txt',
    'Hagezi-Pro++':           'https://raw.githubusercontent.com/hagezi/dns-blocklists/main/adblock/proplus.txt',
    'ADgk(开屏/视频APP)':      'https://raw.githubusercontent.com/banbendalao/ADgk/master/ADgk.txt',
    'halflife综合':            'https://raw.githubusercontent.com/o0HalfLife0o/list/master/ad.txt',
    'OISD-big':               'https://big.oisd.nl',
    'OISD-medium':            'https://medium.oisd.nl',
    '1Hosts-Lite':            'https://badmojr.github.io/1Hosts/Lite/ad.txt',
    '乘风-通用(gitee)':        'https://gitee.com/xinggsf/Adblock-Rule/raw/master/rule.txt',
    '乘风-视频(gitee)':        'https://gitee.com/xinggsf/Adblock-Rule/raw/master/mv.txt',
}

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, 'root', PW, timeout=12)

_, o, _ = c.exec_command('free -k | grep Mem; echo ---; uptime', timeout=15)
print(o.read().decode())

for name, url in URLS.items():
    cmd = ("curl -sL --max-time 25 -o /tmp/probe.txt -w \"%{http_code} %{size_download}\" '" + url +
           "' 2>/dev/null; echo \" lines=$(wc -l < /tmp/probe.txt)\"")
    _, o, _ = c.exec_command(cmd, timeout=40)
    print('%-24s -> %s' % (name, ' '.join(o.read().decode().split())))

c.exec_command('rm -f /tmp/probe.txt')
c.close()
