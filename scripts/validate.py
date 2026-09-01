#!/usr/bin/env python3
"""
DoH 失效域名校验：对 surge/ 下所有 DOMAIN/DOMAIN-SUFFIX 规则做 NXDOMAIN 检测并清理

判定标准（保守）：3 次查询中 >=2 次 NXDOMAIN 且无成功解析才移除；
SERVFAIL/超时等异常保留。移除清单存档到 surge/removed_rules_<date>.txt
"""
import concurrent.futures
import datetime
import glob
import json
import os
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RULES_DIR = os.path.join(ROOT, 'surge')
DOH = 'https://1.1.1.1/dns-query'
WORKERS = 24


def doh(name):
    req = urllib.request.Request(f'{DOH}?name={name}&type=A', headers={'accept': 'application/dns-json'})
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
    domains = set()
    for f in glob.glob(os.path.join(RULES_DIR, '**', '*.list'), recursive=True):
        for l in open(f, encoding='utf-8'):
            s = l.strip()
            if s.startswith(('DOMAIN,', 'DOMAIN-SUFFIX,')):
                domains.add(s.split(',')[1].lower())
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

    # 清理 + 存档
    removed_log = []
    for f in sorted(glob.glob(os.path.join(RULES_DIR, '**', '*.list'), recursive=True)):
        lines = open(f, encoding='utf-8').read().splitlines()
        header_i = next((i for i, l in enumerate(lines) if l.startswith('# 规则数')), None)
        if header_i is None:
            continue
        body = [l for l in lines[header_i + 1:] if l.strip() and not l.startswith('#')]
        kept = []
        for s in body:
            parts = s.split(',')
            if parts[0] in ('DOMAIN', 'DOMAIN-SUFFIX') and parts[1].lower() in dead:
                removed_log.append(f'{os.path.relpath(f, RULES_DIR)}\t{s}')
                continue
            kept.append(s)
        if len(kept) == len(body):
            continue
        kept.sort(key=lambda x: (x.split(',')[0], x.split(',')[1].lower() if ',' in x else ''))
        with open(f, 'w', encoding='utf-8') as out:
            for h in lines[:header_i + 1]:
                out.write(f'# 规则数: {len(kept)}\n' if h.startswith('# 规则数') else h + '\n')
            out.write('\n')
            cur = None
            for s in kept:
                typ = s.split(',')[0]
                if typ != cur:
                    cur = typ
                    out.write(f'# {typ}\n')
                out.write(s + '\n')

    if removed_log:
        date = datetime.date.today().isoformat()
        log_path = os.path.join(RULES_DIR, f'removed_rules_{date}.txt')
        with open(log_path, 'w', encoding='utf-8') as log:
            log.write(f'# 移除规则数: {len(removed_log)}（DoH NXDOMAIN 判定）\n\n')
            log.write('\n'.join(removed_log) + '\n')
        print(f'移除 {len(removed_log)} 条，清单: {log_path}')
    else:
        print('无失效规则')


if __name__ == '__main__':
    main()
