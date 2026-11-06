# Surge / mihomo 规则集

`surge/` 保存源规则，`clash/` 自动转换生成。AI 在源头合并为 `surge/AI.list`，对应生成 `clash/AI.list`，每端仅一个完整 AI 文件。

mihomo 构建版本固定为 **v1.19.30**。Surge 专属的 `USER-AGENT`、`URL-REGEX` 仅保留在 Surge；进程规则转换为 mihomo 对应语法，两端匹配大小写的行为不同。

## 使用

- **Surge**：将 [surge/rules.conf](surge/rules.conf) 合并到主配置的 `[Rule]`。
- **mihomo**：选用 [clash/mrs.yaml](clash/mrs.yaml)（混合优化）或 [clash/classical.yaml](clash/classical.yaml)（完整文本），将 `rule-providers` 和 `rules` 合并到主配置。
- mihomo 同时合并 [clash/geodata.yaml](clash/geodata.yaml)，保留主配置中其他 `geox-url` 地址。使用自己的仓库时，一并替换规则和 ASN 数据库 URL。

主配置需提供以下策略组。公司域名、局域网等自定义优先规则放在业务规则之前，最终兜底保持末尾。片段不包含节点、DNS 或 TUN 配置；两套规则片段择一完整导入。

| 服务文件（相对于 `surge/` 或 `clash/`） | mihomo 策略组 |
|---|---|
| `AI.list` | 🤖 AI 服务 |
| `Apple.list` | 🍎 苹果服务 |
| `Game.list` | 🎮 游戏 |
| `Proxy/Google.list` | 🔍 谷歌服务 |
| 其余 `Proxy/*.list` | 🚀 节点选择 |
| `Bilibili.list` | 📽 哔哩哔哩 |
| `Direct.list` | 🔒 国内服务 |

服务顺序为 AI → Apple → Game → Proxy → Bilibili → Direct。Proxy 内依次为 Google、YouTube、Netflix、Disney、Spotify、Streaming、GitHub、Microsoft、Social、Dev、Cloudflare、Others。AI 整组优先，包含 IP 和专属进程规则。mihomo 最终兜底为 `🐟 漏网之鱼`；Surge 使用文件头的六类策略名及 `🐠 Final`。

优化片段保留服务顺序，AI 和小型服务使用完整 classical 文件。引用中的 `no-resolve` 参数须保留。

## 自动更新

每周一北京时间 **02:17** 自动更新规则及 ASN 快照，也可手动触发 GitHub Actions。规则 provider 刷新周期为 `604800` 秒，geodata 为 `168` 小时。

## 来源

- [666OS/rules](https://github.com/666OS/rules)：主要规则来源。
- [OverseasAI](https://github.com/viewer12/OverseasAI.list)：海外 AI 规则。
- [blackmatrix7 BiliBili](https://github.com/blackmatrix7/ios_rule_script/tree/master/rule/Surge/BiliBili)：哔哩哔哩规则。
- [MetaCubeX/meta-rules-dat](https://github.com/MetaCubeX/meta-rules-dat)：Copilot 规则。
- [xishang0128/geoip](https://github.com/xishang0128/geoip)：ASN 数据库。
- [Surge 官方文档](https://manual.nssurge.com/rules/)：Surge 规则语法。
- [mihomo 路由规则](https://wiki.metacubex.one/config/rules/)：mihomo 规则语法。
- [mihomo rule-providers](https://wiki.metacubex.one/config/rule-providers/)：规则集配置。
