#!/usr/bin/env python3
"""
转换脚本：surge/ → clash/（classical 规则集，Clash / Clash.Meta / mihomo 通用）

两性行格式高度兼容，仅做差异处理：
  - DOMAIN / DOMAIN-SUFFIX / DOMAIN-KEYWORD / IP-CIDR / IP-CIDR6 / GEOIP / IP-ASN 原样保留
  - no-resolve 参数保留
  - URL-REGEX / USER-AGENT / PROCESS-NAME 等 Clash 不支持的类型跳过并统计

用法: python3 scripts/convert_clash.py [--check]
  --check 只校验 clash/ 是否与 surge/ 同步，不同步则退出码非 0（CI 用）
"""
import argparse
import glob
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SRC_DIR = os.path.join(ROOT, 'surge')
OUT_DIR = os.path.join(ROOT, 'clash')

# Clash classical 支持的规则类型
CLASH_TYPES = {'DOMAIN', 'DOMAIN-SUFFIX', 'DOMAIN-KEYWORD', 'IP-CIDR', 'IP-CIDR6',
               'IP-ASN', 'GEOIP'}

SKIPPED = {}  # 类型 -> 跳过条数


def parse_rules(text):
    """解析规则文本为 (typ, val, no_resolve) 元组列表（与 build.py 口径一致）"""
    rules = []
    for line in text.splitlines():
        s = line.strip()
        if not s or s.startswith('#'):
            continue
        parts = [p.strip() for p in s.split(',')]
        if len(parts) < 2 or parts[0] not in CLASH_TYPES:
            if parts and parts[0] not in ('', '#'):
                SKIPPED[parts[0]] = SKIPPED.get(parts[0], 0) + 1
            continue
        rules.append((parts[0], parts[1], 'no-resolve' in parts[2:]))
    return rules


def render(name, policy, rules):
    """渲染为一个 clash classical .list 文件内容"""
    lines = [f'# 策略: {policy}', f'# 规则数: {len(rules)}', '']
    cur = None
    for typ, val, nr in rules:
        if typ != cur:
            cur = typ
            lines.append(f'# {typ}')
        lines.append(f'{typ},{val}{",no-resolve" if nr else ""}')
    return '\n'.join(lines) + '\n'


def convert():
    """执行转换，返回 (输出文件数, 总规则数)"""
    n_files = n_rules = 0
    valid_paths = []
    for src in sorted(glob.glob(os.path.join(SRC_DIR, '**', '*.list'), recursive=True)):
        rel = os.path.relpath(src, SRC_DIR)
        with open(src, encoding='utf-8') as f:
            text = f.read()
        # 读策略名（与 build.py read_policy 口径一致）
        policy = ''
        for line in text.splitlines():
            s = line.strip()
            if s.startswith('# 策略:'):
                policy = s[len('# 策略:'):].strip()
                break
            if s and not s.startswith('#'):
                break
        rules = parse_rules(text)
        out_path = os.path.join(OUT_DIR, rel)
        os.makedirs(os.path.dirname(out_path) or OUT_DIR, exist_ok=True)
        with open(out_path, 'w', encoding='utf-8') as f:
            f.write(render(rel, policy, rules))
        valid_paths.append(out_path)
        n_files += 1
        n_rules += len(rules)
        print(f'✓ clash/{rel:28s} {len(rules):6d} 条')
    return n_files, n_rules, valid_paths


def clean_stale(valid_paths):
    """删除 clash/ 下已无对应 surge/ 源的陈旧文件"""
    removed = 0
    for f in glob.glob(os.path.join(OUT_DIR, '**', '*.list'), recursive=True):
        if f not in valid_paths:
            os.remove(f)
            removed += 1
            print(f'🗑 删除陈旧文件 clash/{os.path.relpath(f, OUT_DIR)}')
    # 清掉空目录
    for dirpath, dirnames, filenames in os.walk(OUT_DIR, topdown=False):
        if not dirnames and not filenames and dirpath != OUT_DIR:
            os.rmdir(dirpath)
    return removed


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--check', action='store_true', help='只校验 clash/ 是否同步，不写文件')
    args = ap.parse_args()

    if not os.path.isdir(SRC_DIR):
        print(f'❌ 缺少源目录 {SRC_DIR}', file=sys.stderr)
        sys.exit(1)

    if args.check:
        # 重新生成到内存比对
        dirty = []
        for src in sorted(glob.glob(os.path.join(SRC_DIR, '**', '*.list'), recursive=True)):
            rel = os.path.relpath(src, SRC_DIR)
            with open(src, encoding='utf-8') as f:
                text = f.read()
            policy = ''
            for line in text.splitlines():
                s = line.strip()
                if s.startswith('# 策略:'):
                    policy = s[len('# 策略:'):].strip()
                    break
                if s and not s.startswith('#'):
                    break
            expected = render(rel, policy, parse_rules(text))
            out_path = os.path.join(OUT_DIR, rel)
            actual = ''
            if os.path.exists(out_path):
                with open(out_path, encoding='utf-8') as f:
                    actual = f.read()
            if actual != expected:
                dirty.append(rel)
        if dirty:
            print(f'❌ clash/ 未同步，共 {len(dirty)} 个文件不一致: {dirty}', file=sys.stderr)
            sys.exit(1)
        print('✓ clash/ 与 surge/ 已同步')
        return

    n_files, n_rules, valid_paths = convert()
    removed = clean_stale(valid_paths)
    if SKIPPED:
        detail = ', '.join(f'{k}×{v}' for k, v in sorted(SKIPPED.items()))
        print(f'⚠️ 跳过 Clash 不支持的类型: {detail}')
    print(f'\n输出 {n_files} 个文件，共 {n_rules} 条规则，删除陈旧 {removed} 个')


if __name__ == '__main__':
    main()
