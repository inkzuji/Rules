#!/usr/bin/env python3
"""隔离运行固定 mihomo：真实 ASN/MRS 路由、受控 DNS 差分和端到端探测基准。"""
import argparse
import hashlib
import json
from pathlib import Path
import queue
import re
import shutil
import socket
import socketserver
import statistics
import struct
import subprocess
import tempfile
import threading
import time

from convert_clash import MIHOMO_VERSION
from rules import parse_rules

ROOT = Path(__file__).resolve().parent.parent


class DNS(socketserver.BaseRequestHandler):
    def handle(self):
        packet, sock = self.request
        labels, offset = [], 12
        while packet[offset]:
            size = packet[offset]
            labels.append(packet[offset + 1:offset + 1 + size].decode())
            offset += size + 1
        name = '.'.join(labels)
        self.server.queries.append(name)
        question = packet[12:offset + 5]
        typ = struct.unpack('!H', packet[offset + 1:offset + 3])[0]
        ip = {'selected.test': '223.6.6.6', 'early.test': '223.5.5.5',
              'after.test': '198.51.100.1'}.get(name)
        answer = b''
        if ip and typ == 1:
            answer = b'\xc0\x0c' + struct.pack('!HHIH', 1, 1, 0, 4) + socket.inet_aton(ip)
        flags = 0x8180 if ip else 0x8183
        sock.sendto(packet[:2] + struct.pack('!HHHHH', flags, 1, bool(answer), 0, 0)
                    + question + answer, self.client_address)


class Kernel:
    def __init__(self, mihomo, home, rules, providers, dns_port):
        self.home = home
        home.mkdir(exist_ok=True)
        shutil.copyfile(ROOT / 'inputs/ASN.mmdb', home / 'ASN.mmdb')
        self.lines = queue.Queue()
        self.log = (home / 'runtime.log').open('w')
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]
        config = {'mixed-port': self.port, 'bind-address': '127.0.0.1', 'log-level': 'debug',
                  'ipv6': True, 'find-process-mode': 'off', 'geo-auto-update': False,
                  'dns': {'enable': True, 'ipv6': True, 'enhanced-mode': 'redir-host',
                          'nameserver': [f'udp://127.0.0.1:{dns_port}']},
                  'proxy-groups': [{'name': n, 'type': 'select', 'proxies': ['REJECT']}
                                   for n in ('HIT', 'MISS', 'EARLY', 'AFTER')],
                  'rule-providers': providers, 'rules': rules}
        path = home / 'config.json'
        path.write_text(json.dumps(config))
        started = time.perf_counter()
        self.process = subprocess.Popen([mihomo, '-d', str(home), '-f', str(path)],
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                self.close()
                raise RuntimeError(f'mihomo 启动失败，见 {home / "runtime.log"}')
            try:
                with socket.create_connection(('127.0.0.1', self.port), timeout=.1):
                    self.ready_ms = (time.perf_counter() - started) * 1000
                    return
            except OSError:
                time.sleep(.02)
        self.close()
        raise RuntimeError('mihomo 启动超时')

    def _read(self):
        for line in self.process.stdout:
            self.log.write(line)
            self.log.flush()
            match = re.search(r' using (HIT|MISS|EARLY|AFTER)\[', line)
            if match:
                self.lines.put(match.group(1))

    def request(self, target):
        authority = f'[{target}]:443' if ':' in target else target + ':443'
        started = time.perf_counter()
        with socket.create_connection(('127.0.0.1', self.port), timeout=10) as conn:
            conn.sendall(f'CONNECT {authority} HTTP/1.1\r\nHost: {authority}\r\n\r\n'.encode())
            conn.recv(1024)
            result = self.lines.get(timeout=15)
        return result, (time.perf_counter() - started) * 1000

    def metrics(self):
        output = subprocess.run(['ps', '-p', str(self.process.pid), '-o', 'rss=', '-o', 'time='],
                                capture_output=True, text=True, check=True).stdout.split()
        rss, cpu = output
        day, separator, clock = cpu.partition('-')
        days = int(day) if separator else 0
        seconds = 0
        clock = clock if separator else day
        for value in clock.split(':'):
            seconds = seconds * 60 + float(value)
        seconds += days * 86400
        resolution = 10 ** -len(clock.partition('.')[2]) if '.' in clock else 1
        return {'rss_kib': int(rss), 'cpu_seconds': seconds,
                'cpu_resolution_seconds': resolution}

    def close(self):
        self.process.terminate()
        self.process.wait(timeout=10)
        self.reader.join(timeout=2)
        self.log.close()


def validate(mihomo, clash_dir, rounds=5, batch=30):
    version = subprocess.run([mihomo, '-v'], capture_output=True, text=True, check=True).stdout
    if not re.search(r'Meta v?' + re.escape(MIHOMO_VERSION) + r' ', version):
        raise ValueError(f'需要 mihomo {MIHOMO_VERSION}')
    directory = Path(tempfile.mkdtemp(prefix='rules-native-acceptance-'))
    server = socketserver.ThreadingUDPServer(('127.0.0.1', 0), DNS)
    server.queries = []
    threading.Thread(target=server.serve_forever, daemon=True).start()
    selected = [rule for rule in parse_rules((ROOT / 'surge/Direct.list').read_text()) if rule[0] == 'IP-ASN']
    old = [','.join((typ, value, 'HIT', *options)) for typ, value, options in selected]
    prefix = ['IP-CIDR,223.5.5.5/32,EARLY,no-resolve']
    suffix = ['IP-CIDR,198.51.100.0/24,AFTER,no-resolve', 'MATCH,MISS']
    mrs = Path(clash_dir).resolve() / 'mrs/Direct-asn-ip.mrs'
    # provider paths stay inside the isolated home, matching normal safe-path rules.
    providers = {'compiled': {'type': 'file', 'behavior': 'ipcidr', 'format': 'mrs',
                              'path': './compiled.mrs'}}
    kernels = []
    try:
        for name, rules, entries in [('old', prefix + old + suffix, {}),
                                      ('new', prefix + ['RULE-SET,compiled,HIT'] + suffix, providers)]:
            home = directory / name
            if name == 'new':
                home.mkdir(exist_ok=True)
                shutil.copyfile(mrs, home / 'compiled.mrs')
                # 文件 provider 限制在该隔离 Home 内。
            kernel = Kernel(mihomo, home, rules, entries, server.server_address[1])
            kernels.append(kernel)
        cases = [('223.5.5.5', 'EARLY'), ('223.6.6.6', 'HIT'), ('198.51.100.1', 'AFTER'),
                 ('192.0.2.1', 'MISS'), ('2001:db8::1', 'MISS'), ('::ffff:223.6.6.6', 'HIT'),
                 ('::223.6.6.6', 'HIT'),
                 ('2002:df06:606::', 'HIT'), ('2001:0:df06:606::', 'HIT'),
                 ('selected.test', 'HIT'), ('early.test', 'HIT'), ('after.test', 'AFTER'),
                 ('missing.test', 'MISS')]
        for kernel in kernels:
            for target, expected in cases:
                before = len(server.queries)
                result, _ = kernel.request(target)
                if result != expected:
                    raise ValueError(f'{kernel.home.name}: {target}: {result} != {expected}')
                if target.endswith('.test') and len(server.queries) == before:
                    raise ValueError(f'{target} 未通过受控 DNS 解析')
        # Early no-resolve rule must never initiate DNS on its own.
        for kernel in kernels:
            before = len(server.queries)
            result, _ = kernel.request('223.5.5.5')
            if len(server.queries) != before:
                raise ValueError('前序 no-resolve 纯 IP 命中意外产生 DNS 查询')
            if result != 'EARLY':
                raise ValueError('前序纯 IP 匹配失败')
        resources = {kernel.home.name: {'ready_ms': kernel.ready_ms, 'before': kernel.metrics()}
                     for kernel in kernels}
        benchmark = {}
        for target in ('223.6.6.6', '192.0.2.1'):
            timings = {'old': [], 'new': []}
            for turn in range(rounds):
                for kernel in kernels[::1 if turn % 2 == 0 else -1]:
                    samples = [kernel.request(target)[1] for _ in range(batch)]
                    timings[kernel.home.name].extend(samples)
            benchmark[target] = {name: {'p50_ms': statistics.median(values),
                                       'p95_ms': sorted(values)[int(len(values) * .95)],
                                       'samples': len(values)} for name, values in timings.items()}
        for kernel in kernels:
            measurement = resources[kernel.home.name]
            measurement['after'] = kernel.metrics()
            measurement['benchmark_cpu_seconds'] = (measurement['after']['cpu_seconds']
                                                    - measurement['before']['cpu_seconds'])
        return {'resources': resources,
                'resource_measurement': 'ready_ms为进程启动到端口可连接；RSS为基准前后快照而非峰值；CPU为整个隔离内核累计CPU差，包含日志和后台工作，精度由ps平台输出决定',
                'no_resolve_dns_queries': 0, 'cases_per_kernel': len(cases), 'rounds': rounds, 'benchmark': benchmark,
                'mihomo': version.strip(),
                'database_sha256': hashlib.sha256((ROOT / 'inputs/ASN.mmdb').read_bytes()).hexdigest(),
                'mrs_sha256': hashlib.sha256(mrs.read_bytes()).hexdigest(),
                'measurement': 'localhost HTTP CONNECT 到内核路由日志的端到端耗时，包含 IPC/日志开销',
                'evidence': str(directory)}
    finally:
        for kernel in kernels:
            kernel.close()
        server.shutdown()
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mihomo', default='mihomo')
    parser.add_argument('--clash-dir', type=Path, default=ROOT / 'clash')
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    result = validate(args.mihomo, args.clash_dir)
    if args.report:
        args.report.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
