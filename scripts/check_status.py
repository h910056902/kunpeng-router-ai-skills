#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
鲲鹏 C2000 Max 路由器 · 全量状态巡检（严格只读）

覆盖：系统/固件、资源（内存/存储/温度/swap）、Docker、AdGuard Home、
DNS 四段链路、OpenClash、应用商店注册表与补丁在位情况、计划任务。

用法：
    export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<SSH密码>
    export AGH_USER=<AGH账号> AGH_PASS=<AGH密码>     # 只看 DNS/AGH 那节可省略，省略则该节登录失败并跳过
    python scripts/check_status.py

铁律：本脚本只有读操作（cat/grep/ls/df/free/ps/docker inspect/ubus/curl 查询），
不写任何配置文件、不重启任何服务。唯一的副作用是对本机 53/3000 端口的只读 DNS/API 查询
（AGH 会话 cookie 走内存变量传递，不落盘）。
"""
import os
import sys

import paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')

if not PW:
    sys.exit('[FATAL] 未设置 ROUTER_PW 环境变量')

# (标题, 远端命令, exec timeout 秒)
SECTIONS = [
    ('系统 / 固件', r'''
echo "hostname : $(cat /proc/sys/kernel/hostname)"
echo "model    : $(cat /tmp/sysinfo/model 2>/dev/null)"
echo "board    : $(cat /tmp/sysinfo/board_name 2>/dev/null)"
. /etc/openwrt_release 2>/dev/null; echo "release  : $DISTRIB_DESCRIPTION"; echo "rev      : $DISTRIB_REVISION"
echo "kernel   : $(uname -r)"
echo "arch     : $(uname -m)"
echo "uptime   : $(uptime)"
echo "date     : $(date)"
''', 20),

    ('资源：内存 / swap / 存储', r'''
echo "-- memory --"; free -k | grep -E 'Mem|Swap'
echo "-- overlay --"; df -h /overlay 2>/dev/null | tail -1
echo "-- eMMC --"; df -h /tmp/storage/mmcblk0p1 2>/dev/null | tail -1
echo "-- tmp --"; df -h /tmp 2>/dev/null | tail -1
echo "-- top mem procs --"; ps -o rss,comm 2>/dev/null | sort -rn | head -8
''', 25),

    ('温度 / 负载', r'''
for z in /sys/class/thermal/thermal_zone*; do
  [ -r "$z/temp" ] || continue
  echo "$(cat $z/type 2>/dev/null): $(cat $z/temp) mdegC"
done
echo "-- loadavg --"; cat /proc/loadavg
''', 20),

    ('Docker', r'''
which docker >/dev/null 2>&1 && echo "docker bin : $(docker --version 2>&1)" || echo "docker bin : NOT FOUND"
/etc/init.d/dockerd enabled >/dev/null 2>&1 && echo "dockerd enabled : yes" || echo "dockerd enabled : no"
echo "-- containers --"
docker ps -a --format '{{.Names}}|{{.Status}}|{{.Image}}' 2>&1 | head -20
echo "-- daemon.json --"; cat /etc/docker/daemon.json 2>/dev/null
echo "-- swap info --"; free -m | grep -i swap
''', 40),

    ('AdGuard Home', r'''
echo "-- container state --"
docker inspect adguardhome --format 'status={{.State.Status}} running={{.State.Running}} exit={{.State.ExitCode}} restarts={{.RestartCount}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} policy={{.HostConfig.RestartPolicy.Name}}' 2>&1
echo "-- mounts --"
docker inspect adguardhome --format '{{range .Mounts}}{{.Source}} -> {{.Destination}}{{"\n"}}{{end}}' 2>&1
echo "-- yaml 真实路径定位 --"
CFG=$(find /opt/docker /etc /root /mnt /tmp/storage /overlay -maxdepth 6 -name 'AdGuardHome.yaml' 2>/dev/null | head -3)
echo "$CFG"
for f in $CFG; do
  echo "--- $f ---"
  ls -la "$f" 2>/dev/null
  echo "listen ports:"; grep -n 'port:' "$f" 2>/dev/null | head -6
  echo "filters(url:) : $(grep -c 'url:' "$f" 2>/dev/null)"
  echo "filter names  :"; grep -n 'name:' "$f" 2>/dev/null | head -15
done
echo "-- 最近日志 --"
docker logs --tail 25 adguardhome 2>&1 | tail -25
''', 70),

    ('DNS 链路四段', r'''
echo "== 1) 谁在听 :53 / :5353 ==" ; netstat -ln 2>/dev/null | grep -E ':(53|5353|5354|7874)[^0-9]' | head -14
echo "== 2) resolv.conf ==" ; cat /etc/resolv.conf 2>/dev/null
echo "== 3) dnsmasq 监听配置 ==" ; grep -rn 'port\|noresolv\|server=' /etc/dnsmasq.conf /etc/config/dhcp 2>/dev/null | head -10
echo "== 4) dnsmasq 状态 ==" ; /etc/init.d/dnsmasq enabled >/dev/null 2>&1 && echo enabled || echo disabled; ps w 2>/dev/null | grep -c '[d]nsmasq'
echo "== 5) AGH 自启 ==" ; ls -la /etc/init.d/*adguard* 2>/dev/null; grep -n 'adguard' /etc/crontabs/root 2>/dev/null
''', 30),

    ('OpenClash', r'''
/etc/init.d/openclash enabled >/dev/null 2>&1 && echo "enabled : yes" || echo "enabled : no"
ps w 2>/dev/null | grep -c '[o]penclash'
echo "-- clash core --"; ps w 2>/dev/null | grep -o '[^ ]*clash[^ ]*' | head -5
echo "-- current config --"; ls -la /etc/openclash/config/ 2>/dev/null | head -10
echo "-- running cfg --"; readlink -f /etc/openclash/*.yaml 2>/dev/null | head -3; grep -n 'config_path\|enable_redirect_dns\|enable_custom_dns' /etc/config/openclash 2>/dev/null | head -8
''', 30),

    ('应用商店 · 注册表', r'''
echo "-- installed.list ($(wc -l < /etc/kp_store/installed.list 2>/dev/null) 条) --"
cat /etc/kp_store/installed.list 2>/dev/null
echo "-- plugins.json 条数 --"
grep -o '"name"' /etc/kp_store/plugins.json 2>/dev/null | wc -l
''', 25),

    ('应用商店 · 补丁在位核查', r'''
BK=/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
FR=/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm
echo "-- 备份清单（按时间戳倒序）--"
ls -1t /usr/lib/lua/luci/controller/nradio_adv/ 2>/dev/null | grep '^appcenter' | head -8
ls -1t /usr/lib/lua/luci/view/nradio_appcenter/ 2>/dev/null | grep '^appcenter' | head -8
echo "-- 后端补丁标记 --"
echo "open_url=ourl      : $(grep -c 'open_url = ourl' $BK 2>/dev/null)"
echo "src2(来源字段)     : $(grep -c 'src2' $BK 2>/dev/null)"
echo "installed.list引用 : $(grep -c 'installed.list' $BK 2>/dev/null)"
echo "percent 相关行     : $(grep -c 'percent' $BK 2>/dev/null)"
echo "fl[9](第9列外链)   : $(grep -c 'fl\[9\]' $BK 2>/dev/null)"
echo "-- 前端补丁标记 --"
echo "db.open_url        : $(grep -c 'db.open_url' $BK $FR 2>/dev/null | grep -v ':0' | tr '\n' ' ')"
echo "percent 相关行     : $(grep -c 'percent' $FR 2>/dev/null)"
echo "-- 后端函数清单（percent/progress/install 相关）--"
grep -n 'function' $BK 2>/dev/null | grep -iE 'percent|progress|install|online|extra' | head -15
echo "-- 文件大小/时间 --"
ls -la $BK $FR 2>/dev/null
''', 40),

    ('负载 / 内存 深挖', r'''
echo "-- top CPU --"; top -b -n1 2>/dev/null | head -14
echo "-- meminfo --"; head -5 /proc/meminfo
echo "-- docker stats --"; docker stats --no-stream --format '{{.Name}} CPU:{{.CPUPerc}} MEM:{{.MemUsage}}' 2>&1 | head -5
echo "-- swap 占用 >5MB 的进程 --"
for p in /proc/[0-9]*; do
  s=$(grep -s VmSwap $p/status 2>/dev/null | awk '{print $2}')
  [ -n "$s" ] && [ "$s" -gt 5000 ] 2>/dev/null && echo "$s kB  $(cat $p/comm 2>/dev/null)"
done | sort -rn | head -8
echo "-- conntrack --"; echo "count=$(cat /proc/sys/net/netfilter/nf_conntrack_count 2>/dev/null) max=$(cat /proc/sys/net/netfilter/nf_conntrack_max 2>/dev/null)"
''', 60),

    ('DNS 功能验证 / AGH API', r'''
echo "== 问 53 端口（当前解析者）=="
nslookup doubleclick.net 127.0.0.1 2>&1 | head -8
echo "== AGH API 登录 + 状态（凭据走 AGH_USER/AGH_PASS 环境变量，运行期注入，不落盘）=="
CK=$(curl -s -i -m 12 -X POST -H 'Content-Type: application/json' \
   -d '{"name":"__AGH_USER__","password":"__AGH_PASS__"}' http://127.0.0.1:3000/control/login 2>/dev/null \
   | grep -i '^set-cookie:' | sed 's/^[Ss]et-[Cc]ookie: //' | cut -d';' -f1 | tr -d '\r')
if [ -z "$CK" ]; then echo "登录未取到 cookie（AGH 未起或凭据已改）"; else
  echo "-- /control/status --"
  curl -s -m 12 -b "$CK" http://127.0.0.1:3000/control/status | head -c 900; echo
  echo "-- /control/filtering/status --"
  curl -s -m 15 -b "$CK" http://127.0.0.1:3000/control/filtering/status | head -c 1600; echo
  echo "-- /control/stats --"
  curl -s -m 15 -b "$CK" http://127.0.0.1:3000/control/stats | head -c 600; echo
fi
''', 70),

    ('商店清单源', r'''
ls -la /etc/kp_store/ 2>/dev/null
echo "-- plugins.json 大小 --"; wc -c /etc/kp_store/plugins.json 2>/dev/null
echo "-- 前 300 字节 --"; head -c 300 /etc/kp_store/plugins.json 2>/dev/null; echo
echo "-- 注册表列数抽查 --"; awk -F'|' '{print NF" 列  "$1}' /etc/kp_store/installed.list 2>/dev/null
''', 30),

    ('计划任务 / 开机自启', r'''
echo "-- crontab --"; crontab -l 2>/dev/null
echo "-- rc.local --"; tail -20 /etc/rc.local 2>/dev/null
echo "-- 自启脚本 --"; ls -la /etc/init.d/ 2>/dev/null | grep -iE 'adguard|docker|clash|aria|smb|mini' 
''', 25),
]


def run(client, cmd, timeout):
    stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode('utf-8', 'replace')
    err = stderr.read().decode('utf-8', 'replace')
    return out.strip(), err.strip()


def main():
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(HOST, 22, USER, PW, timeout=15)

    for title, cmd, tmo in SECTIONS:
        # 凭据运行期注入：AGH 账号密码只从环境变量取，绝不写死在脚本里
        cmd = (cmd.replace('__AGH_USER__', os.environ.get('AGH_USER', ''))
                  .replace('__AGH_PASS__', os.environ.get('AGH_PASS', '')))
        print('\n' + '=' * 68)
        print('== ' + title)
        print('=' * 68)
        try:
            out, err = run(client, cmd, tmo)
            print(out if out else '(空)')
            if err:
                print('[stderr] ' + err[:500])
        except Exception as exc:  # 单节失败不影响整体
            print('[SECTION FAILED] %s' % exc)

    client.close()
    print('\n巡检完成（全程只读）')


if __name__ == '__main__':
    main()
