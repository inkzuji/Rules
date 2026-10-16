#!/usr/bin/env python3
"""独立验收文本归属、实际 provider 首匹配和官方反解后的 MRS 覆盖。

匹配场景覆盖域名、CIDR 与进程；不模拟 ASN/GEOIP、URL-REGEX、USER-AGENT
或 extended-matching。后两类只按转换器公开契约验证文本转换，不声称内核等价。
"""
import argparse
import collections
import csv
from dataclasses import dataclass
import fnmatch
import ipaddress
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.parse

from convert_clash import to_clash
from rules import POLICIES, parse_rules, read_policy

ROOT = Path(__file__).resolve().parent.parent
AI = '🤖️AI'
PROXY = '🚀节点选择'
FINAL = '🐠 Final'
# 这些预期来自服务归属契约，独立于构建器的关键词、来源与分类配置。
SERVICE_CASES = (
    ('google.com', 'Proxy/Google', PROXY),
    ('www.google.com', 'Proxy/Google', PROXY),
    ('accounts.google.com', 'Proxy/Google', PROXY),
    ('mail.google.com', 'Proxy/Google', PROXY),
    ('storage.googleapis.com', 'Proxy/Google', PROXY),
    ('gemini.google.com', 'AI/Gemini', AI),
    ('aistudio.google.com', 'AI/Gemini', AI),
    ('generativelanguage.googleapis.com', 'AI/Gemini', AI),
    ('antigravity.google', 'AI/Gemini', AI),
    ('ai.studio', 'AI/Gemini', AI),
    ('ppl-ai-file-upload.s3.amazonaws.com', 'AI/Others', AI),
    ('production-openaicom-storage.azureedge.net', 'AI/OpenAI', AI),
    ('youtubei.googleapis.com', 'Proxy/YouTube', PROXY),
    ('bing.com', 'Proxy/Microsoft', PROXY),
    ('github.com', 'Proxy/GitHub', PROXY),
    ('api.githubcopilot.com', 'AI/Copilot', AI),
    ('www.copilot-stg.com', 'AI/Copilot', AI),
    ('claude.ai', 'AI/Claude', AI),
    ('cursor.com', 'AI/Others', AI),
    ('perplexity.ai', 'AI/Others', AI),
    ('huggingface.co', 'AI/Others', AI),
    ('x.ai', 'AI/Others', AI),
    ('grok.com', 'AI/Others', AI),
    ('midjourney.com', 'AI/Others', AI),
    ('suno.com', 'AI/Others', AI),
    ('poe.com', 'AI/Others', AI),
    ('windsurf.com', 'AI/Others', AI),
    ('ollama.com', 'AI/Others', AI),
)
PROCESS_TYPES = {'PROCESS-NAME', 'PROCESS-PATH', 'PROCESS-NAME-WILDCARD', 'PROCESS-PATH-WILDCARD'}


@dataclass(frozen=True)
class Provider:
    name: str
    theme: str
    policy: str
    rules: tuple
    no_resolve: bool = False


@dataclass(frozen=True)
class Request:
    host: str = ''
    ip: str = ''
    process: str = ''


def read_config(path):
    """读取仓库生成器的 YAML 子集；不引入 CI 未安装的 YAML 依赖。"""
    providers, routes = {}, []
    section = current = None
    for number, raw in enumerate(path.read_text(encoding='utf-8').splitlines(), 1):
        if not raw.strip() or raw.lstrip().startswith('#'):
            continue
        if raw in ('rule-providers:', 'rules:'):
            section, current = raw[:-1], None
        elif section == 'rule-providers' and raw.startswith('  ') and not raw.startswith('    ') and raw.endswith(':'):
            current = raw.strip()[:-1]
            if current in providers:
                raise ValueError(f'{path}:{number}: 重复 provider {current}')
            providers[current] = {}
        elif section == 'rule-providers' and current and raw.startswith('    '):
            key, separator, value = raw.strip().partition(': ')
            if not separator or key in providers[current]:
                raise ValueError(f'{path}:{number}: 非法或重复 provider 字段')
            providers[current][key] = json.loads(value)
        elif section == 'rules' and raw.startswith('  - '):
            routes.append(json.loads(raw[4:]))
        else:
            raise ValueError(f'{path}:{number}: 不支持的生成配置格式')
    if not providers or not routes or routes[-1] != f'MATCH,{FINAL}':
        raise ValueError(f'{path}: 缺少 provider、规则或最终策略')
    references = []
    for route in routes[:-1]:
        fields = route.split(',')
        if len(fields) not in (3, 4) or fields[0] != 'RULE-SET' or (len(fields) == 4 and fields[3] != 'no-resolve'):
            raise ValueError(f'{path}: 非法引用 {route}')
        if fields[1] not in providers or fields[2] not in POLICIES:
            raise ValueError(f'{path}: 未知 provider 或策略 {route}')
        references.append((fields[1], fields[2], len(fields) == 4))
    names = [name for name, _, _ in references]
    if len(names) != len(set(names)) or set(names) != set(providers):
        raise ValueError(f'{path}: provider 未引用或重复引用')
    return providers, references


def local_path(directory, relative):
    path = (directory / relative).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise ValueError(f'产物引用缺失或越界: {relative}')
    return path


def clash_rules(text, source):
    """沿用公共语法验证，但独立保留 Clash 转换后的进程类型。"""
    result = []
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith(('#', '//', ';')):
            continue
        fields = next(csv.reader([line]))
        typ = fields[0]
        if typ in PROCESS_TYPES:
            fields[0] = 'PROCESS-NAME'
            from io import StringIO
            output = StringIO()
            csv.writer(output, lineterminator='').writerow(fields)
            _, value, options = parse_rules(output.getvalue(), source)[0]
            result.append((typ, value, options))
        else:
            result.extend(parse_rules(line, source))
    return tuple(result)


def load_text(surge_dir, clash_dir, require_surge_config=False):
    config, references = read_config(clash_dir / 'classical.yaml')
    surge, clash = [], []
    expected_files = {p.relative_to(surge_dir).as_posix() for p in surge_dir.rglob('*.list')}
    actual_files = {p.relative_to(clash_dir).as_posix() for p in clash_dir.rglob('*.list')
                    if p.relative_to(clash_dir).parts[0] != 'mrs'}
    if not expected_files or actual_files != expected_files:
        raise ValueError('Surge / Clash 文本文件集合不一致')
    referenced = set()
    skipped = collections.Counter()
    for name, policy, no_resolve in references:
        entry = config[name]
        if (entry.get('behavior'), entry.get('format')) != ('classical', 'text'):
            raise ValueError(f'classical provider 格式错误: {name}')
        path = local_path(clash_dir, entry['path'])
        relative = path.relative_to(clash_dir.resolve()).as_posix()
        referenced.add(relative)
        source = local_path(surge_dir, relative)
        source_text = source.read_text(encoding='utf-8')
        target_text = path.read_text(encoding='utf-8')
        if read_policy(source_text, str(source)) != policy or read_policy(target_text, str(path)) != policy:
            raise ValueError(f'provider 策略与文件头不一致: {relative}')
        source_rules = tuple(parse_rules(source_text, str(source)))
        target_rules = clash_rules(target_text, str(path))
        converted = set()
        for rule in source_rules:
            translated = to_clash(rule)
            if translated is None:
                skipped[rule[0]] += 1
            else:
                converted.add(translated)
        if converted != set(target_rules):
            raise ValueError(f'Surge / Clash 文本转换契约不一致: {relative}')
        theme = relative[:-5]
        if theme.startswith('routing/') and theme.endswith('-domain'):
            theme = theme[len('routing/'):-len('-domain')]
        surge.append(Provider(name, theme, policy, source_rules, no_resolve))
        clash.append(Provider(name, theme, policy, target_rules, no_resolve))
    if referenced != expected_files:
        raise ValueError('classical.yaml 未完整引用文本文件')
    routes_path = surge_dir / 'rules.conf'
    if require_surge_config and not routes_path.is_file():
        raise ValueError(f'缺少 Surge 实际引用配置: {routes_path}')
    if routes_path.is_file():
        by_relative = {Path(config[provider.name]['path']).as_posix().removeprefix('./'): provider
                       for provider in surge}
        ordered = []
        routes = [line.strip() for line in routes_path.read_text(encoding='utf-8').splitlines()
                  if line.strip() and not line.lstrip().startswith('#')]
        if not routes or routes[-1] != f'FINAL,{FINAL}':
            raise ValueError(f'{routes_path}: 缺少正确的末尾 FINAL 策略')
        for line in routes[:-1]:
            fields = line.split(',')
            if len(fields) != 3 or fields[0] != 'RULE-SET':
                raise ValueError(f'{routes_path}: 非法 Surge 引用 {line}')
            relative = urllib.parse.unquote(urllib.parse.urlparse(fields[1]).path).partition('/surge/')[2]
            if relative not in by_relative or fields[2] != by_relative[relative].policy:
                raise ValueError(f'{routes_path}: 未知文件或策略 {line}')
            ordered.append(by_relative[relative])
        if len(ordered) != len(surge) or {p.name for p in ordered} != {p.name for p in surge}:
            raise ValueError(f'{routes_path}: 未完整引用 Surge 文件或存在重复')
        surge = ordered
    return surge, clash, skipped


def decode_mrs(mihomo, behavior, source, directory):
    destination = directory / (source.name + '.decoded.txt')
    result = subprocess.run([str(mihomo), 'convert-ruleset', behavior, 'mrs', str(source), str(destination)],
                            capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode or any(word in output.lower() for word in ('level=warning', 'level=error', 'invalid ')):
        raise RuntimeError(f'MRS 反解失败 {source}: {output}')
    rules = []
    for value in destination.read_text(encoding='utf-8').splitlines():
        value = value.strip()
        if not value or value.startswith('#'):
            continue
        if behavior == 'domain':
            rules.append(('DOMAIN-SUFFIX' if value.startswith('+.') else 'DOMAIN',
                          value[2:] if value.startswith('+.') else value, ()))
        else:
            network = ipaddress.ip_network(value, strict=False)
            rules.append(('IP-CIDR6' if network.version == 6 else 'IP-CIDR', str(network), ('no-resolve',)))
    return tuple(rules)


def load_mrs(clash_dir, mihomo, directory):
    config, references = read_config(clash_dir / 'mrs.yaml')
    providers = []
    for name, policy, no_resolve in references:
        entry = config[name]
        source = local_path(clash_dir, entry['path'])
        if not source.is_relative_to((clash_dir / 'mrs').resolve()):
            raise ValueError(f'MRS provider 必须引用 mrs/ 产物: {name}')
        behavior, fmt = entry.get('behavior'), entry.get('format')
        if fmt == 'mrs' and behavior in ('domain', 'ipcidr'):
            rules = decode_mrs(mihomo, behavior, source, directory)
            if behavior == 'ipcidr' and not no_resolve:
                raise ValueError(f'MRS IP provider 缺少 no-resolve: {name}')
        elif fmt == 'text' and behavior == 'classical':
            text = source.read_text(encoding='utf-8')
            if read_policy(text, str(source)) != policy:
                raise ValueError(f'MRS 配套文本策略不一致: {name}')
            rules = clash_rules(text, str(source))
        else:
            raise ValueError(f'MRS provider 格式错误: {name}')
        providers.append(Provider(name, name, policy, rules, no_resolve))
    actual = {p.resolve() for p in (clash_dir / 'mrs').iterdir() if p.suffix in ('.mrs', '.list')}
    referenced = {local_path(clash_dir, entry['path']) for entry in config.values()}
    if actual != referenced:
        raise ValueError('mrs.yaml 未完整引用 MRS 与配套文本')
    return providers


def coverage(providers):
    """比较全部已转换规则的覆盖，允许 MRS 合并相邻 CIDR 与后缀冗余。"""
    groups = collections.defaultdict(list)
    for provider in providers:
        groups[provider.policy].extend(provider.rules)
    result = {}
    for policy, rules in groups.items():
        suffixes = {value for typ, value, options in rules if typ == 'DOMAIN-SUFFIX' and not options}
        domains = set()
        networks = []
        extra = set()
        for typ, value, options in rules:
            if typ in ('DOMAIN', 'DOMAIN-SUFFIX') and not options:
                labels = value.split('.')
                start = 1 if typ == 'DOMAIN-SUFFIX' else 0
                if not any('.'.join(labels[i:]) in suffixes for i in range(start, len(labels))):
                    domains.add((typ, value))
            elif typ in ('IP-CIDR', 'IP-CIDR6'):
                # 保留解析行为；no-resolve CIDR 才能与二进制 IP 集合互换。
                networks.append((ipaddress.ip_network(value), 'no-resolve' in options))
            else:
                extra.add((typ, value, options))
        cidrs = set()
        for version in (4, 6):
            for no_resolve in (False, True):
                selected = (net for net, flag in networks if net.version == version and flag == no_resolve)
                cidrs.update((str(net), no_resolve) for net in ipaddress.collapse_addresses(selected))
        if domains or cidrs or extra:
            result[policy] = (domains, cidrs, extra)
    return result


def matches(rule, request, clash=False):
    typ, value, _ = rule
    host = request.host.lower().rstrip('.')
    if typ == 'DOMAIN':
        return host == value
    if typ == 'DOMAIN-SUFFIX':
        return host == value or host.endswith('.' + value)
    if typ == 'DOMAIN-KEYWORD':
        return value in host
    if typ == 'DOMAIN-WILDCARD':
        return fnmatch.fnmatchcase(host, value)
    if typ in ('IP-CIDR', 'IP-CIDR6') and request.ip:
        return ipaddress.ip_address(request.ip) in ipaddress.ip_network(value)
    if typ in PROCESS_TYPES and request.process:
        candidate = request.process
        if clash:
            candidate, value = candidate.lower(), value.lower()
        if 'WILDCARD' in typ or (not clash and any(char in value for char in '*?')):
            return fnmatch.fnmatchcase(candidate, value)
        return candidate == value
    return False


def first_match(providers, request, clash=False):
    for provider in providers:
        if any(matches(rule, request, clash) for rule in provider.rules):
            return provider.theme, provider.policy
    return None, FINAL


def validate_routes(surge, clash, mrs):
    count = 0
    # 从真实规则中选跨策略地址，确保能发现 IP provider 抢在域名之前的错误。
    shared_addresses = ['', '192.0.2.222', '2001:db8::222']
    representatives = {}
    for provider in clash:
        for typ, value, _ in provider.rules:
            if typ in ('IP-CIDR', 'IP-CIDR6'):
                network = ipaddress.ip_network(value)
                key = (provider.policy, network.version)
                address = network.network_address + (1 if network.num_addresses > 1 else 0)
                representatives.setdefault(key, str(address))
    shared_addresses = list(dict.fromkeys(shared_addresses + list(representatives.values())))
    for host, theme, policy in SERVICE_CASES:
        # 相同测试 IP 与不同域名仍按服务归属，避免 IP 提前遮盖域名。
        for address in shared_addresses:
            request = Request(host, address)
            source = first_match(surge, request)
            target = first_match(clash, request, True)
            binary = first_match(mrs, request, True)
            if source != (theme, policy) or target != (theme, policy) or binary[1] != policy:
                raise ValueError(f'服务归属验收失败 {request}: 预期 {(theme, policy)}; '
                                 f'Surge={source}, Clash={target}, MRS={binary}')
            count += 1
    for address in shared_addresses:
        if not address:
            continue
        request = Request(ip=address)
        results = [first_match(providers, request, mode) for providers, mode in
                   ((surge, False), (clash, True), (mrs, True))]
        if len({result[1] for result in results}) != 1:
            raise ValueError(f'纯 IP 三端策略不一致: {request}: {results}')
        count += 1
    for host in ('notgoogle.com', 'ordinary.example'):
        for process in ('', 'MicrosoftEdge', 'VSCode'):
            request = Request(host, process=process)
            results = [first_match(providers, request, mode) for providers, mode in
                       ((surge, False), (clash, True), (mrs, True))]
            policies = {result[1] for result in results}
            if len(policies) != 1 or AI in policies or any(theme == 'Proxy/Google' for theme, _ in results):
                raise ValueError(f'普通域名/进程误分类: {request}: {results}')
            count += 1
    return count


def validate_artifacts(surge_dir, clash_dir, mihomo='mihomo', *, require_surge_config=False):
    """只读验收暂存或仓库产物；失败抛异常，不发布，临时反解证据保留。"""
    surge_dir, clash_dir = Path(surge_dir).resolve(), Path(clash_dir).resolve()
    executable = shutil.which(str(mihomo))
    if not executable:
        raise ValueError(f'缺少 mihomo: {mihomo}')
    directory = Path(tempfile.mkdtemp(prefix='rules-acceptance-'))
    surge, clash, skipped = load_text(surge_dir, clash_dir, require_surge_config)
    mrs = load_mrs(clash_dir, executable, directory)
    if coverage(clash) != coverage(mrs):
        raise ValueError(f'Clash / MRS 全量语义覆盖不一致；反解证据: {directory}')
    cases = validate_routes(surge, clash, mrs)
    return {'scenarios': cases, 'text_providers': len(clash), 'mrs_providers': len(mrs),
            'surge_only': dict(skipped), 'evidence': str(directory)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--surge-dir', type=Path, default=ROOT / 'surge')
    parser.add_argument('--clash-dir', type=Path, default=ROOT / 'clash')
    parser.add_argument('--mihomo', default='mihomo')
    args = parser.parse_args()
    try:
        result = validate_artifacts(args.surge_dir, args.clash_dir, args.mihomo, require_surge_config=True)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'❌ 分类验收失败: {error}', file=sys.stderr)
        return 1
    print('✓ 分类与三端产物验收通过: ' + json.dumps(result, ensure_ascii=False))
    print('匹配场景限域名、显式 IP 与进程；ASN/GEOIP、UA、URL 正则的内核行为未模拟。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
