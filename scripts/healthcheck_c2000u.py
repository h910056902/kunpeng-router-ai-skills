#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
鲲鹏 C2000 U (192.168.66.1) · 固件与系统功能 bug 排查（严格只读）

适配 B 机特性：
  - 992MB 内存 / 7.5G TF 卡 /mnt/storage
  - Docker data-root /mnt/storage/data/docker (overlay2)
  - 1Panel 端口 10090 (procd)
  - OpenClash 内核进程名 clash (非 mihomo)
  - 无 /etc/kp_store（商店未初始化，跳过商店检查）
  - DNS: AGH(:53) -> OpenClash(:7874)，dnsmasq :5354

bug 导向重点：
  1. 服务一致性：enabled 但未运行的服务
  2. 日志错误：logread / dmesg 中的 error/fail/OOM/IO 错误
  3. AGH 53 劫持规则顺序复查（已知坑：firewall reload 后 AGH 被旁路）
  4. DNS 真实解析验证 + 真实 HTTP 连通性（不做假 ping 判断）
  5. 文件系统只读/错误、磁盘空间、温度、内存/swap
  6. cron / NTP 时间同步

凭据：ROUTER_HOST / ROUTER_USER / ROUTER_PW / AGH_USER / AGH_PASS 全部运行期注入，零落盘。
本脚本无任何写操作、无服务重启。
"""
import os
import sys

SP = r"%USERPROFILE%\.workbuddy\binaries\python\envs\default\Lib\site-packages"
if SP not in sys.path:
    sys.path.insert(0, SP)

import paramiko  # noqa: E402

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')
AGH_USER = os.environ.get('AGH_USER', '')
AGH_PASS = os.environ.get('AGH_PASS', '')

if not PW:
    sys.exit('[FATAL] ROUTER_PW 未设置')

OUT_PATH = os.environ.get('CHECK_OUT', r'%USERPROFILE%\WorkBuddy\2026-09-13-22-04-27\router_check_report.txt')
_buf = []


def w(line=''):
    _buf.append(line)


# (标题, 远端命令, timeout 秒)
SECTIONS = [
    ('1. 系统 / 固件基本信息', r'''
echo "hostname : $(cat /proc/sys/kernel/hostname)"
echo "model    : $(cat /tmp/sysinfo/model 2>/dev/null)"
echo "board    : $(cat /tmp/sysinfo/board_name 2>/dev/null)"
. /etc/openwrt_release 2>/dev/null; echo "release  : $DISTRIB_DESCRIPTION"
echo "kernel   : $(uname -r)"
echo "arch     : $(uname -m)"
echo "uptime   : $(uptime)"
echo "date     : $(date)"
echo "== NTP 时间同步 =="
uci get system.@system[0].timezone 2>/dev/null
/etc/init.d/sysntpd enabled && echo "sysntpd: enabled" || echo "sysntpd: disabled"
date +%s
''', 20),

    ('2. 内存 / swap / 温度 / 负载', r'''
echo "-- memory --"; free -k | grep -E 'Mem|Swap'
echo "-- loadavg --"; cat /proc/loadavg
for z in /sys/class/thermal/thermal_zone*; do
  [ -r "$z/temp" ] || continue
  echo "$(cat $z/type 2>/dev/null): $(cat $z/temp) mdegC"
done
echo "-- swap top5 --"
for p in /proc/[0-9]*; do
  s=$(grep -s VmSwap $p/status 2>/dev/null | awk '{print $2}')
  [ -n "$s" ] && [ "$s" -gt 10000 ] 2>/dev/null && echo "$s kB  $(cat $p/comm 2>/dev/null)"
done | sort -rn | head -5
echo "-- conntrack --"
echo "count=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null) max=$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null)"
''', 30),

    ('3. 存储 / 文件系统健康', r'''
echo "-- 挂载点与空间 --"
df -h 2>/dev/null | grep -vE 'tmpfs.*(tmp|run)$'
echo "-- 只读异常检查（ro 且不是 squashfs 的）--"
mount | grep -E ' ro[,)] ' | grep -v squashfs
echo "-- f2fs / TF 卡 状态 --"
dmesg 2>/dev/null | grep -iE 'f2fs.*(error|fail|corrupt)|mmc.*(error|timeout|crc)' | tail -15
echo "(空 = 无文件系统/TF卡错误)"
''', 30),

    ('4. 内核日志 bug 扫描（dmesg）', r'''
echo "== OOM / 内存压力 =="
dmesg 2>/dev/null | grep -iE 'out of memory|oom.kill|oom-killer|memory cgroup' | tail -8
echo "(空 = 无 OOM 记录)"
echo "== 段错误 / 崩溃 =="
dmesg 2>/dev/null | grep -iE 'segfault|oops|bug:|call trace' | tail -8
echo "(空 = 无内核崩溃)"
echo "== I/O 错误 =="
dmesg 2>/dev/null | grep -iE 'i/o error|blk_update' | tail -8
echo "(空 = 无 I/O 错误)"
echo "== 最近 20 条内核告警级以上 =="
dmesg 2>/dev/null | grep -iE '\[err|\[warn|fail' | tail -20
''', 30),

    ('5. 系统日志 bug 扫描（logread）', r'''
echo "== error/fail/segfault 关键词（最近 5000 行内）=="
logread 2>/dev/null | grep -iE 'error|fail|segfault|crash|refused|timed? out' | grep -viE 'uwebp|webrtc|error: none' | tail -30
echo "--"
echo "== OOM =="
logread 2>/dev/null | grep -iE 'oom|out of memory' | tail -6
echo "(空 = 无)"
echo "== 守护进程异常退出/重启 =="
logread 2>/dev/null | grep -iE 'exit code|respawn|procd.*crash|into instance' | tail -12
''', 40),

    ('6. 服务一致性：enabled vs 实际运行', r'''
echo "== 所有 enabled 开机自启服务 =="
for s in /etc/init.d/*; do
  $s enabled 2>/dev/null && echo "ENABLED: $(basename $s)"
done
echo "--"
echo "== 关键基础设施进程存活（busybox 无 pgrep -c，用 pidof）=="
for p in dropbear uhttpd dnsmasq crond odhcpd rpcd; do
  if pidof $p >/dev/null 2>&1; then echo "ok: $p"; else echo "!! NOT RUNNING: $p"; fi
done
if pidof ntpd >/dev/null 2>&1 || pidof sysntpd >/dev/null 2>&1; then echo "ok: sysntpd"; else echo "!! NOT RUNNING: sysntpd"; fi
''', 40),

    ('7. Docker / 1Panel 状态', r'''
echo "== dockerd 服务 =="
/etc/init.d/dockerd enabled >/dev/null 2>&1 && echo "dockerd: enabled" || echo "dockerd: disabled"
if pidof dockerd >/dev/null 2>&1; then echo "dockerd: running"; else echo "dockerd: NOT running"; fi
echo "-- containers --"
docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>&1 | head -20
echo "-- daemon.json --"
cat /etc/docker/daemon.json 2>/dev/null
echo "== 1Panel（服务名 1paneld）=="
/etc/init.d/1paneld enabled >/dev/null 2>&1 && echo "1paneld: enabled" || echo "1paneld: not found/disabled"
if pidof 1panel >/dev/null 2>&1; then echo "1panel proc: running"; else echo "1panel proc: NOT running"; fi
netstat -lnt 2>/dev/null | grep -E ':(10090|9099|9090|7890|7874|53)[^0-9]' | head -12
''', 50),

    ('8. DNS 链路四段 + AGH 旁路复查（关键坑位）', r'''
echo "== 1) 谁在听 :53/:5354/:7874 =="
netstat -lnup 2>/dev/null | grep -E ':(53|5354|7874)[^0-9]' | head -10
netstat -lntp 2>/dev/null | grep -E ':(53|5354|7874)[^0-9]' | head -10
echo "== 2) 53 劫持规则顺序（KP 的 AGH 规则行号必须 < OpenClash 规则）=="
iptables -t nat -S PREROUTING 2>/dev/null | grep -n 'dport 53' | head -10
echo "== 3) 自定义防火墙钩子 =="
ls -la /etc/openclash/custom/openclash_custom_firewall_rules.sh 2>/dev/null
grep -n 'dport 53' /etc/openclash/custom/openclash_custom_firewall_rules.sh 2>/dev/null | head -4
echo "== 4) dnsmasq 端口 =="
uci -q get dhcp.@dnsmasq[0].port || echo "(默认53)"
echo "== 5) resolv.conf =="
cat /etc/resolv.conf 2>/dev/null
''', 30),

    ('9. DNS 真实解析功能验证', r'''
echo "== 经本机 :53 解析（AGH 链路）=="
for d in www.baidu.com www.qq.com doubleclick.net; do
  ip=$(nslookup $d 127.0.0.1 2>/dev/null | awk '/^Address 1/{print $3; exit}')
  echo "$d -> ${ip:-FAILED}"
done
echo "== 对照：直问 223.5.5.5 =="
ip=$(nslookup www.baidu.com 223.5.5.5 2>/dev/null | awk '/^Address 1/{print $3; exit}')
echo "www.baidu.com @223.5.5.5 -> ${ip:-FAILED}"
echo "== fake-ip 检查（198.18.x.x = 代理接管，正常现象）=="
nslookup www.baidu.com 127.0.0.1 2>/dev/null | grep 'Address 1' | head -2
''', 40),

    ('10. 真实 HTTP 连通性（国内外各 2 组 x 重试）', r'''
echo "== 国内直连 =="
for i in 1 2 3; do
  c1=$(curl -s -o /dev/null -m 8 -w '%{http_code}' http://www.baidu.com 2>/dev/null)
  [ "$c1" = "200" ] && break; sleep 1
done
echo "baidu.com -> $c1 (x3 retry)"
c2=$(curl -s -o /dev/null -m 8 -w '%{http_code}' -H 'Host: www.qq.com' http://121.51.142.37 2>/dev/null)
echo "qq.com -> $c2"
echo "== 境外（走代理）=="
for i in 1 2 3; do
  g=$(curl -s -o /dev/null -m 10 -w '%{http_code}' http://www.gstatic.com/generate_204 2>/dev/null)
  [ "$g" = "204" ] && break; sleep 1
done
echo "gstatic generate_204 -> $g (x3 retry)"
for i in 1 2 3; do
  y=$(curl -s -o /dev/null -m 10 -w '%{http_code}' https://www.youtube.com 2>/dev/null)
  [ "$y" = "200" ] && break; sleep 1
done
echo "youtube.com -> $y (x3 retry)"
''', 90),

    ('11. OpenClash 核心 / 节点健康', r'''
echo "== 进程（B 机内核名 clash）=="
ps w 2>/dev/null | grep -E '[c]lash' | head -4
echo "== OpenClash 服务 =="
/etc/init.d/openclash enabled >/dev/null 2>&1 && echo "openclash: enabled" || echo "openclash: disabled"
ls -la /etc/openclash/config/*.yaml 2>/dev/null | head -5
echo "== 端口监听 =="
netstat -lnt 2>/dev/null | grep -E ':(9090|9099|7890|7891|7892|7893|7874)' | head -10
echo "== mihomo/clash API 当前节点（若密码未知仅显示可达性）=="
curl -s -m 6 -o /dev/null -w 'API :9090 http_code=%{http_code}\n' http://127.0.0.1:9090/version 2>/dev/null
curl -s -m 6 http://127.0.0.1:9090/version 2>/dev/null | head -c 200; echo
echo "== ocspeed 故障转移开关 =="
uci -q get ocspeed.main.failover_enable; uci -q get ocspeed.main.backup_enable
''', 40),

    ('12. cron / 自启 / rc.local', r'''
echo "== crontab =="
crontab -l 2>/dev/null
echo "(空 = 无计划任务)"
echo "== rc.local（非注释行）=="
grep -v '^#' /etc/rc.local 2>/dev/null | grep -v '^$'
''', 25),

    ('13. 网络接口 / WAN / WiFi', r'''
echo "== 接口状态 =="
ubus call network.interface.wan status 2>/dev/null | grep -E '"up"|"address"|"proto"' | head -5
ubus call network.interface.lan status 2>/dev/null | grep -E '"up"|"address"' | head -4
echo "== WiFi =="
iwinfo 2>/dev/null | head -10
echo "== 默认路由 =="
ip -4 route show default 2>/dev/null
echo "== IPv6 默认路由（空 = v6 黑洞风险）=="
ip -6 route show default 2>/dev/null
echo "== IPv6 RA 下发 =="
uci -q get dhcp.lan.ra; uci -q get dhcp.lan.dhcpv6
''', 30),
]


def run(client, cmd, timeout):
    _, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace')
    err = stderr.read().decode('utf-8', 'replace')
    return out.strip(), err.strip()


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, 22, USER, PW, timeout=15, banner_timeout=20, auth_timeout=20)
    except Exception as e:
        sys.exit('[FATAL] SSH 连接失败: %r' % e)

    w('鲲鹏 C2000 U (192.168.66.1) 固件与系统功能 bug 排查报告（只读巡检）')
    w('巡检时间: ' + __import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
    w('=' * 70)

    for title, cmd, tmo in SECTIONS:
        w('')
        w('=' * 70)
        w('== ' + title)
        w('=' * 70)
        try:
            out, err = run(client, cmd, tmo)
            w(out if out else '(空输出)')
            if err:
                w('[stderr] ' + err[:400])
        except Exception as exc:
            w('[SECTION FAILED] %r' % exc)

    client.close()
    w('')
    w('巡检完成（全程只读，未修改任何配置）')

    with open(OUT_PATH, 'w', encoding='utf-8') as f:
        f.write('\n'.join(_buf))
    print('REPORT WRITTEN: %s (%d lines)' % (OUT_PATH, len(_buf)))


if __name__ == '__main__':
    main()
