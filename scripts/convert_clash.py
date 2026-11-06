#!/usr/bin/env python3
"""surge/ → mihomo 单 AI 文本、分服务优化片段及可核验产物清单。

用法: python3 scripts/convert_clash.py [--check] [--mihomo PATH]
--check 在临时目录重新编译、校验全部产物，不改仓库文件。
"""
import argparse
import collections
import hashlib
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
import routing
import asn

ROOT = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT / 'surge'
OUT_DIR = ROOT / 'clash'
RAW_BASE = 'https://raw.githubusercontent.com/inkzuji/Rules/main/clash/'
MIHOMO_VERSION = '1.19.30'
CLASH_POLICIES = dict(zip(POLICIES, ('🤖 AI 服务', '🍎 苹果服务', '🎮 游戏', '🚀 节点选择', '📽 哔哩哔哩', '🔒 国内服务')))
CLASH_FINAL = '🐟 漏网之鱼'


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
            provider.update(url=RAW_BASE + relative, interval=604800)
        providers[name] = provider
        target = '🔍 谷歌服务' if name.startswith('Proxy-Google') or name.startswith('Google-') else CLASH_POLICIES[policy]
        routes.append(f'RULE-SET,{name},{target}' + (',no-resolve' if no_resolve else ''))
    routes.append('MATCH,' + CLASH_FINAL)
    return {'rule-providers': providers, 'rules': routes}


def render_config(entries):
    config = config_for(entries)
    scalar = lambda value: json.dumps(value, ensure_ascii=False)
    lines = ['# 合并到已有主配置；策略组名称须与主配置一致。', '# 配套 geodata 更新周期：geo-update-interval: 168（小时）；规则 provider 为每周。', 'rule-providers:']
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
                              for policy in sorted({route.split(',')[2] for route in config['rules'] if route.startswith('RULE-SET,')} | {CLASH_FINAL}) if policy != 'DIRECT']
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
    if not any(f'Meta {prefix}{MIHOMO_VERSION} ' in version for prefix in ('', 'v')):
        raise ValueError(f'构建需要 mihomo {MIHOMO_VERSION}，实际: {version.strip()}')
    files = routing.service_paths(surge_dir)
    if not files:
        raise ValueError(f'缺少 Surge 源规则: {surge_dir}')
    directory = Path(tempfile.mkdtemp(prefix='rules-convert-'))
    artifacts = {}
    groups = collections.defaultdict(set)
    classical_entries = []
    service_files = []
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
        service_files.append((relative, policy, converted))
        artifacts[relative] = render_rules(policy, converted).encode('utf-8')
        groups[policy].update(converted)
        name = relative[:-5].replace('/', '-')
        classical_entries.append((name, relative, policy, 'classical', 'text', False))
    classical_entries = sorted(classical_entries, key=routing.entry_order)
    mrs_entries = []
    for relative, policy, converted in sorted(service_files, key=lambda item: routing.entry_order(
            (item[0][:-5].replace('/', '-'), item[0], item[1]))):
        theme = relative[:-5]
        if theme not in ('Proxy/Google', 'Proxy/Others', 'Direct'):
            mrs_entries.append((theme.replace('/', '-'), relative, policy, 'classical', 'text', False))
            continue
        label = theme.split('/')[-1]
        domains = [rule for rule in converted if rule[0] in ('DOMAIN', 'DOMAIN-SUFFIX')]
        remaining = [rule for rule in converted if rule[0] not in ('DOMAIN', 'DOMAIN-SUFFIX')]
        partitions = [('domain', domains, 'domain', False)]
        if theme == 'Proxy/Google':
            keywords = [rule for rule in remaining if rule[0] == 'DOMAIN-KEYWORD']
            ips = [rule for rule in remaining if rule[0] in ('IP-CIDR', 'IP-CIDR6')]
            if len(keywords) + len(ips) != len(remaining) or any(rule[2] != ('no-resolve',) for rule in ips):
                raise ValueError('Google 规则结构改变，需要重新审查分区')
            partitions.extend([('keyword', keywords, 'classical', False), ('ip', ips, 'ipcidr', True)])
        elif theme == 'Proxy/Others':
            partitions.append(('extra', remaining, 'classical', False))
        else:
            positions = [i for i, rule in enumerate(remaining) if rule[0] == 'IP-ASN']
            if positions:
                start, end = positions[0], positions[-1] + 1
                segment = remaining[start:end]
                if any(rule[0] != 'IP-ASN' for rule in segment) or 'no-resolve' in segment[0][2]:
                    raise ValueError('Direct ASN 必须连续且首条允许解析，拒绝盲目合并')
                networks = asn.export_networks([value for _, value, _ in segment], ROOT / 'inputs/ASN.mmdb', directory)
                partitions.extend([('before', remaining[:start], 'classical', False),
                                   ('asn-ip', networks, 'ipcidr', False),
                                   ('after', remaining[end:], 'classical', False)])
            else:
                partitions.append(('after', remaining, 'classical', False))
        for suffix, values, behavior, no_resolve in partitions:
            if not values:
                continue
            name = f'{label}-{suffix}'
            if behavior == 'classical':
                target = f'mrs/{name}.list'
                artifacts[target] = render_rules(policy, values, preserve_order=True).encode('utf-8')
                fmt = 'text'
            else:
                target = f'mrs/{name}.mrs'
                if behavior == 'domain':
                    values = [('+.' if typ == 'DOMAIN-SUFFIX' else '') + value for typ, value, options in values]
                elif suffix != 'asn-ip':
                    values = [value for typ, value, options in values]
                artifacts[target] = compile_mrs(values, behavior, directory / f'{name}.mrs', mihomo)
                fmt = 'mrs'
            mrs_entries.append((name, target, policy, behavior, fmt, no_resolve))
    artifacts['classical.yaml'] = render_config(classical_entries).encode('utf-8')
    artifacts['mrs.yaml'] = render_config(mrs_entries).encode('utf-8')
    for relative, content in artifacts.items():
        path = directory / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)
    all_rules = [rule for rules in groups.values() for rule in rules]
    validate_config(classical_entries, all_rules, directory, mihomo)
    validate_config(mrs_entries, all_rules, directory, mihomo)
    artifacts['geodata.yaml'] = ('# 与规则片段一起合并到主配置；ASN 使用同一仓库的每周快照。\n'
        'geo-auto-update: true\ngeo-update-interval: 168\ngeox-url:\n'
        '  asn: https://raw.githubusercontent.com/inkzuji/Rules/main/inputs/ASN.mmdb\n').encode('utf-8')
    manifest = {'schema': 1, 'mihomo': MIHOMO_VERSION, 'update_interval': 604800,
                'asn_database': json.loads((ROOT / 'inputs/asn-lock.json').read_text()),
                'sources': {p.relative_to(surge_dir).as_posix(): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
                'artifacts': {name: hashlib.sha256(content).hexdigest() for name, content in sorted(artifacts.items())}}
    artifacts['manifest.json'] = (json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2) + '\n').encode('utf-8')
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
    managed.update(f'routing/{name}-domain.list' for name in routing.THEME_NAMES)
    managed.update(f'AI/{name}.list' for name in ('OpenAI', 'Claude', 'Gemini', 'Copilot', 'Others'))
    managed.update(f'mrs/{name}{suffix}' for name in ('Google', 'Others', 'Direct')
                   for suffix in ('-domain.mrs', '-keyword.list', '-ip.mrs', '-extra.list', '-before.list', '-asn-ip.mrs', '-after.list'))
    managed.update(routing.RETIRED_PATHS)
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
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        backups = {path: path.read_bytes() for path in paths}
        deleted = []
        try:
            for path in paths:
                path.unlink()
                deleted.append(path)
        except OSError:
            for path in reversed(deleted):
                path.write_bytes(backups[path])
            raise
        for path in deleted:
            print(f'已删除退役产物: {path}')
        return
    moved = []
    try:
        for path in paths:
            moved.append((path, trash_file(path)))
    except (OSError, ValueError):
        for original, trashed in reversed(moved):
            shutil.move(str(trashed), str(original))
        raise


def publish(artifacts, out_dir, check=False):
    """检查模式严格只读；写入前退役旧产物，Actions 直接删除，本机移入废纸篓。"""
    directory = Path(out_dir)
    stale = preflight(artifacts, directory)
    if check and stale:
        raise ValueError(f'{directory}: 多余产物，请先运行构建退役: {stale}')
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
