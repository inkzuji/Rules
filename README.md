# Surge / mihomo 规则集

`surge/` 保存 Surge 规则，`clash/` 由同一构建链路自动生成 mihomo 规则。每日拉取上游、按策略优先级去重、按服务主题输出原有 21 个 `.list` 文件，同时按六类业务策略聚合 MRS。既有文本文件地址保持不变。

Clash 目录以 **mihomo** 为兼容目标，不承诺旧 Clash 内核兼容。域名、IP、ASN 等兼容规则保留参数；进程名称、路径及通配符转换为对应 mihomo 进程规则。保留进程值的原始大小写，但两端内核语义不同：Surge 区分进程大小写，mihomo 的名称、路径和通配符匹配不区分。Surge 专属的 `USER-AGENT`、`URL-REGEX` 保留在 Surge，转换时明确统计无法转换的条目；未知语法或无法等价转换的参数中止构建。

## 策略与文件

统一优先级和引用顺序为 **🤖️AI → 🍎苹果 → 🎮游戏 → 🚀节点选择 → 📽哔哩 → DIRECT**。每个规则文件对应一个策略，规则行不携带策略名。同一 `(类型, 值)` 按策略优先级去重；同策略优先采用本次上游参数，来源间按脚本固定顺序处理。

以下相对路径在 `surge/` 和 `clash/` 中各有一份；文件头记录策略和规则数。

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
| `Proxy/Others.list` | 🚀节点选择 | 其余代理规则 |

## 按业务策略聚合的 MRS

MRS 位于 `clash/mrs/`，按策略聚合对应文本文件，AI 包含 OpenAI、Claude、Gemini、Copilot 和其他 AI；不生成服务主题级 MRS，也不生成跨策略混合的规则类型总文件。

| 策略 | 域名主文件 | 聚合范围 |
|---|---|---|
| 🤖️AI | `AI.mrs` | `AI/*.list` |
| 🍎苹果 | `Apple.mrs` | `Apple.list` |
| 🎮游戏 | `Game.mrs` | `Game.list` |
| 🚀节点选择 | `Proxy.mrs` | `Proxy/*.list` |
| 📽哔哩 | `Bilibili.mrs` | `Bilibili.list` |
| DIRECT | `Direct.mrs` | `Direct.list` |

MRS 仅支持 `domain` 和 `ipcidr`，因此每组按需要附带下列文件，空分区省略：

- `*-ip.mrs`：带 `no-resolve` 的 IPv4/IPv6 CIDR，引用处保留 `no-resolve`。
- `*-extra.list`：关键词、ASN、进程等 classical 配套规则，必须一起引用。

存在会触发 DNS 的 CIDR、ASN 或 GEOIP 时，该策略的 IP 规则保留在配套文本中，并保持细分文本的原有执行顺序。例如 Direct 的 ASN 会为后续 `no-resolve` CIDR 提供解析结果，因此不单独生成 `Direct-ip.mrs`。与 IPv4-mapped IPv6 地址段重叠的规则也保留为文本，避免 MRS 转换扩大到 IPv4 匹配。

域名主文件将 `DOMAIN` 写为裸域名、`DOMAIN-SUFFIX` 写为 `+.` 前缀域名。MRS 使用官方 mihomo **v1.19.30** 编译，域名、IP 和残余文本仍指向同一业务策略。

## Surge 引用

将 `<user>/<repo>` 替换为可匿名访问的 GitHub 仓库，策略名称必须已存在于主配置中。按以下顺序放入 `[Rule]`：

```ini
[Rule]
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/OpenAI.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Claude.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Gemini.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Copilot.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/AI/Others.list,🤖️AI
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Apple.list,🍎苹果
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Game.list,🎮游戏
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
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Bilibili.list,📽哔哩
RULE-SET,https://raw.githubusercontent.com/<user>/<repo>/main/surge/Direct.list,DIRECT
FINAL,🐠 Final
```

## mihomo 引用

选用自动生成的一个片段，合并其 `rule-providers` 和 `rules` 到主配置：

- [classical.yaml](clash/classical.yaml)：引用全部 21 个细分文本规则。
- [mrs.yaml](clash/mrs.yaml)：引用六类策略的 MRS 及各自残余文本，组内连续排列。

片段已包含 provider 的 `behavior`、`format`、URL、缓存路径和更新周期；`RULE-SET` 引用 **provider 名称**。将片段中的仓库地址替换为自己的地址时，保留文件相对路径。主配置须提供上述策略组与 `🐠 Final`，`DIRECT` 为内置策略。两套片段择一使用；MRS 方案不能只引用域名主文件，否则会遗漏 IP、关键词、进程等规则。

这些文件仅提供规则引用，不包含订阅、DNS、TUN 或完整客户端配置。进程规则能否命中取决于客户端平台的进程识别能力与配置。

## 本地构建与自动更新

使用 Python 标准库以及官方 mihomo v1.19.30，无新增 Python 依赖。先将对应平台的 mihomo 放入 `PATH`；转换器也支持 `--mihomo /path/to/mihomo`。Linux x86_64 可用 `bash scripts/setup_mihomo.sh /path/to/bin` 下载并校验固定版本，然后将该目录加入 `PATH`。

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/build.py
python3 -B scripts/convert_clash.py --check
```

- `scripts/build.py` 拉取全部必需来源、保留历史规则及细分主题归属，并生成 Surge、mihomo 和 MRS 产物。必需来源抓取或解析失败、异常空响应、转换或校验失败时中止，不发布部分结果。
- `scripts/convert_clash.py --check` 在临时目录重建并比对文本、MRS 及引用片段，检查缺失、多余和内容差异，不修改仓库。未找到 mihomo 或转换失败返回非零退出码。明确的主题来源可纠正历史分类，聚合来源更新参数时保留历史细分归属。
- 原生校验使用隔离配置和空 MMDB stub，逐条检查规则语法、provider 引用及 MRS 覆盖，不下载真实地理数据库；不验证 ASN/GEOIP 的实际归属或真实代理流量。stub 不进入发布文件。
- `scripts/validate.py` 为可选的 DNS 诊断，只报告，不删规则；每日构建不执行 DNS 检查。上游移除和 DNS 查询失败都不会自动删除历史规则。
- 生成和原生校验成功后，自动将不再需要的六策略 MRS 及配套文本移入系统废纸篓（macOS `~/.Trash`，Linux XDG Trash，保留恢复信息）；多文件退役失败时恢复已移动文件。未知产物或废纸篓不可用会阻断构建，`--check` 始终只读。
- `.github/workflows/update-rules.yml` 保留每日 UTC 18:17（北京时间次日 02:17）和手动构建，同一分支的更新任务串行执行，排队后检出最新分支。CI 下载官方固定版本并验证锁定的 SHA-256，成功后仅提交 `surge/`、`clash/` 和 `scripts/.last_count`。
- Pull request 运行测试和只读同步检查，仅授予读取权限，不抓取更新上游、不提交和推送。

## 来源与参考

| 项目 | 使用方式 |
|---|---|
| [666OS/rules](https://github.com/666OS/rules) | `release` 分支 Surge 规则为主要来源，含 Direct |
| [viewer12/OverseasAI.list](https://github.com/viewer12/OverseasAI.list) | 海外 AI 聚合来源 |
| [blackmatrix7 BiliBili](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/BiliBili) | 哔哩哔哩规则来源 |
| [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat/tree/meta/geo/geosite/classical) | GitHub Copilot 规则来源 |
| 本仓库现有 `surge/` | 历史规则合并基底 |
| [ClashMi Rules](https://clashmi.app/wiki/rules) | 客户端规则与规则集使用参考 |
| [HenryChiao/MIHOMO_YAMLS](https://github.com/HenryChiao/MIHOMO_YAMLS) | 按业务组织 MRS 和残余规则的参考 |
| [Surge 官方文档](https://manual.nssurge.com/rules/) | Surge 规则语法依据 |
| [mihomo 规则](https://wiki.metacubex.one/config/rules/) / [rule-providers](https://wiki.metacubex.one/config/rule-providers/) | mihomo 语法、provider 引用及 MRS 格式依据 |
