#!/usr/bin/env python3
"""
规则构建：拉取必需来源 → 保留历史并合并 → 暂存验证 → 同步发布 Surge / mihomo。

上游：
  1. 666OS/rules        (release 分支, surge/*.txt, 每日自动更新)
  2. viewer12/OverseasAI.list (main 分支, AI 聚合规则)

用法: python3 scripts/build.py [--mihomo PATH] [--validate]
"""
import argparse
import os
import sys
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

import convert_clash
from rules import POLICIES, parse_rules, read_policy, render_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'surge')
RAW_BASE = 'https://raw.githubusercontent.com'

# ---------------------------------------------------------------------------
# 上游配置：666OS 规则集 → 目标策略
# 策略优先级（同时出现时小编号优先）: AI > Apple > Game > Proxy > Bili > Direct
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

POLICY_ORDER = {policy: i for i, policy in enumerate(POLICIES)}

# ---------------------------------------------------------------------------
# 主题关键词（顺序即优先级，先专后泛）；策略 → [(文件名, 关键词列表)]
# ---------------------------------------------------------------------------
THEMES_AI = [
    ('AI/OpenAI', ['openai', 'chatgpt', 'oai', 'sora', 'arkoselabs', 'statsig', 'featuregates', 'livekit']),
    ('AI/Claude', ['anthropic', 'claude', 'identrust', 'intercom', 'segment', 'sentry', 'algolia', 'launchdarkly']),
    ('AI/Gemini', ['gemini', 'bard', 'makersuite', 'aistudio', 'deepmind', 'generativelanguage', 'ai.google']),
    ('AI/Copilot', ['copilot', 'githubnext', 'bing']),
]
THEMES_PROXY = [
    ('Proxy/YouTube', ['youtube', 'ytimg', 'googlevideo', 'youtu', 'ytbe']),
    ('Proxy/Netflix', ['netflix', 'nflx']),
    ('Proxy/Disney', ['disney', 'dssot', 'bamgrid', 'hulu', 'hbo', 'max.com', 'primevideo', 'amazonvideo', 'amazon']),
    ('Proxy/Spotify', ['spotify']),
    ('Proxy/GitHub', ['github', 'ghproxy']),
    ('Proxy/Microsoft', ['microsoft', 'msn.com', 'bing', 'azure', 'office365', 'onedrive', 'live.com',
                         'visualstudio', 'msedge', 'windowsupdate', 'xbox']),
    ('Proxy/Google', ['google', 'gmail', 'gstatic', 'ggpht', '1e100', 'doubleclick', 'blogger',
                      'android', 'appengine', 'gvt1', 'recaptcha', 'adsense', 'firebase', 'chromium']),
    ('Proxy/Social', ['twitter', 'x.com', 'twimg', 't.co', 'facebook', 'fbcdn', 'instagram', 'cdninstagram',
                      'telegram', 't.me', 'whatsapp', 'discord', 'reddit', 'tiktok', 'musically',
                      'snapchat', 'pinterest', 'linkedin', 'threads']),
    ('Proxy/Dev', ['docker', 'npmjs', 'rubygems', 'pypi', 'maven', 'stackoverflow', 'jetbrains', 'homebrew',
                   'rust', 'golang', 'python', 'nodejs', 'kernel', 'apache', 'nginx', 'mysql', 'postgres',
                   'redis', 'linux', 'ubuntu', 'debian', 'redhat', 'gnu', 'openssl', 'mozilla', 'w3.org',
                   'spring', 'gradle', 'atlassian', 'goland', 'pycharm', 'intellij', 'webstorm', 'datagrip',
                   'clion', 'rustrover', 'phpstorm', 'rubymine', 'java']),
    ('Proxy/Cloudflare', ['cloudflare', 'cloudflaredns', 'cloudflareinsights', 'cloudflared', 'argo']),
    ('Proxy/Streaming', ['crunchyroll', 'peacock', 'abema', 'tver', 'fod', 'paravi', 'telasa', 'dazn', 'fubo',
                         'paramount', 'fox', 'nbc', 'cbs', 'pbs', 'discovery', 'tidal', 'deezer', 'soundcloud',
                         'pandora', 'netease', 'qqmusic', 'kugou', 'kuwo', 'viu', 'vuclip']),
]
# 单文件主题（保持平铺）
SINGLE = {'🍎苹果': 'Apple', '🎮游戏': 'Game', '📽哔哩': 'Bilibili', 'DIRECT': 'Direct'}
THEME_POLICIES = {name: policy for policy, name in SINGLE.items()}
THEME_POLICIES.update({name: '🤖️AI' for name, _ in THEMES_AI})
THEME_POLICIES.update({name: '🚀节点选择' for name, _ in THEMES_PROXY})
THEME_POLICIES.update({'AI/Others': '🤖️AI', 'Proxy/Others': '🚀节点选择'})

DOMAIN_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD'}


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


def classify(policy, rule):
    """仅按完整域名标签匹配，避免 t.co / rust 等子串误归类。"""
    if policy in SINGLE:
        return SINGLE[policy]
    typ, value, _ = rule
    themes = THEMES_AI if policy == '🤖️AI' else THEMES_PROXY
    if typ in DOMAIN_TYPES:
        domain = '.' + value.strip('.') + '.'
        for name, keywords in themes:
            if any('.' + keyword + '.' in domain for keyword in keywords):
                return name
    return 'AI/Others' if policy == '🤖️AI' else 'Proxy/Others'


def merge(best, policy, rules, theme=None, historical=False):
    """策略优先；当前参数优先历史，聚合源沿用同策略已明确的历史主题。"""
    for rule in rules:
        typ, value, _ = rule
        key = (typ, value)
        rank = (POLICY_ORDER[policy], historical)
        if key not in best or rank < best[key][0]:
            target = theme or classify(policy, rule)
            previous = best.get(key)
            if (theme is None and previous and previous[1] == policy
                    and previous[2] not in ('AI/Others', 'Proxy/Others')):
                target = previous[2]
            best[key] = (rank, policy, target, rule)


def collect(surge_dir, source_list=None):
    """抓取和解析全部来源，任何来源失败或为空均中止，不写产物。"""
    best = {}
    for path in sorted(Path(surge_dir).rglob('*.list')):
        text = path.read_text(encoding='utf-8')
        policy = read_policy(text, source=str(path))
        theme = path.relative_to(surge_dir).with_suffix('').as_posix()
        if theme not in THEME_POLICIES:
            raise ValueError(f'{path}: 未知历史主题 {theme!r}')
        if THEME_POLICIES[theme] != policy:
            raise ValueError(f'{path}: 历史主题 {theme!r} 与策略 {policy!r} 不兼容')
        merge(best, policy, parse_rules(text, source=str(path)), theme, historical=True)
    total_fetched = 0
    for url, policy, theme in sources() if source_list is None else source_list:
        try:
            rules = parse_rules(fetch(url), source=url)
            if not rules:
                raise ValueError('来源没有有效规则')
        except Exception as exc:
            raise RuntimeError(f'必需来源失败 {url}: {exc}') from exc
        merge(best, policy, rules, theme)
        total_fetched += len(rules)
        print(f'✓ {url.rsplit("/", 1)[-1]:24s} {len(rules):6d} 条 → {policy}')
    if not best:
        raise ValueError('没有可构建的规则')
    return best, total_fetched


def surge_artifacts(best):
    """保持全部 21 个历史地址，即使某主题暂时为空也生成文件。"""
    buckets = {name: (policy, []) for name, policy in THEME_POLICIES.items()}
    for _, policy, theme, rule in best.values():
        buckets[theme][1].append(rule)
    return {name + '.list': render_rules(policy, rules).encode('utf-8')
            for name, (policy, rules) in buckets.items()}


def reject_stale(artifacts, directory):
    """Surge 没有可退役的动态配套文件，所有多余产物均阻断。"""
    stale = convert_clash.stale_paths(artifacts, directory)
    if stale:
        raise ValueError(f'{directory}: 未知的多余产物: {stale}')


def build(surge_dir=OUT_DIR, clash_dir=None, count_path=None, mihomo='mihomo', validate=False,
          source_list=None):
    clash_dir = Path(clash_dir or os.path.join(ROOT, 'clash'))
    count_path = Path(count_path or os.path.join(ROOT, 'scripts', '.last_count'))
    best, total_fetched = collect(surge_dir, source_list)
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
    args = ap.parse_args()
    try:
        build(mihomo=args.mihomo, validate=args.validate)
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as exc:
        print(f'❌ 构建失败: {exc}', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__':
    main()
