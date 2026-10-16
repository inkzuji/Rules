# Surge / mihomo 规则集

`surge/` 保存 Surge 规则，`clash/` 由同一构建链路自动生成 mihomo 规则。每日拉取上游、按服务归属合并去重，保留原有 21 个服务 `.list` 地址，并生成域名优先路由片段及六类业务策略 MRS。策略组名称保持不变。

Clash 目录以 **mihomo** 为兼容目标，不承诺旧 Clash 内核兼容。域名、IP、ASN 等兼容规则保留参数；进程名称、路径及通配符转换为对应 mihomo 进程规则。保留进程值的原始大小写，但两端内核语义不同：Surge 区分进程大小写，mihomo 的名称、路径和通配符匹配不区分。Surge 专属的 `USER-AGENT`、`URL-REGEX` 保留在 Surge，转换时明确统计无法转换的条目；未知语法或无法等价转换的参数中止构建。

## 策略与文件

服务归属与策略顺序分开处理。`scripts/ownership.py` 的完整域名/后缀契约优先，专属子域覆盖公司公共域；例如 Google 通用域归 `Proxy/Google`，Gemini 专属子域归 `AI/Gemini`。当前来源优先历史；来源按命名服务、开发者等主题聚合、AI 专题聚合、全网代理聚合区分证据强弱，未知的同级明确归属冲突中止构建。共享云的专属租户使用具体域名例外，避免公共云父域反向吞并 AI 服务。Google、Microsoft、GitHub 等仍统一映射到原有 `🚀节点选择`，不新增策略组。

生成配置先引用所有 `DOMAIN` / `DOMAIN-SUFFIX` 路由片段，再执行完整服务文件中的关键词、IP、进程等兜底。两个阶段内部保持 **🤖️AI → 🍎苹果 → 🎮游戏 → 🚀节点选择 → 📽哔哩 → DIRECT**；Proxy 内 YouTube 等专属服务在 Google 等公共父域之前。每个规则文件对应一个策略，规则行不携带策略名。

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

## 历史错分与共享基础设施

- 归属契约覆盖公司公共域及 Gemini、Copilot、YouTube 等专属例外；专属例外显式输出，不依赖上游是否仍包含它们。历史规则也执行同一契约，不能因为原来在 AI 就永久留在 AI。
- [scripts/non_ai_domains.txt](scripts/non_ai_domains.txt) 固定记录已审核的历史支付/素材误分类；只声明这些条目不属于 AI，不认证域名的品牌所有权。新增纠正须使用完整域名及标签边界，不能恢复品牌子串猜测。
- AI 的宽泛关键词、通用浏览器/编辑器进程及未经审核的宽匹配不发布。专属 AI 应用进程保留；共享认证、支付、遥测、CDN 域回到相应公共服务。
- 官方 Cloudflare 共享网段归 Cloudflare；聚合 AI 来源中的未知 IP 和整个 ASN 保守归通用代理。只有命名服务来源提供的非共享 IP 才可保留服务归属。纯 IP 缺乏域名上下文时不能保证识别具体业务。
- 通用代理 IP 若被明确服务网段完整覆盖，去除冗余而保留覆盖；其余未解决的跨策略 IPv4/IPv6 CIDR 重叠阻断构建。同一策略内部的主题交叠不构成跨策略路由冲突。

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

使用自动生成的 [surge/rules.conf](surge/rules.conf)，将其中规则合并到主配置的 `[Rule]`。其中先引用 `surge/routing/*-domain.list`，再引用原有 21 个完整服务文件，最后为 `FINAL`。使用自己的仓库时替换 URL 的仓库地址，策略名称须已存在于主配置中。

**已有配置需要同步更新引用顺序。** 原有 21 个文件地址仍有效；仅继续沿用旧的逐策略完整文件顺序，无法获得全局“域名先于 IP/进程”的保护。不要同时重复导入旧引用列表和新片段。

## mihomo 引用

选用自动生成的一个片段，合并其 `rule-providers` 和 `rules` 到主配置：

- [classical.yaml](clash/classical.yaml)：先引用域名路由片段，再引用全部 21 个完整服务文本规则。
- [mrs.yaml](clash/mrs.yaml)：先引用六类策略的域名 MRS，再引用各类 IP MRS 和残余文本。

片段已包含 provider 的 `behavior`、`format`、URL、缓存路径和更新周期；`RULE-SET` 引用 **provider 名称**。将片段中的仓库地址替换为自己的地址时，保留文件相对路径。主配置须提供上述策略组与 `🐠 Final`，`DIRECT` 为内置策略。两套片段择一使用；MRS 方案不能只引用域名主文件，否则会遗漏 IP、关键词、进程等规则。

这些文件仅提供规则引用，不包含订阅、DNS、TUN 或完整客户端配置。进程规则能否命中取决于客户端平台的进程识别能力与配置。

## 本地构建与自动更新

使用 Python 标准库以及官方 mihomo v1.19.30，无新增 Python 依赖。先将对应平台的 mihomo 放入 `PATH`；转换器也支持 `--mihomo /path/to/mihomo`。Linux x86_64 可用 `bash scripts/setup_mihomo.sh /path/to/bin` 下载并校验固定版本，然后将该目录加入 `PATH`。

```sh
python3 -B -m unittest discover -s scripts -p 'test_*.py'
python3 -B scripts/build.py --report /tmp/rules-classification-report.json
python3 -B scripts/convert_clash.py --check
python3 -B scripts/acceptance.py
```

- `scripts/build.py` 拉取全部必需来源，按归属契约重新审查历史及当前规则，再在暂存目录生成 Surge、mihomo 和 MRS。全部来源、跨策略 CIDR 重叠检查、转换、原生语法验证和分类验收通过后才更新正式产物；失败保留已发布规则和计数。`--report` 写出来源内容 SHA-256、分类统计、候选纠正/过滤原因、逐条最终归属及证据来源、网段冲突和验收结果。
- `scripts/convert_clash.py --check` 在临时目录重建并比对文本、MRS 及引用片段，检查缺失、多余和内容差异，不修改仓库。未找到 mihomo 或转换失败返回非零退出码。命名服务来源可纠正历史分类；没有相反归属证据时，聚合来源更新参数仍保留有效历史细分主题。转换检查本身不代替分类验收。
- 原生校验使用隔离配置和空 MMDB stub，逐条检查规则语法、provider 引用及 MRS 覆盖，不下载真实地理数据库；不验证 ASN/GEOIP 的实际归属或真实代理流量。stub 不进入发布文件。
- `scripts/acceptance.py` 独立读取 Surge 实际引用片段、Clash classical 配置和官方反解后的 MRS，检查完整文本转换契约、全量规则覆盖及服务首匹配。包含 Google/YouTube/Gemini、Microsoft/Copilot/GitHub、跨策略真实 IP、IPv6、纯 IP、普通浏览器/编辑器和仿名域名场景；三端同时错分也会失败。实际 ASN/GEOIP 数据、UA、URL 正则及客户端真实连接未模拟，不能据此声称已验证这些运行行为。
- `scripts/validate.py` 为可选的 DNS 诊断，只报告，不删规则；每日构建不执行 DNS 检查。上游移除和 DNS 查询失败都不会自动删除历史规则。
- 生成和原生校验成功后，自动退役不再需要的六策略 MRS 及配套文本：GitHub Actions（`GITHUB_ACTIONS=true`）直接删除，本机移入系统废纸篓（macOS `~/.Trash`，Linux XDG Trash，保留恢复信息）；多文件退役失败时恢复已处理文件。未知产物或退役失败会阻断构建，`--check` 始终只读。
- `.github/workflows/update-rules.yml` 保留每日 UTC 18:17（北京时间次日 02:17）和手动构建，同一分支的更新任务串行执行，排队后检出最新分支。CI 下载官方固定版本并验证锁定的 SHA-256，成功后仅提交 `surge/`、`clash/` 和 `scripts/.last_count`。
- Pull request 运行测试、只读同步检查和分类验收，仅授予读取权限，不更新上游、不提交和推送。每日构建执行同样的验收门禁，并上传分类报告；失败不会提交规则。

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
