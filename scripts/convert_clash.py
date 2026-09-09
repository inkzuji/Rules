#!/usr/bin/env python3
"""surge/ → mihomo 细分 classical 文本及六类业务策略 MRS。

用法: python3 scripts/convert_clash.py [--check] [--mihomo PATH]
--check 在临时目录重新编译、校验全部产物，不改仓库文件。
"""
import argparse
import collections
from datetime import datetime
import ipaddress
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import urllib.parse
import uuid

from rules import POLICIES, parse_rules, read_policy, render_rules, rule_line

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / 'surge'
OUT_DIR = ROOT / 'clash'
RAW_BASE = 'https://raw.githubusercontent.com/inkzuji/Rules/main/clash/'
MIHOMO_VERSION = '1.19.30'


def to_clash(rule):
    """转换当前 Surge 语法；不能等价转换的类型明确统计，参数则报错。"""
    typ, value, options = rule
    if typ in ('USER-AGENT', 'URL-REGEX'):
        return None
    if 'extended-matching' in options:
        raise ValueError(f'mihomo 无等价 extended-matching 参数: {rule_line(rule)}')
    if typ == 'PROCESS-NAME':
        if value.startswith('/'):
            typ = 'PROCESS-PATH'
            if value.endswith('/'):
                value += '*'
        if '*' in value or '?' in value:
            typ += '-WILDCARD'
    return typ, value, options


def run_mihomo(mihomo, *args):
    result = subprocess.run([mihomo, *map(str, args)], capture_output=True, text=True)
    output = result.stdout + result.stderr
    if result.returncode or any(word in output.lower() for word in ('level=warning', 'level=error', 'invalid ', 'parse classical rule')):
        raise RuntimeError(f'mihomo {args[0]} 失败 ({result.returncode}):\n{output}')
    return output


def canonical_domains(values):
    """去除已被同集合后缀覆盖的条目，用于 MRS 优化后的语义比对。"""
    values = set(values)
    suffixes = {value[2:] for value in values if value.startswith('+.')}
    result = set()
    for value in values:
        name = value[2:] if value.startswith('+.') else value
        labels = name.split('.')
        start = 1 if value.startswith('+.') else 0
        if not any('.'.join(labels[i:]) in suffixes for i in range(start, len(labels))):
            result.add(value)
    return result


def canonical_cidrs(values):
    networks = [ipaddress.ip_network(value, strict=False) for value in values]
    return {str(net) for version in (4, 6)
            for net in ipaddress.collapse_addresses(n for n in networks if n.version == version)}


def compile_mrs(values, behavior, path, mihomo):
    source = path.with_suffix('.input.txt')
    source.write_text('\n'.join(sorted(set(values))) + '\n', encoding='utf-8')
    run_mihomo(mihomo, 'convert-ruleset', behavior, 'text', source, path)
    decoded = path.with_suffix('.decoded.txt')
    run_mihomo(mihomo, 'convert-ruleset', behavior, 'mrs', path, decoded)
    normalize = canonical_domains if behavior == 'domain' else canonical_cidrs
    if normalize(values) != normalize(decoded.read_text(encoding='utf-8').splitlines()):
        raise ValueError(f'MRS 往返覆盖不一致: {path.name}')
    return path.read_bytes()


def config_for(entries, remote=True):
    providers = {}
    routes = []
    for name, relative, policy, behavior, fmt, no_resolve in entries:
        provider = {'type': 'http' if remote else 'file', 'behavior': behavior,
                    'format': fmt, 'path': './' + relative}
        if remote:
            provider.update(url=RAW_BASE + relative, interval=86400)
        providers[name] = provider
        routes.append(f'RULE-SET,{name},{policy}' + (',no-resolve' if no_resolve else ''))
    routes.append('MATCH,🐠 Final')
    return {'rule-providers': providers, 'rules': routes}


def render_config(entries):
    config = config_for(entries)
    scalar = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ['# 合并到已有主配置；策略组名称须与主配置一致。', 'rule-providers:']
    for name, provider in config['rule-providers'].items():
        lines.append(f'  {name}:')
        for key, value in provider.items():
            lines.append(f'    {key}: {scalar(value)}')
    lines.extend(['', 'rules:'])
    lines.extend('  - ' + scalar(rule) for rule in config['rules'])
    return '\n'.join(lines) + '\n'


def empty_mmdb():
    """MaxMind DB v2 空数据 stub，仅供语法校验；所有地址均无归属记录。

    格式依据 https://maxmind.github.io/MaxMind-DB/ 。不用于实际路由。
    """
    def text(value):
        data = value.encode('utf-8')
        return bytes([0x40 + len(data)]) + data

    def uint(value, typ):
        data = value.to_bytes((value.bit_length() + 7) // 8, 'big')
        header = bytes([(typ << 5) + len(data)]) if typ < 8 else bytes([len(data), typ - 7])
        return header + data

    fields = [('node_count', uint(1, 6)), ('record_size', uint(24, 5)),
              ('ip_version', uint(6, 5)), ('database_type', text('Syntax-Only-Empty')),
              ('binary_format_major_version', uint(2, 5)),
              ('binary_format_minor_version', uint(0, 5)), ('build_epoch', uint(0, 9))]
    # 根节点两个指针都等于 node_count，代表不存在匹配记录。
    return (b'\x00\x00\x01' * 2 + b'\x00' * 16 + b'\xab\xcd\xefMaxMind.com'
            + bytes([0xe0 + len(fields)]) + b''.join(text(key) + value for key, value in fields))


def validate_config(entries, all_rules, directory, mihomo):
    """隔离目录内校验 provider 与逐条规则；不启动代理、不使用用户配置。"""
    config = config_for(entries, remote=False)
    config['proxy-groups'] = [{'name': policy, 'type': 'select', 'proxies': ['DIRECT']}
                              for policy in [*POLICIES, '🐠 Final'] if policy != 'DIRECT']
    config['log-level'] = 'info'
    # ASN/GEOIP 构造器需要数据库；空 stub 隔离远程服务，不声称验证实际地理归属。
    for filename in ('ASN.mmdb', 'country.mmdb'):
        (directory / filename).write_bytes(empty_mmdb())
    config['geodata-mode'] = False
    config['geox-url'] = {'asn': 'http://127.0.0.1:1/disabled', 'mmdb': 'http://127.0.0.1:1/disabled'}
    path = directory / 'check.json'
    path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    run_mihomo(mihomo, '-t', '-d', directory, '-f', path)
    # -t 对外部 provider 的初始化行为可能随核心变化；内联规则确保解析逐条执行。
    config.pop('rule-providers')
    config['rules'] = [rule_line(rule, 'DIRECT') for rule in sorted(set(all_rules))] + ['MATCH,DIRECT']
    path.write_text(json.dumps(config, ensure_ascii=False), encoding='utf-8')
    run_mihomo(mihomo, '-t', '-d', directory, '-f', path)


def generate(surge_dir, mihomo='mihomo'):
    """生成并验证全部产物，返回相对路径到 bytes 的映射，不改输出目录。"""
    mihomo = shutil.which(str(mihomo))
    if not mihomo:
        raise ValueError('缺少 mihomo，请安装固定版本或使用 --mihomo 指定路径')
    version = run_mihomo(mihomo, '-v')
    if f'Meta {MIHOMO_VERSION} ' not in version:
        raise ValueError(f'构建需要 mihomo {MIHOMO_VERSION}，实际: {version.strip()}')
    files = sorted(Path(surge_dir).rglob('*.list'))
    if not files:
        raise ValueError(f'缺少 Surge 源规则: {surge_dir}')
    directory = Path(tempfile.mkdtemp(prefix='rules-convert-'))
    artifacts = {}
    groups = collections.defaultdict(set)
    ordered_groups = collections.defaultdict(list)
    classical_entries = []
    skipped = collections.Counter()
    for path in files:
        text = path.read_text(encoding='utf-8')
        policy = read_policy(text, str(path))
        converted = []
        for rule in parse_rules(text, str(path)):
            translated = to_clash(rule)
            if translated is None:
                skipped[rule[0]] += 1
            else:
                converted.append(translated)
        relative = path.relative_to(surge_dir).as_posix()
        artifacts[relative] = render_rules(policy, converted).encode('utf-8')
        groups[policy].update(converted)
        ordered_groups[policy].extend(sorted(set(converted)))
        name = relative[:-5].replace('/', '-')
        classical_entries.append((name, relative, policy, 'classical', 'text', False))
    order = list(POLICIES)
    classical_entries.sort(key=lambda entry: (order.index(entry[2]), entry[0]))
    mrs_entries = []
    for policy, name in POLICIES.items():
        domains, ips, extra = [], [], []
        # 解析型 ASN/GEOIP/CIDR 会为后续 no-resolve 规则提供 IP。
        # 此时保留非域名规则的细分文件顺序，不能将 IP 独立提前。
        resolves = any(typ in ('IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP') and 'no-resolve' not in options
                       for typ, _, options in groups[policy])
        for typ, value, options in ordered_groups[policy]:
            if typ in ('DOMAIN', 'DOMAIN-SUFFIX') and not options:
                domains.append(('+.' if typ == 'DOMAIN-SUFFIX' else '') + value)
            elif typ in ('IP-CIDR', 'IP-CIDR6'):
                network = ipaddress.ip_network(value)
                if resolves or (network.version == 6 and network.overlaps(ipaddress.ip_network('::ffff:0:0/96'))):
                    # MRS 的 IPSet 会将 IPv4-mapped IPv6 转成 IPv4，不能改变匹配范围。
                    extra.append((typ, value, options))
                else:
                    ips.append(value)
            else:
                extra.append((typ, value, options))
        for suffix, values, behavior, no_resolve in (
                ('', domains, 'domain', False),
                ('-ip', ips, 'ipcidr', True)):
            if values:
                relative = f'mrs/{name}{suffix}.mrs'
                artifacts[relative] = compile_mrs(values, behavior, directory / f'{name}{suffix}.mrs', mihomo)
                mrs_entries.append((name + suffix, relative, policy, behavior, 'mrs', no_resolve))
        if extra:
            relative = f'mrs/{name}-extra.list'
            artifacts[relative] = render_rules(policy, extra, preserve_order=resolves).encode('utf-8')
            mrs_entries.append((name + '-extra', relative, policy, 'classical', 'text', False))
        print(f'✓ {name:8s} 域名 {len(domains):6d} IP {len(ips):6d} 配套文本 {len(extra):6d}')
    artifacts['classical.yaml'] = render_config(classical_entries).encode('utf-8')
    artifacts['mrs.yaml'] = render_config(mrs_entries).encode('utf-8')
    for relative, content in artifacts.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    all_rules = [rule for rules in groups.values() for rule in rules]
    validate_config(classical_entries, all_rules, directory, mihomo)
    validate_config(mrs_entries, all_rules, directory, mihomo)
    if skipped:
        print('⚠️ 仅保留在 Surge 的类型: ' + ', '.join(f'{typ}×{count}' for typ, count in sorted(skipped.items())))
    return artifacts


def stale_paths(artifacts, out_dir):
    directory = Path(out_dir)
    actual = {path.relative_to(directory).as_posix() for path in directory.rglob('*')
              if path.is_file() and path.suffix in ('.list', '.mrs', '.yaml')}
    return sorted(actual - set(artifacts))


def preflight(artifacts, out_dir):
    """只允许自动退役本转换器管理的六策略配套文件，未知文件不动。"""
    for relative in artifacts:
        path = Path(out_dir) / relative
        if path.exists() and not path.is_file():
            raise ValueError(f'产物路径冲突，目标不是普通文件: {path}')
        for parent in path.parents:
            if parent.exists() and not parent.is_dir():
                raise ValueError(f'产物路径冲突，父路径不是目录: {parent}')
    stale = stale_paths(artifacts, out_dir)
    managed = {f'mrs/{name}{suffix}' for name in POLICIES.values()
               for suffix in ('.mrs', '-ip.mrs', '-extra.list')}
    unknown = sorted(set(stale) - managed)
    if unknown:
        raise ValueError(f'{out_dir}: 未知的多余产物，请检查后移入系统废纸篓: {unknown}')
    return stale


def trash_file(path):
    """移入系统废纸篓；Linux 同时写入 freedesktop Trash 恢复信息。"""
    path = Path(path).absolute()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f'不能自动退役非普通文件: {path}')
    name = f'{path.name}.{uuid.uuid4().hex}'
    if sys.platform == 'darwin':
        directory = Path.home() / '.Trash'
        if not directory.is_dir():
            raise ValueError('系统废纸篓不可用，停止退役产物')
    elif sys.platform.startswith('linux'):
        data_home = Path(os.environ.get('XDG_DATA_HOME') or Path.home() / '.local/share')
        if not data_home.is_absolute():
            raise ValueError('XDG_DATA_HOME 必须为绝对路径，停止退役产物')
        directory = data_home / 'Trash/files'
        info = data_home / 'Trash/info'
        directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        info.mkdir(parents=True, exist_ok=True, mode=0o700)
        with (info / (name + '.trashinfo')).open('x', encoding='utf-8') as output:
            output.write('[Trash Info]\n'
                         f'Path={urllib.parse.quote(str(path), safe="/")}\n'
                         f'DeletionDate={datetime.now().isoformat(timespec="seconds")}\n')
    else:
        raise ValueError(f'{sys.platform}: 不支持系统废纸篓，停止退役产物')
    target = directory / name
    shutil.move(str(path), str(target))
    print(f'已移入系统废纸篓: {path} → {target}')
    return target


def retire_stale(artifacts, out_dir):
    paths = [Path(out_dir) / relative for relative in preflight(artifacts, out_dir)]
    for path in paths:
        if path.is_symlink() or not path.is_file():
            raise ValueError(f'不能自动退役非普通文件: {path}')
    moved = []
    try:
        for path in paths:
            moved.append((path, trash_file(path)))
    except (OSError, ValueError):
        for original, trashed in reversed(moved):
            shutil.move(str(trashed), str(original))
        raise


def publish(artifacts, out_dir, check=False):
    """检查模式严格只读；写入前将已知退役产物移入废纸篓。"""
    directory = Path(out_dir)
    stale = preflight(artifacts, directory)
    if check and stale:
        raise ValueError(f'{directory}: 多余产物，请先移入系统废纸篓: {stale}')
    dirty = [relative for relative, content in artifacts.items()
             if not (directory / relative).is_file() or (directory / relative).read_bytes() != content]
    if check:
        if dirty:
            raise ValueError(f'{directory}: 未同步或损坏的产物: {dirty}')
        return
    retire_stale(artifacts, directory)
    for relative in dirty:
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, staged = tempfile.mkstemp(prefix='.rules-', dir=path.parent)
        with os.fdopen(descriptor, 'wb') as output:
            output.write(artifacts[relative])
        os.replace(staged, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='校验全部产物，不修改仓库')
    parser.add_argument('--mihomo', default='mihomo', help='固定版本 mihomo 可执行文件')
    args = parser.parse_args()
    try:
        artifacts = generate(SRC_DIR, args.mihomo)
        publish(artifacts, OUT_DIR, check=args.check)
    except (OSError, ValueError, RuntimeError) as error:
        print(f'❌ {error}', file=sys.stderr)
        return 1
    print(f'✓ {len(artifacts)} 个 Clash 产物' + ('已同步' if args.check else '已生成'))
    return 0


if __name__ == '__main__':
    sys.exit(main())
