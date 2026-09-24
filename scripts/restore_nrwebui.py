# -*- coding: utf-8 -*-
"""nr_webui 一键还原：从本地归档重建整套 WebUI 到鲲鹏路由器

传输思路：
  路由器无 SFTP、无 base64，SSH 单条命令 >8KB 会被 dropbear reset，
  2.7MB / 167 个文件的前端目录用 SSH 分块写是不现实的。
  → **反向利用 HTTP**：PC 上起一个临时 http.server，路由器用 curl 拉。
    实测这是唯一又快又可靠的通道（前提：PC 防火墙放行该端口的入站）。

用法：
  set ROUTER_PW=xxx
  python restore_nrwebui.py                 # 完整还原
  python restore_nrwebui.py --only frontend # 只还原前端
  python restore_nrwebui.py --check         # 只做连通性与现状检查
"""
import os, sys, io, time, socket, tarfile, threading, tempfile, shutil, argparse, functools

sys.path.insert(0, r"C:\Users\91005\.workbuddy\skills\kunpeng-router-tuning\scripts")
os.environ.setdefault("ROUTER_PW", "admin")
from rtr_lib import Rtr
import http.server, socketserver

ARCH = r"C:\Users\91005\WorkBuddy\2026-09-06-00-21-37\nr-webui-archive"
ROUTER = "192.168.66.1"
PORT = 18899

log = []
def L(s=""):
    log.append(str(s)); print(s)


def pc_lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect((ROUTER, 22))
        return s.getsockname()[0]
    finally:
        s.close()


class Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *a):
        pass


def serve_dir(d):
    # 必须传 directory=，否则 SimpleHTTPRequestHandler 服务的是进程 CWD（会 404）
    handler = functools.partial(Quiet, directory=d)
    socketserver.TCPServer.allow_reuse_address = True
    httpd = socketserver.TCPServer(("0.0.0.0", PORT), handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", choices=["frontend", "bin", "all"], default="all")
    ap.add_argument("--check", action="store_true")
    args = ap.parse_args()

    ip = pc_lan_ip()
    L("PC LAN IP: %s   归档: %s" % (ip, ARCH))

    # ---------- 打包 ----------
    tmp = tempfile.mkdtemp(prefix="nrrestore_")
    tgz = os.path.join(tmp, "webui.tar")
    src = os.path.join(ARCH, "router", "webui")
    L("打包前端: %s -> %s" % (src, tgz))
    with tarfile.open(tgz, "w") as tf:
        tf.add(src, arcname="webui")
    shutil.copy(os.path.join(ARCH, "router", "nr_webui_current"),
                os.path.join(tmp, "nr_webui"))
    L("  前端包 %.1f KB，二进制 %.1f KB" % (
        os.path.getsize(tgz) / 1024.0,
        os.path.getsize(os.path.join(tmp, "nr_webui")) / 1024.0))

    httpd = serve_dir(tmp)
    base = "http://%s:%d" % (ip, PORT)
    L("临时 HTTP: %s  (服务目录 %s)" % (base, tmp))

    r = Rtr()
    ok = True
    try:
        # ---------- 连通性 ----------
        L("")
        L("=== 连通性探测 ===")
        code = r.safe("curl -s -o /dev/null -w '%%{http_code}' -m 8 %s/nr_webui" % base, t=30)
        L("  路由器 curl PC: HTTP %s" % code)
        if code.strip() != "200":
            L("  !! PC 的 %d 端口对路由器不可达（多半是 Windows 防火墙）。" % PORT)
            L("     可用管理员 PowerShell 放行：")
            L("     New-NetFirewallRule -DisplayName 'nrwebui-restore' -Direction Inbound "
              "-LocalPort %d -Protocol TCP -Action Allow" % PORT)
            if args.check:
                return
            ok = False
            return
        if args.check:
            L("  通道可用。")
            return

        ts = time.strftime("%Y%m%d_%H%M%S")

        # ---------- 备份现状 ----------
        L("")
        L("=== 备份现状 ===")
        L(r.safe("/etc/init.d/nrwebui stop 2>/dev/null; "
                 "mv /root/webui /root/webui.bak-%s 2>/dev/null; "
                 "cp -a /root/nr_webui /root/nr_webui.bak-%s 2>/dev/null; "
                 "ls -d /root/webui.bak-%s /root/nr_webui.bak-%s 2>&1" % (ts, ts, ts, ts), t=60))

        # ---------- 还原前端 ----------
        if args.only in ("frontend", "all"):
            L("")
            L("=== 还原前端 ===")
            L(r.safe("rm -rf /tmp/webui.tar; curl -s -m 120 -o /tmp/webui.tar %s/webui.tar; "
                     "ls -la /tmp/webui.tar" % base, t=180))
            L(r.safe("cd /root && rm -rf /root/webui && tar xf /tmp/webui.tar -C /root && "
                     "echo '文件数: '$(find /root/webui -type f | wc -l); "
                     "cat /root/webui/ver", t=180))

        # ---------- 还原二进制 ----------
        if args.only in ("bin", "all"):
            L("")
            L("=== 还原后端二进制 ===")
            L(r.safe("curl -s -m 60 -o /root/nr_webui %s/nr_webui && "
                     "chmod 755 /root/nr_webui && ls -la /root/nr_webui" % base, t=120))

        # ---------- 配置 + 自启 ----------
        L("")
        L("=== 配置与自启 ===")
        conf = open(os.path.join(ARCH, "router", "webui.conf"), encoding="utf-8").read()
        okc, _ = r.put_text_verified("/root/webui.conf", conf, t=60)
        L("  webui.conf: %s" % okc)
        fwd = open(os.path.join(ARCH, "router", "forward.config.example"), encoding="utf-8").read()
        if not os.path.exists("/root/forward.config"):
            pass
        # 只在不存在时写，避免覆盖用户已配的推送 token
        exist = r.safe("test -f /root/forward.config && echo yes || echo no", t=20)
        if "no" in exist:
            okf, _ = r.put_text_verified("/root/forward.config", fwd, t=60)
            L("  forward.config: 新建 %s" % okf)
        else:
            L("  forward.config: 已存在，保留")

        init = open(os.path.join(ARCH, "router", "nrwebui.init"), encoding="utf-8").read()
        oki, _ = r.put_text_verified("/etc/init.d/nrwebui", init, t=60)
        r.safe("chmod 755 /etc/init.d/nrwebui", t=20)
        L("  /etc/init.d/nrwebui: %s" % oki)

        L(r.safe("/etc/init.d/nrwebui enable 2>&1 | tail -2; "
                 "/etc/init.d/nrwebui restart 2>&1 | tail -2; sleep 3; "
                 "ls /etc/rc.d/ | grep nrwebui", t=90))

        # ---------- 验证 ----------
        L("")
        L("=== 验证 ===")
        L("  进程: " + r.safe("pidof nr_webui", t=20))
        L("  端口: " + r.safe("netstat -lnt 2>/dev/null | grep 10086", t=20))
        L("  islogin: " + r.safe("curl -s -m 8 http://%s:10086/api/islogin; echo" % ROUTER, t=30))
        for u in ["/", "/login.html", "/css/common.css", "/js/common.js", "/ver"]:
            c = r.safe("curl -s -o /dev/null -w '%%{http_code}' -m 8 http://%s:10086%s"
                       % (ROUTER, u), t=30)
            L("  %-18s %s" % (u, c))
        L("  版本: " + r.safe("cat /root/webui/ver", t=20))
        L("  文件数: " + r.safe("find /root/webui -type f | wc -l", t=30))

        if ok:
            L("")
            L("还原完成 -> http://%s:10086" % ROUTER)
    finally:
        r.close()
        httpd.shutdown()
        shutil.rmtree(tmp, ignore_errors=True)
        open(r"C:\Users\91005\WorkBuddy\2026-09-06-00-21-37\restore_log.txt",
             "w", encoding="utf-8").write("\n".join(log))


if __name__ == "__main__":
    main()
