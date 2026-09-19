#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""识别路由器上的 Docker 面板：谁在听哪个端口、跑的是什么容器、返回什么页面（只读）"""
import os
import re
import sys

import paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')
if not PW:
    sys.exit('未设置 ROUTER_PW')

CAND = [5001, 9000, 9443, 8000, 3000, 8080]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, USER, PW, timeout=15)


def run(cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    out = o.read().decode('utf-8', 'replace')
    err = e.read().decode('utf-8', 'replace')
    return out, err


print('=' * 70)
print('1) 候选端口归属（netstat）')
print('=' * 70)
pat = '|'.join(':%d ' % p for p in CAND) + '|:%d$' % CAND[0]
out, _ = run("netstat -lnpt 2>/dev/null | grep -E ':(5001|9000|9443|8000|3000|8080)\\b'")
print(out or '(无匹配)')

print('=' * 70)
print('2) docker ps -a（全部容器）+ docker info')
print('=' * 70)
out, err = run("docker ps -a --format '{{.Names}} | {{.Status}} | {{.Ports}} | {{.Image}}'")
print(out or '(无容器)')
if err.strip():
    print('[stderr]', err[:300])

print('-' * 70)
out, _ = run("docker images --format '{{.Repository}}:{{.Tag}} {{.Size}}' | head -20")
print('镜像清单:\n' + (out or '(空)'))

print('=' * 70)
print('3) 各端口 HTTP 指纹（从路由器本机探测）')
print('=' * 70)
for p in CAND:
    scheme = 'https' if p == 9443 else 'http'
    cmd = ("curl -sk -m 8 -D - -o /tmp/_p.html %s://127.0.0.1:%d/ 2>/dev/null | head -8; "
           "echo '  --- title ---'; grep -o '<title>[^<]*</title>' /tmp/_p.html 2>/dev/null | head -2; "
           "echo '  --- 首页片段 ---'; head -c 260 /tmp/_p.html 2>/dev/null; echo") % (scheme, p)
    out, _ = run(cmd, 30)
    print('\n[端口 %d]\n%s' % (p, out.rstrip() or '(无响应)'))
run('rm -f /tmp/_p.html')

print('=' * 70)
print('4) 残留的 docker run 进程 / 相关命令行')
print('=' * 70)
out, _ = run("ps w 2>/dev/null | grep -E '[d]ocker|[p]ortainer|[d]ockge' | head -20")
print(out or '(无)')

print('=' * 70)
print('5) /opt/docker 布局 + stacks')
print('=' * 70)
out, _ = run("ls -la /opt/docker/ 2>/dev/null; echo '--- stacks ---'; ls -la /opt/docker/stacks/ 2>/dev/null; "
             "echo '--- data ---'; ls -la /opt/docker/data/ 2>/dev/null | head -15")
print(out or '(无)')

print('=' * 70)
print('6) 开机自启 / 计划任务里有没有拉起面板')
print('=' * 70)
out, _ = run("cat /etc/rc.local 2>/dev/null; echo '--- crontab ---'; crontab -l 2>/dev/null; "
             "echo '--- init.d ---'; ls /etc/init.d/ 2>/dev/null | tr '\\n' ' '")
print(out or '(无)')

c.close()
print('\n识别完成（只读）')
