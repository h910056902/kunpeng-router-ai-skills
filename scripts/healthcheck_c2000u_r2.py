#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""第二轮针对性补查（严格只读）：
1. 用 ps 复核关键服务真实存活（第一轮 pgrep -c 在 busybox 上误报）
2. 全部无线接口 + SSID/加密配置（确认 2G_OPEN_0 角色）
3. qq.com 用域名重测（第一轮 IP+Host 方式失败）
4. top 看 CPU（load 1.8 的来源）
5. AGH_PORT 钩子变量值
"""
import os
import sys

SP = r"C:\Users\91005\.workbuddy\binaries\python\envs\default\Lib\site-packages"
if SP not in sys.path:
    sys.path.insert(0, SP)
import paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')
OUT = r'C:\Users\91005\WorkBuddy\2026-09-13-22-04-27\router_check_round2.txt'
_buf = []


def w(line=''):
    _buf.append(line)


SECTIONS = [
    ('A. 关键服务真实存活（ps 复核）', r'''
ps w | grep -E '[d]ropbear|[u]httpd|[d]nsmasq|[c]rond|[1]panel|[d]ockerd|[c]ontainerd|[o]dhcpd|[r]pcd|[s]ysntpd|[n]tpd' | awk '{print $1, $2, $3, $4, $5, $6}'
echo "--"
echo "dropbear count : $(ps w | grep -c '[d]ropbear')"
echo "uhttpd count   : $(ps w | grep -c '[u]httpd')"
echo "dnsmasq count  : $(ps w | grep -c '[d]nsmasq')"
echo "crond count    : $(ps w | grep -c '[c]rond')"
echo "1panel count   : $(ps w | grep -c '[1]panel')"
echo "dockerd count  : $(ps w | grep -c '[d]ockerd')"
echo "containerd     : $(ps w | grep -c '[c]ontainerd')"
echo "odhcpd count   : $(ps w | grep -c '[o]dhcpd')"
''', 30),

    ('B. 无线接口全景 + SSID/加密', r'''
iwinfo 2>/dev/null
echo "== wireless uci 配置（ssid/加密/设备）=="
uci show wireless 2>/dev/null | grep -E '\.ssid=|\.encryption=|\.disabled=|\.mode=|\.network=' | head -30
echo "== 访客/OPEN 接口归属 =="
uci show wireless 2>/dev/null | grep -B2 -A2 'OPEN' | head -20
''', 30),

    ('C. QQ / 国内连通性域名重测', r'''
c1=$(curl -s -o /dev/null -m 8 -w '%{http_code}' https://www.qq.com 2>/dev/null)
echo "https://www.qq.com -> $c1"
c2=$(curl -s -o /dev/null -m 8 -w '%{http_code}' http://www.qq.com 2>/dev/null)
echo "http://www.qq.com -> $c2"
c3=$(curl -s -o /dev/null -m 8 -w '%{http_code}' https://www.jd.com 2>/dev/null)
echo "https://www.jd.com -> $c3"
''', 40),

    ('D. CPU 占用 top（load 来源）', r'''
top -b -n1 2>/dev/null | head -18
''', 30),

    ('E. AGH 钩子变量 / 容器全景', r'''
echo "== AGH_PORT 定义 =="
grep -n 'AGH_PORT' /etc/openclash/custom/openclash_custom_firewall_rules.sh 2>/dev/null
echo "== docker ps -a 全量 =="
docker ps -a --format '{{.Names}} | {{.Status}} | {{.Image}}' 2>&1
echo "== dockerd 实际状态 =="
ps w | grep -E '[d]ockerd|[c]ontainerd' | head -4
''', 40),

    ('F. 手机"不可上网"坑位复查：v6 RA 下发状态', r'''
echo "ra=$(uci -q get dhcp.lan.ra || echo '(未设置=默认)')"
echo "dhcpv6=$(uci -q get dhcp.lan.dhcpv6 || echo '(未设置=默认)')"
echo "managed=$(uci -q get dhcp.lan.ra_management || echo '(未设置)')"
echo "-- LAN v6 地址 --"
ip -6 addr show dev br-lan 2>/dev/null | grep -E 'inet6' | head -6
echo "-- WAN v6 地址 --"
ip -6 addr show dev eth0 2>/dev/null | grep -E 'inet6 (2|3)' | head -3
echo "(空 = WAN 无公网 v6，此时下 ULA RA 就是黑洞诱因)"
''', 25),
]


def run(client, cmd, timeout):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    return (stdout.read().decode('utf-8', 'replace').strip(),
            stderr.read().decode('utf-8', 'replace').strip())


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, PW, timeout=15, banner_timeout=20, auth_timeout=20)
    for title, cmd, tmo in SECTIONS:
        w('')
        w('=' * 66)
        w('== ' + title)
        w('=' * 66)
        try:
            out, err = run(client, cmd, tmo)
            w(out if out else '(空)')
            if err:
                w('[stderr] ' + err[:300])
        except Exception as exc:
            w('[FAILED] %r' % exc)
    client.close()
    with open(OUT, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_buf))
    print('ROUND2 DONE')


if __name__ == '__main__':
    main()
