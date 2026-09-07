# Surge / Clash 规则集（RULE-SET 远程引用版）

规则统一位于 `surge/` 目录，由 GitHub Actions 每日自动构建：拉取上游规则 → 按策略优先级合并去重 → 按服务主题拆分 → DoH 校验剔除失效域名。

`clash/` 目录为 Clash 版规则集，由 `surge/` 自动转换生成（classical 格式，Clash / Clash.Meta / mihomo 通用），目录结构与 `surge/` 一一对应。转换规则：

- `DOMAIN` / `DOMAIN-SUFFIX` / `DOMAIN-KEYWORD` / `IP-CIDR` / `IP-CIDR6` / `IP-ASN` / `GEOIP`（含 `no-resolve`）原样保留
- `URL-REGEX` / `USER-AGENT` / `PROCESS-NAME` 等 Clash 不支持的类型剔除

## 设计要点

- **一个文件一个策略**：`RULE-SET` 整文件统一策略，规则行不含策略名
- **细分 + 兜底并存**：可识别服务拆到独立文件，其余进 `Others.list` 兜底
- **全局唯一**：同一 `(类型, 值)` 只出现一次，策略优先级 AI > 苹果 > 游戏 > 节点选择 > 哔哩 > DIRECT
- 文件内按规则类型 + 字典序排序，便于 diff
- Surge 自上而下匹配，引用顺序决定优先级

## 文件清单

| 文件 | 策略 | 覆盖范围 |
|---|---|---|
| `AI/OpenAI.list` | 🤖️AI | OpenAI / ChatGPT / Sora |
| `AI/Claude.list` | 🤖️AI | Anthropic / Claude |
| `AI/Gemini.list` | 🤖️AI | Gemini / Bard / DeepMind |
| `AI/Copilot.list` | 🤖️AI | GitHub Copilot |
| `AI/Others.list` | 🤖️AI | 其余 AI 服务（聚合自 OverseasAI） |
| `Apple.list` | 🍎苹果 | Apple 全系 |
| `Game.list` | 🎮游戏 | Steam / Epic / PlayStation / Xbox 等 |
| `Bilibili.list` | 📽哔哩 | 哔哩哔哩 |
| `Direct.list` | DIRECT | 国内直连 |
| `Proxy/YouTube.list` | 🚀节点选择 | YouTube |
| `Proxy/Netflix.list` | 🚀节点选择 | Netflix |
| `Proxy/Disney.list` | 🚀节点选择 | Disney+ / Hulu / HBO / Prime Video |
| `Proxy/Spotify.list` | 🚀节点选择 | Spotify |
| `Proxy/Streaming.list` | 🚀节点选择 | 其余流媒体 |
| `Proxy/GitHub.list` | 🚀节点选择 | GitHub |
| `Proxy/Microsoft.list` | 🚀节点选择 | Microsoft / Azure / Bing / OneDrive |
| `Proxy/Google.list` | 🚀节点选择 | Google 系（除 YouTube） |
| `Proxy/Social.list` | 🚀节点选择 | Twitter/X / Facebook / Telegram / TikTok 等 |
| `Proxy/Dev.list` | 🚀节点选择 | 开发者站点 |
| `Proxy/Cloudflare.list` | 🚀节点选择 | Cloudflare |
| `Proxy/Others.list` | 🚀节点选择 | 兜底（含全部 IP-CIDR / IP-ASN） |

各文件精确规则数以文件头 `# 规则数` 注释为准。

## 上游来源

- [666OS/rules](https://github.com/666OS/rules)（`surge/*.txt`，release 分支，每日自动更新）
- [viewer12/OverseasAI.list](https://github.com/viewer12/OverseasAI.list)（AI 服务聚合，每日构建）
- 本仓库 `surge_rules/surge/` 现有内容作为基底合并（保留 Direct / Bilibili 等上游未覆盖部分）

## 主配置引用

把 `<user>/<repo>` 替换为你的 GitHub 仓库（分支 `main`）：

```ini
[Rule]
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/OpenAI.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Claude.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Gemini.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Copilot.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Others.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Apple.list,🍎苹果
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Game.list,🎮游戏
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Bilibili.list,📽哔哩
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Direct.list,DIRECT
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/YouTube.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Netflix.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Disney.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Spotify.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Streaming.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/GitHub.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Microsoft.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Google.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Social.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Dev.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Cloudflare.list,🚀节点选择
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Proxy/Others.list,🚀节点选择
FINAL,🐠 Final
```

仓库需**公开**（raw 地址才能匿名访问）；Surge 每 48 小时自动更新外部规则集，也可手动刷新。

## Clash / mihomo 主配置引用

`clash/` 目录与 `surge/` 文件一一对应，把 `<user>/<repo>` 替换为你的 GitHub 仓库（分支 `main`）：

```yaml
rules:
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/AI/OpenAI.list,🤖️AI
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/AI/Claude.list,🤖️AI
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/AI/Gemini.list,🤖️AI
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/AI/Copilot.list,🤖️AI
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/AI/Others.list,🤖️AI
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Apple.list,🍎苹果
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Game.list,🎮游戏
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Bilibili.list,📽哔哩
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Direct.list,DIRECT
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/YouTube.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Netflix.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Disney.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Spotify.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Streaming.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/GitHub.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Microsoft.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Google.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Social.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Dev.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Cloudflare.list,🚀节点选择
  - RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/clash/Proxy/Others.list,🚀节点选择
  - MATCH,🐠 Final
```

## 自动更新

- Workflow：`.github/workflows/update-rules.yml`，每日 UTC 18:17（北京凌晨 2:17）自动构建，支持 Actions 页面手动触发
- 构建脚本：`scripts/build.py`（上游列表与主题关键词表均在脚本内配置），末尾自动调用 `scripts/convert_clash.py` 同步生成 `clash/`
- 失效校验：`scripts/validate.py`（DoH NXDOMAIN 判定，仅输出移除数量，不生成移除清单文件）
- Clash 转换：`scripts/convert_clash.py`（`--check` 校验 clash/ 与 surge/ 是否同步）
- 保护：上游全部拉取失败或规则数骤降超 40% 时构建中止不 push

🟢 上游覆盖面变化（新增/移除某规则集）只需改 `scripts/build.py` 里的 `SOURCE_666OS` 配置表。

## 参考链接

本仓库构建与使用过程中参考/引用的项目：

| 项目 | 说明 | 引用内容 |
|---|---|---|
| [666OS/rules](https://github.com/666OS/rules) | Surge 规则集，每日自动更新 | 主要规则来源，`surge/*.txt` 共 30+ 个规则文件 |
| [viewer12/OverseasAI.list](https://github.com/viewer12/OverseasAI.list) | 海外 AI 服务聚合规则 | `AI/Others.list` 数据来源 |
| [blackmatrix7/ios_rule_script](https://github.com/blackmatrix7/ios_rule_script) | 各分流工具规则合集 | 规则拆分思路与主题分类参考 |
| [ACL4SSR/ACL4SSR](https://github.com/ACL4SSR/ACL4SSR) | 经典 Clash/Surge 分流规则 | 策略组设计与兜底方案参考 |
| [Surge 官方文档](https://manual.nssurge.com/book/understanding-surge/rule.html) | Surge 规则语法说明 | `RULE-SET` / 规则类型语法依据 |
| [mihomo (Clash.Meta) 文档](https://wiki.metacubex.one/config/rules/) | mihomo 规则语法说明 | Clash classical 规则集格式依据 |
