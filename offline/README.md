# offline/ —— 离线安装素材（版本钉死的快照）

> 目的：让「装 OpenClash / 拉内核 / 装 ocspeed / 装 Docker+1Panel」这四件事
> **在设备完全拉不到外网 CDN 时也能推进**，并且让任何 AI 都能看到**到底要传哪些字节**。
>
> 校验：`md5sum -c checksums.md5`（在 `offline/` 目录下执行）。
> **入库时已用 `.gitattributes` 的 `-text` 属性保护二进制**，若 `gunzip -t` 或 ipk md5 对不上，
> 就是有人动了换行符转换，别怀疑素材本身。

## 目录

| 路径 | 内容 | 大小 | 来源 |
|---|---|---|---|
| `openclash/luci-app-openclash_0.47.156_all.ipk` | OpenClash LuCI 应用包（含内核管理脚本） | 9.9 MB | 厂商源/OpenClash 上游 |
| `openclash/config.openclash.template` | OpenClash 主配置 UCI 模板（**已脱敏**，3 处凭据待填） | 7.9 KB | 真机实测产出 |
| `core/mihomo-linux-arm64.gz` | **Mihomo Meta 内核 v1.19.30**（linux-arm64, with_gvisor） | 16.6 MB | [MetaCubeX/mihomo releases](https://github.com/MetaCubeX/mihomo/releases/download/v1.19.30/mihomo-linux-arm64-v1.19.30.gz) |
| `stubs/*.ipk` ×6 | kmod 空桩包（veth / dm / fs-btrfs / br-netfilter / ikconfig / nf-ipvs），5.4.281-1 aarch64 | ~3 KB | 自造（见 `references/one-command-restore.md` §二） |
| `ocspeed/speedswitch.sh` | ocspeed 主脚本（测速/切换/故障转移/备用预选） | 42 KB | [nros-panel](https://github.com/h910056902/nros-panel) `ocspeed/` |
| `ocspeed/ocspeed.lua` | LuCI 控制器 | 31 KB | 同上 |
| `ocspeed/ocspeed.htm` | 分类测速页面模板 | 109 KB | 同上 |
| `ocspeed/nodetest.htm` | 节点测试页面模板 | 4.5 KB | 同上 |
| `ocspeed/config.ocspeed` | ocspeed 默认 UCI 配置（无凭据） | 1 KB | 同上 |
| `ocspeed/kp-ocspeed.sh` | ocspeed 一键安装/恢复脚本 | 10 KB | 同上 |
| `panel/*.sh` ×6 | nros-panel 一键链（`install.sh` / `kp-install.sh` / `kp-storage-init.sh` / `kp-store-lib.sh` / `kp-store-check.sh` / `kp-ui.sh`） | 78 KB | 同上仓库根 |

## ⚠️ 刻意**没有**入库的东西（以及为什么）

| 未入库 | 原因 |
|---|---|
| `bbydy.yaml`（订阅渲染出的 mihomo 配置） | 里面每个节点都带 `password:` / `server:`，等于泄露机场凭据 |
| 真实 `config.openclash` | 含面板密码、代理认证密码、2 条订阅 token |
| ocspeed 的 `*.bak-*` / `*.v10-pending` | 历史中间产物，同内容重复，只会让"哪份是正版"变模糊 |
| `kp-ui-preview.sh` | 本地开发预览用，设备上不需要 |
| 内核包以外的 ipk | `dockerd`/`containerd`/`runc` 等真依赖**从阿里云 opkg 源装**（见任务 03），只有 6 个 kmod 需要桩包 |

## 🔴 一条必须知道的上游残留

`http_stage/`（本机工作区）里那份**旧 v3.3** `ocspeed.lua` 第 153 行仍硬编码了
`Authorization: Bearer <旧面板密码>`；`scripts/speedswitch.sh`（v3.3 冻结副本）第 26 行同样残留。

**本目录用的是 `nros-panel` 的版本，已修好**：
- `ocspeed.lua`：从 `uci get openclash.config.dashboard_password` 动态取（不再写死）
- `speedswitch.sh`：从 `openclash.config.{cn_port,dashboard_password}` 取，未设置时按无密钥访问

→ **不要把 `http_stage/` 的那两份拷回来用**，否则改过面板密码的机器上页面会静默显示陈旧数据。

## 两条使用路径

### A. 有网（推荐，最省事）

```sh
# 全链（换源 + OpenClash + Docker + 1Panel + ocspeed）
wget -qO /tmp/kp.sh https://raw.githubusercontent.com/h910056902/nros-panel/main/install.sh && sh /tmp/kp.sh

# 只装某一步
SCRIPT=kp-ocspeed.sh sh /tmp/kp.sh
SCRIPT=kp-store-check.sh sh /tmp/kp.sh          # 只读体检
```

### B. 无网 / 只差内核或 ipk（本目录的用途）

用 `scripts/revtunnel_put.py` 走 SSH 反向隧道投递（设备**没有 SFTP**，PC 的 HTTP 服务
也被 Windows 防火墙拦入站，反向隧道是唯一可靠通道；实测 16.6 MB / 2.2 s）：

```sh
# PC 侧（仓库根目录执行，凭据走环境变量）
export ROUTER_HOST=192.168.66.1 ROUTER_USER=root ROUTER_PW=<设备密码>
python scripts/revtunnel_put.py offline/openclash/luci-app-openclash_0.47.156_all.ipk /tmp/oc_stage/
python scripts/revtunnel_put.py offline/core/mihomo-linux-arm64.gz /tmp/oc_stage/
```

> ⚠️ `offline/panel/` 里的 nros-panel 脚本**只能"单步执行"，不能整链离线跑**：
> `install.sh` 的 `fetch()` 不做本地回退，永远去三源下载。离线时请直接调具体那一个脚本，
> 并保证 `kp-ui.sh` / `kp-store-lib.sh` 与它**同目录**（脚本启动时会检查并报错）。
> 另外 opkg 装包本身就依赖阿里云源，所以"完全离线"只对**已装好系统、只差内核/插件**的场景成立。

## 许可与来源

| 素材 | 许可 |
|---|---|
| OpenClash（`luci-app-openclash`） | GPL-3.0 · <https://github.com/vernesong/OpenClash> |
| Mihomo（`mihomo-linux-arm64.gz`） | GPL-3.0 · <https://github.com/MetaCubeX/mihomo> |
| ocspeed 五件套 + `kp-*.sh` | 本项目自建（同本仓库许可） |

内核与 ipk 为**上游原样分发**，未做任何修改；请以各自上游仓库的版本为准。
若日后想给仓库瘦身，把这两个二进制挪到 GitHub Release 附件、此处只留下载链接即可。
