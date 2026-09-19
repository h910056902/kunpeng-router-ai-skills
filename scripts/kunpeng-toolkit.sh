#!/bin/sh
# ============================================================
#  鲲鹏 C2000 Max 深度定制工具箱 (kunpeng-toolkit) v1.0
#  一键打包: 商店增强 / Docker 适配 / AGH DNS 接管 / 体检 / 回滚
#  适用: NRadio_C2000MAX 官方 NROS (OpenWrt 21.02.7, mt7987/aarch64)
#  特性: 幂等(可重复执行)、改前备份、语法校验后才落盘
#  免责: 自用学习项目, 禁止付费传播; 变砖风险自负
# ============================================================
set -u
umask 077

VER="1.0"
LUA='/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua'
HTM='/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm'
KP_DIR='/etc/kp_store'
BAKROOT='/root/kp-toolkit-backup'
TS="$(date +%Y%m%d_%H%M%S)"

c_msg() { printf '\033[32m[OK]\033[0m %s\n' "$1"; }
w_msg() { printf '\033[33m[!!]\033[0m %s\n' "$1"; }
e_msg() { printf '\033[31m[X]\033[0m %s\n' "$1"; }
line()  { printf '--------------------------------------------\n'; }

need_root() {
    [ "$(id -u)" = '0' ] || { e_msg '请用 root 运行 (ssh root@192.168.66.1)'; exit 1; }
}

backup_file() {
    f="$1"; [ -f "$f" ] || return 0
    mkdir -p "$BAKROOT"
    cp "$f" "$BAKROOT/$(echo "$f" | tr '/' '_').$TS"
    c_msg "已备份: $f -> $BAKROOT"
}

# ============ 模块 1: 系统体检 ============
do_check() {
    line; printf '鲲鹏工具箱体检 v%s\n' "$VER"; line
    printf '内存: '; free -k | grep Mem | awk '{printf "总量%dMB 可用约%dMB\n", $2/1024, ($7)/1024}'
    t=$(awk '{printf "%d", $1/1000}' /sys/class/thermal/thermal_zone0/temp 2>/dev/null)
    [ -n "$t" ] && printf '温度: %d°C%s\n' "$t" "$([ "$t" -gt 70 ] && echo ' (偏热!)')"
    printf '磁盘: '; df -h /overlay | tail -1 | awk '{print $4" 空闲 / "$2}'
    echo; printf '-- Docker --\n'
    if opkg list-installed | grep -q '^dockerd '; then
        c_msg "dockerd 已装 ($(docker info 2>/dev/null | grep 'Server Version' | awk '{print $NF}'))"
    else
        w_msg 'dockerd 未安装 (菜单 4 可适配)'
    fi
    printf -- '-- AdGuard Home --\n'
    if docker ps 2>/dev/null | grep -q adguard; then
        c_msg 'AGH 容器运行中'
        p=$(grep -A2 'dns:' /opt/docker/data/adguard/AdGuardHome.yaml 2>/dev/null | grep 'port:' | head -1 | awk '{print $2}')
        [ -n "$p" ] && printf '  AGH DNS 端口: %s\n' "$p"
    else
        w_msg 'AGH 容器未运行'
    fi
    printf -- '-- DNS 链路 (53=AGH 5354=dnsmasq 7874=OpenClash) --\n'
    netstat -lnup 2>/dev/null | grep -E ':53 |:5354 |:7874 ' | awk '{print "  "$4" <- "$NF}' | sort -u
    echo; printf -- '-- 我们的商店补丁指纹 --\n'
    ok=0; total=0
    for m in nradio_appcenter_extra_installed_merge nradio_appcenter_extra_action \
             _kp_installed_registry _online_install_percent '&& kp-store-register'; do
        total=$((total+1))
        if grep -q "$m" "$LUA" 2>/dev/null; then ok=$((ok+1)); c_msg "lua: $m"
        else e_msg "lua 缺失: $m"; fi
    done
    total=$((total+1))
    if grep -q 'aurora_open_app' "$HTM" 2>/dev/null; then ok=$((ok+1)); c_msg 'htm: aurora_open_app'
    else e_msg 'htm 缺失: aurora_open_app (打开按钮)'; fi
    printf '补丁完好率: %d/%d\n' "$ok" "$total"
    printf -- '-- maye 插件助手 --\n'
    [ -d /root/.nradio-plugin-menu ] && w_msg '已安装过 (改商店文件的脚本, 跑完记得复查指纹)' || c_msg '未安装'
}

# ============ 模块 2: 商店增强补丁 (lua 增量, 幂等) ============
LUA_PATCHER='
-- 纯字面替换工具(不用 pattern, 避免 ()% 特殊字符问题)
local function plain_replace(s, old, new)
    local i, j = s:find(old, 1, true)
    if not i then return s, false end
    return s:sub(1, i - 1) .. new .. s:sub(j + 1), true
end

local f = arg[1]
local fh = io.open(f, "r"); if not fh then os.exit(2) end
local src = fh:read("*a"); fh:close()
local changed = false

-- 1) 辅助函数块 (注册表读取/合并/卸载分发)
if not src:find("_kp_installed_registry", 1, true) then
    local helpers = [===[-- ============ kp 扩展插件「已安装」注册表 ============
local function _kp_installed_registry()
    local vfs = require "nixio.fs"
    local rows = {}
    local raw = vfs.readfile("/etc/kp_store/installed.list") or ""
    for line in raw:gmatch("[^\r\n]+") do
        local fl = {}
        for w in (line .. "|"):gmatch("([^|]*)|") do fl[#fl+1] = w end
        if fl[1] and #fl[1] > 0 then rows[#rows+1] = fl end
    end
    return rows
end

-- opkg 已装包索引(v1.1 内建, 兼容无 iStore 固件)
local function _areuok_full_inst()
    local t = {}
    local f = io.open("/usr/lib/opkg/status", "r")
    if not f then return t end
    local cur
    for line in f:lines() do
        if line:sub(1, 9) == "Package: " then
            cur = line:sub(10)
        elseif line:sub(1, 8) == "Status: " and cur and line:find("installed", 1, true) then
            t[cur] = true
        end
    end
    f:close()
    return t
end

local function nradio_appcenter_extra_installed_merge(parameter)
    if type(parameter) ~= "table" then parameter = { applist = {} } end
    if type(parameter.applist) ~= "table" then parameter.applist = {} end
    local rows = _kp_installed_registry()
    if #rows == 0 then return parameter end
    local inst = _areuok_full_inst()
    local existing = {}
    for _, e in ipairs(parameter.applist) do
        if type(e) == "table" and e.name then existing[tostring(e.name)] = true end
    end
    for _, fl in ipairs(rows) do
        local id, title, pkg, ver, route, src2, des = fl[1], fl[2], fl[3] or "", fl[4] or "", fl[6] or "", fl[7] or "opkg", fl[8] or ""
        if (inst[pkg] or src2 == "docker") and not existing[title] then
            local route_n = route:gsub("^/cgi%-bin/luci/", ""):gsub("^/", "")
            table.insert(parameter.applist, {
                name = title, version = tostring(ver), size = 0, status = 1,
                has_luci = (#route_n > 0) and 1 or 0, open = 0,
                icon = _online_icon_sync("extra-" .. id, ""),
                des = des, action_status = 0, luci_module_route = route_n,
                online_key = "extra-" .. id
            })
            existing[title] = true
        end
    end
    return parameter
end

local function nradio_appcenter_extra_action(name, action)
    if not name or #name == 0 then return nil end
    local key = tostring(name):gsub("^extra%-", "")
    local rows = _kp_installed_registry()
    for _, fl in ipairs(rows) do
        if fl[1] == key or fl[2] == name or ("extra-" .. fl[1]) == name then
            local util = require "luci.util"
            if action == "uninstall" then
                if tostring(fl[7] or "") == "areuok" then
                    util.exec("kp-areuok uninstall " .. fl[1] .. " >/tmp/nradio-extra-uninstall.log 2>&1")
                elseif tostring(fl[7] or "") == "docker" then
                    util.exec("docker rm -f " .. fl[1] .. " >/tmp/nradio-extra-uninstall.log 2>&1")
                else
                    util.exec("is-opkg remove " .. fl[3] .. " >/tmp/nradio-extra-uninstall.log 2>&1")
                end
                util.exec("kp-store-unregister " .. fl[3] .. " >/dev/null 2>&1")
                return { code = 0, msg = "卸载成功" }
            end
            return { code = 0, msg = "OK" }
        end
    end
    return nil
end

function action_app_list_data()]===]
    local anchor = "function action_app_list_data()"
    local ok1
    src, ok1 = plain_replace(src, anchor, helpers)
    if not ok1 then print("E:no anchor"); os.exit(3) end
    changed = true
end

-- 2) 合并链
if not src:find("extra_installed_merge(nradio_appcenter_areuok", 1, true) then
    local old1 = "online_installed_merge(nradio_appcenter_areuok_installed_merge"
    local new1 = "online_installed_merge(nradio_appcenter_extra_installed_merge(nradio_appcenter_areuok_installed_merge"
    local ok2
    src, ok2 = plain_replace(src, old1, new1)
    if ok2 then
        src = plain_replace(src, "runtime_compat_v2(applist.parameter)))))",
                                "runtime_compat_v2(applist.parameter))))))")
        changed = true
    end
end

-- 3) 卸载分发挂进 app_core
if not src:find("local extra_result = nradio_appcenter_extra_action", 1, true) then
    local oldd = "local online_result = nradio_appcenter_online_action(name, action)\n\tif online_result then\n\t\tluci.nradio.luci_call_result(online_result)\n\t\treturn\n\tend"
    local newd = "\tlocal extra_result = nradio_appcenter_extra_action(name, action)\n\tif extra_result then\n\t\tluci.nradio.luci_call_result(extra_result)\n\t\treturn\n\tend\n\nlocal online_result = nradio_appcenter_online_action(name, action)\n\tif online_result then\n\t\tluci.nradio.luci_call_result(online_result)\n\t\treturn\n\tend"
    local ok3
    src, ok3 = plain_replace(src, oldd, newd)
    if ok3 then changed = true end
end

-- 4) 安装命令尾部自动注册
if not src:find("&& kp-store-register", 1, true) then
    local oldi = "cmd = \"is-opkg install \" .. _online_shquote(pkg)\n\t\t\t\tend"
    local newi = "cmd = \"is-opkg install \" .. _online_shquote(pkg) ..\n\t\t\t\t\t\" && kp-store-register \" .. _online_shquote(pkg)\n\t\t\t\tend"
    local ok4
    src, ok4 = plain_replace(src, oldi, newi)
    if ok4 then changed = true end
end

if not changed then print("noop"); os.exit(0) end
local w = io.open(f, "w"); w:write(src); w:close()
print("patched")
'

do_store() {
    line; printf '商店增强补丁 (lua 增量, 幂等)\n'; line
    [ -f "$LUA" ] || { e_msg '找不到 appcenter.lua'; return 1; }
    # 快速指纹 (新旧版固件锚点均可)
    if grep -q '_kp_installed_registry' "$LUA" && \
       { grep -q 'extra_installed_merge(nradio_appcenter_areuok' "$LUA" || \
         grep -q 'nradio_appcenter_extra_installed_merge(applist.parameter)' "$LUA"; } && \
       { grep -q 'local extra_result = nradio_appcenter_extra_action' "$LUA" || \
         grep -q 'local er = nradio_appcenter_extra_action' "$LUA"; }; then
        c_msg 'lua 后端补丁已全部在位, 跳过'
    else
        backup_file "$LUA"
        printf '%s' "$LUA_PATCHER" > /tmp/kp_lua_patch.lua
        lua /tmp/kp_lua_patch.lua "$LUA"
        rc=$?
        if [ $rc -eq 0 ] && lua -e "assert(loadfile('$LUA')); print('SYNTAX_OK')" 2>&1 | grep -q SYNTAX_OK; then
            c_msg 'lua 补丁已写入且语法校验通过'
        else
            e_msg "lua 补丁失败(rc=$rc), 已自动回滚"
            latest=$(ls -t "$BAKROOT" 2>/dev/null | head -1)
            [ -n "$latest" ] && cp "$BAKROOT/$latest" "$LUA" && c_msg "已回滚: $latest"
            return 1
        fi
    fi
    # 注册/注销脚本
    if [ ! -f /usr/bin/kp-store-register ]; then
        cat > /usr/bin/kp-store-register <<'EOF_REG'
#!/usr/bin/lua
local cjson = require "cjson"
local MANIFEST = "/etc/kp_store/plugins.json"
local REG = "/etc/kp_store/installed.list"
local pkg = arg[1]
if not pkg or pkg == "" then io.stderr:write("usage: kp-store-register <pkg>\n"); os.exit(1) end
local fh = io.open(MANIFEST, "r")
if not fh then io.stderr:write("manifest missing\n"); os.exit(1) end
local ok, dec = pcall(cjson.decode, fh:read("*a") or ""); fh:close()
if not ok or type(dec) ~= "table" then io.stderr:write("manifest broken\n"); os.exit(1) end
local item = nil
for _, p in ipairs(dec.plugins or dec) do
    if tostring(p.pkg or "") == pkg then item = p; break end
end
if not item then io.stderr:write("pkg not in manifest\n"); os.exit(2) end
local ver = ""
local st = io.open("/usr/lib/opkg/status", "r")
if st then
    local cur, matched = nil, false
    for line in st:lines() do
        local p = line:match("^Package:%s*(%S+)")
        if p then cur, matched = p, (p == pkg)
        elseif matched then
            local s = line:match("^Status:%s*(.-)%s*$")
            if s then matched = (s:match("^install ok installed") or s:match("^install user installed")) ~= nil end
            if matched then
                local v = line:match("^Version:%s*(.-)%s*$")
                if v and v ~= "" then ver = v; break end
            end
        end
    end
    st:close()
end
local lines = {}
local rf = io.open(REG, "r")
if rf then
    for line in rf:lines() do
        local fl = {}
        for w in (line .. "|"):gmatch("([^|]*)|") do fl[#fl+1] = w end
        if tostring(fl[3] or "") ~= pkg then lines[#lines+1] = line end
    end
    rf:close()
end
local row = table.concat({tostring(item.id or pkg), tostring(item.name or pkg), pkg, ver,
    tostring(os.time()), tostring(item.route or ""), tostring(item.source or "opkg"),
    tostring(item.des or "")}, "|")
lines[#lines+1] = row
local wf = io.open(REG, "w")
if not wf then io.stderr:write("cannot write registry\n"); os.exit(1) end
wf:write(table.concat(lines, "\n") .. "\n"); wf:close()
print("registered: " .. pkg .. " " .. ver)
EOF_REG
        chmod +x /usr/bin/kp-store-register
    fi
    if [ ! -f /usr/bin/kp-store-unregister ]; then
        cat > /usr/bin/kp-store-unregister <<'EOF_UNREG'
#!/usr/bin/lua
local REG = "/etc/kp_store/installed.list"
local pkg = arg[1]
if not pkg or pkg == "" then os.exit(1) end
local rf = io.open(REG, "r")
if not rf then os.exit(0) end
local keep = {}
for line in rf:lines() do
    local fl = {}
    for w in (line .. "|"):gmatch("([^|]*)|") do fl[#fl+1] = w end
    if tostring(fl[3] or "") ~= pkg then keep[#keep+1] = line end
end
rf:close()
local wf = io.open(REG, "w")
if wf then
    if #keep > 0 then wf:write(table.concat(keep, "\n") .. "\n") end
    wf:close()
end
print("unregistered: " .. pkg)
EOF_UNREG
        chmod +x /usr/bin/kp-store-unregister
    fi
    c_msg 'kp-store-register / unregister 就绪'
    grep -q 'aurora_open_app' "$HTM" 2>/dev/null \
        && c_msg 'htm 打开按钮补丁在位' \
        || w_msg 'htm 打开按钮补丁缺失 (前端补丁暂由 PC 端 patches/patch_online_ui.py 维护)'
    rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache 2>/dev/null
    c_msg 'LuCI 缓存已清理'
}

# ============ 模块 3: Docker 适配 ============
STUBS="kmod-veth kmod-br-netfilter kmod-ikconfig kmod-nf-ipvs kmod-fs-btrfs kmod-dm"

make_stub() {
    name="$1"; d="/tmp/kpstub/$name"
    rm -rf "$d"; mkdir -p "$d/control" "$d/data" "$d/outer"
    cat > "$d/control/control" <<EOF_C
Package: $name
Version: 5.4.281-1
Architecture: aarch64_cortex-a53
Priority: optional
Maintainer: kp-stub
Section: kernel
Description: STUB - satisfies dep; module built-in or not required
EOF_C
    (cd "$d/control" && tar czf "$d/control.tar.gz" .) 2>/dev/null
    (cd "$d/data" && tar czf "$d/data.tar.gz" .) 2>/dev/null
    echo "2.0" > "$d/outer/debian-binary"
    cp "$d/control.tar.gz" "$d/data.tar.gz" "$d/outer/" 2>/dev/null
    (cd "$d/outer" && tar czf "/tmp/kpstub/${name}_5.4.281-1_aarch64_cortex-a53.ipk" \
        ./debian-binary ./control.tar.gz ./data.tar.gz) 2>/dev/null
}

do_docker() {
    line; printf 'Docker 适配 (host 网络 + vfs + 1G swap)\n'; line
    if opkg list-installed | grep -q '^dockerd '; then
        c_msg 'dockerd 已安装, 跳过 (重装请先 opkg remove dockerd)'
        docker info 2>/dev/null | grep -E 'Server Version|Storage Driver' | sed 's/^/  /'
        return 0
    fi
    # 1) swap
    if [ ! -f /overlay/.docker-swap ]; then
        c_msg '创建 1G swap (约 1 分钟)...'
        dd if=/dev/zero of=/overlay/.docker-swap bs=1M count=1024 2>&1 | tail -1
        chmod 600 /overlay/.docker-swap && mkswap /overlay/.docker-swap >/dev/null 2>&1
    fi
    swapon /overlay/.docker-swap 2>/dev/null
    if ! grep -q '.docker-swap' /etc/rc.local 2>/dev/null; then
        sed -i 's/^exit 0$/swapon \/overlay\/.docker-swap 2>\/dev\/null\nexit 0/' /etc/rc.local 2>/dev/null || \
            printf 'swapon /overlay/.docker-swap 2>/dev/null\nexit 0\n' >> /etc/rc.local
        c_msg 'swap 已加入开机自启'
    else
        c_msg 'swap 就绪'
    fi
    # 2) feed
    if ! grep -q 'aarch64_cortex-a53/packages' /etc/opkg/customfeeds.conf 2>/dev/null; then
        printf '\nsrc/gz owrt21027_pkgs https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages\n' >> /etc/opkg/customfeeds.conf
        c_msg '已添加 alpine/openwrt packages feed'
    fi
    opkg update >/dev/null 2>&1
    # 3) stubs
    mkdir -p /tmp/kpstub
    for s in $STUBS; do
        make_stub "$s"
        opkg install "/tmp/kpstub/${s}_5.4.281-1_aarch64_cortex-a53.ipk" >/dev/null 2>&1
    done
    ok=0; for s in $STUBS; do opkg list-installed | grep -q "^$s " && ok=$((ok+1)); done
    c_msg "stub 依赖登记: $ok/6"
    [ "$ok" -lt 6 ] && { e_msg 'stub 不全, 中止'; return 1; }
    # 4) 安装引擎
    rm -f /var/lock/opkg.lock 2>/dev/null
    c_msg '安装 dockerd / docker / docker-compose (需几分钟)...'
    opkg install dockerd docker docker-compose >/tmp/kp-docker-install.log 2>&1 \
        || { e_msg '安装失败, 日志: /tmp/kp-docker-install.log'; tail -5 /tmp/kp-docker-install.log; return 1; }
    c_msg '引擎安装完成'
    # 5) daemon.json
    mkdir -p /etc/docker /opt/docker
    cat > /etc/docker/daemon.json <<'EOF_D'
{
  "bridge": "none",
  "storage-driver": "vfs",
  "data-root": "/opt/docker",
  "log-level": "warn",
  "log-driver": "json-file",
  "log-opts": {"max-size": "10m", "max-file": "3"}
}
EOF_D
    c_msg 'daemon.json: bridge=none + vfs + /opt/docker + 日志轮转'
    # 6) 启动
    /etc/init.d/dockerd enable >/dev/null 2>&1
    /etc/init.d/dockerd start >/dev/null 2>&1
    sleep 6
    docker info 2>/dev/null | grep -E 'Server Version|Storage Driver' | sed 's/^/  /'
    # 7) 商店注册
    if [ -f /usr/bin/kp-store-register ] && [ -f "$KP_DIR/plugins.json" ]; then
        lua -e 'local cjson=require"cjson"; local f=io.open("/etc/kp_store/plugins.json"); local d=cjson.decode(f:read("*a")); f:close(); local lst=d; local wrap=false; if type(d)=="table" and d.plugins then lst=d.plugins; wrap=true end; local found=false; for _,x in ipairs(lst) do if x.id=="docker" then found=true end end; if not found then table.insert(lst,{id="docker",name="Docker 容器",pkg="dockerd",source="opkg",tags={"system","net"},des="Docker 引擎 20.10（host 网络模式；docker / docker-compose 可用，镜像数据在 /opt/docker）"}) end; local w=io.open("/etc/kp_store/plugins.json","w"); if wrap then w:write(cjson.encode(d)) else w:write(cjson.encode(lst)) end; w:close()'
        kp-store-register dockerd 2>&1 | tail -1
        rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache 2>/dev/null
        c_msg '已注册进商店'
    fi
    c_msg 'Docker 适配完成。试一下: docker run --rm --network=host alpine echo OK'
}

# ============ 模块 4: AGH/DNS 体检与修复 ============
do_agh() {
    line; printf 'AGH / DNS 链路\n'; line
    Y=/opt/docker/data/adguard/AdGuardHome.yaml
    [ -f "$Y" ] || { e_msg "找不到 $Y"; return 1; }
    cur=$(grep -A2 '^dns:' "$Y" | grep 'port:' | head -1 | awk '{print $2}')
    printf 'AGH DNS 端口: %s (目标 53)\n' "${cur:-?}"
    dnsmasq_53=$(netstat -lnup 2>/dev/null | grep ':53 ' | grep -cv adguard)
    printf 'dnsmasq 占用 53: %s\n' "$([ "$dnsmasq_53" = '0' ] && echo 否 || echo 是)"
    if [ "${cur:-0}" = '53' ] && [ "$dnsmasq_53" = '0' ]; then
        c_msg '链路正常, 无需修复'
        return 0
    fi
    printf '\n执行修复将: 1) dnsmasq 迁到 5354  2) AGH DNS 端口改 53  3) 按序重启\n'
    printf '确认修复? [y/N]: '
    read ans
    [ "$ans" = 'y' ] || return 0
    cp /etc/config/dhcp /root/kp-dhcp-bak.$TS
    cp "$Y" "$Y.bak-$TS"
    if ! uci -q get dhcp.@dnsmasq[0].port >/dev/null 2>&1; then
        uci set dhcp.@dnsmasq[0].port='5354'
        uci commit dhcp
        /etc/init.d/dnsmasq restart
        c_msg 'dnsmasq 已迁至 5354'
    fi
    sed -i "/^dns:/,\$s/^\(\s*port:\s*\).*/\153/" "$Y"
    docker restart adguard >/dev/null 2>&1
    sleep 5
    netstat -lnup 2>/dev/null | grep ':53 ' | grep -q adguard \
        && c_msg 'AGH 已接管 :53' || e_msg '53 未被 AGH 接管, 查 docker logs adguard'
    c_msg "回滚备份: /root/kp-dhcp-bak.$TS 与 $Y.bak-$TS"
}

# ============ 模块 5: 备份清单 ============
do_backups() {
    line; printf '备份清单\n'; line
    for d in "$BAKROOT" /root/nradio-plugin-fix "$KP_DIR"; do
        [ -d "$d" ] && { printf '[%s]\n' "$d"; ls -lt "$d" 2>/dev/null | head -6 | tail -5; }
    done
    printf '[appcenter 备份(最近5)]\n'
    ls -t /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua.bak-* 2>/dev/null | head -5
}

# ============ 主菜单 ============
main_menu() {
    while :; do
        line
        printf '鲲鹏 C2000 Max 深度定制工具箱 v%s\n' "$VER"
        line
        printf '1. 系统体检 (内存/温度/DNS/补丁指纹)\n'
        printf '2. 商店增强补丁 安装/修复\n'
        printf '3. Docker 适配 (host+vfs+swap)\n'
        printf '4. AGH/DNS 接管检查与修复\n'
        printf '5. 备份清单\n'
        printf '0. 退出\n'
        printf '请选择: '
        read ch
        case "$ch" in
            1) do_check ;;
            2) do_store ;;
            3) do_docker ;;
            4) do_agh ;;
            5) do_backups ;;
            0) exit 0 ;;
            *) w_msg '无效输入' ;;
        esac
    done
}

need_root
case "${1:-}" in
    check)   do_check ;;
    store)   do_store ;;
    docker)  do_docker ;;
    agh)     do_agh ;;
    backups) do_backups ;;
    menu|"") main_menu ;;
    *) printf '用法: sh kunpeng-toolkit.sh [check|store|docker|agh|backups|menu]\n' ;;
esac
