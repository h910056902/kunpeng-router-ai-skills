#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""查看 /etc/kp_store/installed.list 当前内容 (只读)"""
import os, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, 'root', PW, timeout=12)
_, o, e = c.exec_command("cat /etc/kp_store/installed.list", timeout=20)
print(o.read().decode('utf-8', 'replace'))
err = e.read().decode('utf-8', 'replace')
if err.strip():
    print('STDERR:', err)
c.close()
