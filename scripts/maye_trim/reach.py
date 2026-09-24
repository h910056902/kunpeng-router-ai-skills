#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""静态调用闭包 + 写盘/破坏性操作扫描。

用途（裁剪前必做的一步）：回答"我想保留的这个菜单项，跑起来到底会碰到什么"。
从入口函数出发沿**静态调用图**做 BFS，把闭包内每个函数的
写盘 / 删除 / 服务控制 / 挂载 等操作连同**行号**一起列出来，
用来判断某个 handler 是不是"只读" —— 只读的 handler 就是最好的真机冒烟靶子。

⚠️ 本工具只做**静态**扫描，误报不可避免，判据要靠人看行内容：
   - `> /dev/null 2>&1`、`command -v xxx >/dev/null` 会被 `>` 规则命中（命令探测，非写盘）
   - `mkdir -p "$WORKDIR"` 若 WORKDIR 在 /tmp 或 /var/run（tmpfs），则非持久化
   - 命中不等于有害，**要逐条读行**再定论
   因此本工具用于"缩小审查范围"，不代替结论。真正的结论建议配运行期实测：
   设备侧 `touch /tmp/marker` → 跑 → **遍历 + shell `[ f -nt marker ]`** 列出改动。

   🕳️ **绝不可用 `find -xdev -newer <marker>` 做这一步**：BusyBox v1.33.2 的 `find`
   不支持 `-newer` / `-mmin` / `-newermt`，它报 `unrecognized: -newer` 但错误常被
   `2>/dev/null` 吞掉 → **静默返回空 → 假阴性"零改动"**（本项目已因此把两轮结论判错）。
   正确写法（实测全盘 0.06–0.6 s）：:

       M=/tmp/marker; cd /
       find . -xdev -type f 2>/dev/null | while IFS= read -r f; do
           [ "$f" -nt "$M" ] && printf 'F %s\n' "$f"
       done

用法::

    python reach.py <脚本路径> <入口函数名> [更多入口...]
    python reach.py maye-lite.sh run_unified_test_mode

退出码：命中写盘类操作 = 1，闭包干净 = 0（便于接进 CI / 手工流水线）。
"""
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mayelib import parse  # noqa: E402

# 写盘 / 破坏性操作模式（tag 只用于分组展示，判据仍需人读原行）
WRITE_PATS = [
    (r'\bcp\s', 'copy'),
    (r'\bmv\s', 'move'),
    (r'\brm\s+-', 'remove'),
    (r'\bmkdir\b', 'mkdir'),
    (r'\br ?mdir\b', 'rmdir'),
    (r'\bsed\s+-i', 'sed -i 原地改写'),
    (r'\buci\s+(set|add|del|delete|commit|revert)\b', 'uci 写入'),
    (r'\bopkg\s+(install|remove|upgrade|update)\b', 'opkg'),
    (r'\bwget\s+[^|]*-O\s', 'wget -O'),
    (r'\bcurl\s+[^|]*\s-o\s', 'curl -o'),
    (r'\btouch\s+/', 'touch'),
    (r'(^|[^>0-9])>{1,2}\s*/', '重定向到绝对路径'),
    (r'\btee\s+/', 'tee'),
    (r'\bchmod\s', 'chmod'),
    (r'\bchown\s', 'chown'),
    (r'/etc/init\.d/\S+\s+(start|stop|restart|enable|disable|reload)', '服务控制'),
    (r'\breboot\b', 'reboot'),
    (r'\bumount\b', 'umount'),
    (r'\bmount\s', 'mount'),
    (r'\bmtd\s+write\b', 'mtd write'),
    (r'\bmkswap\b', 'mkswap'),
    (r'\bswapon\b', 'swapon'),
    (r'\bsysupgrade\b', 'sysupgrade'),
    (r'\bmkfs', 'mkfs'),
    (r'\bdd\s+.*\bof=', 'dd'),
]

WORD_RE = re.compile(r'\b([a-z_][a-z0-9_]{2,})\b')


def closure(by_name, lines, entries):
    """从入口出发做静态调用图 BFS，返回 (有序闭包, 每个函数的行列表)。"""
    bodies = {}

    def body(name):
        if name not in bodies:
            f = by_name[name]
            bodies[name] = [(f['start'] + i, l)
                            for i, l in enumerate(lines[f['start'] - 1:f['true_end']])]
        return bodies[name]

    seen, order, queue = set(), [], list(entries)
    while queue:
        cur = queue.pop(0)
        if cur in seen or cur not in by_name:
            continue
        seen.add(cur)
        order.append(cur)
        for w in set(WORD_RE.findall('\n'.join(l for _, l in body(cur)))):
            if w in by_name and w not in seen:
                queue.append(w)
    return order, body


def main(argv):
    if len(argv) < 3:
        print(__doc__)
        return 2
    path, entries = argv[1], argv[2:]
    P = parse(path)
    by_name, lines = P['name_index'], P['lines']

    missing = [e for e in entries if e not in by_name]
    if missing:
        print('!! 入口不存在:', ', '.join(missing))
        print('   可用入口（前 40 个）:', ', '.join(sorted(by_name)[:40]))
        return 2

    order, body = closure(by_name, lines, entries)
    print('脚本   :', path)
    print('入口   :', ', '.join(entries))
    print('调用闭包函数数 :', len(order))
    print('总行数 :', len(lines))
    print()

    total = 0
    for name in sorted(order):
        hits = []
        for ln, l in body(name):
            s = l.strip()
            if s.startswith('#'):
                continue
            for pat, tag in WRITE_PATS:
                if re.search(pat, l):
                    hits.append((ln, tag, s[:150]))
                    break
        if hits:
            total += len(hits)
            print('### %s  (%d 处)' % (name, len(hits)))
            for ln, tag, t in hits:
                print('   %6d  [%s]  %s' % (ln, tag, t))
    print()
    print('写盘/破坏性操作命中总数:', total, '（命中 ≠ 有害，请逐条读原行）')
    print('闭包函数清单:')
    print('  ' + ', '.join(sorted(order)))
    return 1 if total else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
