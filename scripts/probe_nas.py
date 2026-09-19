#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""NAS 升级前体检: CPU/USB/块设备/内核模块/挂载/温度/NAS 软件源/内存 (只读)"""
import os, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, 'root', PW, timeout=12)


def sh(cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    return (o.read().decode('utf-8', 'replace') + e.read().decode('utf-8', 'replace')).strip()


sections = [
    ('CPU',        'grep -E "processor|model name" /proc/cpuinfo | sort -u'),
    ('USB',        'lsusb 2>/dev/null || echo no-lsusb'),
    ('块设备',      'ls /dev/sd* 2>/dev/null || echo "(无 sdX — usb-storage 未装或无盘)"'),
    ('存储内核模块', 'lsmod | grep -E "usb_storage|uas|xhci" | awk "{print \\$1}"'),
    ('挂载',       'df -h | grep -vE "tmpfs" '),
    ('温度°C',     'awk "{printf \\"%d\\", \\$1/1000}" /sys/class/thermal/thermal_zone0/temp'),
    ('NAS 软件源',  'opkg list | grep -iE "^(ksmbd-server|luci-app-ksmbd|luci-app-samba4|aria2|minidlna|nfs-kernel-server |ntfs-3g |block-mount|kmod-usb-storage|kmod-fs-ext4)" | sort -u | cut -d" " -f1,2'),
    ('已装相关',    'opkg list-installed | grep -E "ntfs|vfat|fuse|ksmbd|samba|aria2|minidlna" '),
    ('内存 KB',    'free -k | grep Mem'),
]
for title, cmd in sections:
    print('== %s ==' % title)
    print(sh(cmd))
    print()
c.close()
