#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
扩展插件「已安装」闭环:
  1. 部署 /usr/bin/kp-store-register、kp-store-unregister (Lua, 读写清单与注册表)
  2. 安装命令尾部追加注册动作 (装完自动进「已安装」)
  3. Lua 新增:
     - _kp_installed_registry()  读 /etc/kp_store/installed.list
     - nradio_appcenter_extra_installed_merge() 合并进 applist
     - nradio_appcenter_extra_action() 卸载分发(areuok->kp-areuok / opkg->is-opkg)
  4. 接入 action_app_list_data 合并链 与 action_app_core 分发
"""
import os, sys, time
import paramiko

HOST = os.environ.get('ROUTER_HOST', '192.168.66.1')
USER = os.environ.get('ROUTER_USER', 'root')
PW = os.environ.get('ROUTER_PW', '')
LUA = '/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua'
MANIFEST = '/etc/kp_store/plugins.json'
REG = '/etc/kp_store/installed.list'

REGISTER_LUA = r'''#!/usr/bin/lua
-- kp-store-register <pkg>  : 把清单中已安装的插件写入已安装注册表
local cjson = require "cjson"
local MANIFEST = "/etc/kp_store/plugins.json"
local REG = "/etc/kp_store/installed.list"

local pkg = arg[1]
if not pkg or pkg == "" then io.stderr:write("usage: kp-store-register <pkg>\n"); os.exit(1) end

local fh = io.open(MANIFEST, "r")
if not fh then io.stderr:write("manifest missing\n"); os.exit(1) end
local ok, dec = pcall(cjson.decode, fh:read("*a") or "")
fh:close()
if not ok or type(dec) ~= "table" or type(dec.plugins) ~= "table" then
	io.stderr:write("manifest broken\n"); os.exit(1)
end

local item = nil
for _, p in ipairs(dec.plugins) do
	if tostring(p.pkg or "") == pkg then item = p; break end
end
if not item then io.stderr:write("pkg not in manifest: " .. pkg .. "\n"); os.exit(2) end

-- 取实际安装版本
local ver = ""
local st = io.open("/usr/lib/opkg/status", "r")
if st then
	local cur, matched = nil, false
	for line in st:lines() do
		local p = line:match("^Package:%s*(%S+)")
		if p then
			cur, matched = p, (p == pkg)
		elseif matched then
			local s = line:match("^Status:%s*(.-)%s*$")
			if s then
				matched = (s:match("^install ok installed") or s:match("^install user installed")) ~= nil
			end
			if matched then
				local v = line:match("^Version:%s*(.-)%s*$")
				if v and v ~= "" then ver = v; break end
			end
		end
	end
	st:close()
end

-- 去重: 已存在则先移除
local lines = {}
local rf = io.open(REG, "r")
if rf then
	for line in rf:lines() do
		local f = {}
		for w in (line .. "|"):gmatch("([^|]*)|") do f[#f+1] = w end
		if tostring(f[3] or "") ~= pkg then lines[#lines+1] = line end
	end
	rf:close()
end

local row = table.concat({
	tostring(item.id or pkg),
	tostring(item.name or pkg),
	pkg,
	ver,
	tostring(os.time()),
	tostring(item.route or ""),
	tostring(item.source or "opkg"),
	tostring(item.des or "")
}, "|")
lines[#lines+1] = row

local wf = io.open(REG, "w")
if not wf then io.stderr:write("cannot write registry\n"); os.exit(1) end
wf:write(table.concat(lines, "\n") .. "\n")
wf:close()
print("registered: " .. pkg .. " " .. ver)
'''

UNREGISTER_LUA = r'''#!/usr/bin/lua
-- kp-store-unregister <pkg> : 从已安装注册表移除
local REG = "/etc/kp_store/installed.list"
local pkg = arg[1]
if not pkg or pkg == "" then os.exit(1) end
local rf = io.open(REG, "r")
if not rf then os.exit(0) end
local keep = {}
for line in rf:lines() do
	local f = {}
	for w in (line .. "|"):gmatch("([^|]*)|") do f[#f+1] = w end
	if tostring(f[3] or "") ~= pkg then keep[#keep+1] = line end
end
rf:close()
local wf = io.open(REG, "w")
if wf then
	if #keep > 0 then wf:write(table.concat(keep, "\n") .. "\n") end
	wf:close()
end
print("unregistered: " .. pkg)
'''

EXTRA_HELPERS = r'''
-- ============ 扩展插件「已安装」注册表 ============
local function _kp_installed_registry()
\tlocal vfs = require "nixio.fs"
\tlocal rows = {}
\tlocal raw = vfs.readfile("/etc/kp_store/installed.list") or ""
\tfor line in raw:gmatch("[^\r\n]+") do
\t\tlocal f = {}
\t\tfor w in (line .. "|"):gmatch("([^|]*)|") do f[#f+1] = w end
\t\tif f[1] and #f[1] > 0 then rows[#rows+1] = f end
\tend
\treturn rows
end

local function nradio_appcenter_extra_installed_merge(parameter)
\tif type(parameter) ~= "table" then parameter = { applist = {} } end
\tif type(parameter.applist) ~= "table" then parameter.applist = {} end
\tlocal rows = _kp_installed_registry()
\tif #rows == 0 then return parameter end
\t-- 注意: _kp_installed_set 定义在文件后部(online_list 附近), 此处不可见,
\t-- 故复用前面已定义的 _areuok_full_inst() 取已安装包集合
\tlocal inst = _areuok_full_inst()

\tlocal existing = {}
\tfor _, e in ipairs(parameter.applist) do
\t\tif type(e) == "table" and e.name then existing[tostring(e.name)] = true end
\tend

\tfor _, f in ipairs(rows) do
\t\t-- 字段: 1 id 2 title 3 pkg 4 ver 5 time 6 route 7 source 8 描述
\t\tlocal id, title, pkg, ver, route, src, des = f[1], f[2], f[3] or "", f[4] or "", f[6] or "", f[7] or "opkg", f[8] or ""
\t\tif (inst[pkg] or src == "docker") and not existing[title] then
\t\t\tlocal route_n = route:gsub("^/cgi%-bin/luci/", ""):gsub("^/", "")
\t\t\ttable.insert(parameter.applist, {
\t\t\t\tname = title,
\t\t\t\tversion = tostring(ver),
\t\t\t\tsize = 0,
\t\t\t\tstatus = 1,
\t\t\t\thas_luci = (#route_n > 0) and 1 or 0,
\t\t\t\topen = 0,
\t\t\t\ticon = _online_icon_sync("extra-" .. id, ""),
\t\t\t\tdes = des,
\t\t\t\taction_status = 0,
\t\t\t\tluci_module_route = route_n,
\t\t\t\tonline_key = "extra-" .. id
\t\t\t})
\t\t\texisting[title] = true
\t\tend
\tend
\treturn parameter
end

local function nradio_appcenter_extra_action(name, action)
\tif not name or #name == 0 then return nil end
\tlocal key = tostring(name):gsub("^extra%-", "")
\tlocal rows = _kp_installed_registry()
\tfor _, f in ipairs(rows) do
\t\tif f[1] == key or f[2] == name or ("extra-" .. f[1]) == name then
\t\t\tlocal util = require "luci.util"
\t\t\tif action == "uninstall" then
\t\t\t\tif tostring(f[7] or "") == "areuok" then
\t\t\t\t\tutil.exec("kp-areuok uninstall " .. f[1] .. " >/tmp/nradio-extra-uninstall.log 2>&1")
\t\t\t\telse
\t\t\t\t\tutil.exec("is-opkg remove " .. f[3] .. " >/tmp/nradio-extra-uninstall.log 2>&1")
\t\t\t\tend
\t\t\t\tutil.exec("kp-store-unregister " .. f[3] .. " >/dev/null 2>&1")
\t\t\t\treturn { code = 0, msg = "卸载成功" }
\t\t\tend
\t\t\treturn { code = 0, msg = "OK" }
\t\tend
\tend
\treturn nil
end
'''

CHAIN_OLD = '\treturn nradio_appcenter_version_sync(nradio_appcenter_local_apps_merge(nradio_appcenter_online_installed_merge(nradio_appcenter_areuok_installed_merge(nradio_appcenter_runtime_compat_v2(applist.parameter)))))'
CHAIN_NEW = '\treturn nradio_appcenter_version_sync(nradio_appcenter_local_apps_merge(nradio_appcenter_online_installed_merge(nradio_appcenter_extra_installed_merge(nradio_appcenter_areuok_installed_merge(nradio_appcenter_runtime_compat_v2(applist.parameter))))))'

DISPATCH_OLD = (
    'local online_result = nradio_appcenter_online_action(name, action)\n'
    '\tif online_result then\n'
    '\t\tluci.nradio.luci_call_result(online_result)\n'
    '\t\treturn\n'
    '\tend'
)
DISPATCH_NEW = (
    '\tlocal extra_result = nradio_appcenter_extra_action(name, action)\n'
    '\tif extra_result then\n'
    '\t\tluci.nradio.luci_call_result(extra_result)\n'
    '\t\treturn\n'
    '\tend\n'
    '\n'
    'local online_result = nradio_appcenter_online_action(name, action)\n'
    '\tif online_result then\n'
    '\t\tluci.nradio.luci_call_result(online_result)\n'
    '\t\treturn\n'
    '\tend'
)

INSTALL_CMD_OLD = '''\t\t\t\tif tostring(extra.source or "") == "areuok" then
\t\t\t\t\tcmd = "kp-areuok install " .. _online_shquote(tostring(extra.id or ""))
\t\t\t\telse
\t\t\t\t\tcmd = "is-opkg install " .. _online_shquote(pkg)
\t\t\t\tend'''
INSTALL_CMD_NEW = '''\t\t\t\tif tostring(extra.source or "") == "areuok" then
\t\t\t\t\t-- kp-areuok 内部会自己登记到 /etc/areuok_registry.list, 无需重复注册
\t\t\t\t\tcmd = "kp-areuok install " .. _online_shquote(tostring(extra.id or ""))
\t\t\t\telse
\t\t\t\t\tcmd = "is-opkg install " .. _online_shquote(pkg) ..
\t\t\t\t\t\t" && kp-store-register " .. _online_shquote(pkg)
\t\t\t\tend'''


def sh(c, cmd, t=90):
    _, o, e = c.exec_command(cmd, timeout=t)
    return o.read().decode('utf-8', 'replace'), e.read().decode('utf-8', 'replace')


def main():
    c = paramiko.SSHClient()
    c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    c.connect(HOST, 22, USER, PW, timeout=12)
    sftp = c.open_sftp()

    # 1) 部署注册/注销脚本
    for path, body in (('/usr/bin/kp-store-register', REGISTER_LUA),
                       ('/usr/bin/kp-store-unregister', UNREGISTER_LUA)):
        with sftp.open(path, 'w') as f:
            f.write(body)
        sh(c, 'chmod +x %s' % path)
    print('已部署: /usr/bin/kp-store-register, /usr/bin/kp-store-unregister')
    out, err = sh(c, 'lua -e "assert(loadfile(\'/usr/bin/kp-store-register\')); print(\'OK\')" 2>&1', 30)
    print('注册脚本语法:', (out + err).strip())

    # 2) Lua 补丁
    # 2.0 自检: 若现有文件语法不通过, 先回滚到最近的备份
    out, err = sh(c, "lua -e \"assert(loadfile('%s')); print('SYNTAX_OK')\" 2>&1" % LUA, 30)
    if 'SYNTAX_OK' not in (out + err):
        # 按时间戳倒序, 并校验内容含关键补丁, 避免退回过旧版本
        d = os.path.dirname(LUA)
        import re
        def _ts(n):
            m = re.search(r'(\d{8}_\d{6})', n)
            return m.group(1) if m else '0'
        cands = sorted([n for n in sftp.listdir(d) if n.startswith('appcenter.lua.bak-')],
                       key=_ts, reverse=True)
        for n in cands:
            with sftp.open(d + '/' + n, 'r') as f:
                body = f.read().decode('utf-8')
            if all(k in body for k in ('nradio_appcenter_areuok_installed_merge',
                                       'action_online_precheck',
                                       '_kp_extra_merge')):
                with sftp.open(LUA, 'w') as f:
                    f.write(body)
                print('! 现有文件语法异常, 已回滚到含完整补丁的备份:', n)
                break

    with sftp.open(LUA, 'r') as f:
        src = f.read().decode('utf-8')

    changed = False
    if 'nradio_appcenter_extra_installed_merge' not in src:
        bak = LUA + '.bak-extrainst-' + time.strftime('%Y%m%d_%H%M%S')
        with sftp.open(bak, 'w') as f:
            f.write(src)
        print('备份:', bak)
        assert 'function action_app_list_data()' in src
        # 源串是 raw 字符串, 需把字面 \t 转成真正的制表符
        src = src.replace('function action_app_list_data()',
                          EXTRA_HELPERS.replace('\\t', '\t') + '\nfunction action_app_list_data()', 1)
        print('  + extra 辅助函数已插入')
        changed = True

    if 'nradio_appcenter_extra_installed_merge(nradio_appcenter_areuok' not in src:
        if CHAIN_OLD not in src:
            print('  ! 合并链锚点未找到(可能已改), 跳过链式插入')
        else:
            src = src.replace(CHAIN_OLD, CHAIN_NEW, 1)
            print('  + 合并链已插入')
            changed = True

    # 注意: 必须判断"调用点"而非函数定义, 否则会被定义自身的同名文本误判为已插入
    if 'local extra_result = nradio_appcenter_extra_action' not in src:
        if DISPATCH_OLD not in src:
            print('  ! 分发锚点未找到, 跳过分发插入')
        else:
            src = src.replace(DISPATCH_OLD, DISPATCH_NEW, 1)
            print('  + 卸载分发已插入')
            changed = True

    if INSTALL_CMD_OLD in src:
        src = src.replace(INSTALL_CMD_OLD, INSTALL_CMD_NEW, 1)
        print('  + 安装命令追加注册动作')
        changed = True

    if changed:
        with sftp.open(LUA, 'w') as f:
            f.write(src)
        print('LUA: 补丁已写入')

    out, err = sh(c, "lua -e \"assert(loadfile('%s')); print('SYNTAX_OK')\" 2>&1" % LUA, 30)
    print('语法校验:', (out + err).strip())

    # 3) 把当前已装的扩展插件补登记(例如刚装的 nlbwmon)
    print(sh(c, 'lua /usr/bin/kp-store-register luci-app-nlbwmon 2>&1')[0])
    sh(c, "rm -rf /tmp/luci-indexcache* /tmp/luci-modulecache")
    print('缓存已清理')
    sftp.close(); c.close()


if __name__ == '__main__':
    main()
