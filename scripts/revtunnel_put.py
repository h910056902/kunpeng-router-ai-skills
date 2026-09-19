#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""revtunnel_put.py — 无 SFTP 设备的大文件投递库（SSH 反向端口转发 + 设备侧 curl 自拉）

适用场景：
  - 设备无 sftp-server（paramiko open_sftp() 报 EOF during negotiation）
  - PC 防火墙拦 LAN 入站（设备无法直连 PC 上的 HTTP 服务）
  - 文件较大，printf 八进制通道太慢

原理：paramiko transport.request_port_forward() 让 SSH 服务端（设备）监听
127.0.0.1:RPORT，转发到 PC 本地 127.0.0.1 的内置 http.server；
设备侧 curl http://127.0.0.1:RPORT/<name> 自己拉，PC 侧 md5 对账。

依赖：paramiko。文本/小文件仍建议用 rtr_lib.Rtr.put_text_verified。
"""
import functools
import hashlib
import http.server
import os
import socket
import threading


class QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def md5f(path):
    h = hashlib.md5()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


class RevTunnel:
    """把 PC 上 127.0.0.1:lport 反向暴露到路由器的 127.0.0.1:rport。"""

    def __init__(self, ssh_client, lport=0, rport=8899):
        self.lp = lport
        self.rp = rport
        self.t = ssh_client.get_transport()
        self.port = self.t.request_port_forward('127.0.0.1', rport, self._handle)

    def _handle(self, chan, origin, server):
        threading.Thread(target=self._bridge, args=(chan,), daemon=True).start()

    def _bridge(self, chan):
        try:
            s = socket.create_connection(('127.0.0.1', self.lp), timeout=10)
        except Exception:
            try:
                chan.close()
            except Exception:
                pass
            return

        def pump(a, b):
            try:
                while True:
                    d = a.recv(65536)
                    if not d:
                        break
                    b.sendall(d)
            except Exception:
                pass
            finally:
                try:
                    b.shutdown(socket.SHUT_WR)
                except Exception:
                    pass

        t1 = threading.Thread(target=pump, args=(chan, s), daemon=True)
        t2 = threading.Thread(target=pump, args=(s, chan), daemon=True)
        t1.start(); t2.start(); t1.join(); t2.join()
        for x in (s, chan):
            try:
                x.close()
            except Exception:
                pass


class TunnelPusher:
    """一次性组合：本地 HTTP + 反向隧道 + 设备拉取 + md5 对账。

    用法：
        tp = TunnelPusher(rtr, stage_dir="/path/to/files")
        tp.open()                          # 起 HTTP + 隧道（自动选随机本地端口）
        ok = tp.put("bigfile.ipk", "/tmp/bigfile.ipk")
        tp.close()
    """

    def __init__(self, rtr, stage_dir, rport=8899):
        self.r = rtr
        self.stage = stage_dir
        self.rport = rport
        self.srv = None
        self.tun = None

    def open(self):
        handler = functools.partial(QuietHandler, directory=self.stage)
        self.srv = http.server.ThreadingHTTPServer(('127.0.0.1', 0), handler)
        self.lp = self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.tun = RevTunnel(self.r.c, self.lp, self.rport)
        return self

    def put(self, name, remote_path, timeout=300):
        """投递单个文件，返回 (md5_ok: bool, info: str)。"""
        local = os.path.join(self.stage, name)
        want = md5f(local)
        dl = ("curl -s -m %d -o %s -w '%%{http_code} %%{size_download}' "
              "http://127.0.0.1:%d/%s 2>&1" % (timeout, remote_path, self.rport, name))
        out = self.r.run(dl, t=timeout + 40)
        got = self.r.run("md5sum %s 2>/dev/null | awk '{print $1}'" % remote_path, t=60)
        return (got == want), out

    def close(self):
        if self.tun is not None:
            try:
                self.tun.t.cancel_port_forward('127.0.0.1', self.rport)
            except Exception:
                pass
        if self.srv is not None:
            self.srv.shutdown()
