"""Surge 源规则的解析、策略与文本渲染，供构建和转换复用。"""
import csv
import io
import ipaddress

POLICIES = {'🤖️AI': 'AI', '🍎苹果': 'Apple', '🎮游戏': 'Game',
            '🚀节点选择': 'Proxy', '📽哔哩': 'Bilibili', 'DIRECT': 'Direct'}
VALID_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-WILDCARD',
               'IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP', 'URL-REGEX',
               'USER-AGENT', 'PROCESS-NAME'}
DOMAIN_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'DOMAIN-WILDCARD'}
IP_TYPES = {'IP-CIDR', 'IP-CIDR6', 'IP-ASN', 'GEOIP'}


def parse_rules(text, source='<text>'):
    """返回 (类型, 值, 参数元组)；拒绝不能无损解释的规则及参数。"""
    rules = []
    for number, line in enumerate(text.lstrip('\ufeff').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith(('#', '//', ';')):
            continue
        try:
            quote = "'" if line.partition(',')[2].lstrip().startswith("'") else '"'
            parts = next(csv.reader([line], skipinitialspace=True, quotechar=quote, strict=True))
            parts = [part.strip() for part in parts]
            if len(parts) < 2 or parts[0] not in VALID_TYPES or not parts[1]:
                raise ValueError('未知类型、缺少值或非法规则')
            typ, value, *options = parts
            allowed = set()
            if typ in IP_TYPES:
                allowed.add('no-resolve')
            if typ in DOMAIN_TYPES or typ == 'URL-REGEX':
                allowed.add('extended-matching')
            if set(options) - allowed or len(set(options)) != len(options):
                raise ValueError(f'不支持或重复的参数: {options}')
            if typ in DOMAIN_TYPES:
                value = value.lower()
                if any(char.isspace() for char in value) or '/' in value:
                    raise ValueError('非法域名表达式')
                if typ in ('DOMAIN', 'DOMAIN-SUFFIX') and any(c in value for c in '*?+,'):
                    raise ValueError('精确域名/后缀不能包含通配符或逗号')
            if typ in ('IP-CIDR', 'IP-CIDR6'):
                network = ipaddress.ip_network(value, strict=False)
                if network.version != (6 if typ == 'IP-CIDR6' else 4):
                    raise ValueError('CIDR 地址族与规则类型不符')
                value = str(network)
                if network.version == 6 and network.network_address.ipv4_mapped is not None:
                    # Python 3.11 与 3.13 对 mapped IPv6 的 str() 输出不同。
                    value = f'::ffff:{network.network_address.ipv4_mapped}/{network.prefixlen}'
            if typ == 'IP-ASN' and (not value.isdecimal() or not 0 <= int(value) <= 4294967295):
                raise ValueError('非法 ASN')
            if typ == 'GEOIP':
                value = value.upper()
                if len(value) != 2 or not value.isascii() or not value.isalpha():
                    raise ValueError('非法国家代码')
            rules.append((typ, value, tuple(options)))
        except (ValueError, csv.Error) as error:
            raise ValueError(f'{source}:{number}: {error}: {line}') from error
    return rules


def read_policy(text, source='<text>'):
    for line in text.splitlines():
        if line.strip().startswith('# 策略:'):
            policy = line.split(':', 1)[1].strip()
            if policy in POLICIES:
                return policy
            raise ValueError(f'{source}: 未知策略 {policy!r}')
        if line.strip() and not line.strip().startswith(('#', '//', ';')):
            break
    raise ValueError(f'{source}: 缺少策略注释')


def rule_line(rule, policy=None):
    typ, value, options = rule
    fields = [typ, value]
    if policy is not None:
        fields.append(policy)
    fields.extend(options)
    output = io.StringIO()
    csv.writer(output, lineterminator='').writerow(fields)
    return output.getvalue()


def render_rules(policy, rules, preserve_order=False):
    rules = list(dict.fromkeys(rules)) if preserve_order else sorted(set(rules))
    lines = [f'# 策略: {policy}', f'# 规则数: {len(rules)}', '']
    current = None
    for rule in rules:
        if rule[0] != current:
            current = rule[0]
            lines.append(f'# {current}')
        lines.append(rule_line(rule))
    return '\n'.join(lines) + '\n'
