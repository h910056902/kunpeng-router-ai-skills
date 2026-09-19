#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
向 AdGuard Home 添加新的 DNS 封锁清单 (API + cookie 登录):
  1. AWAvenue 秋风广告规则 (AdGuard 版) —— 摇一摇/开屏/公众号/小程序/电视广告, 极轻量
  2. ADgk —— 视频 APP 广告/开屏, 轻量 (9k 行)
已存在同 URL 则跳过。添加后打印各清单条数与内存。
"""
import os, time, json, paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
PW = os.environ.get('ROUTER_PW', '')
AGH_USER = os.environ.get('AGH_USER', '')
AGH_PASS = os.environ.get('AGH_PASS', '')

NEW_LISTS = [
    ('AWAvenue 秋风广告规则 (AdGuard版)',
     'https://raw.githubusercontent.com/TG-Twilight/AWAvenue-Ads-Rule/main/Filters/AWAvenue-Ads-Rule-Adguard.txt'),
    ('ADgk 去广告 (视频APP/开屏)',
     'https://raw.githubusercontent.com/banbendalao/ADgk/master/ADgk.txt'),
]

c = paramiko.SSHClient()
c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
c.connect(HOST, 22, 'root', PW, timeout=12)


def sh(cmd, t=60):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', 'replace'), e.read().decode('utf-8', 'replace')


# 1) 登录拿 cookie
out, _ = sh(("curl -s -m 40 -c /tmp/agh-cookie.txt -X POST http://127.0.0.1:3000/control/login "
             "-H 'Content-Type: application/json' "
             "-d '{\"name\":\"%s\",\"password\":\"%s\"}'" % (AGH_USER, AGH_PASS)), 90)
print('登录:', out.strip() or '(ok, cookie 已存)')

# 2) 现有清单
out, _ = sh('curl -s -b /tmp/agh-cookie.txt http://127.0.0.1:3000/control/filtering/status', 20)
try:
    st = json.loads(out)
    existing = [f['url'] for f in st.get('filters', [])]
    print('现有清单 %d 个, 共 %s 条规则' % (len(existing), st.get('user_rules', '') or sum(f.get('rules_count', 0) for f in st.get('filters', []))))
except Exception as ex:
    print('status 解析失败:', ex, out[:200]); existing = []

# 3) 添加
for name, url in NEW_LISTS:
    if url in existing:
        print('已存在, 跳过:', name)
        continue
    body = json.dumps({'name': name, 'url': url, 'whitelist': False})
    out, _ = sh(("curl -s -b /tmp/agh-cookie.txt -X POST http://127.0.0.1:3000/control/filtering/add_url "
                 "-H 'Content-Type: application/json' -d '%s'" % body), 30)
    print('添加', name, '->', out.strip() or '(ok)')
    time.sleep(1)

# 4) 刷新 + 确认
time.sleep(8)
out, _ = sh('curl -s -b /tmp/agh-cookie.txt http://127.0.0.1:3000/control/filtering/status', 20)
try:
    st = json.loads(out)
    total = 0
    print('\n== 当前封锁清单 ==')
    for f in sorted(st.get('filters', []), key=lambda x: -x.get('rules_count', 0)):
        total += f.get('rules_count', 0)
        flag = '' if f['enabled'] else ' [停用]'
        print('%8d  %s%s' % (f.get('rules_count', 0), f.get('name', f['url'])[:46], flag))
    print('合计: %d 条 + 自定义 %d 条' % (total, len(st.get('user_rules', []))))
except Exception as ex:
    print('status 解析失败:', ex, out[:300])

# 5) 内存
out, _ = sh('free -k | grep Mem', 10)
print('\n内存:', out.strip())
sh('rm -f /tmp/agh-cookie.txt')
c.close()
