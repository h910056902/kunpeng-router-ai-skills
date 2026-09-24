"""maye-lite 硬校验"""
import re, os, subprocess, sys
from mayelib import parse

SRC = os.environ.get('SRC', 'maye-v320.sh')
LITE = os.environ.get('LITE', 'maye-lite.sh')

O = parse(SRC)
L = parse(LITE)
o_names = {f['name'] for f in O['funcs']}
l_names = {f['name'] for f in L['funcs']}
deleted = sorted(o_names - l_names)
added = sorted(l_names - o_names)
print('=== 函数集合 ===')
print(f'原 {len(o_names)}  精简 {len(l_names)}  删除 {len(deleted)}  新增 {len(added)}')
print('新增（应为空或仅模板）:', added)

lite_txt = open(LITE, encoding='utf-8', errors='replace').read()
lite_lines = lite_txt.splitlines()
lite_inside = L['inside']

print()
print('=== ① 悬挂引用检查（已删函数名是否仍出现）===')
dangling = []
for d in deleted:
    # 任何位置出现（含 heredoc，从严）
    for i, l in enumerate(lite_lines):
        if re.search(r'(?<![A-Za-z0-9_])' + re.escape(d) + r'(?![A-Za-z0-9_])', l):
            dangling.append((d, i + 1, l.strip()[:80]))
            break
print('悬挂引用数:', len(dangling))
for d in dangling[:25]:
    print('   ', d)
# 子串形态（可能拼名）
print()
print('=== ② 子串形态残留（动态拼名风险）===')
subs = []
for d in deleted:
    stem = d.split('_')[0] + '_'
    cnt = lite_txt.count(stem)
    if cnt and stem in ('command_', '_switch_sim_', '_command_atcmd_', 'generic_'):
        subs.append((d, stem, cnt))
print('命中:', subs if subs else '无')

print()
print('=== ③ feature ID 一致性 ===')
disp = L['name_index']['run_menu_feature']
body = '\n'.join(L['lines'][disp['start'] - 1:disp['end']])
ids = set(re.findall(r'^\s*([0-9]+)\)\s*$', body, re.M))
print('分派表 ID:', sorted(ids, key=int))
refs = set()
for f in L['funcs']:
    if f['name'] in ('main_menu', 'common_plugin_menu', 'network_route_menu',
                     'appcenter_polish_menu', 'maintenance_test_menu', 'run_menu_feature'):
        continue
refs |= set(re.findall(r'submenu_feature=\'([0-9]+)\'', body))
for f in L['funcs']:
    if f['name'] in ('common_plugin_menu', 'network_route_menu', 'appcenter_polish_menu',
                     'maintenance_test_menu', 'maintenance_test_menu'):
        t = '\n'.join(L['lines'][f['start'] - 1:f['end']])
        refs |= set(re.findall(r"submenu_feature='([0-9]+)'", t))
        refs |= set(re.findall(r'run_menu_feature ([0-9]+)', t))
print('菜单引用到的 ID:', sorted(refs, key=int))
missing = sorted(refs - ids, key=int)
print('❗引用了但分派表里没有的 ID:', missing if missing else '无')

print()
print('=== ④ 保留的「红线邻近」函数（需人工判定读写）===')
ADJ = ('adguard', 'mosdns', 'qiyou', 'leigod', 'hakimi', 'docker', 'openclash')
for f in L['funcs']:
    if any(t in f['name'].lower() for t in ADJ):
        print(f"   {f['end']-f['start']+1:>5} 行 @{f['start']:<6} {f['name']}")

print()
print('=== ⑤ sh -n 语法门禁 ===')
r = subprocess.run(['sh', '-n', LITE], capture_output=True, text=True)
print('returncode:', r.returncode)
print('stderr:', (r.stderr or '(空)')[:500])

print()
print('=== ⑥ 体积 ===')
print('原:', os.path.getsize(SRC), '字节 /', len(O['lines']), '行')
print('精简:', os.path.getsize(LITE), '字节 /', len(L['lines']), '行')
