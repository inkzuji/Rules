"""真实固定数据库下的集合语义、地址别名与锁文件回归。"""
import ipaddress
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

import asn


class ASNTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = Path(tempfile.mkdtemp(prefix='rules-asn-test-'))
        cls.networks = asn.export_networks([45102, 4294967295], asn.DATABASE, cls.directory)

    def test_real_database_aliases_and_missing_asn(self):
        addresses = ['223.5.5.5', '::ffff:223.5.5.5', '::223.5.5.5',
                     '2002:df05:505::', '2001:0:df05:505::']
        answers = asn.lookup_asns(addresses, asn.DATABASE, self.directory)
        networks = [ipaddress.ip_network(value) for value in self.networks]
        for address in addresses:
            with self.subTest(address=address):
                self.assertEqual(answers[address], 45102)
                ip = ipaddress.ip_address(address)
                ip = ip.ipv4_mapped or ip if ip.version == 6 else ip
                self.assertTrue(any(ip.version == net.version and ip in net for net in networks))
        evidence = asn.verify_networks([45102, 4294967295], asn.DATABASE, self.networks, self.directory)
        self.assertIn(4294967295, evidence['missing_asns'])
        self.assertEqual(evidence['sha256'], json.loads(asn.LOCK.read_text())['sha256'])

    def test_full_interval_check_rejects_added_and_removed_coverage(self):
        for candidate in (self.networks[:-1], [*self.networks, '0.0.0.0/0']):
            with self.subTest(added=len(candidate) > len(self.networks)):
                with self.assertRaisesRegex(ValueError, '全区间覆盖不一致'):
                    asn.verify_networks([45102, 4294967295], asn.DATABASE, candidate, self.directory)

    def test_absent_selection_cannot_publish_empty_mrs(self):
        with self.assertRaisesRegex(ValueError, '全部缺失'):
            asn.export_networks([4294967295], asn.DATABASE, self.directory)

    def test_invalid_selection_is_rejected(self):
        for values in ([], [-1], [4294967296]):
            with self.subTest(values=values), self.assertRaises(ValueError):
                asn.export_networks(values, asn.DATABASE, self.directory)

    def test_invalid_download_preserves_committed_input_pair(self):
        source = self.directory / 'invalid.mmdb'
        source.write_bytes(b'not a MaxMind database')
        before = (asn.DATABASE.read_bytes(), asn.LOCK.read_bytes())
        with mock.patch.object(asn, 'SOURCE', source.as_uri()), self.assertRaises(subprocess.CalledProcessError):
            asn.refresh()
        self.assertEqual((asn.DATABASE.read_bytes(), asn.LOCK.read_bytes()), before)

    def test_second_replace_failure_restores_existing_input_pair(self):
        database = self.directory / 'previous.mmdb'
        lock = self.directory / 'previous-lock.json'
        database.write_bytes(b'previous database')
        lock.write_bytes(b'previous lock')
        replace = asn.os.replace
        calls = []

        def fail_second(source, destination):
            calls.append(destination)
            if len(calls) == 2:
                raise OSError('simulated lock replacement failure')
            return replace(source, destination)

        with mock.patch.object(asn, 'SOURCE', asn.DATABASE.as_uri()), \
             mock.patch.object(asn, 'DATABASE', database), mock.patch.object(asn, 'LOCK', lock), \
             mock.patch.object(asn.os, 'replace', side_effect=fail_second), \
             self.assertRaisesRegex(OSError, 'lock replacement failure'):
            asn.refresh()
        self.assertEqual(database.read_bytes(), b'previous database')
        self.assertEqual(lock.read_bytes(), b'previous lock')


if __name__ == '__main__':
    unittest.main()
