# -*- coding: utf-8 -*-
"""在 GitHub 被 DNS 污染的网络里推送/拉取 git 仓库。

背景：某些网络里 github.com 解析到的 IP（如 20.205.243.166）443 被阻断，
      但 GitHub 的其它边缘 IP 完全可用。本脚本起一个**只监听 127.0.0.1** 的
      HTTP CONNECT 代理，把 *.github.com:443 强制转发到可用 IP，让 git 走它。

优点：不改 hosts、不需要管理员、不改全局 git 配置，用完即关。
      TLS SNI 仍是 github.com → 证书校验正常通过。

注意：可用 IP 的"可用"是波动的 —— 有时某个 IP **TCP 能连上但 TLS 握手中途被掐**
      （`OpenSSL SSL_read: unexpected eof while reading`）。本脚本因此内置
      **失败重试 + 每次重试轮换首选 IP**，实测第二次就成功。

用法：
    python gh_proxy_push.py push  [仓库目录] [分支]
    python gh_proxy_push.py ls    [仓库目录]          # 只比对本地/远端 HEAD
    python gh_proxy_push.py curl                      # 自检各 IP 可用性

凭据：交给系统 git 凭据管理器（credential.helper）；本脚本不读任何 token。
"""
import io
import os
import select
import socket
import subprocess
import sys
import threading
import time

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace', write_through=True)

PORT = 18443
# 实测可用的 GitHub 边缘 IP。
# ⚠️ 2026-09-11 二次实测：140.82.113/114/116.3 这三个会「TCP 连上但 TLS 被掐」，
#    而 20.27.177.113 连续多次成功 —— 故按实测可靠性排序，最稳的放首位。
GOOD_IPS = ['20.27.177.113', '20.200.245.247', '4.237.22.38', '20.248.137.48',
            '20.205.243.168', '140.82.113.3', '140.82.114.3', '140.82.116.3']
FORCE_SUFFIX = 'github.com'     # 命中该后缀的域名强制走 GOOD_IPS
STOP = threading.Event()
_IP_OFFSET = [0]                # 重试时轮换首选 IP（某些 IP 能连通但 TLS 会被掐）


def _ip_order():
    """返回按当前轮换偏移重排的 IP 列表。"""
    k = _IP_OFFSET[0] % len(GOOD_IPS)
    return GOOD_IPS[k:] + GOOD_IPS[:k]


# ---------------- 极简 CONNECT 代理 ----------------
def _pump(a, b):
    try:
        while True:
            r, _, _ = select.select([a, b], [], [], 60)
            if not r:
                break
            for s in r:
                d = s.recv(65536)
                if not d:
                    return
                (b if s is a else a).sendall(d)
    except Exception:
        pass
    finally:
        for s in (a, b):
            try:
                s.close()
            except Exception:
                pass


def _handle(conn):
    try:
        conn.settimeout(20)
        buf = b''
        while b'\r\n\r\n' not in buf:
            c = conn.recv(4096)
            if not c:
                return
            buf += c
        parts = buf.decode('latin-1').split('\r\n')[0].split()
        if len(parts) < 2 or parts[0].upper() != 'CONNECT':
            conn.sendall(b'HTTP/1.1 400 Bad Request\r\n\r\n')
            return
        host, _, port = parts[1].rpartition(':')
        port = int(port or 443)
        up = None
        if host.endswith(FORCE_SUFFIX):
            for ip in _ip_order():
                try:
                    up = socket.create_connection((ip, port), timeout=6)
                    print("    [proxy] %s:%d -> %s" % (host, port, ip))
                    break
                except Exception:
                    continue
        else:
            try:
                up = socket.create_connection((host, port), timeout=10)
            except Exception:
                pass
        if up is None:
            conn.sendall(b'HTTP/1.1 502 Bad Gateway\r\n\r\n')
            return
        conn.sendall(b'HTTP/1.1 200 Connection established\r\n\r\n')
        conn.settimeout(None)
        _pump(conn, up)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass


def _serve():
    srv = socket.socket()
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(('127.0.0.1', PORT))     # 只回环，绝不对外
    srv.listen(32)
    srv.settimeout(1)
    print("  [proxy] 监听 127.0.0.1:%d" % PORT)
    while not STOP.is_set():
        try:
            c, _ = srv.accept()
        except socket.timeout:
            continue
        except Exception:
            break
        threading.Thread(target=_handle, args=(c,), daemon=True).start()
    srv.close()


def git(args, cwd, use_proxy=True):
    env = dict(os.environ)
    for k in ('http_proxy', 'https_proxy', 'HTTP_PROXY', 'HTTPS_PROXY'):
        env.pop(k, None)                      # 清掉沙箱/系统代理，避免与本地代理打架
    env['GIT_TERMINAL_PROMPT'] = '0'          # 缺凭据时快速失败，不挂住
    if use_proxy:
        env.update({'GIT_CONFIG_COUNT': '1',
                    'GIT_CONFIG_KEY_0': 'http.proxy',
                    'GIT_CONFIG_VALUE_0': 'http://127.0.0.1:%d' % PORT})
    p = subprocess.run(['git'] + list(args), cwd=cwd, capture_output=True, env=env)
    return (p.returncode,
            p.stdout.decode('utf-8', 'replace').strip(),
            p.stderr.decode('utf-8', 'replace').strip())


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else 'push'
    repo = sys.argv[2] if len(sys.argv) > 2 else os.getcwd()
    branch = sys.argv[3] if len(sys.argv) > 3 else 'main'

    if mode == 'curl':
        for ip in GOOD_IPS:
            p = subprocess.run(['curl.exe', '-s', '-o', 'NUL', '-w', '%{http_code} t=%{time_total}',
                                '--resolve', 'github.com:443:%s' % ip, '--max-time', '8',
                                'https://github.com'], capture_output=True)
            print("  %-18s %s" % (ip, p.stdout.decode('utf-8', 'replace').strip()))
        return

    threading.Thread(target=_serve, daemon=True).start()
    time.sleep(1)

    _, local, _ = git(['rev-parse', 'HEAD'], repo)
    print("local : %s" % local)

    if mode in ('push', 'pull'):
        for i in range(3):
            rc, o, e = git([mode, 'origin', branch], repo)
            print("  git %s rc=%d" % (mode, rc))
            if o:
                print("  stdout: " + o[:300])
            if e:
                print("  stderr: " + e[:300])
            if rc == 0:
                break
            # 失败多为「TCP 能连、TLS 被掐」→ 下次换一个边缘 IP 再试
            _IP_OFFSET[0] += 1
            print("  retry -> 首选 IP 轮换为 %s" % _ip_order()[0])
            time.sleep(3)

    # 唯一可信判据：ls-remote 与本地 HEAD 比对
    _, remote, _ = git(['ls-remote', 'origin', 'refs/heads/%s' % branch], repo)
    remote = remote.split()[0] if remote.strip() else ''
    print("remote: %s" % (remote or '(取不到)'))
    print("MATCH : %s" % (bool(local) and local == remote))
    _, ahead, _ = git(['rev-list', '--count', 'origin/%s..HEAD' % branch], repo) if False else (0, '', '')
    STOP.set()
    time.sleep(1)


if __name__ == '__main__':
    main()
