# -*- coding: utf-8 -*-
"""把 kp-webui 部署到 C2000 U：写文件 -> chmod -> 自启 -> 启动 -> 验证
要点：
  - 用 rtr_lib.put_text_verified（heredoc + md5 对账 + 4KB 分块降级），
    因为超长单条命令会被 dropbear reset（本次实测 12KB 的 app.js 直接把通道打掉）
  - 每条命令都用 safe() 包一层断线重连
"""
import os, sys, time, hashlib
sys.path.insert(0, r"%USERPROFILE%\.workbuddy\skills\kunpeng-router-tuning\scripts")
os.environ.setdefault("ROUTER_PW", "admin")
from rtr_lib import Rtr

LOCAL = r"<工作区>\kpwebui"
BASE = "http://192.168.66.1:10087"

FILES = [
    ("www/index.html",    "/root/kpwebui/www/index.html",    644),
    ("www/css/style.css", "/root/kpwebui/www/css/style.css", 644),
    ("www/js/app.js",     "/root/kpwebui/www/js/app.js",     644),
    ("cgi/api.sh",        "/root/kpwebui/www/cgi/api.sh",    755),
    ("init.d/kpwebui",    "/etc/init.d/kpwebui",             755),
    ("lua/reqdec.lua",    "/root/kpwebui/lua/reqdec.lua",    644),
    ("lua/smsapi.lua",    "/root/kpwebui/lua/smsapi.lua",    644),
    ("lua/atapi.lua",     "/root/kpwebui/lua/atapi.lua",     644),
    ("lua/cellapi.lua",   "/root/kpwebui/lua/cellapi.lua",   644),
    ("smsfwd.sh",         "/root/kpwebui/smsfwd.sh",         755),
    # forward.conf 不进 FILES: 它是用户配置, 重部署不能覆盖（首次部署时才写模板）
]

log = []
def L(s=""):
    log.append(str(s))
    print(s)

r = Rtr()

def _chunk_write(dest, text, chunk=3000):
    """按行切成 <=chunk 字节的小块逐块写入。
    实测：单条 exec_command 超过 ~8KB 会被 dropbear reset（EOFError），
    而 put_text_verified 只在 md5 不一致时才降级，异常直接抛出 -> 这里自己分块。
    """
    lines = text.split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    buf, size, first = [], 0, True
    blocks = []

    def flush():
        nonlocal buf, size, first
        if not buf:
            return
        # 注意：body **不带**尾换行，命令里的 \n 负责补上那一个换行。
        # 如果这里再加 '\n'，每块之间就会多出一个空行（本次踩坑点）
        blocks.append((">" if first else ">>", "\n".join(buf)))
        first = False
        buf, size = [], 0

    for ln in lines:
        if size + len(ln) + 1 > chunk and buf:
            flush()
        buf.append(ln)
        size += len(ln) + 1
    flush()

    for op, body in blocks:
        for i in range(3):
            try:
                r.ensure()
                r.sh("cat %s '%s' << 'WBCHUNK'\n%s\nWBCHUNK\n" % (op, dest, body), t=90, silent=True)
                break
            except Exception as ex:
                L("  [chunk warn] %s 重连重试 %d/3" % (type(ex).__name__, i + 1))
                time.sleep(2)
                try:
                    r.reconnect()
                except Exception:
                    pass
        else:
            return False
    want = hashlib.md5(text.encode("utf-8")).hexdigest()
    got = r.run("md5sum '%s' 2>/dev/null | awk '{print $1}'" % dest, t=30)
    return want == got


def put(rel, dest):
    """小文件走 put_text_verified，大文件直接分块写入 + md5 校验"""
    src = os.path.join(LOCAL, rel.replace("/", os.sep))
    text = open(src, "r", encoding="utf-8").read()
    # 归一化：分块写入必然以换行收尾，校验基准要按“归一化后的文本”算，
    # 否则原文没有尾换行时就永远对不上（本次踩坑点）
    if not text.endswith("\n"):
        text += "\n"
    if len(text.encode("utf-8")) < 4000:
        for i in range(3):
            try:
                r.ensure()
                ok, md5 = r.put_text_verified(dest, text, t=90)
                if ok:
                    return True, md5
            except Exception:
                pass
            time.sleep(2)
            try:
                r.reconnect()
            except Exception:
                pass
    for i in range(3):
        try:
            r.ensure()
            if _chunk_write(dest, text):
                return True, "chunk-ok"
            L("  [warn] %s 分块后 md5 仍不一致，重传 %d/3" % (rel, i + 1))
        except Exception as ex:
            L("  [warn] %s 异常 %s，重连重传 %d/3" % (rel, type(ex).__name__, i + 1))
            time.sleep(2)
            try:
                r.reconnect()
            except Exception:
                pass
    return False, "fail"

try:
    L(r.safe("mkdir -p /root/kpwebui/www/cgi /root/kpwebui/www/css /root/kpwebui/www/js /root/kpwebui/lua; "
             "echo dirs-ok"))

    L("\n--- 写文件 ---")
    allok = True
    for rel, dest, mode in FILES:
        ok, md5 = put(rel, dest)
        r.safe("chmod %d %s" % (mode, dest))
        L("WRITE %-20s -> %-32s %s md5=%s" % (rel, dest, "OK " if ok else "FAIL", md5))
        allok = allok and ok
    if not allok:
        L("!! 有文件写入校验失败，中止")
        raise SystemExit(1)

    L("\n--- forward.conf（仅首次） ---")
    L(r.safe("if [ ! -f /root/kpwebui/forward.conf ]; then "
             "printf 'Forward_Open=0\\nForward_Type=0\\nForward_title=\\nForward_sleep=3\\n"
             "Pushplus_token=\\nDingtalk_webhook=\\nDingtalk_secret=\\nFeishu_webhook=\\n"
             "Feishu_secret=\\nMeow_webhook=\\nDelete_When_Pushed=0\\n' > /root/kpwebui/forward.conf; "
             "chmod 600 /root/kpwebui/forward.conf; echo created; else echo 'kept user config'; fi", t=30))

    L("\n--- 语法检查 ---")
    L(r.safe("sh -n /root/kpwebui/www/cgi/api.sh && echo 'api.sh syntax OK'"))
    L(r.safe("sh -n /etc/init.d/kpwebui && echo 'init syntax OK'"))

    L("\n--- 启服务 ---")
    L(r.safe("/etc/init.d/kpwebui enable 2>&1 | tail -2"))
    L(r.safe("/etc/init.d/kpwebui restart 2>&1 | tail -3", t=90))
    time.sleep(2)
    L(r.safe("ls /etc/rc.d/ | grep kpwebui; ps | grep '[u]httpd'"))

    L("\n--- 静态资源 ---")
    for u in ["/", "/css/style.css", "/js/app.js"]:
        code = r.safe("curl -s -o /dev/null -w '%%{http_code}' -m 6 %s%s" % (BASE, u), t=30)
        L("  %-18s %s" % (u, code))

    L("\n--- API ---")
    for ep in ["hello", "status", "store", "docker", "network", "ports", "fw",
               "sms?action=list&type=all", "cell", "file?path=/root"]:
        s = r.safe("curl -s -m 30 '%s/cgi/api.sh/%s'" % (BASE, ep), t=90)
        s = s.strip()
        ok = s.startswith("{") and '"code":0' in s
        L("[%s] /%-24s len=%-6d %s" % ("OK " if ok else "BAD", ep, len(s), s[:230]))

    L("\n--- 路由内部 JSON 合法性（粗检）---")
    L(r.safe("curl -s -m 25 '%s/cgi/api.sh/status' | tr ',' '\\n' | head -20" % BASE, t=60))
finally:
    r.close()

open(r"<工作区>\deploy_log.txt", "w", encoding="utf-8").write("\n".join(log))
print("=== done ===")
