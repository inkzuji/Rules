"""构建的分类、覆盖优先级和失败时保留已发布结果。"""
import contextlib
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import build
import validate


class BuildTests(unittest.TestCase):
    def test_domain_label_boundaries(self):
        for domain, expected in [('t.co', 'Proxy/Social'), ('a.t.co', 'Proxy/Social'),
                                 ('not.co', 'Proxy/Others'), ('trust.example', 'Proxy/Others'),
                                 ('rust.example', 'Proxy/Dev'),
                                 ('a.cloudflare.com', 'Proxy/Cloudflare'),
                                 ('a.cloudfront.net', 'Proxy/Others')]:
            with self.subTest(domain=domain):
                self.assertEqual(build.classify('🚀节点选择', ('DOMAIN-SUFFIX', domain, ())), expected)

    def test_specific_source_keeps_ip_with_service(self):
        best = {}
        rule = ('IP-CIDR', '192.0.2.0/24', ('no-resolve',))
        build.merge(best, '🚀节点选择', [rule], 'Proxy/Google')
        artifacts = build.surge_artifacts(best)
        self.assertEqual(len(artifacts), 21)
        self.assertIn(b'IP-CIDR,192.0.2.0/24,no-resolve', artifacts['Proxy/Google.list'])
        self.assertNotIn(b'192.0.2.0', artifacts['Proxy/Others.list'])

    def test_policy_then_current_then_source_order(self):
        best = {}
        old = ('IP-CIDR', '192.0.2.0/24', ())
        current = ('IP-CIDR', '192.0.2.0/24', ('no-resolve',))
        key = old[:2]
        build.merge(best, '🚀节点选择', [old], historical=True)
        build.merge(best, '🚀节点选择', [current], 'Proxy/Google')
        build.merge(best, '🚀节点选择', [old], 'Proxy/Netflix')
        self.assertEqual(best[key][2:], ('Proxy/Google', current))
        build.merge(best, '🤖️AI', [old], historical=True)
        build.merge(best, 'DIRECT', [current])
        self.assertEqual(best[key][1], '🤖️AI')
        self.assertEqual(best[key][3], old)

    def prepare_outputs(self):
        root = Path(tempfile.mkdtemp(prefix='rules-build-test-'))
        surge = root / 'surge'
        clash = root / 'clash'
        surge.mkdir()
        clash.mkdir()
        (surge / 'Direct.list').write_text('# 策略: DIRECT\nDOMAIN,old.example\n', encoding='utf-8')
        (clash / 'Direct.list').write_text('old clash output', encoding='utf-8')
        count = root / '.last_count'
        count.write_text('1', encoding='utf-8')
        return root, surge, clash, count

    def test_history_keeps_service_when_removed_upstream_across_builds(self):
        root = Path(tempfile.mkdtemp(prefix='rules-history-test-'))
        path = root / 'Proxy' / 'Google.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🚀节点选择\nIP-CIDR,192.0.2.0/24,no-resolve\n'
                        'DOMAIN,service.cdn.example\n', encoding='utf-8')
        for _ in range(3):
            with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.google.example\n'):
                best, _ = build.collect(root, [('fake', '🚀节点选择', 'Proxy/Google')])
            artifacts = build.surge_artifacts(best)
            self.assertIn(b'IP-CIDR,192.0.2.0/24,no-resolve', artifacts['Proxy/Google.list'])
            self.assertIn(b'DOMAIN,service.cdn.example', artifacts['Proxy/Google.list'])
            self.assertNotIn(b'192.0.2.0', artifacts['Proxy/Others.list'])
            self.assertNotIn(b'service.cdn.example', artifacts['Proxy/Others.list'])
            build.convert_clash.publish(artifacts, root)

    def test_aggregate_updates_parameters_without_losing_historical_service(self):
        root = Path(tempfile.mkdtemp(prefix='rules-history-test-'))
        path = root / 'Proxy' / 'Google.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🚀节点选择\nIP-CIDR,192.0.2.0/24\n'
                        'DOMAIN,service.cdn.example\n', encoding='utf-8')
        for _ in range(3):
            with mock.patch.object(build, 'fetch', return_value='IP-CIDR,192.0.2.0/24,no-resolve\n'
                                   'DOMAIN,service.cdn.example\n'):
                best, _ = build.collect(root, [('fake', '🚀节点选择', None)])
            artifacts = build.surge_artifacts(best)
            self.assertIn(b'IP-CIDR,192.0.2.0/24,no-resolve', artifacts['Proxy/Google.list'])
            self.assertIn(b'DOMAIN,service.cdn.example', artifacts['Proxy/Google.list'])
            self.assertNotIn(b'192.0.2.0', artifacts['Proxy/Others.list'])
            build.convert_clash.publish(artifacts, root)

    def test_specific_source_corrects_history_but_policy_priority_still_wins(self):
        root = Path(tempfile.mkdtemp(prefix='rules-history-test-'))
        path = root / 'Proxy' / 'Google.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🚀节点选择\nIP-CIDR,192.0.2.0/24\n', encoding='utf-8')
        with mock.patch.object(build, 'fetch', return_value='IP-CIDR,192.0.2.0/24,no-resolve\n'):
            best, _ = build.collect(root, [('specific', '🚀节点选择', 'Proxy/Netflix'),
                                           ('aggregate', '🚀节点选择', None)])
        self.assertEqual(best[('IP-CIDR', '192.0.2.0/24')][2], 'Proxy/Netflix')
        with mock.patch.object(build, 'fetch', return_value='IP-CIDR,192.0.2.0/24,no-resolve\n'):
            best, _ = build.collect(root, [('lower', 'DIRECT', 'Direct')])
        self.assertEqual(best[('IP-CIDR', '192.0.2.0/24')][1:3], ('🚀节点选择', 'Proxy/Google'))

    def test_unknown_or_incompatible_historical_theme_is_rejected_before_fetch(self):
        for filename, policy, error in [('Unexpected.list', 'DIRECT', '未知历史主题'),
                                         ('Apple.list', 'DIRECT', '不兼容')]:
            with self.subTest(filename=filename):
                root = Path(tempfile.mkdtemp(prefix='rules-history-test-'))
                (root / filename).write_text(f'# 策略: {policy}\nDOMAIN,old.example\n', encoding='utf-8')
                with mock.patch.object(build, 'fetch') as fetch, self.assertRaisesRegex(ValueError, error):
                    build.collect(root, [('fake', 'DIRECT', 'Direct')])
                fetch.assert_not_called()

    def snapshot(self, root):
        return {str(path.relative_to(root)): path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def test_source_failure_and_empty_response_do_not_publish(self):
        for response in [OSError('offline'), '# empty source\n', 'UNKNOWN,new.example\n']:
            with self.subTest(response=response):
                root, surge, clash, count = self.prepare_outputs()
                before = self.snapshot(root)
                kwargs = {'side_effect': response} if isinstance(response, Exception) else {'return_value': response}
                with mock.patch.object(build, 'fetch', **kwargs), self.assertRaises(RuntimeError):
                    build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
                self.assertEqual(self.snapshot(root), before)

    def test_fetch_retries_timeout_but_not_missing_source(self):
        response = mock.MagicMock()
        response.__enter__.return_value.read.return_value = b'DOMAIN,new.example\n'
        with mock.patch.object(build.urllib.request, 'urlopen', side_effect=[TimeoutError(), response]) as fetch, \
             mock.patch.object(build.time, 'sleep'):
            self.assertEqual(build.fetch('https://rules.example/list'), 'DOMAIN,new.example\n')
        self.assertEqual(fetch.call_count, 2)
        missing = build.urllib.error.HTTPError('https://rules.example/list', 404, 'missing', {}, None)
        with mock.patch.object(build.urllib.request, 'urlopen', side_effect=missing) as fetch, \
             self.assertRaises(build.urllib.error.HTTPError):
            build.fetch('https://rules.example/list')
        self.assertEqual(fetch.call_count, 1)

    def test_conversion_failure_does_not_publish_or_count(self):
        root, surge, clash, count = self.prepare_outputs()
        before = self.snapshot(root)
        with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
             mock.patch.object(build.convert_clash, 'publish', create=True) as publish, \
             mock.patch.object(build.convert_clash, 'generate', side_effect=RuntimeError('bad mrs'), create=True), \
             self.assertRaisesRegex(RuntimeError, 'bad mrs'):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        self.assertEqual(publish.call_count, 1)
        self.assertNotIn(str(root), str(publish.call_args.args[1]))
        self.assertEqual(self.snapshot(root), before)

    def test_stale_file_prevents_either_tree_being_published(self):
        root, surge, clash, count = self.prepare_outputs()
        (clash / 'obsolete.mrs').write_bytes(b'old')
        before = self.snapshot(root)
        with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
             mock.patch.object(build.convert_clash, 'publish', create=True) as publish, \
             mock.patch.object(build.convert_clash, 'generate', return_value={'Direct.list': b'new'}, create=True), \
             self.assertRaisesRegex(ValueError, 'obsolete.mrs'):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        self.assertEqual(publish.call_count, 1)
        self.assertEqual(self.snapshot(root), before)

    def test_dns_report_preserves_rules(self):
        root, surge, _, _ = self.prepare_outputs()
        before = self.snapshot(root)
        with mock.patch('sys.argv', ['validate.py', '--rules-dir', str(surge)]), \
             mock.patch.object(validate, 'check', return_value='dead'), \
             contextlib.redirect_stdout(io.StringIO()) as output:
            validate.main()
        self.assertIn('old.example', output.getvalue())
        self.assertEqual(self.snapshot(root), before)

    def test_output_path_conflict_preserves_both_trees_and_count(self):
        for tree in ('surge', 'clash'):
            for parent_conflict in (False, True):
                with self.subTest(tree=tree, parent_conflict=parent_conflict):
                    root, surge, clash, count = self.prepare_outputs()
                    target = root / tree / 'AI'
                    if parent_conflict:
                        target.write_bytes(b'user file')
                    else:
                        (target / 'OpenAI.list').mkdir(parents=True)
                    before = self.snapshot(root)
                    # Surge 源文件被目录占用时，读取历史阶段就应中止。
                    error = IsADirectoryError if tree == 'surge' and not parent_conflict else ValueError
                    with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
                         mock.patch.object(build.convert_clash, 'generate', return_value={
                             'Direct.list': b'new', 'AI/OpenAI.list': b'new ai'}), \
                         self.assertRaises(error):
                        build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
                    self.assertEqual(self.snapshot(root), before)
                    self.assertTrue(target.is_file() if parent_conflict else (target / 'OpenAI.list').is_dir())

    def test_trash_failure_preserves_both_trees_and_count(self):
        root, surge, clash, count = self.prepare_outputs()
        stale = clash / 'mrs/Direct-ip.mrs'
        stale.parent.mkdir()
        stale.write_bytes(b'old')
        before = self.snapshot(root)
        with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
             mock.patch.object(build.convert_clash, 'generate', return_value={'Direct.list': b'new'}), \
             mock.patch.object(build.convert_clash.sys, 'platform', 'darwin'), \
             mock.patch.dict(build.os.environ, {'GITHUB_ACTIONS': 'false'}), \
             mock.patch.object(Path, 'home', return_value=root / 'missing-home'), \
             self.assertRaisesRegex(ValueError, '废纸篓不可用'):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        self.assertEqual(self.snapshot(root), before)

    def test_actions_delete_failure_restores_files_and_preserves_trees_and_count(self):
        root, surge, clash, count = self.prepare_outputs()
        (clash / 'mrs').mkdir()
        for name in ('AI', 'Apple'):
            (clash / f'mrs/{name}-ip.mrs').write_bytes(name.encode())
        before = self.snapshot(root)
        retained = Path(tempfile.mkdtemp(prefix='rules-actions-deleted-fixture-'))
        calls = []

        def fail_second(path):
            calls.append(path)
            if len(calls) == 2:
                raise OSError('simulated delete failure')
            path.rename(retained / path.name)

        with mock.patch.dict(build.os.environ, {'GITHUB_ACTIONS': 'true'}), \
             mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
             mock.patch.object(build.convert_clash, 'generate', return_value={'Direct.list': b'new'}), \
             mock.patch.object(Path, 'unlink', autospec=True, side_effect=fail_second), \
             mock.patch.object(build.convert_clash, 'trash_file') as trash, \
             self.assertRaisesRegex(OSError, 'simulated delete failure'):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        self.assertEqual(len(calls), 2)
        trash.assert_not_called()
        self.assertEqual(self.snapshot(root), before)

    def test_surge_does_not_retire_clash_named_files(self):
        root, surge, clash, count = self.prepare_outputs()
        (surge / 'mrs').mkdir()
        (surge / 'mrs/AI.mrs').write_bytes(b'user file')
        before = self.snapshot(root)
        with mock.patch.object(build, 'fetch', return_value='DOMAIN,new.example\n'), \
             mock.patch.object(build.convert_clash, 'generate', return_value={'Direct.list': b'new'}), \
             self.assertRaisesRegex(ValueError, 'mrs/AI.mrs'):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        self.assertEqual(self.snapshot(root), before)

    def test_native_repeated_build_retires_ip_mrs_after_resolving_rule(self):
        root, surge, clash, count = self.prepare_outputs()
        first = 'DOMAIN,new.example\nIP-CIDR,192.0.2.0/24,no-resolve\n'
        with mock.patch.object(build, 'fetch', return_value=first), \
             contextlib.redirect_stdout(io.StringIO()):
            build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
        stale = clash / 'mrs/Direct-ip.mrs'
        self.assertTrue(stale.exists())
        original = stale.read_bytes()
        with mock.patch.object(build, 'fetch', return_value=first + 'IP-ASN,64512\n'), \
             mock.patch.object(build.convert_clash.sys, 'platform', 'linux'), \
             mock.patch.dict(build.os.environ, {'XDG_DATA_HOME': str(root / 'data'), 'GITHUB_ACTIONS': 'false'}), \
             contextlib.redirect_stdout(io.StringIO()):
            for _ in range(2):
                build.build(surge, clash, count, source_list=[('fake', 'DIRECT', 'Direct')])
            build.convert_clash.publish(build.convert_clash.generate(surge), clash, check=True)
        self.assertFalse(stale.exists())
        extra = (clash / 'mrs/Direct-extra.list').read_text()
        self.assertIn('IP-ASN,64512', extra)
        self.assertIn('IP-CIDR,192.0.2.0/24,no-resolve', extra)
        trashed = list((root / 'data/Trash/files').iterdir())
        self.assertEqual(len(trashed), 1)
        self.assertEqual(trashed[0].read_bytes(), original)


if __name__ == '__main__':
    unittest.main()
