# 任务 05 · 跑第三方 NROS 插件安装器（maye 助手）

> `id: nros.plugin-installer` · `risk: **write**`（它改 LuCI 商店页与 opkg 源；跑完必须校验我们的补丁还在）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> 目标：用社区脚本「NRadio 官方系统插件安装助手」（作者 maye）给设备装插件、做系统维护，
> **且不冲掉我们自己的商店补丁**。
> 上游仓库：<https://github.com/561410590/ssh-nradio-plugin-installer> ·
> 支持页：<https://nradio.mayebano.shop/>
> 配套档案：[`references/maye-assistant.md`](../references/maye-assistant.md) ·
> 适配器：[`scripts/adapt_maye_assistant.py`](../scripts/adapt_maye_assistant.py)

---

## 0. 三条置顶红线（先看这个，再看别的）

> ⚠️ 以下三条都是**实测**结论，不是推测。踩中任一条都不好收场。

1. 🔴 **它不产生任何备份。**
   脚本有 `BACKUP_DIR="/root/nradio-plugin-fix"`（第 19 行）和 `backup_file()`（第 2575-2578 行、
   第 54767-54769 行），但 `backup_file()` 是**空实现** —— 函数体只有 `return 0`，
   注释写「用户要求所有安装、修复和页面操作直接写入，**不在路由器上生成持久备份**」。
   脚本里 100+ 处 `backup_file "..."` 调用全部是**空操作**，全脚本没有任何一处 `mkdir`/`cp` 落到 `$BACKUP_DIR`。
   真机实测：`ls -ld /root/nradio-plugin-fix` → `No such file or directory`。
   **→ 想回滚，只能靠你自己在跑之前备份。**

2. 🔴 **绝对不要在它菜单里选「卸载 / 移除 Docker」。**
   该分支（第 4512-4530 行）执行：
   ```sh
   rm -f /etc/config/dockerd /etc/config/docker /etc/config/cgroupfs-mount /etc/docker/daemon.json \
         "$DOCKER_CONTROLLER" "$DOCKER_VIEW" ...
   rm -rf /etc/docker /usr/libexec/docker "$DOCKER_ROOT" /tmp/nradio-docker-*
   cleanup_appcenter_entry ...   # 还会改商店条目
   ```
   本机 `/etc/config/dockerd`（304 B，实测）正是 **Docker `data_root` 与镜像加速源的唯一载体**：
   ```
   option data_root '/mnt/storage/data/docker'
   list registry_mirrors 'https://docker.1ms.run'
   list registry_mirrors 'https://docker.m.daocloud.io'
   ```
   删掉它 = 1Panel 的 Docker 环境连带容器数据一起报废，且 `cleanup_appcenter_entry` 会改到
   appcenter 相关文件（可能冲掉我们的商店补丁）。

3. 🔴 **不要在它菜单里装 AdGuardHome / mosdns。**
   它给的是 native 版（DNS 端口 554/553 + uci 配置），与本机 Docker AGH（`:53` 全网接管）端口冲突。
   去广告继续用我们现成的方案（见 `references/adguard-setup.md`）。

> 📌 **用法更正（2026-09-19 真终端实测）**：运行命令**不能带任何参数**。
> 上游 README 的官方写法就是 `sh ssh-nradio-plugin-installer.sh`。若把仓库地址当参数传进去
> （`sh ssh-nradio-plugin-installer.sh https://github.com/561410590/ssh-nradio-plugin-installer`），
> 脚本会把它当作「**菜单编号**」→ 直接 `ERROR: 无效编号：https://github.com/…` 退出，进不了菜单。
> 合法的位置参数只有 `0`~`5`（= 直接进入某个功能分类）。

---

## 0.5 环境门禁：逐关卡实测结论（2026-09-19 真机）

上游脚本在进菜单前有一整套 `require_supported_nradio_model_environment` 门禁，
任一关卡不过就 `die` 退出。**已在真机逐字复刻判据跑过，全链 PASS。**

| 门禁 | 位置 | 本机实测结果 |
|---|---|---|
| 机型可归一化 | 第 1430 行 | ✅ `HC-WT9500` → `NRadio_C2000Ultra`（`normalize_nradio_model` 第 1209-1210 行） |
| 版本非空 | 第 1431 行 | ✅ `2.3.0.n0.c1` |
| **版本受支持** | 第 1432 行 → `is_supported_nros_revision`（第 1224-1240 行） | ✅ 匹配 `2.*` → `return 0` |
| SD 卡前置 | 第 1410 行 → `require_c2000max_storage_ready`（第 1406-1421 行） | ✅ `/tmp/storage/mmcblk0p1`，可用 15438 MiB |
| 应用商店环境 | `require_nradio_appcenter_startup_environment`（第 1472-1484 行） | ✅ profile = `legacy_appcenter`，三路径齐全 |

> 🧨 **最容易误判的一个坑：版本判据读的是 `ubus call system board` 的 `release.revision`，
> 不是 `/etc/openwrt_release` 的 `DISTRIB_RELEASE`。**
> 本机 `DISTRIB_RELEASE='21.02-SNAPSHOT'`（**看起来不匹配 `2.*`，容易被误判为会被拒**），
> 但 `detect_nros_revision`（第 1133-1139 行）第一优先级读的是
> `ubus call system board` 里的 `"revision": "2.3.0.n0.c1"` → 归一化后 = `2.3.0.n0.c1` → 匹配 `2.*`。
> 实测 `ubus` 原始输出：
> ```json
> "release": { "distribution": "OpenWrt", "version": "21.02-SNAPSHOT",
>              "revision": "2.3.0.n0.c1", ... }
> ```
> 所以**本机是放行的**。（`/etc/openwrt_release` 只是第 2 优先级回落。）

### 门禁的触发时机（省事的关键）

- **主菜单选分类 `1/2/3/4` 才会触发环境检查**（第 72416 行：
  `case "$UI_READ_RESULT" in 1|2|3|4) require_nradio_menu_environment ;; esac`）。
- **选分类 `5`（设备维护与检测）不触发**。
- `run_menu_feature` 里 feature `33|34` 被显式豁免（第 69922 行：`case "$feature_choice" in 33|34) ;; ...`）。
- `require_nradio_menu_environment` 自身有一次性开关（第 69911 行 `NRADIO_MENU_ENVIRONMENT_CHECKED`），
  过了一次后面不再查。

→ 也就是说：**只想做「设备维护 / 体检」的话，压根不会走到版本门禁**；
只有装插件（分类 1）才必然经过它。而它已实测全 PASS。

---

## 1. 它到底改哪些文件

| 路径 | 它在做什么 |
|---|---|
| `/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm` | 商店前端（加卸载按钮、图标、状态徽标、MaYe 标识） |
| `/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua` | 商店后端（注册表、异步端点） |
| `/etc/config/appcenter` | 商店配置 |
| `/etc/opkg/distfeeds.conf` | opkg 软件源（**有守卫，实测会原样保留**，见风险 1） |
| `/etc/openclash/core/clash_meta` | OpenClash 内核（**别从它菜单里重装**，见风险 2） |
| `/etc/crontabs/root` | 智能频段等定时任务 |
| `/etc/config/dockerd` | **只在选「卸载 Docker」时**（见红线 2） |

| 项 | 事实（2026-09-19 真机实测；2026-09-24 增补版本漂移） |
|---|---|
| 它是什么 | **社区 SSH 菜单脚本**（不是 ipk、不是固件包、不能上应用商店） |
| 体积 / 行数 | **V3.2.0** 2,878,882 字节 · 约 7 万行（V3.2.1 为 2,893,017 字节 · 72,772 行） |
| 版本 | **本仓锁定 `V3.2.0`（2026-09-14）** · 脚本内 `SCRIPT_SIGNATURE="Designed by maye 2026-09-14"`。⚠️ 上游 `00-current/` 是**滚动单文件**，当前 HEAD 已是 `V3.2.1`（2026-09-23），**取用必须锁 commit，否则会静默拿到未验证版本** |
| 完整性 | sha256 `62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8` —— ✅ **上游 `CHECKSUMS.txt`（仓库根目录）官方登记值**、档案记录值、2026-09-24 双通道实测值**三方一致**。⚠️ 上游 CHECKSUMS **至今仍只登记 V3.2.0**，`CHANGELOG.md` 最新条目也仍是 V3.2.0 → **V3.2.1 无官方哈希、无变更记录，不得裸跑** |
| 适用边界 | 脚本自述 `SCRIPT_SCOPE_NOTICE`：**「适用于受支持的官方 NROS…并非标准 OpenWrt」** → **刷过原版 OpenWrt 的机器不要跑** |
| 本机匹配 | model `HC-WT9500` → `normalize_nradio_model()`（第 1209-1210 行）归一化为 **`NRadio_C2000Ultra`**；board_name `HCMT7987-SNSD`；NROS `2.3.0.n0.c1` |
| 本机额外开放 | 脚本按 `model_name == "NRadio_C2000Ultra"` 放行 **swap 扩容 / SD 卡检测**（第 7123 行，仅 C2000MAX 与 C2000Ultra 有） |
| 不碰什么 | **1Panel**（全脚本 `grep -c '1panel\|1Panel\|1PANEL'` = **0 处**，实测确认）；不动 Docker 容器（除非你主动选它的 Docker 菜单） |
| **备份** | 🔴 **无任何备份**（见红线 1）。状态目录 `/root/.nradio-plugin-menu` 只存免责声明 flag 与菜单偏好，不是备份 |

---

## 2. 四条必须先知道的风险

1. **它会写 `/etc/opkg/distfeeds.conf` —— 但有守卫，实测会原样保留**
   脚本常量 `FEEDS="/etc/opkg/distfeeds.conf"`（第 17 行）。第 5699-5703 行有守卫：
   ```sh
   if [ -f "$FEEDS" ] && ! grep -q 'releases/21\.02-SNAPSHOT/' "$FEEDS" 2>/dev/null; then
       if awk '$1 == "src/gz" && $2 !~ /^#/ && $3 ~ /^https?:\/\// { found=1 } END { exit(found ? 0 : 1) }' "$FEEDS"; then
           log "软件源: 保留当前固件源"
           return 0
       fi
   fi
   ```
   本机 `distfeeds.conf` 现状（334 B，**3 条源**，实测）：
   ```
   src/gz openwrt_base     https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/base
   src/gz openwrt_packages https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/packages
   src/gz openwrt_routing  https://mirrors.aliyun.com/openwrt/releases/21.02.7/packages/aarch64_cortex-a53/routing
   ```
   不含 `21.02-SNAPSHOT`，且每行都是规范的 `src/gz <name> https://…` →
   **实测守卫命中，输出「软件源: 保留当前固件源」，不会重写**。
   → 风险等级**低**（原初稿判断为「会被整体重写」，已被实测推翻）。
   仍建议跑前备份一份，成本为零。

2. **它会动 OpenClash 内核 —— 别从它菜单里重装**
   脚本内 `openclash` 出现 563 次，含 `install_openclash_smart_core()`（第 2452 行，写 `/etc/openclash/core`）。
   本机核心文件是 `/etc/openclash/core/clash_meta`（10,754,792 B，Mihomo 内核），进程名 `clash`（实测 pid 16659）。
   **不要从它菜单里重装 OpenClash 内核** —— 会覆盖我们那份。

3. **绝不在它菜单里装 AdGuardHome / mosdns**（= 红线 3）。

4. **游戏加速器走明文 HTTP 下载 + 直接执行**
   ```sh
   QIYOU_INSTALLER_URL="${QIYOU_INSTALLER_URL:-http://sd.qiyou.cn}"                                  # 第 97 行
   LEIGOD_INSTALLER_URL="${LEIGOD_INSTALLER_URL:-http://119.3.40.126/router_plugin_new/plugin_install.sh}"  # 第 106 行
   ```
   （雷神那条是**裸 IP + 明文 http**。）下载后只做 `grep -q 'qyplug.sh'` 内容检查和 `sh -n` 语法检查
   （第 71783-71784 行），**没有校验和 / 签名验证**，然后 `sh /tmp/qiyou-install.sh` 直接以 root 执行
   （第 71789 行）。中间人可替换脚本体 → 等于远程代码执行。
   → **不要在它菜单里装奇游/雷神**；要用就自己下、先核对内容再执行。

---

## 3. 前置检查

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| 1 | SSH 可达 | `echo ok` | `ok` | 后台「系统 → 安全」先开 SSH；C8-788 用官方 SSH 管理 ipk |
| 2 | **是官方 NROS** | `cat /tmp/sysinfo/model` | 在支持列表内 | 标准 OpenWrt → **停手**，本脚本不适用 |
| 3 | 机型归一化 | 见 §0.5 | `NRadio_C2000Ultra` | 其它值 → 脚本会 `die "环境检测失败：当前设备不在支持列表内"` |
| 4 | **版本门禁** | `ubus call system board` 看 `release.revision` | `2.*` 或 `1.9.*`(仅 C5800-650) | ⚠️ **别拿 `DISTRIB_RELEASE` 判断**（见 §0.5 的坑） |
| 5 | **SD 卡在场** | `awk '$1 ~ /^\/dev\/mmcblk/ && $2 ~ /^\/tmp\/storage/' /proc/mounts` | 有输出 | C2000Ultra 强制要求，无卡会 `die "未检测到 SD 存储卡"` |
| 6 | wget 可用 | `wget --version \| head -1` | 有输出（本机是 **GNU Wget 1.19.2**，非 busybox） | 走 `uclient-fetch` |
| 7 | 镜像可达 | 见下方 | `MIRROR_OK` | 换 `ghfast.top` 或 raw 直连（本机四条链路全通） |
| 8 | 交互式终端 | —— | 有**真 TTY**（推荐；非 TTY 的三种行为见下方实测表） | —— |
| 9 | 内存 >100MB | `free -k` | `MemAvailable` > 100000（本机约 531 MB） | 别跑大插件 |
| 10 | **已自行备份** | 见 §4 第 ① 步 | 备份文件在本地 | 🔴 **它自己不备份**，必须你先做 |
| 11 | 已拍补丁基线 | `python scripts/adapt_maye_assistant.py snapshot` | 基线写入 | 先 snapshot 再跑 |

```sh
# 一次性跑完（设备侧，只读）
echo "--- 1 ssh"; ok
echo "--- 2 model"; cat /tmp/sysinfo/model; cat /tmp/sysinfo/board_name
echo "--- 4 version"; ubus call system board | grep -A1 revision
echo "--- 5 sdcard"; awk '$1 ~ /^\/dev\/mmcblk/ && $2 ~ /^\/tmp\/storage/' /proc/mounts
echo "--- 6 wget"; wget --version 2>&1 | head -1
echo "--- 7 mirror"; wget -q -T 10 -O /dev/null "https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/refs/heads/main/CHECKSUMS.txt" && echo MIRROR_OK || echo MIRROR_FAIL
echo "--- 9 mem"; free -k | head -2
```

> **启动流程（脚本第 999-1024 行）**：清屏 → 打印免责声明（顶部显示识别到的机型）→
> `run_startup_disclaimer_countdown 10`（**10 秒倒计时**，真终端下逐秒刷新）→ 提示
> `同意并继续 [y/N，回车退出]:` → 读 stdin。输入 `y` 才 `mkdir -p $STATE_DIR` 并写
> `/root/.nradio-plugin-menu/disclaimer_accepted_20260615-v260-model-disclaimer-c2000pro-risk-v1.flag`
> （27 B，内容 `accepted V3.2.0 2026-09-14`）；**回车或其它字符 = `exit 0`，完全不写盘**。
>
> **stdin 的三种行为（2026-09-19 真机实测，别记错）**：
>
> | 喂法 | 实测结果 |
> |---|---|
> | `sh …sh < /dev/null`（stdin 关闭） | 打印完免责声明后 `die "input cancelled"`，rc=1，耗时 10.3 s |
> | `exec_command` 直接跑、**不喂数据也不关**（AI 的默认写法） | **永久挂住**在 `read`（实测 14 s 后进程仍在；客户端挂满 3.8 min 才被手动终止）—— 比报错更糟 |
> | `printf 'y\n0\n' \| sh …sh`（管道喂够数据） | **能跑通**「同意 → 菜单 → 退出」，rc=0 |
>
> 也就是说：**技术上传管道可以自动化它**（旧稿写的「非交互必然失败」不准确，已按实测更正）；
> 但 🔴 **绝不许替使用者在它菜单里选任何一项** —— 它菜单里有「卸载 Docker」这类毁设备选项。
> 正确姿势仍是：AI 把命令贴出来，交给人在真终端里按。
> （实测：`mkdir -p $STATE_DIR` 只在**输入 y 之后**执行 → 菜单出现前**不写盘**。）

---

## 4. 执行

```sh
# ① 先自行备份它可能改到的文件（🔴 它自己不备份，这一步不能省）
mkdir -p /tmp/kp-maye-bak
for f in /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm \
         /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua \
         /etc/config/appcenter /etc/opkg/distfeeds.conf /etc/crontabs/root; do
    [ -f "$f" ] && cp "$f" "/tmp/kp-maye-bak/$(basename "$f")"
done
ls -l /tmp/kp-maye-bak/
#   想更稳就把这个目录拉到 PC 上：scp root@192.168.66.1:/tmp/kp-maye-bak/* ./

# ② 先拍我们补丁的基线（PC 侧跑；记录我们商店补丁的指纹）
python scripts/adapt_maye_assistant.py snapshot

# ③ 设备侧下载 —— ⚠️ 必须【锁 commit】取 V3.2.0，不要用 refs/heads/main
#    （后者是滚动单文件，当前已是未经验证的 V3.2.1；2026-09-24 实测会静默换版）
cd /tmp && wget -O ssh-nradio-plugin-installer.sh \
  "https://ghproxy.vip/https://github.com/561410590/ssh-nradio-plugin-installer/raw/2daa69d8b4/00-current/ssh-nradio-plugin-installer.sh"
#   2daa69d8b4 = V3.2.0 的 commit（2026-09-14，feat: release V3.2.0 and updated router plugins）

# ④ 校验完整性 + 语法（两条都要过，缺一不可）
sha256sum /tmp/ssh-nradio-plugin-installer.sh
#   必须 62f248a924e7b05ccb5c1053ddc800835e075f3697d9221196eac1a0993c8ed8
#   —— 这三方必须一致，任一不符就停：①上行 sha256 ②本仓档案记录
#      ③上游 CHECKSUMS.txt（仓库根目录，官方登记值，2026-09-24 仍只登记 V3.2.0）
#   若哪天要改用 V3.2.1+：上游 CHECKSUMS.txt 必须先补登该版本哈希，否则不得裸跑
#   （V3.2.1 至今无官方哈希、CHANGELOG 也无条目 —— 详见 references/maye-assistant.md
#    的「版本漂移记录」+「V3.2.1 到底改了什么」两节）
sh -n /tmp/ssh-nradio-plugin-installer.sh && echo SYNTAX_OK

# ⑤ 在真终端里跑（人工操作菜单；进菜单前不要选 Docker/AGH/mosdns/奇游/雷神）
sh /tmp/ssh-nradio-plugin-installer.sh
#   ⚠️ 结尾**不要**再跟任何参数！上游官方写法就是不带参数。
#      多带一个仓库 URL 会被当成菜单编号 → `ERROR: 无效编号：https://…` → 直接退出。

# ⑥ 跑完立刻校验我们的补丁有没有被冲掉
python scripts/adapt_maye_assistant.py check
#   有丢失 → python scripts/adapt_maye_assistant.py check --fix
```

**跑完必须复跑一次 check**，并确认第 ⑥ 步输出全 ✓ 才算完成。

---

## 5. 验证判据

```sh
# ① 脚本自身完整（且必须是锁 commit 取回的 V3.2.0）
sha256sum /tmp/ssh-nradio-plugin-installer.sh | awk '{print $1}'
#   必须 62f248a9...8ed8（V3.2.0）。若得到 67e57576...4403，说明拿到的是 V3.2.1 —— 停，别跑。

# ② 它认出了本机（菜单顶部应显示 NRadio_C2000Ultra，而不是「不在支持列表」）
cat /tmp/sysinfo/model            # HC-WT9500

# ③ opkg 源仍是阿里云 21.02.7（本机实测 3 条，不是 5 条）
grep -c 'mirrors.aliyun.com/openwrt/releases/21.02.7' /etc/opkg/distfeeds.conf
#   期望 3

# ④ 我们的商店补丁仍在位（三个关键 marker，任一为 0 就要 --fix）
grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
grep -c '_kp_installed_registry'        /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
grep -c 'aurora_open_app'               /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm

# ⑤ OpenClash 没被误伤
pidof clash                       # 有输出（本机实测 16659）
curl -s -o /dev/null -w '%{http_code}\n' -m 5 http://127.0.0.1:9090/version   # 401 也算活着
/etc/init.d/openclash status      # running

# ⑥ Docker 载体没被动（红线 2 的哨兵）
grep -nE 'data_root|registry_mirrors' /etc/config/dockerd

# ⑦ 它自己的状态目录（注意：**没有** nradio-plugin-fix，因为它不备份）
ls -la /root/.nradio-plugin-menu/ 2>&1 | head
#   实测内容：disclaimer_accepted_20260615-v260-model-disclaimer-c2000pro-risk-v1.flag
#   （27 B，内容 `accepted V3.2.0 2026-09-14`）
ls -ld /root/nradio-plugin-fix 2>&1   # 预期 No such file or directory
```

| 期望 | 说明 |
|---|---|
| sha256 对上 | 对不上就别跑 —— 要么下载残缺，要么镜像被篡改 |
| 菜单显示 `NRadio_C2000Ultra` | 显示别的值 = 环境检测失败，脚本会自行退出 |
| distfeeds 阿里云源 = **3** | 少了说明被覆盖过，用自己备份还原 |
| 三个 marker 全 ≥1 | 任一为 0 → `check --fix` 重放我们的补丁 |
| `pidof clash` 有输出 | 它没碰内核（你没在它菜单里重装 OpenClash） |
| `/etc/config/dockerd` 仍在且含 `data_root` | 你没误选「卸载 Docker」 |
| `/root/nradio-plugin-fix` **不存在** | 正常现象 —— 它从不备份 |

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 它改的 LuCI 文件 | 🔴 **只能靠你自己 §4① 的备份**（`/tmp/kp-maye-bak/`）；或从 `/rom` 取原厂副本 |
| 我们的商店补丁 | `python scripts/adapt_maye_assistant.py check --fix`（自动重放 patches） |
| opkg 源 | 用自己备份还原 → `opkg update` |
| OpenClash 内核 | 重走 [`tasks/01-openclash-install.md`](01-openclash-install.md)（离线素材在 `offline/core/`） |
| Docker 载体（误选卸载） | 重建 `/etc/config/dockerd` 的 `data_root` 与 `registry_mirrors`（见红线 2 的三行原文） |
| 免责声明状态 | 删 `/root/.nradio-plugin-menu/disclaimer_accepted_*.flag`（下次会重新询问） |
| LuCI 崩了 | 见 `references/istore-integration.md` 的 `/rom` 全量恢复 |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| `input cancelled` 直接退出 | stdin 被关闭（`< /dev/null`、管道已 EOF） | 到真终端里跑（它会先打印完整免责声明再报错） |
| 命令发出后**一直没反应也不报错** | `exec_command` 跑但没喂 stdin → 永久阻塞在 `read` | 别用 `exec_command` 跑它；到真终端里跑 |
| `无效编号：https://github.com/…` | 运行命令**多带了参数**（脚本把 `$1` 当菜单编号） | 去掉参数：`sh /tmp/ssh-nradio-plugin-installer.sh` |
| 卡在 10 秒倒计时 | 免责声明流程，属正常 | 等倒计时结束，输入 `y` |
| `环境检测失败：当前设备不在支持列表内` | 机型不被识别 | 确认是官方 NROS；本机应为 `HC-WT9500` |
| ~~`当前系统不是受支持的 NROS 1.9/2.x`~~ | ⚠️ **本机不会出现**（实测 PASS）。若真出现，**先查 `ubus call system board` 的 `release.revision`**，别看 `DISTRIB_RELEASE` | 见 §0.5 |
| `当前机型为 NRadio_C2000Ultra，但未检测到 SD 存储卡` | TF 卡没插或挂载点不在 `/tmp/storage/*`、`/mnt/app_data` | 插卡重启；或选分类 5 绕开该门禁 |
| 跑完商店页面按钮消失 / 装机无进度 | 它重写了 appcenter.lua 或 htm，冲掉我们的补丁 | `check --fix` 重放，再清缓存 `rm -rf /tmp/luci-indexcache*` |
| `opkg update` 之后装不上包 | distfeeds 被改 | 用自己备份还原 |
| OpenClash 起不来了 | 在它菜单里重装过内核 | 用 `offline/core/mihomo-linux-arm64.gz` 重装内核 |
| 1Panel / 容器全没了 | 误选了「卸载 Docker」（红线 2） | 重建 `/etc/config/dockerd`，见 §6 |
| 菜单里中文错行 | 按字节算宽的固件差异 | 见 `references/script-ui.md` |

---

## 8. 实战记录（2026-09-19 · C2000 U）

**第一轮**只做了「只读验证 + 门禁逐关卡实测」（未进菜单）；**第二轮**补做了「真终端完整走通菜单」
的可用性验证 —— 见 §8.4 / §8.5。

### 8.1 下载与完整性

| 阶段 | 实测结果 |
|---|---|
| 下载 | `cd /tmp && wget -O ssh-nradio-plugin-installer.sh https://ghproxy.vip/https://github.com/.../00-current/ssh-nradio-plugin-installer.sh` → **0.9 秒 / 715 KB/s / 2,878,882 字节** |
| 解析 | 设备侧 DNS 解析到 `198.18.1.10`（OpenClash 的 fake-ip），即下载走本机代理转发 —— **代理关掉时该链路未必通**，这是隐含依赖 |
| 完整性 | `sha256sum` = `62f248a9…8ed8`，与上游 `CHECKSUMS.txt` **完全一致** |
| ⚠️ 版本漂移（2026-09-24 增补） | 上表那次下载走的是 `refs/heads/main`。**该 URL 是滚动的**：2026-09-24 复跑同 URL 已拿到 **V3.2.1**（`67e57576…4403` / 2,893,017 B），不再是 V3.2.0。**今后必须锁 commit `2daa69d8b4`**；且上游 `CHECKSUMS.txt` / `CHANGELOG.md` **至今只覆盖到 V3.2.0** → V3.2.1 无官方校验值，不得裸跑。详见 `references/maye-assistant.md` 的「版本漂移记录」 |
| 语法 | `sh -n` → `SYNTAX_OK` |
| 4 条镜像链路 | `ghproxy.vip + raw` / `ghproxy.vip + github/raw` / `ghfast.top` / `raw 直连` **全部 OK** |

### 8.2 门禁逐关卡实测（详见 §0.5）

在真机上把 `installer.sh` 的判定链**逐字复刻**成探针脚本跑了一遍，输出：

```
raw_model=[HC-WT9500]        raw_board=[HCMT7987-SNSD]
raw_compat=[HCMT7987-SNSD mediatek,mt7987a mediatek,mt7987 ]
nros_revision=[2.3.0.n0.c1]  normalized_model=[NRadio_C2000Ultra]
L1430 机型非空 ......... PASS
L1431 版本非空 ......... PASS
L1432 版本门禁 ......... PASS      <-- case 匹配 2.* => return 0
L1410 SD 卡前置 ........ 会触发
storage_mount=[/tmp/storage/mmcblk0p1]   avail=15438 MiB
```

`ubus call system board` 原始输出（关键一行）：
```json
"release": { "distribution": "OpenWrt", "version": "21.02-SNAPSHOT",
             "revision": "2.3.0.n0.c1", "target": "mediatek/mt7987", ... }
```

`/etc/opkg/distfeeds.conf` 守卫逐字复刻结果：**「软件源: 保留当前固件源」，不重写**。

### 8.3 本机痕迹与现况

| 项 | 实测 |
|---|---|
| 本机跑过它吗 | **没有**。`/root/.nradio-plugin-menu/`、`/root/nradio-plugin-fix/` 均不存在；appcenter.htm 的 `Design By MaYe` 计数 = 0（档案里原先记的「本机已跑过 V2.9.9」是**已下线的 C2000 Max**，不是这台 U） |
| 我们的补丁现状 | appcenter 三个 marker 全为 0，`/etc/kp_store/` 只有 `routes.list`（无 `patch-baseline.json`）→ **本机还没跑过我们的商店补丁**，当前无冲突面 |
| OpenClash | `pidof clash` = **16659**，`/etc/init.d/openclash status` = `running`，内核 `/etc/openclash/core/clash_meta`（10.75 MB） |
| Docker | `pidof dockerd` = 25269，`/etc/config/dockerd` = 304 B（含 `data_root` + 2 条镜像加速源） |
| 启动写盘 | 免责声明流程里 `mkdir -p $STATE_DIR` 只在**输入 y 之后**执行 → **菜单出现前不写盘** |

### 8.4 可用性验证：真终端完整走通（第二轮 · PTY 会话）

用 PTY 伪终端按**正确用法**（不带参数）跑了一遍，全程只浏览菜单、不选任何功能项：

```
① 免责声明 [y/N] -> 输入 y
② 主菜单渲染   -> 输入 1
③ 子菜单渲染   -> 输入 0 返回
④ 回到主菜单   -> 输入 0 退出 -> 回到 root@nradio:~#
```

菜单顶部（**脚本自己打印的**，不是我方复刻）：

```
--------------------------------
  NRadio 官方系统插件安装助手
--------------------------------
  版本  V3.2.0  /  2026-09-14
  设备  NRadio_C2000Ultra          <-- 机型识别正确
  系统  NROS 2.3.0.n0.c1           <-- 版本识别正确
  作者  maye
--------------------------------
  功能分类
--------------------------------
   1. 常用插件安装
   2. VPN / 组网 / 路由向导
   3. 游戏加速器
   4. 应用商店与页面美化
   5. 设备维护与检测
   0. 退出

选择 [0-5]:
```

选 `1` 后打印 **`环境检测: 已检测到 NRadio 应用商店`**（= `require_nradio_menu_environment` 实跑通过），
然后渲染子菜单：

```
  1 / 常用插件
   1. swap 虚拟内存（C2000MAX / C2000Ultra）
   2. 哈基米
   3. ttyd / Web SSH
   4. AdGuardHome
   5. OpenList
   6. MosDNS
   7. DDNS-GO
   8. Docker（C5800 系列 / C8-688）
   9. MT5700 WebUI V3.0.0
  10. Open-Box
   0. 返回功能分类
```

**跑后复核（与跑前基线逐项对比，全部一致）**：

| 项 | 跑前 | 跑后 |
|---|---|---|
| `pidof clash` | 16659 | 16659（未变） |
| `pidof dockerd` | 25269 | 25269 |
| `/etc/config/dockerd` sha256 | `ec346b56…1924` | 同左 |
| `appcenter.lua` sha256 | `68e919c3…4b47` | 同左 |
| `appcenter.htm` sha256 | `34880d1a…5bbc` | 同左 |
| appcenter 三个 marker | 0 / 0 / 0 | 0 / 0 / 0 |
| `/etc/opkg/distfeeds.conf` sha256 | `aa8c4df3…cc93` | 同左 |
| `curl -m 8 http://www.baidu.com` | 200 | 200 |

**零残留**：`/etc/config`、`/usr/lib/lua/luci`、`/etc/kp_store` 无任何新增或改动；`/var/run` 无残留锁；
测试创建的 `/root/.nradio-plugin-menu/` 已删除（回到测试前状态）。
唯一新增是 `/root/.ash_history`（PTY 会话记录的命令历史，无害）。

### 8.5 stdin 三种行为实测（决定「能不能自动化」）

| 喂法 | rc | 耗时 | 结果 |
|---|---|---|---|
| `sh …sh < /dev/null` | 1 | 10.3 s | 打印完免责声明 → `ERROR: input cancelled` |
| `exec_command` 不喂不关 | — | — | **永久挂住**在 `read`（进程 14 s 后仍驻留；客户端挂满 3.8 min 才被手动终止） |
| `printf 'y\n0\n' \| sh …sh` | **0** | 10.3 s | **完整跑通**「同意 → 菜单 → 退出」 |
| `printf '0\n' \| sh …sh`（flag 已存在） | **0** | 0.3 s | 跳过免责声明，直接菜单 → 退出 |

→ **技术上传管道能自动化它**（旧稿「非交互必然失败」的说法不准确，已更正）；
但**流程上仍然不许 AI 替使用者选菜单项** —— 它菜单里有「卸载 Docker」等毁设备选项。

**结论**：链路、机型、版本门禁、SD 卡前置、商店环境**全部就绪**；
真终端下**已完整走通菜单并正常退出** —— **脚本在本机可用**。
剩余风险集中在四条红线/风险上（无备份、别卸 Docker、别装 AGH/mosdns、别装奇游/雷神），
按上面 §0 与 §2 规避即可。
