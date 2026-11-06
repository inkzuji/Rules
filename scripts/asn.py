"""固定 MMDB 快照的 ASN 导出、全区间等价检查与独立地址查询。"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import subprocess
import tempfile
import urllib.request

ROOT = Path(__file__).resolve().parent.parent
DATABASE = ROOT / 'inputs/ASN.mmdb'
LOCK = ROOT / 'inputs/asn-lock.json'
SOURCE = 'https://github.com/xishang0128/geoip/releases/download/latest/GeoLite2-ASN.mmdb'
_exports = {}
_binary = None


def _tool():
    global _binary
    if _binary is None:
        directory = Path(tempfile.mkdtemp(prefix='rules-asn-tool-'))
        _binary = directory / 'asn-export'
        subprocess.run(['go', 'build', '-mod=readonly', '-o', str(_binary), '.'],
                       cwd=ROOT / 'tools/asn-export', check=True, capture_output=True, text=True)
    return _binary


def _export(asns, database, directory):
    values = sorted({int(value) for value in asns})
    if not values or any(value < 0 or value > 4294967295 for value in values):
        raise ValueError('需要非空的 uint32 ASN 集合')
    database = Path(database)
    digest = hashlib.sha256(database.read_bytes()).hexdigest()
    if database.resolve() == DATABASE.resolve():
        lock = json.loads(LOCK.read_text(encoding='utf-8'))
        if digest != lock['sha256']:
            raise ValueError('ASN 快照与锁文件 SHA-256 不一致')
    key = (tuple(values), digest)
    if key not in _exports:
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        selection = directory / 'selected-asns.json'
        selection.write_text(json.dumps(values), encoding='utf-8')
        result = subprocess.run([str(_tool()), '-database', str(database), '-asns', str(selection)],
                                check=True, capture_output=True, text=True)
        exported = json.loads(result.stdout)
        if exported['sha256'] != digest or 'ASN' not in exported['database_type']:
            raise ValueError('数据库类型或 SHA-256 不匹配')
        if not exported['networks']:
            raise ValueError('所选 ASN 在数据库中全部缺失，拒绝空产物')
        _exports[key] = exported
    return _exports[key]


def _canonical(networks):
    parsed = [ipaddress.ip_network(value) for value in networks]
    # mihomo's net.IP.To4 / IPSet normalize IPv4-mapped IPv6 to IPv4.
    normalized = []
    for network in parsed:
        if network.version == 6 and network.prefixlen >= 96 and network.network_address.ipv4_mapped:
            normalized.append(ipaddress.ip_network(f'{network.network_address.ipv4_mapped}/{network.prefixlen-96}'))
        else:
            normalized.append(network)
    return [str(network) for version in (4, 6)
            for network in ipaddress.collapse_addresses(n for n in normalized if n.version == version)]


def export_networks(asns, database, directory):
    """返回所选 ASN 在固定数据库中的完整 IPv4/IPv6 地址并集。"""
    return _canonical(_export(asns, database, directory)['networks'])


def verify_networks(asns, database, networks, directory):
    """全区间集合比较；既检查遗漏，也拒绝越界覆盖和空洞扩大。"""
    exported = _export(asns, database, directory)
    if _canonical(exported['networks']) != _canonical(networks):
        raise ValueError('ASN 数据库与生成网段的全区间覆盖不一致')
    return {key: value for key, value in exported.items() if key != 'networks'}


def lookup_asns(addresses, database, directory):
    """直接查原数据库，作为路由样本的独立 oracle；不读取生成集合。"""
    addresses = list(dict.fromkeys(addresses))
    for address in addresses:
        ipaddress.ip_address(address)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    queries = directory / 'asn-queries.json'
    queries.write_text(json.dumps(addresses), encoding='utf-8')
    result = subprocess.run([str(_tool()), '-database', str(database), '-queries', str(queries)],
                            check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def refresh():
    """每周任务显式刷新；下载或数据库检查失败不覆盖已锁定输入。"""
    directory = Path(tempfile.mkdtemp(prefix='rules-asn-refresh-'))
    downloaded = directory / 'ASN.mmdb'
    request = urllib.request.Request(SOURCE, headers={'User-Agent': 'rules-builder/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        downloaded.write_bytes(response.read())
    # The exporter opens and fully traverses the real database before publication.
    from rules import parse_rules
    selected = [value for typ, value, _ in parse_rules((ROOT / 'surge/Direct.list').read_text(encoding='utf-8'))
                if typ == 'IP-ASN']
    probe = _export(selected, downloaded, directory)
    lock = {key: probe[key] for key in ('sha256', 'database_type', 'build_epoch')}
    lock.update(source=SOURCE, reader='maxminddb-golang v1.12.0',
                bytes=downloaded.stat().st_size)
    staged_lock = directory / 'asn-lock.json'
    staged_lock.write_text(json.dumps(lock, indent=2) + '\n', encoding='utf-8')
    DATABASE.parent.mkdir(parents=True, exist_ok=True)
    previous_database = DATABASE.read_bytes() if DATABASE.exists() else None
    previous_lock = LOCK.read_bytes() if LOCK.exists() else None
    try:
        os.replace(downloaded, DATABASE)
        os.replace(staged_lock, LOCK)
    except OSError:
        # Restore the existing committed pair when the second replacement fails.
        if previous_database is not None:
            DATABASE.write_bytes(previous_database)
        if previous_lock is not None:
            LOCK.write_bytes(previous_lock)
        raise
    return lock


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--refresh', action='store_true', required=True)
    parser.parse_args()
    print(json.dumps(refresh(), ensure_ascii=False))


if __name__ == '__main__':
    main()
