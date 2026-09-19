---
id: REF-portainer-i18n
title: "Portainer CE 汉化（鲲鹏 C2000 Max 实测）"
tags: [portainer, i18n, zh-cn, static-js]
risk: low
preconditions:
  - "Portainer 镜像已拉取"
  - "汉化走静态 JS 替换 + 挂载卷"
verified: 2026-09-19
source: kunpeng-router-tuning
---
# Portainer CE 汉化（鲲鹏 C2000 Max 实测）

## 一、结论速览

| 方案 | 结论 |
|---|---|
| 官方 i18n 语言包 | ❌ 没用 —— `/public/locales/en/translation.json` 只有 765 字节，官方才迁移了「访问令牌」一个模块 |
| 第三方汉化镜像 | ⚠️ 未采用（第三方镜像安全性不可控，且 arm64 构建不确定） |
| **静态 JS 替换 + 挂载卷** | ✅ **已落地**：1872 处替换 / 426 词条生效，账号密码与设置不受影响 |
| i18n 语言选择 | 无 —— 改的是字面量，与语言设置无关 |

## 二、前端结构（Portainer CE 2.45）

```
/public/main.<hash>.js      7.0MB  ← Portainer 自身代码，UI 文案全在这里（唯一需要改的）
/public/vendor.<hash>.js    5.7MB  ← 第三方库，跳过
/public/runtime.<hash>.js   4KB    ← webpack runtime，跳过
/public/701|709|933|572.js         ← 小 chunk，实测几乎无文案（709 仅 1 处）
/public/locales/en/translation.json ← 765B，官方 i18n 半成品
```

前端是 **React + AngularJS 混合**（`jsx`、`component("dockerDashboardView")`），
文案形态为 `title:"Dashboard"`、`children:"Containers"`、`label:"Status"`。
容器是 **host 网络模式**，端口 9000 直接监听，无 PortBindings。

## 三、⛑️ 最大的坑：转义引号让正则配对整体错位

**现象**：正则扫出 71894 个"字符串"，却一个 UI 文案都匹配不上（Containers=0）。

**原因**：minified JS 里有 `\"` 转义（本例仅 27 处）。若用
`'"([^"\\\r\n]+)"'` 这种「排除反斜杠」的写法，遇到 `\"` 就会匹配失败并从错误位置
重新配对，**错位会一直传播到文件末尾**，导致之后几万个字符串全部错切。

**验证方法**（务必先做）：
```python
OLD = re.compile(r'"([^"\\\r\n]+)"')       # 错：Containers 命中 0
NEW = re.compile(r'"([^"\\]*(?:\\.[^"\\]*)*)"')  # 对：命中 13（与实际一致）
```
修复后命中数从 **31 → 1872**。

**空串陷阱**：新正则允许 `""`，此时 `m.group(1)` 为 `''`（falsy），
`m.group(1) or m.group(2)` 会取到 `None`。必须写成：
```python
w = m.group(1) if m.group(1) is not None else m.group(2)
```

## 四、四重保护规则（错一个就破坏功能）

只替换「带引号字符串字面量」，并跳过以下语境：

| 规则 | 防的是什么 | 实例 |
|---|---|---|
| `nxt == ':'` | JSON 对象键 / switch-case 值 | `{"Name":`, `case "Running":` |
| `prev in ('[', '.')` | 数组枚举值 / 属性访问 | `["Ready","PodScheduled"]`, `x["Name"]` |
| `nxt in ('=', '!')` **或** `prev=='=' and src[j-1] in '=!'` | 比较运算 | `"Ready"===o.Status`, `x==="Running"` |
| 词典只收**首字母大写** | API 枚举值 / 字段名 | 见下 |

**⚠️ 小写词一律不要收进词典**（血泪）：
- `"no"` → 是 `RestartPolicy:{Name:"no"}` 的 Docker API 枚举值
- `"host"` / `"container"` → 端口映射 API 值 `oneOf(["ingress","host"])`
- `"protocol"` → 字段名 `on("protocol", e)`

**反向教训（保护过度）**：别加 `prev == '('` 保护，
它会挡掉 `.required("This field is required.")` 这类**表单校验提示**（确实是 UI 文案）。

## 五、部署与回滚

```sh
# 汉化文件上传到 /opt/portainer-cn/，原始数据备份在 /opt/portainer-cn/orig/
docker run -d --name portainer --network host --restart unless-stopped \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v /opt/docker/data/portainer:/data \
  -v /opt/portainer-cn/main.<hash>.js:/public/main.<hash>.js:ro \
  portainer/portainer-ce:alpine
```
- **容器是 host 网络 + 数据卷 `/opt/docker/data/portainer`，重建不丢账号密码**
- 回滚：`python cn_rollback.py`（去掉挂载卷重启）
- PC 侧脚本：`patches/portainer_cn_dict.py`（词典）、`portainer_cn_engine.py`（引擎）、
  `cn_build.py`（构建）、`cn_deploy.py`（上传）、`cn_rollback.py`（回滚）、`cn_report.py`（对照表）

## 六、验证清单

1. `node --check main.cn.js` —— 语法必须 OK
2. 响应头 `Content-Type: text/javascript; charset=utf-8` —— 否则中文乱码
3. `curl -s http://127.0.0.1:9000/main.*.js | grep 仪表盘` —— 汉化已下发
4. 关键 API 值仍在：`RestartPolicy:{Name:"no"}`、`oneOf(["ingress","host"])`
5. 用原密码打 `/api/auth` —— 确认配置未丢
6. **提醒用户 `Ctrl + F5` 强制刷新**，否则浏览器缓存旧 js

## 七、上传/下载大文件的姿势

dropbear 无 SFTP、无 base64，7MB 文件这样传：
```python
# 下载：远端 gzip，读 stdout 二进制
_, o, _ = c.exec_command('gzip -c /tmp/main.js', timeout=300)
raw = gzip.decompress(o.read())
# 上传：写 gzip 数据到 stdin，远端 gunzip 落地
stdin, stdout, _ = c.exec_command('gunzip -c > /opt/x/main.js', timeout=300)
stdin.write(gzip.compress(data, 6)); stdin.channel.shutdown_write(); stdout.read()
# 校验：md5sum 对账
```
`stat` 命令在此固件不存在（exit 127），用 `wc -c` / `md5sum`。
