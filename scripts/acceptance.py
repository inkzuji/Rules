#!/usr/bin/env python3
"""独立验收文本归属、实际 provider 首匹配和官方反解后的 MRS 覆盖。

匹配场景覆盖域名、CIDR、进程和固定快照的 ASN 查询；不模拟真实 DNS 状态、
GEOIP、URL-REGEX、USER-AGENT 或 extended-matching，不代替内核运行测试。
"""
import argparse
import collections
import csv
from dataclasses import dataclass, replace
import fnmatch
import functools
import hashlib
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
CLASH_FINAL = '🐟 漏网之鱼'
CLASH_POLICIES = {'🤖 AI 服务': AI, '🍎 苹果服务': '🍎苹果', '🎮 游戏': '🎮游戏',
                  '🚀 节点选择': PROXY, '📽 哔哩哔哩': '📽哔哩',
                  '🔒 国内服务': 'DIRECT', '🔍 谷歌服务': 'Google'}
SERVICE_ORDER = ('AI', 'Apple', 'Game', 'Proxy/Google', 'Proxy/YouTube', 'Proxy/Netflix',
                 'Proxy/Disney', 'Proxy/Spotify', 'Proxy/Streaming', 'Proxy/GitHub',
                 'Proxy/Microsoft', 'Proxy/Social', 'Proxy/Dev', 'Proxy/Cloudflare',
                 'Proxy/Others', 'Bilibili', 'Direct')
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
    ('youtubei.googleapis.com', 'Proxy/Google', PROXY),
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
# 真实交集差分反复匹配同一批地址/网段，缓存解析结果而不缓存匹配结果。
_network = functools.lru_cache(maxsize=65536)(ipaddress.ip_network)
_address = functools.lru_cache(maxsize=1024)(ipaddress.ip_address)


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
    asn: str = ''


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
    for name, entry in providers.items():
        if entry.get('type') == 'http':
            if entry.get('interval') != 604800:
                raise ValueError(f'{path}: provider {name} 必须每周更新')
            remote = urllib.parse.unquote(urllib.parse.urlparse(entry.get('url', '')).path).partition('/clash/')[2]
            if remote != entry.get('path', '').removeprefix('./'):
                raise ValueError(f'{path}: provider {name} 的 URL 与本地产物路径不一致')
    if not providers or not routes or routes[-1] != f'MATCH,{CLASH_FINAL}':
        raise ValueError(f'{path}: 缺少 provider、规则或最终策略')
    references = []
    for route in routes[:-1]:
        fields = route.split(',')
        if len(fields) not in (3, 4) or fields[0] != 'RULE-SET' or (len(fields) == 4 and fields[3] != 'no-resolve'):
            raise ValueError(f'{path}: 非法引用 {route}')
        if fields[1] not in providers or fields[2] not in CLASH_POLICIES:
            raise ValueError(f'{path}: 未知 provider 或策略 {route}')
        references.append((fields[1], CLASH_POLICIES[fields[2]], len(fields) == 4))
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
        header_policy = PROXY if policy == 'Google' else policy
        if read_policy(source_text, str(source)) != header_policy or read_policy(target_text, str(path)) != header_policy:
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
            if relative not in by_relative or fields[2] != (PROXY if by_relative[relative].policy == 'Google' else by_relative[relative].policy):
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
    referenced = set()
    for name, policy, no_resolve in references:
        entry = config[name]
        source = local_path(clash_dir, entry['path'])
        referenced.add(source)
        relative = source.relative_to(clash_dir).as_posix()
        behavior, fmt = entry.get('behavior'), entry.get('format')
        if fmt == 'mrs' and behavior in ('domain', 'ipcidr'):
            if not relative.startswith('mrs/'):
                raise ValueError(f'二进制 MRS 必须位于 mrs/: {name}')
            rules = decode_mrs(mihomo, behavior, source, directory)
            if behavior == 'ipcidr':
                if name == 'Direct-asn-ip':
                    if no_resolve or policy != 'DIRECT':
                        raise ValueError('Direct ASN 集合必须允许解析且指向国内服务')
                    rules = tuple((typ, value, ()) for typ, value, _ in rules)
                elif not no_resolve:
                    raise ValueError(f'MRS IP provider 缺少 no-resolve: {name}')
        elif fmt == 'text' and behavior == 'classical':
            text = source.read_text(encoding='utf-8')
            if read_policy(text, str(source)) != (PROXY if policy == 'Google' else policy):
                raise ValueError(f'MRS 配套文本策略不一致: {name}')
            rules = clash_rules(text, str(source))
        else:
            raise ValueError(f'MRS provider 格式错误: {name}')
        if relative.startswith('mrs/'):
            stem = source.stem.split('-')[0]
            theme = {'Google': 'Proxy/Google', 'Others': 'Proxy/Others'}.get(stem, stem)
        else:
            theme = relative[:-5]
        providers.append(Provider(name, theme, policy, rules, no_resolve))
    actual = {p.resolve() for p in (clash_dir / 'mrs').iterdir() if p.suffix in ('.mrs', '.list')}
    if actual != {p for p in referenced if p.parent == (clash_dir / 'mrs')}:
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
        return _address(request.ip) in _network(value)
    if typ == 'IP-ASN':
        return bool(request.asn) and value == request.asn
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
    for label, providers in (('Surge', surge), ('Clash', clash), ('MRS', mrs)):
        themes = [p.theme for p in providers]
        if any(theme not in SERVICE_ORDER for theme in themes):
            raise ValueError(f'{label}: 未知服务或旧 AI 分文件: {themes}')
        ranks = [SERVICE_ORDER.index(theme) for theme in themes]
        if ranks != sorted(ranks):
            raise ValueError(f'{label}: 服务引用顺序不符合原 Clash 配置')
        ai = [p for p in providers if p.theme == 'AI']
        if len(ai) != 1:
            raise ValueError(f'{label}: AI 必须只有一个完整 provider')
    # 独立业务预期验证域名归属；共享 IP 场景按已确认的整组优先契约另作差分。
    for host, theme, policy in SERVICE_CASES:
        expected_theme = 'AI' if theme.startswith('AI/') else theme
        expected_policy = 'Google' if expected_theme == 'Proxy/Google' else policy
        request = Request(host)
        for label, providers, mode in (('Surge', surge, False), ('Clash', clash, True), ('MRS', mrs, True)):
            actual = first_match(providers, request, mode)
            if actual != (expected_theme, expected_policy):
                raise ValueError(f'服务归属验收失败 {request}: 预期 {(expected_theme, expected_policy)}; {label}={actual}')
        count += 1
    addresses = {'192.0.2.222', '2001:db8::222'}
    for provider in clash:
        for typ, value, _ in provider.rules:
            if typ in ('IP-CIDR', 'IP-CIDR6'):
                network = ipaddress.ip_network(value)
                addresses.add(str(network.network_address + (1 if network.num_addresses > 1 else 0)))
                break
    asns = {}
    if any(r[0] == 'IP-ASN' for p in clash for r in p.rules):
        from asn import lookup_asns
        asns = lookup_asns(sorted(addresses), ROOT / 'inputs/ASN.mmdb', Path(tempfile.mkdtemp(prefix='rules-asn-routes-')))
    for host in ('google.com', 'gemini.google.com', 'ordinary.example', ''):
        for address in sorted(addresses):
            request = Request(host, address, asn=str(asns.get(address, '')))
            results = [first_match(providers, request, mode) for providers, mode in zip((surge, clash, mrs), (False, True, True))]
            if len(set(results)) != 1:
                raise ValueError(f'服务块首匹配不一致: {request}: {results}')
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


def validate_proxy_overlaps(surge, clash, mrs, directory):
    """逐个真实 Google/其他代理 CIDR 交集检查独立优先级和三端首匹配。"""
    intervals = []
    for provider in clash:
        if not provider.theme.startswith('Proxy/'):
            continue
        for typ, value, _ in provider.rules:
            if typ in ('IP-CIDR', 'IP-CIDR6'):
                network = ipaddress.ip_network(value)
                intervals.append((network.version, int(network.network_address),
                                  int(network.broadcast_address), provider.theme == 'Proxy/Google'))
    active, samples = [], []
    for interval in sorted(intervals):
        version, start, end, google = interval
        active = [other for other in active if other[0] == version and other[2] >= start]
        for other in active:
            if google != other[3]:
                address = str((ipaddress.IPv4Address if version == 4 else ipaddress.IPv6Address)(start))
                samples.append((version, address))
        active.append(interval)
    if not samples:
        return {'overlap_scenarios': 0, 'overlap_ipv4': 0, 'overlap_ipv6': 0}
    from asn import lookup_asns
    asns = lookup_asns([address for _, address in samples], ROOT / 'inputs/ASN.mmdb', directory)
    for version, address in samples:
        request = Request(ip=address, asn=str(asns.get(address, '')))
        complete = []
        for providers, mode in ((surge, False), (clash, True), (mrs, True)):
            proxy = [p for p in providers if p.theme.startswith('Proxy/')]
            winner = first_match(proxy, request, mode)
            if winner != ('Proxy/Google', 'Google'):
                raise ValueError(f'Google 真实重叠网段优先级错误 {address}: {winner}')
            complete.append(first_match(providers, request, mode))
        # 前序 AI/Apple/Game 的合法覆盖以完整源配置为基准，不能硬改成 Google。
        if len(set(complete)) != 1:
            raise ValueError(f'真实重叠网段三端首匹配不一致 {address}: {complete}')
    return {'overlap_scenarios': len(samples),
            'overlap_ipv4': sum(version == 4 for version, _ in samples),
            'overlap_ipv6': sum(version == 6 for version, _ in samples)}


def validate_asn_compilation(clash, mrs, directory):
    """只对声明的 Direct ASN 编译段作同快照验证，其他规则仍全量比较。"""
    compiled = [p for p in mrs if p.name == 'Direct-asn-ip']
    selected = {value for p in clash if p.theme == 'Direct'
                for typ, value, _ in p.rules if typ == 'IP-ASN'}
    if compiled:
        if len(compiled) != 1 or not selected:
            raise ValueError('Direct ASN 编译产物没有唯一对应的源 ASN 段')
        from asn import verify_networks
        database = ROOT / 'inputs/ASN.mmdb'
        verify_networks(selected, database, [value for _, value, _ in compiled[0].rules], directory)
        clash = [replace(p, rules=tuple(r for r in p.rules if r[0] != 'IP-ASN'))
                 if p.theme == 'Direct' else p for p in clash]
        mrs = [p for p in mrs if p.name != 'Direct-asn-ip']
    if coverage(clash) != coverage(mrs):
        raise ValueError(f'Clash / MRS 全量语义覆盖不一致；反解证据: {directory}')
    return bool(compiled)


def validate_manifest(surge_dir, clash_dir, required=False):
    path = clash_dir / 'manifest.json'
    if not path.is_file():
        if required:
            raise ValueError('生产产物缺少 manifest.json')
        return False
    manifest = json.loads(path.read_text(encoding='utf-8'))
    if manifest.get('schema') != 1 or manifest.get('update_interval') != 604800:
        raise ValueError('manifest 版本或更新周期不一致')
    from convert_clash import MIHOMO_VERSION
    if manifest.get('mihomo') != MIHOMO_VERSION:
        raise ValueError('manifest 内核版本与构建契约不一致')
    expected_sources = {p.relative_to(surge_dir).as_posix() for p in surge_dir.rglob('*.list')}
    expected_artifacts = {p.relative_to(clash_dir).as_posix() for p in clash_dir.rglob('*')
                          if p.is_file() and p.suffix in ('.list', '.mrs', '.yaml')}
    for field, directory, expected in (('sources', surge_dir, expected_sources),
                                       ('artifacts', clash_dir, expected_artifacts)):
        hashes = manifest.get(field, {})
        if set(hashes) != expected:
            raise ValueError(f'manifest {field} 文件集合不一致')
        for relative, digest in hashes.items():
            if hashlib.sha256(local_path(directory, relative).read_bytes()).hexdigest() != digest:
                raise ValueError(f'manifest SHA-256 不一致: {field}/{relative}')
    lock = json.loads((ROOT / 'inputs/asn-lock.json').read_text(encoding='utf-8'))
    if manifest.get('asn_database') != lock or hashlib.sha256((ROOT / 'inputs/ASN.mmdb').read_bytes()).hexdigest() != lock['sha256']:
        raise ValueError('manifest ASN 快照、锁文件或数据库内容不一致')
    return True


def validate_artifacts(surge_dir, clash_dir, mihomo='mihomo', *, require_surge_config=False):
    """只读验收暂存或仓库产物；失败抛异常，不发布，临时反解证据保留。"""
    surge_dir, clash_dir = Path(surge_dir).resolve(), Path(clash_dir).resolve()
    executable = shutil.which(str(mihomo))
    if not executable:
        raise ValueError(f'缺少 mihomo: {mihomo}')
    directory = Path(tempfile.mkdtemp(prefix='rules-acceptance-'))
    surge, clash, skipped = load_text(surge_dir, clash_dir, require_surge_config)
    manifest_checked = validate_manifest(surge_dir, clash_dir, required=require_surge_config)
    mrs = load_mrs(clash_dir, executable, directory)
    asn_compiled = validate_asn_compilation(clash, mrs, directory)
    cases = validate_routes(surge, clash, mrs)
    overlaps = validate_proxy_overlaps(surge, clash, mrs, directory)
    return {'scenarios': cases, 'text_providers': len(clash), 'mrs_providers': len(mrs),
            **overlaps, 'surge_only': dict(skipped), 'manifest_checked': manifest_checked, 'asn_compiled': asn_compiled, 'evidence': str(directory)}


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
    print('已检查域名、显式 IP、进程及同快照 ASN；真实 DNS、GEOIP、UA 和 URL 正则的内核行为未模拟。')
    return 0


if __name__ == '__main__':
    sys.exit(main())
