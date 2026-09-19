# 任务 09 · 分类四「应用商店与页面美化」（助手菜单 8）

> `id: nros.appcenter-polish` · `risk: write`（**直接覆盖我们商店补丁的载体文件 `appcenter.htm` / `appcenter.lua`**）
> 设备：鲲鹏 C2000 U（`192.168.66.1`，aarch64，**NROS 2.3.0.n0.c1** / OpenWrt 21.02-SNAPSHOT，TF 卡存储）
> **这是第三方 NROS 插件安装器（maye 助手）的第 4 个功能分类。**
> 总入口、通用四关、下载/校验/备份/基线/真终端手法全部在
> [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md) —— 本文件只写这一分类特有的东西。
> 对应关系：**助手菜单 `8)` ＝ 上游脚本主菜单 `4. 应用商店与页面美化`**
> 上游真源：`installer.sh:70176-70216`（`appcenter_polish_menu`）· `installer.sh:17274` · `:17388` · `:69527`

---

## 0. 本分类的置顶红线

> 🔴 **这是全脚本对我们仓库影响最直接的一个分类 —— 它要改的两个文件，正好是三个补丁 marker 的载体。**

先看上游的路径常量（`installer.sh:14-15`）：

```sh
TPL="/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm"                     # 前端模板
APPCENTER_CONTROLLER="/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua"    # 后端控制器
```

而我们的补丁 marker 就是落在这两个文件里：

| marker | 载体文件 |
|---|---|
| `nradio_appcenter_extra_action` | `appcenter.lua` |
| `_kp_installed_registry` | `appcenter.lua` |
| `aurora_open_app` | `appcenter.htm` |

1. 🔴 **`1. 美化应用商店` 会先把模板打回 /rom 原厂，再打它自己的补丁。**
   `install_appcenter_polish`（`installer.sh:17274`）的执行顺序实读：
   ```sh
   write_plugin_uninstall_assets
   write_original_appcenter_template     # <-- 回写 /rom 原厂模板（我们的 htm 补丁在此被抹掉）
   patch_common_template
   patch_appcenter_status_controller
   patch_appcenter_card_polish_v3
   install_unified_appcenter_icons
   refresh_luci_appcenter
   ```
   而且它自己明说了 **不备份**：`log "说明: 直接美化应用商店，不创建事务备份或文件备份"`（`:17282`）。

2. 🔴 **`2. 还原应用商店` 会把两个文件都打回原厂 —— 三个 marker 全没。**
   `restore_appcenter_original`（`installer.sh:17388`）实读：
   ```sh
   log "说明: 直接使用 /rom 只读原厂应用商店模板和控制器；不创建备份，不覆盖 /etc/config/appcenter"
   write_original_appcenter_template
   write_original_appcenter_controller   # <-- controller 也回原厂
   refresh_luci_appcenter
   rm -f /usr/libexec/nradio-ai-compat.sh
   /etc/init.d/uhttpd reload
   ```
   → 这是「**把商店恢复成没过我们补丁的样子**」，不是普通回滚。

3. ⚠️ **两者都会 `refresh_luci_appcenter`（`installer.sh:17415`）**：
   ```sh
   fix_nradio_ai_has_ai_compat
   rm -f /tmp/luci-indexcache /tmp/infocd/cache/appcenter
   rm -f /tmp/luci-modulecache/*
   /etc/init.d/infocd restart
   /etc/init.d/appcenter restart
   sleep 2
   ```
   会重启商店后端服务 —— 跑的时候商店页会短暂打不开（正常现象，别误判成坏了）。

4. ⚠️ **`3. OpenWrt 原版 LuCI（8080）` 与上面两条不同，它不碰商店，但会新增一个监听端口。**
   本机**在白名单内**（`openwrt_luci_8080_model_supported`，`installer.sh:68386-68395`，含 `NRadio_C2000Ultra`）。
   它用独立 `uhttpd.openwrt8080` + 独立目录，**不替换 80 端口的 NRadio 界面**（上游 V3.0.0 起）。
   风险：多一个 HTTP 入口；跑前必须确认 `8080` 没被占。

5. ℹ️ **`4. 轻量应用商店` 在本机不会出现**：`lightweight_appcenter_model_supported`（`:17234-17239`）
   只认 `NRadio_C2000Pro|NRadio_AK68-798`。本机菜单里根本没有这一项；若被强行调用会 `die`。

---

## 1. 上游菜单真源（逐字抄自 `appcenter_polish_menu`）

```
  4 / 应用商店与页面
   1. 美化应用商店
   2. 还原应用商店
   3. OpenWrt 原版 LuCI（8080）
   0. 返回功能分类
```

> 第 3 项只在机型白名单内才打印；第 4 项（轻量应用商店）只在 C2000Pro / AK68-798 上打印。

| 菜单号 | 名称 | feature | 实现的函数 | 上游行号 |
|---|---|---|---|---|
| 1 | 美化应用商店 | 15 | `install_appcenter_polish` | 69981-69984 · 函数 17274 |
| 2 | 还原应用商店 | 16 | `restore_appcenter_original` | 70006-70008 · 函数 17388 |
| 3 | OpenWrt 原版 LuCI（8080） | 28 | `manage_openwrt_luci_8080` | 70038-70040 · 函数 69527 |
| （3 的子项） | 1 安装或更新 / 2 卸载 | —— | `install_openwrt_luci_8080` / `uninstall_openwrt_luci_8080` | 69537-69538 · 69505 |
| 4 | 轻量应用商店 | 31/32 | `install_/remove_lightweight_appcenter` | 本机不显示 |

---

## 2. 本机（NRadio_C2000Ultra）可用子集

| 菜单号 | 本机 | 建议 |
|---|---|---|
| 1 美化应用商店 | ⚠️ 可用（**会抹我们的 htm 补丁**） | 想美化**优先用我们自己的补丁集**；真要用它必须先备份 + 跑完 `check --fix` |
| 2 还原应用商店 | ⚠️ 可用（**会抹掉全部三个 marker**） | 只在「你想彻底放弃我们的商店补丁」时才用；用之前必须明确告知 |
| 3 OpenWrt 原版 LuCI（8080） | ✅ 可用 | 唯一相对安全的项；跑前查 8080 占用，跑后验 80 未被影响 |
| 4 轻量应用商店 | ❌ 本机不显示 | 忽略 |

**一句话**：本分类在本机**唯一建议做的是 `3`**；`1` 与 `2` 都会动我们的补丁载体，
要用就得接受「跑完必须 `check --fix` 重放」这个代价。

---

## 3. 前置检查（在 tasks/05 §3 那 11 条之外，本分类额外要测）

| # | 检查 | 命令（设备侧） | 判据 | 不满足怎么办 |
|---|---|---|---|---|
| a | **补丁基线（本分类最重要）** | `python scripts/adapt_maye_assistant.py snapshot` | 基线写入 | 没基线就跑＝没法判断被抹了什么 |
| b | 三个 marker 当前值 | `grep -c 'nradio_appcenter_extra_action' …appcenter.lua` 等三条 | 记下（本机当前**全为 0**：我们还没跑过商店补丁，见 tasks/05 §8.3） | 为 0 说明现在没可丢的东西；≥1 说明必须先备份 |
| c | 两文件 sha256 | `sha256sum /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua` | 记下 | 跑完用它对账 |
| d | `/rom` 原厂是不是真存在 | `ls -l /rom/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm /rom/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua` | 两个都存在 | 不存在 → 上游 `write_original_*` 会失败，先停手 |
| e | 商店服务状态 | `/etc/init.d/appcenter status; /etc/init.d/infocd status` | running | 先修商店，别在坏的基础上美化 |
| f | 8080 端口占用 | `netstat -ltnp \| grep ':8080 '` | 无输出 | 被占 → 第 3 项会冲突 |
| g | 80 端口基线 | `netstat -ltnp \| grep ':80 '` | 记下监听者 | 用来证明「装了 8080 没影响原有 80」 |

```sh
# 一次性跑完（设备侧，只读）
echo "--- b markers"; grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
                      grep -c '_kp_installed_registry'        /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
                      grep -c 'aurora_open_app'               /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm
echo "--- c sha";     sha256sum /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm \
                              /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
echo "--- d rom";     ls -l /rom/usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm \
                            /rom/usr/lib/lua/luci/controller/nradio_adv/appcenter.lua 2>&1
echo "--- e svc";     /etc/init.d/appcenter status; /etc/init.d/infocd status
echo "--- f/g ports"; netstat -ltnp 2>/dev/null | grep -E ':(80|8080) '
```

---

## 4. 执行

**通用部分照 tasks/05 §4 走**（自备备份 → `snapshot` → 下载 → `sha256sum` + `sh -n`）。

### (a) AI 先做

```sh
# ① 备份两文件 + 全套商店相关件（上游明说不备份，见红线 1/2）
mkdir -p /tmp/kp-maye-bak/appcenter
cp /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm              /tmp/kp-maye-bak/appcenter/
cp /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua              /tmp/kp-maye-bak/appcenter/
[ -f /etc/config/appcenter ] && cp /etc/config/appcenter               /tmp/kp-maye-bak/appcenter/
[ -f /usr/libexec/nradio-ai-compat.sh ] && cp /usr/libexec/nradio-ai-compat.sh /tmp/kp-maye-bak/appcenter/
sha256sum /tmp/kp-maye-bak/appcenter/* | tee /tmp/kp-maye-bak/appcenter/sha256.txt
ls -l /tmp/kp-maye-bak/appcenter/
#   强烈建议拉到 PC：scp root@192.168.66.1:/tmp/kp-maye-bak/appcenter/* ./

# ② 拍我们的补丁基线（红线 1/2 的对照组）
python scripts/adapt_maye_assistant.py snapshot

# ③ 记跑前状态（给 §5 做对照）
sha256sum /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm \
          /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua \
          /etc/config/appcenter 2>/dev/null
```

### (b) 然后停下等你 —— 由你在真终端里按

```sh
sh /tmp/ssh-nradio-plugin-installer.sh      # 结尾不许跟参数
```

进菜单 `4` →「应用商店与页面美化」。**建议只按 `3`（OpenWrt 原版 LuCI 8080）**。
按 `1` / `2` 之前，AI 必须把红线 1/2 讲清楚并确认你接受「跑完要 `check --fix`」。
AI **不许**替你按任何编号（协议硬约束 9）。

### (c) 你回来后 AI 立刻跑

```sh
# ① 先看商店还活着没（refresh_luci_appcenter 会重启 infocd/appcenter）
/etc/init.d/appcenter status; /etc/init.d/infocd status
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://127.0.0.1/cgi-bin/luci/      # 期望 200/302

# ② 三个 marker 对账（这就是本分类的验收核心）
grep -c 'nradio_appcenter_extra_action' /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
grep -c '_kp_installed_registry'        /usr/lib/lua/luci/controller/nradio_adv/appcenter.lua
grep -c 'aurora_open_app'               /usr/lib/lua/luci/view/nradio_appcenter/appcenter.htm

# ③ 丢了就重放我们的补丁
python scripts/adapt_maye_assistant.py check        # 看哪些丢了
python scripts/adapt_maye_assistant.py check --fix  # 重放
python scripts/adapt_maye_assistant.py check        # 再确认全 ✓

# ④ 清 LuCI 缓存（上游 refresh 已清一部分，保险再清一次）
rm -rf /tmp/luci-indexcache /tmp/luci-modulecache/*
```

---

## 5. 验证判据

```sh
# ① 商店后端活着
/etc/init.d/appcenter status
/etc/init.d/infocd status

# ② 我们补丁的状态与「你的选择」一致
python scripts/adapt_maye_assistant.py check
#   只按了 3（8080）→ 期望三 marker 与跑前**同值**
#   按了 1 或 2     → 期望 check 显示丢失，且 check --fix 后全部恢复为 ✓

# ③ 只按了 3 时：8080 新增、80 不变
netstat -ltnp 2>/dev/null | grep -E ':(80|8080) '
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://192.168.66.1:8080/     # 8080 入口可用
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://192.168.66.1/          # 80 仍可用

# ④ 全局没被误伤
pidof clash
curl -s -o /dev/null -w '%{http_code}\n' -m 8 http://www.baidu.com          # 200
grep -nE 'data_root|registry_mirrors' /etc/config/dockerd
```

| 判据 | 期望 | 说明 |
|---|---|---|
| `appcenter` / `infocd` 状态 | running | 起不来＝商店页全白，必须先修 |
| 三个 marker | 与你的选择一致（见上） | 与期望不符 → `check --fix` |
| 80 端口 | 仍在监听（且实现未变） | 第 3 项**不应该**动 80 |
| 8080 | 只按了 3 才有 | —— |
| `pidof clash` | 与跑前同值 | 本分类不该碰网络 |
| 真 HTTP | `200` | **别用 ping/TCP 判活** |

---

## 6. 回滚

| 想恢复什么 | 怎么做 |
|---|---|
| 我们的商店补丁被抹 | `python scripts/adapt_maye_assistant.py check --fix`（**首选**，自动重放） |
| 整个商店回原厂 | 上游菜单 `4 → 2`（它自己会从 `/rom` 回写）；或手动 `cp /rom/...appcenter.htm /usr/lib/lua/luci/view/nradio_appcenter/` |
| 美化 / 还原之前的商店状态 | 用 §4(a)① 的备份覆盖两文件 → `rm -rf /tmp/luci-indexcache*` → `/etc/init.d/appcenter restart` |
| 被删的 `nradio-ai-compat.sh` | 从 §4(a)① 备份拷回（`restore_appcenter_original` 会 `rm -f` 它，`:17403`） |
| 8080 想撤 | 上游菜单 `4 → 3 → 2`（`uninstall_openwrt_luci_8080`，`:69505`）：删 `uhttpd.openwrt8080` + 独立目录 + 缓存 |
| 商店彻底崩了 | 见 [`references/istore-integration.md`](../references/istore-integration.md) 的 `/rom` 全量恢复 |

---

## 7. 已知坑速查

| 症状 | 原因 | 修法 |
|---|---|---|
| 商店页白屏 / 转圈 | `refresh_luci_appcenter` 重启了 infocd/appcenter，缓存正在重建 | 等几秒；`rm -rf /tmp/luci-indexcache*` 后刷新 |
| 按钮消失 / 「已装」标记没了 | 我们的 `appcenter.htm` 补丁被 `write_original_appcenter_template` 抹掉 | `check --fix` |
| `install_appcenter_polish` 报找不到原厂模板 | `/rom` 里没有对应文件 | 见 §3(d)，先确认 `/rom` 完整再动手 |
| 想美化又不想丢我们的补丁 | 两套补丁改同一文件 | 先美化 → 立刻 `check --fix`；顺序不能反 |
| 8080 打不开 | `8080` 被别的服务占了 | §3(f) 先查；换端口或先停占用者 |
| 8080 开了之后 NRadio 主界面变了 | 上游 V3.0.0 前的旧版会改主站主题选择 | 用 `4 → 3 → 2` 卸载（`restore_nradio_main_theme_selection` 会回主主题） |
| 按了「轻量应用商店」相关项 | 本机不显示该项；强调用会 `die` | 别绕过去调；那是 C2000Pro/AK68-798 的功能 |

---

## 8. 与其他文件的关系

- 通用四关 / 下载校验 / 真终端手法 / stdin 三种行为 → [`tasks/05-nros-plugin-installer.md`](05-nros-plugin-installer.md)
- 商店补丁机制本身 → [`references/store-patching.md`](../references/store-patching.md)
- 应用商店与 iStore 集成 → [`references/istore-integration.md`](../references/istore-integration.md)
- 上游整体画像 → [`references/maye-assistant.md`](../references/maye-assistant.md)
- 菜单协议（AI 怎么被调用）→ [`AGENTS.md`](../AGENTS.md) §8
