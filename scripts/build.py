#!/usr/bin/env python3
"""
规则构建脚本：拉取上游规则 → 按策略优先级合并去重 → 按主题拆分输出 surge_rules/surge/

上游：
  1. 666OS/rules        (release 分支, surge/*.txt, 每日自动更新)
  2. viewer12/OverseasAI.list (main 分支, AI 聚合规则)

用法: python3 scripts/build.py [--validate]
"""
import argparse
import collections
import glob
import os
import sys
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_DIR = os.path.join(ROOT, 'surge')
RAW_BASE = 'https://raw.githubusercontent.com'

# ---------------------------------------------------------------------------
# 上游配置：666OS 规则集 → 目标策略（None 表示跳过）
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
}
URL_666OS = RAW_BASE + '/666OS/rules/release/surge/'
URL_OVERSEAS_AI = RAW_BASE + '/viewer12/OverseasAI.list/main/rule/Surge/OverseasAI/OverseasAI.list'

POLICY_ORDER = {'🤖️AI': 0, '🍎苹果': 1, '🎮游戏': 2, '🚀节点选择': 3, '📽哔哩': 4, 'DIRECT': 5}

VALID_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'IP-CIDR', 'IP-CIDR6',
               'IP-ASN', 'GEOIP', 'URL-REGEX', 'USER-AGENT', 'PROCESS-NAME'}

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
    ('Proxy/Cloudflare', ['cloudflare', 'cloudflaredns', 'cloudflareinsights', 'cloudfront', 'cloudflared', 'argo']),
    ('Proxy/Streaming', ['crunchyroll', 'peacock', 'abema', 'tver', 'fod', 'paravi', 'telasa', 'dazn', 'fubo',
                         'paramount', 'fox', 'nbc', 'cbs', 'pbs', 'discovery', 'tidal', 'deezer', 'soundcloud',
                         'pandora', 'netease', 'qqmusic', 'kugou', 'kuwo', 'viu', 'vuclip']),
]
# 单文件主题（保持平铺）
SINGLE = {'🍎苹果': 'Apple', '🎮游戏': 'Game', '📽哔哩': 'Bilibili', 'DIRECT': 'Direct'}

DOMAIN_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD'}


def fetch(url, timeout=30):
    req = urllib.request.Request(url, headers={'User-Agent': 'rules-builder/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read().decode('utf-8', errors='replace')


def parse_rules(text):
    """解析规则文本为 (typ, val, no_resolve) 元组列表"""
    rules = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        parts = [p.strip() for p in s.split(',')]
        if len(parts) < 2 or parts[0] not in VALID_TYPES:
            continue
        typ, val = parts[0], parts[1].lower()
        nr = 'no-resolve' in parts[2:]
        rules.append((typ, val, nr))
    return rules


def read_policy(path):
    """从文件头注释 '# 策略: xxx' 读取策略名"""
    with open(path, encoding='utf-8') as f:
        for line in f:
            s = line.strip()
            if s.startswith('# 策略:'):
                return s[len('# 策略:'):].strip()
            if s and not s.startswith('#'):
                break
    return ''


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--validate', action='store_true', help='构建后执行 DoH 失效域名校验')
    args = ap.parse_args()

    # 0. 读现有 surge/ 作为基底（保留历史手工/快照内容，如 Direct、Bilibili）
    best = {}  # (typ, val) -> (优先级, 策略, typ, val, nr)
    total_fetched = 0
    for f in glob.glob(os.path.join(OUT_DIR, '**', '*.list'), recursive=True):
        rel = os.path.relpath(f, OUT_DIR)
        policy = read_policy(f)
        pri = POLICY_ORDER.get(policy, 99)
        with open(f, encoding='utf-8') as fh:
            for typ, val, nr in parse_rules(fh.read()):
                k = (typ, val)
                if k not in best or pri < best[k][0]:
                    best[k] = (pri, policy, typ, val, nr)

    # 1. 拉上游
    sources = [(URL_666OS + name, policy) for name, policy in SOURCE_666OS.items()]
    sources.append((URL_OVERSEAS_AI, '🤖️AI'))
    fetched_ok = 0
    for url, policy in sources:
        try:
            rules = parse_rules(fetch(url))
        except Exception as e:
            print(f'⚠️ 拉取失败 {url}: {e}', file=sys.stderr)
            continue
        fetched_ok += 1
        total_fetched += len(rules)
        pri = POLICY_ORDER.get(policy, 99)
        for typ, val, nr in rules:
            k = (typ, val)
            if k not in best or pri < best[k][0]:
                best[k] = (pri, policy, typ, val, nr)
        print(f'✓ {url.rsplit("/", 1)[-1]:24s} {len(rules):6d} 条 → {policy}')

    if not best or fetched_ok == 0:
        print('❌ 未拉到任何规则，中止', file=sys.stderr)
        sys.exit(1)

    # 骤降保护：不足历史量 60% 时告警（首次构建跳过）
    hist_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.last_count')
    count = len(best)
    if os.path.exists(hist_path):
        last = int(open(hist_path).read().strip())
        if count < last * 0.6:
            print(f'❌ 规则数骤降 {last} → {count}，疑似上游异常，中止', file=sys.stderr)
            sys.exit(1)
    open(hist_path, 'w').write(str(count))

    # 2. 按策略分桶
    by_policy = collections.defaultdict(list)
    for pri, policy, typ, val, nr in best.values():
        by_policy[policy].append((typ, val, nr))

    # 3. 主题归类 + 写文件
    groups = {  # 组目录 → (策略, 主题表, 兜底名)
        'AI': ('🤖️AI', THEMES_AI, 'AI/Others'),
        'Proxy': ('🚀节点选择', THEMES_PROXY, 'Proxy/Others'),
    }
    summary = []
    for group, (policy, themes, fallback) in groups.items():
        buckets = collections.defaultdict(list)
        for typ, val, nr in by_policy.get(policy, []):
            target = fallback
            if typ in DOMAIN_TYPES:
                for name, kws in themes:
                    if any(kw in val for kw in kws):
                        target = name
                        break
            buckets[target].append((typ, val, nr))
        for name, rules in buckets.items():
            write_list(name, policy, rules)
            summary.append((name, policy, len(rules)))

    for policy, fname in SINGLE.items():
        rules = by_policy.get(policy, [])
        if rules:
            write_list(fname, policy, rules)
            summary.append((fname, policy, len(rules)))

    # 4. 可选：DoH 校验
    if args.validate:
        rc = os.system(f'{sys.executable} {os.path.join(os.path.dirname(os.path.abspath(__file__)), "validate.py")}')
        if rc != 0:
            sys.exit(rc)

    total = sum(n for _, _, n in summary)
    print(f'\n上游 {total_fetched} 条 → 去重后 {count} 条 → 输出 {total} 条，{len(summary)} 个文件')

    # 5. 同步生成 clash/ 规则集
    rc = os.system(f'{sys.executable} {os.path.join(os.path.dirname(os.path.abspath(__file__)), "convert_clash.py")}')
    if rc != 0:
        sys.exit(rc)


def write_list(name, policy, rules):
    """写一个 .list 文件（排序 + 头注释）"""
    path = os.path.join(OUT_DIR, name + '.list')
    os.makedirs(os.path.dirname(path), exist_ok=True)
    rules = sorted(set(rules), key=lambda r: (r[0], r[1]))
    with open(path, 'w', encoding='utf-8') as f:
        f.write(f'# 策略: {policy}\n# 规则数: {len(rules)}\n\n')
        cur = None
        for typ, val, nr in rules:
            if typ != cur:
                cur = typ
                f.write(f'# {typ}\n')
            f.write(f'{typ},{val}{",no-resolve" if nr else ""}\n')


if __name__ == '__main__':
    main()
