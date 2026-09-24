"""maye 源码解析库：heredoc 感知的函数边界扫描。
用法: from mayelib import parse
"""
import re

DEF_RE = re.compile(r'^([A-Za-z_][A-Za-z0-9_]*)\(\)[ \t]*\{[ \t]*$')
CLOSE_RE = re.compile(r'^\}[ \t]*$')
# <<EOF / <<'EOF' / <<"EOF" / <<-EOF，同一行可有多个
HD_RE = re.compile(r'<<(-?)[ \t]*([\'"]?)([A-Za-z_][A-Za-z0-9_]*|\S+?)\2(?=[\s;|&)]|$)')


def scan_heredocs(lines):
    """返回每行是否处于 heredoc 内容中（含结束定界行本身标记为 inside）"""
    inside = [False] * len(lines)
    queue = []      # [(delimiter, strip_tabs)]
    for i, raw in enumerate(lines):
        if queue:
            inside[i] = True
            delim, strip_tabs = queue[0]
            probe = raw.lstrip('\t') if strip_tabs else raw
            if probe.rstrip('\r') == delim or raw.rstrip('\r') == delim:
                queue.pop(0)
            continue
        # 不在 heredoc 内：扫描本行的 heredoc 起始符
        for m in HD_RE.finditer(raw):
            strip_tabs = m.group(1) == '-'
            delim = m.group(3)
            queue.append((delim, strip_tabs))
    return inside


def parse(path):
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    N = len(lines)
    inside = scan_heredocs(lines)

    defs = []
    for i, l in enumerate(lines):
        if inside[i]:
            continue
        m = DEF_RE.match(l)
        if m:
            defs.append((i + 1, m.group(1)))

    funcs = []
    for k, (ln, name) in enumerate(defs):
        limit = defs[k + 1][0] - 1 if k + 1 < len(defs) else N
        # 真实结束：limit 之前第一个「列 0 的 } 且不在 heredoc 内」
        true_end = limit
        for j in range(ln, limit + 1):
            if inside[j - 1]:
                continue
            if CLOSE_RE.match(lines[j - 1]):
                true_end = j
                break
        funcs.append({'name': name, 'start': ln, 'end': limit, 'true_end': true_end})

    # 顶层头（第一个函数之前）与尾部（最后一个函数之后）
    head_end = defs[0][0] - 1 if defs else N
    head = list(range(1, head_end + 1))
    tail = list(range(funcs[-1]['end'] + 1, N + 1)) if funcs else []

    return {
        'lines': lines, 'inside': inside, 'funcs': funcs,
        'head': head, 'tail': tail, 'name_index': {f['name']: f for f in funcs},
    }


if __name__ == '__main__':
    import os
    src = os.environ.get('SRC', 'maye-v320.sh')
    P = parse(src)
    lines, inside, funcs = P['lines'], P['inside'], P['funcs']
    print('总行数:', len(lines))
    print('heredoc 内容行数:', sum(inside))
    print('顶层定义数:', len(funcs))

    # 验证：每个函数（除末个）在下一个定义前，最后一个非空行应为列 0 的 }
    ok = bad = 0
    badlist = []
    for k, f in enumerate(funcs[:-1]):
        nxt = funcs[k + 1]['start'] - 1
        lastnonblank = None
        for j in range(nxt - 1, f['start'] - 1, -1):
            if lines[j].strip():
                lastnonblank = j + 1
                break
        if lastnonblank and CLOSE_RE.match(lines[lastnonblank - 1]):
            ok += 1
        else:
            bad += 1
            if len(badlist) < 12:
                badlist.append((f['name'], f['start'], f['end'],
                                lines[lastnonblank - 1][:80] if lastnonblank else '<none>'))
    print('末行是列0  } 的函数数:', ok, ' 异常:', bad)
    for n, s, e, t in badlist:
        print(f'   {n} @{s}-{e}  末行={t!r}')

    print()
    print('顶层尾部代码:')
    for ln in P['tail']:
        if lines[ln - 1].strip() and not lines[ln - 1].strip().startswith('#'):
            print(f'  {ln:>6}| {lines[ln - 1]}')

    print()
    print('函数间隙（定义之间）非空行检查:')
    weird = 0
    for k, f in enumerate(funcs[:-1]):
        nxt = funcs[k + 1]['start']
        gap = [(j + 1, lines[j]) for j in range(f['end'], nxt - 1)
               if lines[j].strip() and not lines[j].strip().startswith('#')]
        if gap:
            weird += 1
            if weird <= 8:
                print(f'   @{f["end"] + 1}-{nxt - 1} 挂在 {f["name"]} 后: {gap[0][1][:80]!r}')
    print('  异常间隙数:', weird)
