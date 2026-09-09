#!/usr/bin/env python3
"""
可选 DoH 诊断：对 DOMAIN / DOMAIN-SUFFIX 查询，只报告疑似 NXDOMAIN，不修改规则。

连续查询至少两次 NXDOMAIN 且无其他错误时标记；DNS 结果不是删除规则的依据。
"""
import argparse
import concurrent.futures
import glob
import json
import os
import time
import urllib.parse
import urllib.request

from rules import parse_rules

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(ROOT, 'surge')
DOH = 'https://1.1.1.1/dns-query'
WORKERS = 24


def doh(name):
    query = urllib.parse.urlencode({'name': name, 'type': 'A'})
    req = urllib.request.Request(f'{DOH}?{query}', headers={'accept': 'application/dns-json'})
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())


def check(name):
    nx = err = 0
    for _ in range(3):
        try:
            st = doh(name).get('Status')
            if st == 0:
                return 'alive'
            elif st == 3:
                nx += 1
            else:
                err += 1
        except Exception:
            err += 1
        time.sleep(0.2)
    return 'dead' if (nx >= 2 and err == 0) else 'error'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rules-dir', default=RULES_DIR, help='只读诊断的规则目录')
    args = ap.parse_args()
    domains = set()
    for f in glob.glob(os.path.join(args.rules_dir, '**', '*.list'), recursive=True):
        with open(f, encoding='utf-8') as source:
            for typ, value, _ in parse_rules(source.read(), source=f):
                if typ in {'DOMAIN', 'DOMAIN-SUFFIX'}:
                    domains.add(value)
    print(f'校验唯一域名: {len(domains)}', flush=True)

    res = {'alive': 0, 'dead': [], 'error': 0}
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=WORKERS) as ex:
        for name, st in ex.map(lambda n: (n, check(n)), domains):
            if st == 'dead':
                res['dead'].append(name)
            else:
                res[st] += 1
            done += 1
            if done % 2000 == 0:
                print(f'  {done}/{len(domains)} dead={len(res["dead"])}', flush=True)
    dead = set(res['dead'])
    print(f"alive={res['alive']} dead={len(dead)} error={res['error']}")

    for name in sorted(dead):
        print(f'疑似 NXDOMAIN（规则保留）: {name}')
    print('诊断完成；未修改任何规则。')


if __name__ == '__main__':
    main()
