#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Portainer / 容器平台 运行态与稳定性取证（只读）"""
import os
import sys

import paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')
if not PW:
    sys.exit('未设置 ROUTER_PW')

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, USER, PW, timeout=15)


def run(cmd, t=90):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', 'replace'), e.read().decode('utf-8', 'replace')


def sec(title, cmd, t=90):
    print('\n' + '=' * 70)
    print('== ' + title)
    print('=' * 70)
    out, err = run(cmd, t)
    print(out.rstrip() or '(空)')
    if err.strip():
        print('[stderr]', err.strip()[:300])


sec('系统 uptime / 是否重启过', r'''
cat /proc/uptime; date; uptime
echo "--- boot 时间（dmesg 首行）---"; dmesg 2>/dev/null | head -2
echo "--- wtmp/last ---"; last -n 5 2>/dev/null | head -6
''')

sec('容器启动时间 / 重启策略 / 重启次数', r'''
for n in portainer adguardhome t1; do
  echo "### $n"
  docker inspect $n --format 'status={{.State.Status}} exit={{.State.ExitCode}} restarts={{.RestartCount}} policy={{.HostConfig.RestartPolicy.Name}} started={{.State.StartedAt}} finished={{.State.FinishedAt}} net={{.HostConfig.NetworkMode}} image={{.Config.Image}} cmd={{.Config.Cmd}}' 2>&1
done
''')

sec('Portainer 数据目录 / 是否已初始化', r'''
ls -la /opt/docker/data/portainer/ 2>/dev/null
echo "--- db ---"; ls -la /opt/docker/data/portainer/portainer.db 2>/dev/null
echo "--- 容器内确认 ---"; docker exec portainer ls -la /data 2>&1 | head -10
''', 120)

sec('Portainer 最近日志', r'''
docker logs --tail 25 portainer 2>&1 | tail -25
''', 90)

sec('AdGuard Home 最近日志（看是否反复崩）', r'''
docker logs --tail 30 adguardhome 2>&1 | tail -30
''', 90)

sec('内核 OOM / 进程被杀记录', r'''
dmesg 2>/dev/null | grep -iE 'oom|killed process|out of memory' | tail -15 || echo '(无 OOM 记录)'
echo "--- logread ---"
logread 2>/dev/null | grep -iE 'oom|adguard|docker|portainer' | tail -20 || echo '(无)'
''', 60)

sec('平台负载来源：du / disk usage 任务', r'''
echo "--- 当前 du/awk 相关进程 ---"
ps w 2>/dev/null | grep -E '[d]u -sk|[d]p/disk|[p]ortainer' | head -10
echo "--- Portainer 磁盘统计缓存 ---"
ls -la /tmp/dp/ 2>/dev/null
cat /tmp/dp/disk.raw 2>/dev/null | head -3
echo "--- /opt/docker 实际体积（可能很慢，超时即断）---"
timeout 45 du -sh /opt/docker 2>/dev/null || echo '(45s 未扫完 → 体积大/IO 重)'
''', 120)

sec('镜像/卷/容器 垃圾盘点', r'''
echo "--- 全部容器 ---"
docker ps -a --format '{{.Names}} | {{.Status}} | {{.Image}} | {{.CreatedAt}}'
echo "--- 全部镜像 ---"
docker images --format '{{.Repository}}:{{.Tag}} | {{.Size}} | {{.CreatedSince}}'
echo "--- 数据卷 ---"
docker volume ls 2>&1 | head -10
echo "--- build cache ---"
docker system df 2>&1 | head -6
''', 120)

sec('Dockge 残留痕迹', r'''
ls -laR /opt/docker/data/dockge/ 2>/dev/null | head -20
echo "--- 5001 监听 ---"; netstat -ln 2>/dev/null | grep ':5001' || echo '(5001 无监听)'
echo "--- dockge 容器/镜像 ---"; docker ps -a --filter name=dockge --format '{{.Names}} {{.Status}}' 2>&1; docker images | grep -i dockge || echo '(无 dockge 镜像)'
''', 60)

sec('端口 8080 复核', r'''
netstat -ln 2>/dev/null | grep ':8080' || echo '(8080 无监听)'
curl -s -m 6 -o /dev/null -w '127.0.0.1:8080 -> %{http_code}\n' http://127.0.0.1:8080/ 2>&1
''', 40)

c.close()
print('\n取证完成（只读）')
