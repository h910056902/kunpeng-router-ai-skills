# -*- coding: utf-8 -*-
"""路由器远程操作公共库（**无 SFTP 环境专用**）。

为什么需要它：鲲鹏官方精简固件 **没有 sftp-server 子系统**，
paramiko 的 `open_sftp()` 会直接抛 `SSHException: EOF during negotiation`。
所以文件传输只能走 `exec_command`：
  - 文本 → heredoc `cat > f << 'TAG'` + md5sum 对账
  - 二进制 → `printf '\\NNN\\NNN...' > f`（固件无 base64/openssl/xxd，printf 是唯一通道）
另外补了断线重连（长任务中途 SSH 被 reset 是常态）。

凭据：**一律从环境变量读，绝不写死在脚本里**
    ROUTER_HOST（默认 192.168.66.1）/ ROUTER_USER（默认 root）/ ROUTER_PW（必填）

用法：
    export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<密码>
    from rtr_lib import Rtr
    r = Rtr()
    r.p(r.run("free -k | head -2"))
    r.put_text_verified("/etc/foo.conf", text)
    r.put_bin_verified("/tmp/bar.ipk", blob)
    r.close()
"""
import os
import sys
import io
import time
import hashlib

import paramiko

# ⚠️ Windows 控制台默认 GBK，打印 ✓ / ✗ / · 这类字符会抛
#    UnicodeEncodeError 并把整个脚本打挂（现象很误导：进程恰好 ~2 分钟退出、零输出，
#    看起来像"设备连不上"）。这里统一把 stdout/stderr 改成 UTF-8 + 替换非法字符，
#    从根上避免。要在 import 之后才安全（避免影响调用方的编码设置）。
for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _env(name, default=None, required=False):
    v = os.environ.get(name)
    if not v:
        if required:
            raise SystemExit("环境变量 %s 未设置（本脚本不保存任何凭据）" % name)
        return default
    return v


class Rtr:
    def __init__(self, host=None, user=None, pw=None, timeout=15):
        self.host = host or _env('ROUTER_HOST', '192.168.66.1')
        self.user = user or _env('ROUTER_USER', 'root')
        self.pw = pw if pw is not None else _env('ROUTER_PW', required=True)
        self.timeout = timeout
        self.log = []
        self._connect()

    # ---------- 连接 ----------
    def _connect(self):
        self.c = paramiko.SSHClient()
        self.c.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self.c.connect(self.host, 22, self.user, self.pw, timeout=self.timeout,
                       banner_timeout=20, auth_timeout=20)

    def reconnect(self):
        try:
            self.c.close()
        except Exception:
            pass
        self._connect()
        self.p("  [reconnect] ok")

    def ensure(self):
        try:
            t = self.c.get_transport()
            if t is None or not t.is_active():
                self.reconnect()
        except Exception:
            self.reconnect()

    def close(self):
        try:
            self.c.close()
        except Exception:
            pass

    # ---------- 输出 ----------
    def p(self, *a):
        line = ' '.join(str(x) for x in a)
        self.log.append(line)
        # 打印绝不能反过来打断长任务：控制台编码异常时只跳过 stdout，日志照留
        try:
            print(line)
        except Exception:
            pass

    def save(self, path):
        with open(path, 'w', encoding='utf-8') as f:
            f.write('\n'.join(self.log))

    # ---------- 执行 ----------
    def sh(self, cmd, t=120, silent=False):
        """执行并返回 stdout+stderr（已 strip）。"""
        _, o, e = self.c.exec_command(cmd, timeout=t)
        so = o.read().decode('utf-8', 'replace')
        se = e.read().decode('utf-8', 'replace')
        out = (so + se).strip()
        if not silent:
            self.p(out)
        return out

    def run(self, cmd, t=120):
        """只取 stdout，不打印（适合取值）。"""
        _, o, _ = self.c.exec_command(cmd, timeout=t)
        return o.read().decode('utf-8', 'replace').strip()

    def safe(self, cmd, t=120, silent=False, retries=3):
        """带断线重连的执行。"""
        last = None
        for i in range(retries):
            try:
                self.ensure()
                return self.sh(cmd, t=t, silent=silent)
            except Exception as ex:
                last = ex
                self.p("  [warn] 命令失败(%s)，重连重试 %d/%d" % (type(ex).__name__, i + 1, retries))
                time.sleep(2)
        raise last

    # ---------- 文件传输 ----------
    def put_text(self, path, text, tag='WBFILE', t=60):
        """heredoc 写文本（自动补尾换行）。返回 (md5是否一致, 远端md5)。"""
        if not text.endswith('\n'):
            text += '\n'
        if ('\n' + tag) in text:
            raise ValueError('内容里出现了 heredoc 结束标签，换一个 tag')
        cmd = "cat > %s << '%s'\n%s%s\n" % (path, tag, text, tag)
        self.sh(cmd, t=t, silent=True)
        want = hashlib.md5(text.encode('utf-8')).hexdigest()
        got = self.run("md5sum %s 2>/dev/null | awk '{print $1}'" % path, t=30)
        return want == got, got

    def put_text_verified(self, path, text, t=60):
        """heredoc 写文本；超阈值或失败时改用 4KB 分块追加（防超长命令被 reset）。返回 (ok, md5)。

        ⚠️ 2026-09-19 二次修正：**单发超限会直接把 SSH 传输层打死**（dropbear 对 >8KB
        的 exec_command 直接 reset），此后 `exec_command` 抛 `SSHException: SSH session
        not active`，连"降级分块"的兜底都跑不起来 —— 原来"先试单发、失败再降级"的顺序
        本身就是错的（kp-1panel-test.sh 20.6KB 实测：先 EOFError、再降级时连接已死）。
        正确做法：**按体积预判，超限直接分块**，绝不先发那条注定失败的命令；并且每块
        写前 `ensure()`，被 reset 也能自己接回来。
        """
        if not text.endswith('\n'):
            text += '\n'
        if len(text.encode('utf-8')) <= 4000:
            try:
                ok, md5 = self.put_text(path, text, t=t)
                if ok:
                    return ok, md5
                self.p("  [warn] %s md5 不一致，改用分块写入" % path)
            except Exception as ex:
                self.p("  [warn] %s 单发写入异常(%s)，改用分块写入" % (path, type(ex).__name__))
            self.ensure()
        else:
            self.p("  [info] %s 超单发上限(>4KB)，直接分块写入" % path)
        lines = text.split('\n')
        # 去掉末尾空元素：否则 join 后再补的 \n 会多写一个尾换行（md5 永远对不上）
        if lines and lines[-1] == '':
            lines.pop()
        buf, size, first = [], 0, True
        def flush():
            nonlocal buf, size, first
            if not buf:
                return
            op = '>' if first else '>>'
            body = '\n'.join(buf)
            cmd = "cat %s %s << 'WBCHUNK'\n%s\nWBCHUNK\n" % (op, path, body)
            # 每块写前确认连接活着：前一块若把传输层打死，这里能自己接回来
            for attempt in (1, 2):
                try:
                    self.ensure()
                    self.sh(cmd, t=t, silent=True)
                    break
                except Exception as ex:
                    if attempt == 2:
                        raise
                    self.p("  [warn] 分块写入失败(%s)，重连重试" % type(ex).__name__)
                    time.sleep(1)
            first = False
            buf, size = [], 0
        for ln in lines:
            buf.append(ln)
            size += len(ln) + 1
            if size > 4000:
                flush()
        flush()
        want = hashlib.md5(text.encode('utf-8')).hexdigest()
        got = self.run("md5sum %s 2>/dev/null | awk '{print $1}'" % path, t=30)
        return want == got, got

    def put_bin(self, path, data):
        """**无 SFTP 时传二进制的唯一可靠通道**：printf 八进制转义。
        固件无 base64/openssl/xxd/python3；实测 256B/900B 全字节覆盖均精确。
        单条命令建议 < 10KB（超长会被 dropbear reset，必要时自行分块 append）。"""
        body = ''.join('\\%03o' % b for b in data)
        if len(body) + len(path) > 9000:
            raise ValueError('payload 过长(%d字节)，请自行分块' % len(data))
        self.sh("printf '%s' > %s" % (body, path), t=60, silent=True)
        want = hashlib.md5(data).hexdigest()
        got = self.run("md5sum %s 2>/dev/null | awk '{print $1}'" % path, t=30)
        return want == got, got

    def put_bin_verified(self, path, data, chunk=600):
        """分块 printf 写二进制（大文件用），末尾校验。"""
        off = 0
        first = True
        while off < len(data):
            part = data[off:off + chunk]
            body = ''.join('\\%03o' % b for b in part)
            op = '>' if first else '>>'
            self.sh("printf '%s' %s %s" % (body, op, path), t=60, silent=True)
            first = False
            off += chunk
        want = hashlib.md5(data).hexdigest()
        got = self.run("md5sum %s 2>/dev/null | awk '{print $1}'" % path, t=30)
        return want == got, got

    # ---------- 常用检查 ----------
    def mem(self):
        return self.run("free -k | head -2")

    def df(self):
        return self.run("df -h / /mnt/storage/data 2>/dev/null | tail -3")
