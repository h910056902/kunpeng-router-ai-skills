---
id: REF-adguard
title: "AdGuard Home：部署、全网接管、国内去广告规则"
tags: [dns, adguard, adblock, dnsmasq, port-move]
risk: high
preconditions:
  - "AdGuard Home 已装"
  - "清楚 dnsmasq 与 AGH 的端口分工（53/5354）"
  - "改端口前记录回滚路径"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# AdGuard Home：部署、全网接管、国内去广告规则

## 当前 DNS 链路

```
设备 → AGH(:53) → OpenClash(:7874, Fake-IP) → 上游
       └─ 域名定向 [/music.163.com/] → dnsmasq(:5354) → UNM 网易云保活
dnsmasq 退到 :5354，只管 DHCP
```

回滚备份：/root/bak-dhcp-*.conf + AdGuardHome.yaml.bak-53

## 切换步骤（顺序敏感）

1. 先 sed 改 AGH `AdGuardHome.yaml` 的 `dns.port`（此版 API 不支持改监听端口）→ `docker restart`
2. 迁移 dnsmasq 到 :5354（改 /etc/config/dhcp 的 dns 端口相关项，备份原 conf）
3. 最后重启 AGH 让 53 生效 —— **顺序反了 53 会被 dnsmasq 占住**

## 管理页

- http://192.168.66.1:3000，Docker host 模式
- 免交互初始化：`POST /control/install/configure`
- 登录：`POST /control/login {"name":..., "password":...}` → 拿 cookie 后调 `/control/...` API（新版返回 cookie 而非 JWT）
- 密码通过环境变量传递，不要写进脚本/仓库

## 过滤清单现状（50 万+ 条）

| 清单 | 条数 | 定位 |
|---|---|---|
| AdRules DNS (Cats-Team) | 196507 | 国内主力 |
| AdGuard DNS filter | 177188 | 官方兜底 |
| anti-AD | 97542 | 中文环境命中率高 |
| EasyList China | 18379 | 网页广告 |
| ADgk | 9117 | 视频 APP/开屏广告 |
| CJX 去广告去骚扰 | 1819 | 弹窗/骚扰 |
| AWAvenue 秋风 (AdGuard版) | 902 | 摇一摇/公众号/小程序/电视广告，极轻量 |

## 加清单的方法

- AGH 管理页或 API：`POST /control/filtering/add_url {"name","url","whitelist":false}`
- 参考脚本 `scripts/add_filterlists.py`（登录 + 添加 + 状态核对）
- 先用 `scripts/probe_filterlists.py` 的模式从**路由器侧**探测 URL 可达性与行数

## 规则选择经验

- 规则不是越多越好：内存只有 493MB，可用 <30MB 时勿加 10 万行级清单
- 国内场景性价比排序：秋风(902) > ADgk(9k) > AdRules > anti-AD；国际大块头（Hagezi Pro 22 万行 / OISD Big 27 万行）对国内提升有限
- URL 可达性（经 OpenClash）：raw.githubusercontent.com 可用；jsdelivr/gitee 403/404；adrules.top 返回 HTML 不可用
- 反馈误杀：AGH「自定义过滤规则」加 `@@||域名^$important` 放行
- 国内实测：pos.baidu.com / hm.baidu.com / alimlog 等 SDK 全拦截
