"""maye 精简器 v2：物化迭代 + 菜单整段重写"""
import re, os, sys, json
from mayelib import parse

SRC = os.environ.get('SRC', 'maye-v320.sh')
DST = os.environ.get('DST', 'maye-lite.sh')

P = parse(SRC)
lines = P['lines']; inside = P['inside']; funcs = P['funcs']
byname = P['name_index']; N = len(lines); known = set(byname)

DENY_IDS = {'2', '4', '9', '10', '11', '16', '17', '19', '22', '23', '33'}
DENY_DIRECT = {'game_accelerator_menu', 'qiyou_integrated_menu', 'leigod_integrated_menu'}
FAMILY = ['adguard', 'mosdns', 'qiyou', 'leigod', 'hakimi', 'docker', 'openclash']

# ---------------- 菜单重写模板 ----------------
MENU = {}

MENU['main_menu'] = '''main_menu() {
    choice="${1:-}"
    require_root
    acquire_script_lock
    require_startup_disclaimer_acceptance_once
    prime_startup_disclaimer_model || true
    CURRENT_DETECTED_NROS_REVISION="$(detect_nros_revision 2>/dev/null || true)"
    print_main_menu_header

    if [ -n "$choice" ]; then
        MENU_ACTION_COMPLETED='0'
        case "$choice" in 1|2|3|4) require_nradio_menu_environment ;; esac
        case "$choice" in
            0)
                return 0
                ;;
            1)
                common_plugin_menu
                ;;
            2)
                network_route_menu
                ;;
            3)
                appcenter_polish_menu
                ;;
            4)
                maintenance_test_menu
                ;;
            *)
                die_menu_input_issue "$choice"
                ;;
        esac
        return 0
    fi

    while :; do
        print_menu_header '功能分类'
        print_menu_item 1 '常用插件安装'
        print_menu_item 2 'VPN / 组网 / 路由向导'
        print_menu_item 3 '应用商店与页面美化'
        print_menu_item 4 '设备维护与检测'
        print_menu_item 0 '退出'
        print_menu_prompt '0-4'
        read_category_choice
        MENU_ACTION_COMPLETED='0'

        case "$UI_READ_RESULT" in 1|2|3|4) require_nradio_menu_environment ;; esac

        case "$UI_READ_RESULT" in
            0)
                return 0
                ;;
            1)
                common_plugin_menu
                ;;
            2)
                network_route_menu
                ;;
            3)
                appcenter_polish_menu
                ;;
            4)
                maintenance_test_menu
                ;;
            *)
                die_menu_input_issue "$UI_READ_RESULT"
                ;;
        esac

        [ "${MENU_ACTION_COMPLETED:-0}" = '1' ] && return 0
    done
}'''

MENU['common_plugin_menu'] = '''common_plugin_menu() {
    while :; do
        submenu_feature=''
        print_menu_header '1 / 常用插件'
        print_menu_item 1 'swap 虚拟内存（C2000MAX / C2000Ultra）'
        print_menu_item 2 'ttyd / Web SSH'
        print_menu_item 3 'OpenList'
        print_menu_item 4 'DDNS-GO'
        print_menu_item 5 'MT5700 WebUI V3.0.0'
        print_menu_item 6 'Open-Box'
        print_menu_item 0 '返回功能分类'
        print_menu_prompt '0-6'
        read_category_choice
        case "$UI_READ_RESULT" in
            0) return 0 ;;
            1) submenu_feature='1' ;;
            2) submenu_feature='3' ;;
            3) submenu_feature='5' ;;
            4) submenu_feature='18' ;;
            5) submenu_feature='30' ;;
            6) submenu_feature='34' ;;
            *) die_menu_input_issue "$UI_READ_RESULT" ;;
        esac
        run_menu_feature "$submenu_feature"
        return 0
    done
}'''

MENU['network_route_menu'] = '''network_route_menu() {
    while :; do
        submenu_feature=''
        print_menu_header '2 / VPN 与组网'
        print_menu_item 1 'ZeroTier'
        print_menu_item 2 'EasyTier'
        print_menu_item 3 'OpenVPN'
        print_menu_item 4 'OpenVPN 自检'
        print_menu_item 0 '返回功能分类'
        print_menu_prompt '0-4'
        read_category_choice
        case "$UI_READ_RESULT" in
            0) return 0 ;;
            1) submenu_feature='6' ;;
            2) submenu_feature='7' ;;
            3) submenu_feature='8' ;;
            4) submenu_feature='12' ;;
            *) die_menu_input_issue "$UI_READ_RESULT" ;;
        esac
        run_menu_feature "$submenu_feature"
        return 0
    done
}'''

MENU['appcenter_polish_menu'] = '''appcenter_polish_menu() {
    while :; do
        submenu_feature=''
        print_menu_header '3 / 应用商店与页面'
        if ! lightweight_appcenter_model_supported; then
            print_menu_item 1 '美化应用商店'
        fi
        if openwrt_luci_8080_model_supported; then
            print_menu_item 2 'OpenWrt 原版 LuCI（8080）'
        fi
        if lightweight_appcenter_model_supported; then
            print_menu_item 3 '轻量应用商店'
        fi
        print_menu_item 0 '返回功能分类'
        print_menu_prompt '上方编号，0 返回'
        read_category_choice
        case "$UI_READ_RESULT" in
            0) return 0 ;;
            1) submenu_feature='15' ;;
            2)
                if openwrt_luci_8080_model_supported; then
                    run_menu_feature 28
                    [ "${MENU_ACTION_COMPLETED:-0}" = '1' ] && return 0
                    continue
                else
                    die_menu_input_issue "$UI_READ_RESULT"
                fi
                ;;
            3)
                lightweight_appcenter_menu
                [ "${MENU_ACTION_COMPLETED:-0}" = '1' ] && return 0
                continue
                ;;
            *) die_menu_input_issue "$UI_READ_RESULT" ;;
        esac
        run_menu_feature "$submenu_feature"
        return 0
    done
}'''

MENU['maintenance_test_menu'] = '''maintenance_test_menu() {
    while :; do
        submenu_feature=''
        maintenance_next_choice=1
        print_menu_header '4 / 设备维护'
        maintenance_health_choice=$maintenance_next_choice
        print_menu_item "$maintenance_health_choice" '统一体检增强版'
        maintenance_next_choice=$((maintenance_next_choice + 1))
        maintenance_fan_choice=$maintenance_next_choice
        print_menu_item "$maintenance_fan_choice" '风扇控制（C8-688/788、C2000MAX）'
        maintenance_next_choice=$((maintenance_next_choice + 1))
        maintenance_emmc_choice=$maintenance_next_choice
        print_menu_item "$maintenance_emmc_choice" 'eMMC 存储扩展'
        maintenance_next_choice=$((maintenance_next_choice + 1))

        maintenance_aggregation_choice=''
        if nradio_5g_aggregation_model_supported; then
            maintenance_aggregation_choice=$maintenance_next_choice
            print_menu_item "$maintenance_aggregation_choice" '5G 聚合修复检查'
            maintenance_next_choice=$((maintenance_next_choice + 1))
        fi

        maintenance_toolbox_choice=$maintenance_next_choice
        print_menu_item "$maintenance_toolbox_choice" '封版工具箱'
        maintenance_next_choice=$((maintenance_next_choice + 1))
        maintenance_operator_choice=$maintenance_next_choice
        print_menu_item "$maintenance_operator_choice" '运营商与卡名显示修复'
        maintenance_next_choice=$((maintenance_next_choice + 1))
        maintenance_temperature_choice=$maintenance_next_choice
        print_menu_item "$maintenance_temperature_choice" '首页 CPU / 5G 温度切换'
        maintenance_next_choice=$((maintenance_next_choice + 1))

        maintenance_monitoring_choice=''
        if nradio_cpe_monitoring_model_supported; then
            maintenance_monitoring_choice=$maintenance_next_choice
            print_menu_item "$maintenance_monitoring_choice" '5G 连接监听'
            maintenance_next_choice=$((maintenance_next_choice + 1))
        fi

        maintenance_return_choice=$maintenance_next_choice
        print_menu_item "$maintenance_return_choice" '返回功能分类'
        print_menu_prompt "0-$maintenance_return_choice"
        read_category_choice
        if [ "$UI_READ_RESULT" = '0' ] || [ "$UI_READ_RESULT" = "$maintenance_return_choice" ]; then
            return 0
        elif [ "$UI_READ_RESULT" = "$maintenance_health_choice" ]; then
            submenu_feature='13'
        elif [ "$UI_READ_RESULT" = "$maintenance_fan_choice" ]; then
            submenu_feature='14'
        elif [ "$UI_READ_RESULT" = "$maintenance_emmc_choice" ]; then
            submenu_feature='20'
        elif [ -n "$maintenance_aggregation_choice" ] && [ "$UI_READ_RESULT" = "$maintenance_aggregation_choice" ]; then
            submenu_feature='21'
        elif [ "$UI_READ_RESULT" = "$maintenance_toolbox_choice" ]; then
            submenu_feature='24'
        elif [ "$UI_READ_RESULT" = "$maintenance_operator_choice" ]; then
            submenu_feature='26'
        elif [ "$UI_READ_RESULT" = "$maintenance_temperature_choice" ]; then
            submenu_feature='27'
            CURRENT_HOME_TEMP_MENU_PATH="4 > $maintenance_temperature_choice"
        elif [ -n "$maintenance_monitoring_choice" ] && [ "$UI_READ_RESULT" = "$maintenance_monitoring_choice" ]; then
            submenu_feature='29'
            CURRENT_CPE_MONITORING_MENU_PATH="4 > $maintenance_monitoring_choice"
        else
            die_menu_input_issue "$UI_READ_RESULT"
        fi
        run_menu_feature "$submenu_feature"
        return 0
    done
}'''

# ---------------- run_menu_feature 分支块 ----------------
rf = byname['run_menu_feature']
rf_start, rf_end = rf['start'], rf['true_end']
body = lines[rf_start - 1:rf_end]
csrf = next(i for i, l in enumerate(body) if 'case "$feature_choice" in' in l)
starts = []
for i in range(len(body)):
    m = re.match(r'^\s*([0-9]+)\)\s*$', body[i])
    if m:
        starts.append((m.group(1), i))
blocks = {}
for k, (fid, i) in enumerate(starts):
    end = len(body) - 1
    for j in range(i + 1, len(body)):
        if re.match(r'^\s*(?:[0-9]+\)|\*\))', body[j]):
            end = j - 1
            break
    blocks[fid] = (i, end)
print('分支块:', len(blocks), sorted(blocks, key=int))


def rf_new_lines():
    drop = set()
    for fid in DENY_IDS:
        if fid in blocks:
            i, e = blocks[fid]
            drop.update(range(i, e + 1))
    out = [l for i, l in enumerate(body) if i not in drop]
    txt = '\n'.join(out)
    txt = txt.replace('case "$feature_choice" in 33|34) ;;',
                      'case "$feature_choice" in 34) ;;')
    out = txt.split('\n')
    return out


# ---------------- 物化 ----------------
def extent_ok(name):
    f = byname[name]
    d = 0
    for i in range(f['start'] - 1, f['true_end']):
        if inside[i]:
            continue
        for ch in lines[i]:
            if ch == '{':
                d += 1
            elif ch == '}':
                d -= 1
    return d == 0


def materialize(deny):
    """按行物化：只跳过被删函数的真实区间，其余原样保留（含文件末尾顶层入口）"""
    removed = {}
    for f in funcs:
        if f['name'] in deny and extent_ok(f['name']):
            removed[f['name']] = (f['start'], f['true_end'])
    skip = set()
    for s, e in removed.values():
        skip.update(range(s - 1, e))
    repl = {}
    for f in funcs:
        nm = f['name']
        if nm in MENU:
            repl[f['start'] - 1] = (MENU[nm].split('\n'), f['true_end'])
        elif nm == 'run_menu_feature':
            repl[f['start'] - 1] = (rf_new_lines(), f['true_end'])
    out = []
    i = 0
    while i < N:
        if i in repl:
            newlines, te = repl[i]
            out.extend(newlines)
            out.append('')
            i = te
            continue
        if i in skip:
            i += 1
            continue
        out.append(lines[i])
        i += 1
    return out


def refs(text_lines):
    out = set()
    for l in text_lines:
        for w in re.findall(r'(?<![A-Za-z0-9_])[A-Za-z_][A-Za-z0-9_]*', l):
            if w in known:
                out.add(w)
    return out


# ---------------- 不动点迭代 ----------------
deny = set(DENY_DIRECT) | {n for n in known if any(t in n.lower() for t in FAMILY)}
deny = {n for n in deny if n in byname}
# 禁选分支的 handler 必须删
for fid in DENY_IDS:
    if fid in blocks:
        txt = '\n'.join(body[blocks[fid][0]:blocks[fid][1] + 1])
        for w in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', txt):
            if w in known and w != 'run_recorded_menu_feature':
                deny.add(w)
print('初始候选:', len(deny))

# 迭代到不动点：被存活文本引用的必须撤删；未被引用的家族成员必须删
for it in range(1, 40):
    text = materialize(deny)
    r = refs(text)
    back = {d for d in deny if d in r}
    add = {c for c in known - deny
           if any(t in c.lower() for t in FAMILY) and c not in r}
    if not back and not add:
        print(f'迭代 {it}: 已收敛（候选 {len(deny)}）')
        break
    if back:
        print(f'迭代 {it}: 撤删 {len(back)} → {sorted(back)[:6]}')
    if add:
        print(f'迭代 {it}: 增删 {len(add)}')
    deny = (deny - back) | add
else:
    print('!! 未收敛')

text = materialize(deny)
r = refs(text)
bad = sorted({d for d in deny if d in r})
print()
print('=== 最终不变式：被删函数仍被存活文本引用 ===', len(bad))
for b in bad[:20]:
    print('   ', b)

# ---------------- 统计与写出 ----------------
deleted = [n for n in deny if extent_ok(n)]
kept_not_ok = [n for n in deny if not extent_ok(n)]
print()
print('=== 结果 ===')
print(f'原: {N} 行 / {len(funcs)} 函数')
print(f'删: {len(deleted)} 函数 / {sum(byname[n]["end"]-byname[n]["start"]+1 for n in deleted)} 行')
print(f'新: {len(text)} 行  (-{100 - len(text)*100//N}%)')
print('边界不可证明而保留:', kept_not_ok)

if DST:
    open(DST, 'w', encoding='utf-8', newline='\n').write('\n'.join(text) + '\n')
    print('已写出', DST)
json.dump({'deleted': sorted(deleted), 'deny_ids': sorted(DENY_IDS, key=int)},
          open('trim_plan.json', 'w', encoding='utf-8'), ensure_ascii=False, indent=1)
