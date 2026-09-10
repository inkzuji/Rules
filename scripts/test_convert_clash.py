"""验证源规则保真、业务聚合和原生 MRS 覆盖，不访问远程规则源。"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import convert_clash
from rules import POLICIES, parse_rules, read_policy, render_rules


class RuleTests(unittest.TestCase):
    def test_values_and_quoted_commas_are_preserved(self):
        text = '''# source
DOMAIN,WWW.Example.COM
PROCESS-NAME,ChatGPTHelper
USER-AGENT,Bilibili*
URL-REGEX,"^https://Example.com/[A-Z]{1,3}$"
IP-CIDR,192.0.2.7/24,no-resolve
'''
        expected = [('DOMAIN', 'www.example.com', ()),
                    ('PROCESS-NAME', 'ChatGPTHelper', ()),
                    ('USER-AGENT', 'Bilibili*', ()),
                    ('URL-REGEX', '^https://Example.com/[A-Z]{1,3}$', ()),
                    ('IP-CIDR', '192.0.2.0/24', ('no-resolve',))]
        self.assertEqual(parse_rules(text), expected)
        self.assertEqual(set(parse_rules(render_rules('DIRECT', expected))), set(expected))

    def test_invalid_input_has_source_and_line(self):
        for value in ['UNKNOWN,x', 'IP-CIDR,invalid', 'DOMAIN,', 'DOMAIN,a.example,PROXY',
                      'IP-CIDR,192.0.2.0/24,no-resolve,no-resolve',
                      'PROCESS-NAME,app,unknown', 'DOMAIN,*.example.com']:
            with self.subTest(value=value), self.assertRaisesRegex(ValueError, 'source.list:2:'):
                parse_rules('# header\n' + value, 'source.list')
        with self.assertRaises(ValueError):
            read_policy('# 策略: unknown\n')

    def test_process_modes_and_surge_only_rules(self):
        for value, typ, converted in [('ChatGPT', 'PROCESS-NAME', 'ChatGPT'),
                                      ('Google*', 'PROCESS-NAME-WILDCARD', 'Google*'),
                                      ('/usr/bin/ssh', 'PROCESS-PATH', '/usr/bin/ssh'),
                                      ('/Applications/*.app/Contents/MacOS/*', 'PROCESS-PATH-WILDCARD', '/Applications/*.app/Contents/MacOS/*'),
                                      ('/Applications/ChatGPT.app/', 'PROCESS-PATH-WILDCARD', '/Applications/ChatGPT.app/*')]:
            with self.subTest(value=value):
                self.assertEqual(convert_clash.to_clash(('PROCESS-NAME', value, ())), (typ, converted, ()))
        self.assertIsNone(convert_clash.to_clash(('USER-AGENT', 'Bilibili*', ())))
        self.assertIsNone(convert_clash.to_clash(('URL-REGEX', '.*', ())))
        with self.assertRaisesRegex(ValueError, 'extended-matching'):
            convert_clash.to_clash(('DOMAIN', 'example.com', ('extended-matching',)))

    def test_kernel_warning_is_a_failure(self):
        result = mock.Mock(returncode=0, stdout='level=warning msg="invalid domain"', stderr='')
        with mock.patch('convert_clash.subprocess.run', return_value=result), self.assertRaises(RuntimeError):
            convert_clash.run_mihomo('mihomo', 'convert-ruleset')


class ArtifactTests(unittest.TestCase):
    def test_generate_accepts_pinned_version_with_optional_v_prefix(self):
        source = Path(tempfile.mkdtemp(prefix='rules-version-test-'))
        for version in ('Mihomo Meta v1.19.30 linux amd64 with go1.26.0\n',
                        'Mihomo Meta 1.19.30 darwin amd64 with go1.26.0\n'):
            with self.subTest(version=version), \
                 mock.patch('convert_clash.shutil.which', return_value='/mock/mihomo'), \
                 mock.patch('convert_clash.run_mihomo', return_value=version) as run, \
                 self.assertRaisesRegex(ValueError, '缺少 Surge 源规则'):
                convert_clash.generate(source)
            run.assert_called_once_with('/mock/mihomo', '-v')

    def test_generate_rejects_other_versions_and_version_suffixes(self):
        source = Path(tempfile.mkdtemp(prefix='rules-version-test-'))
        for version in ('1.19.29', '1.19.300', '1.19.30-rc.1'):
            for prefix in ('', 'v'):
                with self.subTest(version=version, prefix=prefix), \
                     mock.patch('convert_clash.shutil.which', return_value='/mock/mihomo'), \
                     mock.patch('convert_clash.run_mihomo', return_value=f'Mihomo Meta {prefix}{version} linux amd64\n') as run, \
                     self.assertRaisesRegex(ValueError, r'构建需要 mihomo 1\.19\.30'):
                    convert_clash.generate(source)
                run.assert_called_once_with('/mock/mihomo', '-v')

    def test_retirement_failure_restores_previously_moved_files(self):
        root = Path(tempfile.mkdtemp(prefix='rules-retire-failure-'))
        output = root / 'clash'
        (output / 'mrs').mkdir(parents=True)
        for name in ('AI', 'Apple'):
            (output / f'mrs/{name}-ip.mrs').write_bytes(name.encode())
        original = convert_clash.trash_file
        calls = []

        def fail_second(path):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('simulated move failure')
            return original(path)

        with mock.patch.object(convert_clash.sys, 'platform', 'linux'), \
             mock.patch.dict(convert_clash.os.environ, {'XDG_DATA_HOME': str(root / 'data')}), \
             mock.patch.object(convert_clash, 'trash_file', side_effect=fail_second), \
             self.assertRaisesRegex(OSError, 'simulated move failure'):
            convert_clash.publish({'mrs.yaml': b'new'}, output)
        for name in ('AI', 'Apple'):
            self.assertEqual((output / f'mrs/{name}-ip.mrs').read_bytes(), name.encode())
        self.assertFalse((output / 'mrs.yaml').exists())

    def test_managed_stale_check_is_readonly_and_linux_trash_is_recoverable(self):
        root = Path(tempfile.mkdtemp(prefix='rules-trash-test-'))
        output = root / '含 空格'
        stale = output / 'mrs/Direct-ip.mrs'
        stale.parent.mkdir(parents=True)
        stale.write_bytes(b'old mrs')
        artifacts = {'mrs/Direct-extra.list': b'IP-ASN,64512\n'}
        with mock.patch.object(convert_clash.sys, 'platform', 'linux'), \
             mock.patch.dict(convert_clash.os.environ, {'XDG_DATA_HOME': str(root / 'data')}):
            with self.assertRaisesRegex(ValueError, 'Direct-ip.mrs'):
                convert_clash.publish(artifacts, output, check=True)
            self.assertTrue(stale.exists())
            self.assertFalse((root / 'data').exists())
            convert_clash.publish(artifacts, output)
            convert_clash.publish(artifacts, output, check=True)
        self.assertFalse(stale.exists())
        files = list((root / 'data/Trash/files').iterdir())
        self.assertEqual(len(files), 1)
        self.assertEqual(files[0].read_bytes(), b'old mrs')
        info = (root / 'data/Trash/info' / (files[0].name + '.trashinfo')).read_text()
        self.assertIn('Path=' + convert_clash.urllib.parse.quote(str(stale), safe='/'), info)
        self.assertRegex(info, r'DeletionDate=\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}')

    def test_check_missing_changed_and_stale_files_without_writing(self):
        path = Path(tempfile.mkdtemp(prefix='rules-check-test-'))
        artifacts = {'AI.mrs': b'compiled', 'mrs.yaml': b'rules: []\n'}
        with self.assertRaises(ValueError):
            convert_clash.publish(artifacts, path, check=True)
        self.assertEqual(list(path.iterdir()), [])
        convert_clash.publish(artifacts, path)
        convert_clash.publish(artifacts, path, check=True)
        (path / 'AI.mrs').write_bytes(b'corrupt')
        with self.assertRaisesRegex(ValueError, 'AI.mrs'):
            convert_clash.publish(artifacts, path, check=True)
        self.assertEqual((path / 'AI.mrs').read_bytes(), b'corrupt')
        (path / 'old.mrs').write_bytes(b'stale')
        with self.assertRaisesRegex(ValueError, 'old.mrs'):
            convert_clash.publish(artifacts, path)
        self.assertEqual((path / 'AI.mrs').read_bytes(), b'corrupt')
        self.assertEqual((path / 'old.mrs').read_bytes(), b'stale')

    def test_native_business_mrs_and_dns_order(self):
        root = Path(tempfile.mkdtemp(prefix='rules-native-test-'))
        source = root / 'surge'
        source.mkdir()
        for policy, name in POLICIES.items():
            text = f'# 策略: {policy}\nDOMAIN-SUFFIX,{name.lower()}.example\n'
            if name == 'AI':
                (source / 'AI').mkdir()
                (source / 'AI' / 'OpenAI.list').write_text(text + 'DOMAIN-KEYWORD,openai\n', encoding='utf-8')
                (source / 'AI' / 'Claude.list').write_text(f'# 策略: {policy}\nDOMAIN,claude.example\nIP-CIDR,192.0.2.0/24,no-resolve\n', encoding='utf-8')
            else:
                if name == 'Apple':
                    text += 'IP-CIDR6,2001:db8::/32,no-resolve\nIP-CIDR6,::ffff:192.0.2.1/128,no-resolve\n'
                if name == 'Direct':
                    # ASN 先解析，再用 CIDR 匹配解析后的地址，不能反过来执行。
                    text += 'IP-ASN,64512\nIP-CIDR,198.51.100.0/24,no-resolve\n'
                (source / f'{name}.list').write_text(text, encoding='utf-8')
        before = {p: p.read_bytes() for p in source.rglob('*.list')}
        with contextlib.redirect_stdout(io.StringIO()):
            artifacts = convert_clash.generate(source)
        self.assertEqual({p: p.read_bytes() for p in source.rglob('*.list')}, before)
        for name in POLICIES.values():
            self.assertIn(f'mrs/{name}.mrs', artifacts)
        self.assertNotIn('mrs/OpenAI.mrs', artifacts)
        self.assertNotIn('mrs/Claude.mrs', artifacts)
        self.assertNotIn('mrs/Direct-ip.mrs', artifacts)
        extra = artifacts['mrs/Direct-extra.list'].decode()
        self.assertLess(extra.index('IP-ASN,64512'), extra.index('IP-CIDR,198.51.100.0/24,no-resolve'))
        self.assertIn(b'IP-CIDR6,::ffff:192.0.2.1/128,no-resolve', artifacts['mrs/Apple-extra.list'])
        self.assertIn(b'DOMAIN-KEYWORD,openai', artifacts['mrs/AI-extra.list'])
        config = artifacts['mrs.yaml'].decode()
        self.assertNotIn('geox-url', config)
        self.assertNotIn('Syntax-Only-Empty', config)
        self.assertIn('RULE-SET,AI-ip,🤖️AI,no-resolve', config)
        self.assertNotIn('RULE-SET,https://', config)
        previous = -1
        for name in POLICIES.values():
            position = config.index(f'RULE-SET,{name},')
            self.assertGreater(position, previous)
            previous = position
        ai_path = root / 'AI.mrs'
        ai_path.write_bytes(artifacts['mrs/AI.mrs'])
        decoded = root / 'AI.txt'
        convert_clash.run_mihomo('mihomo', 'convert-ruleset', 'domain', 'mrs', ai_path, decoded)
        self.assertEqual(set(decoded.read_text().splitlines()), {'+.ai.example', 'claude.example'})


if __name__ == '__main__':
    unittest.main()
