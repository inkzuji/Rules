"""两阶段路由：明确域名先匹配，再按既有策略执行关键词、IP 和进程兜底。"""
from pathlib import Path

from rules import POLICIES, render_rules


PROXY_ORDER = ['YouTube', 'Netflix', 'Disney', 'Spotify', 'Streaming', 'GitHub',
               'Microsoft', 'Google', 'Social', 'Dev', 'Cloudflare', 'Others']
SERVICE_NAMES = (['AI/' + name for name in ('OpenAI', 'Claude', 'Gemini', 'Copilot', 'Others')]
                 + ['Apple', 'Game', 'Bilibili', 'Direct']
                 + ['Proxy/' + name for name in PROXY_ORDER])


def service_paths(directory):
    return sorted(path for path in Path(directory).rglob('*.list')
                  if 'routing' not in path.relative_to(directory).parts)


def entry_order(entry):
    name, _, policy, *_ = entry
    service = name.removeprefix('domain-').split('-')[-1]
    theme_rank = PROXY_ORDER.index(service) if policy == '🚀节点选择' and service in PROXY_ORDER else 0
    return list(POLICIES).index(policy), theme_rank, name


def domain_artifacts(files):
    """输入为 (相对路径, 策略, 规则列表)，保留服务级地址可追溯性。"""
    artifacts, entries = {}, []
    for relative, policy, rules in files:
        domains = [rule for rule in rules if rule[0] in ('DOMAIN', 'DOMAIN-SUFFIX')]
        if domains:
            path = 'routing/' + relative[:-5] + '-domain.list'
            artifacts[path] = render_rules(policy, domains).encode('utf-8')
            entries.append(('domain-' + relative[:-5].replace('/', '-'), path, policy,
                            'classical', 'text', False))
    return artifacts, sorted(entries, key=entry_order)


def surge_references(entries):
    lines = ['# 合并到 [Rule]；明确域名全部先于 IP、进程等兜底。']
    base = 'https://raw.githubusercontent.com/inkzuji/Rules/main/surge/'
    lines.extend(f'RULE-SET,{base}{relative},{policy}' for _, relative, policy, *_ in entries)
    lines.append('FINAL,🐠 Final')
    return ('\n'.join(lines) + '\n').encode('utf-8')
