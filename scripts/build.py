#!/usr/bin/env python3
"""
规则构建：拉取必需来源 → 保留历史并合并 → 暂存验证 → 同步发布 Surge / mihomo。

上游：
  1. 666OS/rules        (release 分支, surge/*.txt, 每日自动更新)
  2. viewer12/OverseasAI.list (main 分支, AI 聚合规则)

用法: python3 scripts/build.py [--mihomo PATH] [--validate]
"""
import argparse
import collections
import hashlib
import ipaddress
import json
import os
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import convert_clash
from acceptance import validate_artifacts
import ownership
import routing
from rules import POLICIES, parse_rules, read_policy, render_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'surge')
RAW_BASE = 'https://raw.githubusercontent.com'

# ---------------------------------------------------------------------------
# 上游配置：666OS 规则集 → 目标策略
# 策略顺序仅用于路由展示，不能决定服务归属。
# ---------------------------------------------------------------------------
SOURCE_666OS = {
    'AI.txt': '🤖️AI', 'Claude.txt': '🤖️AI', 'Gemini.txt': '🤖️AI', 'OpenAI.txt': '🤖️AI',
    'Apple.txt': '🍎苹果', 'AppleCN.txt': '🍎苹果', 'SystemOTA.txt': '🍎苹果',
    'Microsoft.txt': '🚀节点选择', 'OneDrive.txt': '🚀节点选择',
    'Telegram.txt': '🚀节点选择', 'Twitter.txt': '🚀节点选择', 'Facebook.txt': '🚀节点选择',
    'Instagram.txt': '🚀节点选择', 'SocialMedia.txt': '🚀节点选择', 'TikTok.txt': '🚀节点选择',
    'Games.txt': '🎮游戏',
    'Streaming.txt': '🚀节点选择', 'Netflix.txt': '🚀节点选择', 'Disney.txt': '🚀节点选择',
    'HBO.txt': '🚀节点选择', 'YouTube.txt': '🚀节点选择', 'Spotify.txt': '🚀节点选择',
    'Emby.txt': '🚀节点选择',
    'Google.txt': '🚀节点选择', 'GitHub.txt': '🚀节点选择', 'Dev.txt': '🚀节点选择',
    'PayPal.txt': '🚀节点选择', 'Cloudflare.txt': '🚀节点选择', 'NewsMedia.txt': '🚀节点选择',
    'Crypto.txt': '🚀节点选择', 'Bybit.txt': '🚀节点选择', 'Proxy.txt': '🚀节点选择',
    'Direct.txt': 'DIRECT',
}
URL_666OS = RAW_BASE + '/666OS/rules/release/surge/'
URL_OVERSEAS_AI = RAW_BASE + '/viewer12/OverseasAI.list/main/rule/Surge/OverseasAI/OverseasAI.list'

THEME_POLICIES = {name: ownership.theme_policy(name) for name in routing.SERVICE_NAMES}
SINGLE = {policy: name for policy, name in POLICIES.items() if name not in ('AI', 'Proxy')}


# 明确服务源决定主题（包括 IP / 进程规则）；聚合源才使用域名分类。
SOURCE_THEMES = {
    'Claude.txt': 'AI/Claude', 'Gemini.txt': 'AI/Gemini', 'OpenAI.txt': 'AI/OpenAI',
    'Microsoft.txt': 'Proxy/Microsoft', 'OneDrive.txt': 'Proxy/Microsoft',
    'Telegram.txt': 'Proxy/Social', 'Twitter.txt': 'Proxy/Social',
    'Facebook.txt': 'Proxy/Social', 'Instagram.txt': 'Proxy/Social',
    'SocialMedia.txt': 'Proxy/Social', 'TikTok.txt': 'Proxy/Social',
    'Netflix.txt': 'Proxy/Netflix', 'Disney.txt': 'Proxy/Disney', 'HBO.txt': 'Proxy/Disney',
    'YouTube.txt': 'Proxy/YouTube', 'Spotify.txt': 'Proxy/Spotify',
    'Emby.txt': 'Proxy/Streaming', 'Google.txt': 'Proxy/Google',
    'GitHub.txt': 'Proxy/GitHub', 'Dev.txt': 'Proxy/Dev',
    'Cloudflare.txt': 'Proxy/Cloudflare',
    'PayPal.txt': 'Proxy/Others', 'NewsMedia.txt': 'Proxy/Others',
    'Crypto.txt': 'Proxy/Others', 'Bybit.txt': 'Proxy/Others',
}
URL_BILIBILI = RAW_BASE + '/blackmatrix7/ios_rule_script/master/rule/Surge/BiliBili/BiliBili.list'
URL_COPILOT = RAW_BASE + '/MetaCubeX/meta-rules-dat/meta/geo/geosite/classical/github-copilot.list'


def sources():
    """固定优先级：明确主题来源在先，同类按配置顺序，最后为聚合源。"""
    configured = [(URL_666OS + name, policy, SOURCE_THEMES.get(name, SINGLE.get(policy)))
                  for name, policy in SOURCE_666OS.items()]
    configured.extend([(URL_COPILOT, '🤖️AI', 'AI/Copilot'),
                       (URL_BILIBILI, '📽哔哩', 'Bilibili'),
                       (URL_OVERSEAS_AI, '🤖️AI', None)])
    return [entry for entry in configured if entry[2]] + [entry for entry in configured if not entry[2]]


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'rules-builder/1.0'})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                return response.read().decode('utf-8-sig')
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == 2 or (isinstance(error, urllib.error.HTTPError) and error.code < 500 and error.code != 429):
                raise
            time.sleep(attempt + 1)


class Selections(dict):
    """保留决策记录用于报告；字典值仍为排序依据、策略、主题和规则。"""
    def __init__(self):
        super().__init__()
        self.decisions = []
        self.sources = []
        self.origins = {}
        self.reasons = {}


def classify(policy, rule):
    return ownership.decide(rule, policy, None).theme


def merge(best, policy, rules, theme=None, historical=False, source='<memory>', source_rank=None):
    """先执行归属契约，再以当前来源、明确服务证据决定候选；同级冲突报错。"""
    for rule in rules:
        typ, value, _ = rule
        key = (typ, value)
        decision = ownership.decide(rule, policy, theme)
        target = decision.theme
        if isinstance(best, Selections) and (target != theme or decision.reason != '来源候选'):
            best.decisions.append({'rule': rule, 'source': source, 'historical': historical,
                                   'from': theme or policy, 'to': target, 'reason': decision.reason})
        if target is None:
            continue
        resolved_policy = ownership.theme_policy(target)
        # 专题 AI 聚合的范围小于全网代理聚合；公共服务仍由归属契约纠正。
        evidence = (0 if theme else 2 if policy == '🤖️AI' else 3) if source_rank is None else source_rank
        rank = (historical, evidence)
        previous = best.get(key)
        if previous and previous[0] == rank and previous[2] != target:
            if not historical and theme is not None:
                raise ValueError(f'同级明确来源归属冲突 {key}: {previous[2]} / {target} ({source})')
            # 聚合源、历史来源均不能证明服务专属归属，使用保守公共分类。
            target = 'Proxy/Others'
            resolved_policy = ownership.theme_policy(target)
        if previous is None or rank <= previous[0]:
            preserved = (evidence > 0 and decision.reason == '来源候选'
                    and previous and previous[1] == resolved_policy
                    and previous[2] not in ('AI/Others', 'Proxy/Others'))
            if preserved:
                target = previous[2]
            best[key] = (rank, resolved_policy, target, rule)
            if isinstance(best, Selections):
                best.origins[key] = source
                best.reasons[key] = '聚合源更新参数，保留有效服务归属' if preserved else decision.reason


def collect(surge_dir, source_list=None):
    """抓取和解析全部来源，任何来源失败或为空均中止，不写产物。"""
    best = Selections()
    for path in routing.service_paths(surge_dir):
        text = path.read_text(encoding='utf-8')
        policy = read_policy(text, source=str(path))
        theme = path.relative_to(surge_dir).with_suffix('').as_posix()
        if theme not in THEME_POLICIES:
            raise ValueError(f'{path}: 未知历史主题 {theme!r}')
        if THEME_POLICIES[theme] != policy:
            raise ValueError(f'{path}: 历史主题 {theme!r} 与策略 {policy!r} 不兼容')
        merge(best, policy, parse_rules(text, source=str(path)), theme, historical=True, source=str(path))
    total_fetched = 0
    for url, policy, theme in sources() if source_list is None else source_list:
        try:
            raw = fetch(url)
            rules = parse_rules(raw, source=url)
            if not rules:
                raise ValueError('来源没有有效规则')
        except Exception as exc:
            raise RuntimeError(f'必需来源失败 {url}: {exc}') from exc
        # 开发/流媒体/社交主题是跨公司的聚合，证据弱于命名服务来源。
        source_name = url.rsplit('/', 1)[-1]
        source_rank = 1 if source_name in ('Dev.txt', 'Streaming.txt', 'SocialMedia.txt',
                                         'NewsMedia.txt', 'Crypto.txt') else None
        merge(best, policy, rules, theme, source=url, source_rank=source_rank)
        best.sources.append({'url': url, 'sha256': hashlib.sha256(raw.encode('utf-8')).hexdigest(),
                             'rules': len(rules)})
        total_fetched += len(rules)
        print(f'✓ {url.rsplit("/", 1)[-1]:24s} {len(rules):6d} 条 → {policy}')
    if not best:
        raise ValueError('没有可构建的规则')
    # 专属例外不能依赖上游恰好保留；例如 Google 父域存在时 Gemini 仍须可识别。
    for domain, theme in ownership.DOMAIN_OWNERS.items():
        rule = ('DOMAIN-SUFFIX', domain, ())
        if rule[:2] not in best:
            merge(best, ownership.theme_policy(theme), [rule], theme, source='归属契约')
    return best, total_fetched


def surge_artifacts(best):
    """保持全部 21 个历史地址，即使某主题暂时为空也生成文件。"""
    buckets = {name: (policy, []) for name, policy in THEME_POLICIES.items()}
    for _, policy, theme, rule in best.values():
        buckets[theme][1].append(rule)
    files = [(name + '.list', policy, rules) for name, (policy, rules) in buckets.items()]
    artifacts = {relative: render_rules(policy, rules).encode('utf-8')
                 for relative, policy, rules in files}
    domains, domain_entries = routing.domain_artifacts(files)
    service_entries = [(relative[:-5].replace('/', '-'), relative, policy, 'classical', 'text', False)
                       for relative, policy, _ in files]
    artifacts.update(domains)
    artifacts['rules.conf'] = routing.surge_references(domain_entries + sorted(service_entries, key=routing.entry_order))
    return artifacts


def network_conflicts(best):
    """区间扫描发现跨策略的真实 CIDR 交叠；不把同策略主题重叠误报成路由冲突。"""
    intervals = []
    for _, policy, theme, (typ, value, _) in best.values():
        if typ in ('IP-CIDR', 'IP-CIDR6'):
            network = ipaddress.ip_network(value)
            intervals.append((network.version, int(network.network_address), int(network.broadcast_address),
                              policy, theme, value))
    active, conflicts = [], []
    for interval in sorted(intervals):
        version, start, _, policy, theme, value = interval
        active = [item for item in active if item[0] == version and item[2] >= start]
        for other in active:
            if policy != other[3]:
                conflicts.append({'first': [theme, value], 'second': [other[4], other[5]]})
        active.append(interval)
    return conflicts


def discard_covered_fallbacks(best):
    """通用代理的小网段若被另一明确服务完整覆盖，保留有服务证据的覆盖。"""
    specific = [(ipaddress.ip_network(rule[1]), theme) for _, _, theme, rule in best.values()
                if rule[0] in ('IP-CIDR', 'IP-CIDR6') and theme != 'Proxy/Others']
    for key, (_, _, theme, rule) in list(best.items()):
        if theme != 'Proxy/Others' or rule[0] not in ('IP-CIDR', 'IP-CIDR6'):
            continue
        network = ipaddress.ip_network(rule[1])
        covering = next((owner for other, owner in specific
                         if network.version == other.version and network.subnet_of(other)), None)
        if covering:
            del best[key]
            best.decisions.append({'rule': rule, 'source': '网段覆盖核验', 'from': theme,
                                   'to': covering, 'reason': '通用 IP 已被明确服务网段完整覆盖'})


def reject_stale(artifacts, directory):
    """Surge 没有可退役的动态配套文件，所有多余产物均阻断。"""
    stale = convert_clash.stale_paths(artifacts, directory)
    if stale:
        raise ValueError(f'{directory}: 未知的多余产物: {stale}')


def write_report(path, report):
    if path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def build(surge_dir=OUT_DIR, clash_dir=None, count_path=None, mihomo='mihomo', validate=False,
          source_list=None, report_path=None):
    clash_dir = Path(clash_dir or os.path.join(ROOT, 'clash'))
    count_path = Path(count_path or os.path.join(ROOT, 'scripts', '.last_count'))
    try:
        best, total_fetched = collect(surge_dir, source_list)
    except (OSError, ValueError, RuntimeError) as error:
        write_report(report_path, {'status': 'collection_failed', 'error': str(error)})
        raise
    discard_covered_fallbacks(best)
    conflicts = network_conflicts(best)
    report = {'status': 'collected', 'total': len(best), 'by_theme': dict(sorted(collections.Counter(
        entry[2] for entry in best.values()).items())), 'candidate_decisions': best.decisions,
        'selected': [{'rule': rule, 'policy': policy, 'theme': theme,
                      'source': best.origins[key], 'reason': best.reasons[key]}
                     for key, (_, policy, theme, rule) in sorted(best.items())],
        'network_conflicts': conflicts, 'sources': best.sources}
    write_report(report_path, report)
    if conflicts:
        raise ValueError(f'存在 {len(conflicts)} 个未解决的跨策略 CIDR 重叠: {conflicts[:5]}')
    count = len(best)
    if count_path.exists():
        last = int(count_path.read_text().strip())
        if count < last * 0.6:
            raise ValueError(f'规则数骤降 {last} → {count}，疑似上游异常，中止')
    surge = surge_artifacts(best)
    # 使用留存的暂存目录，避免违反本地文件不得永久删除的约束。
    stage = Path(tempfile.mkdtemp(prefix='rules-build-'))
    print(f'暂存目录: {stage}')
    convert_clash.publish(surge, stage / 'surge')
    clash = convert_clash.generate(stage / 'surge', mihomo=mihomo)
    if validate:
        subprocess.run([sys.executable, os.path.join(ROOT, 'scripts', 'validate.py'),
                        '--rules-dir', str(stage / 'surge')], check=True)
    reject_stale(surge, surge_dir)
    convert_clash.preflight(surge, surge_dir)
    convert_clash.preflight(clash, clash_dir)
    convert_clash.publish(clash, stage / 'clash')
    try:
        report['acceptance'] = validate_artifacts(stage / 'surge', stage / 'clash', mihomo, require_surge_config=True)
    except (OSError, ValueError, RuntimeError) as error:
        report.update(status='acceptance_failed', error=str(error))
        write_report(report_path, report)
        raise
    report['status'] = 'validated'
    write_report(report_path, report)
    # 先退役旧配套文件；退役失败时，尚未更新任一规则树与计数。
    convert_clash.retire_stale(clash, clash_dir)
    # 只有全部来源、转换、原生验证和目标预检均成功，才开始更新仓库。
    convert_clash.publish(surge, surge_dir)
    convert_clash.publish(clash, clash_dir)
    count_path.write_text(str(count), encoding='utf-8')
    print(f'上游 {total_fetched} 条 → 去重后 {count} 条 → '
          f'Surge {len(surge)} 个文件，Clash {len(clash)} 个文件')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--validate', action='store_true', help='可选 DoH 诊断，只报告、不删除规则')
    ap.add_argument('--mihomo', default='mihomo', help='官方 mihomo 可执行文件路径')
    ap.add_argument('--report', help='写出归属纠正、过滤原因和跨策略网段冲突报告')
    args = ap.parse_args()
    try:
        build(mihomo=args.mihomo, validate=args.validate, report_path=args.report)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'❌ 构建失败: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
