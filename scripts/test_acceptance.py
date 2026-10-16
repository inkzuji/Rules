"""分类契约夹具与破坏性回归；临时目录保留，不递归删除。"""
from pathlib import Path
import shutil
import tempfile
import unittest

import acceptance
from convert_clash import compile_mrs, render_config
from rules import render_rules


@unittest.skipUnless(shutil.which('mihomo'), '缺少官方 mihomo，无法执行真实 MRS 反解回归')
class AcceptanceTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix='rules-acceptance-test-'))
        self.surge = self.root / 'surge'
        self.clash = self.root / 'clash'
        self.mihomo = shutil.which('mihomo')
        self.sources = {
            'AI/Gemini': (acceptance.AI, [('DOMAIN', domain, ()) for domain in
                                         ('gemini.google.com', 'aistudio.google.com',
                                          'generativelanguage.googleapis.com', 'antigravity.google', 'ai.studio')]),
            'AI/Copilot': (acceptance.AI, [('DOMAIN-SUFFIX', 'githubcopilot.com', ()),
                                         ('DOMAIN-SUFFIX', 'copilot-stg.com', ())]),
            'AI/Claude': (acceptance.AI, [('DOMAIN-SUFFIX', 'claude.ai', ())]),
            'AI/OpenAI': (acceptance.AI, [('DOMAIN-SUFFIX', 'production-openaicom-storage.azureedge.net', ())]),
            'AI/Others': (acceptance.AI, [('DOMAIN-SUFFIX', domain, ()) for domain in
                                         ('cursor.com', 'perplexity.ai', 'huggingface.co', 'x.ai', 'grok.com',
                                          'midjourney.com', 'suno.com', 'poe.com', 'windsurf.com', 'ollama.com',
                                          'ppl-ai-file-upload.s3.amazonaws.com')]),
            'Proxy/YouTube': (acceptance.PROXY, [('DOMAIN', 'youtubei.googleapis.com', ())]),
            'Proxy/Google': (acceptance.PROXY, [('DOMAIN-SUFFIX', 'google.com', ()),
                                               ('DOMAIN-SUFFIX', 'googleapis.com', ())]),
            'Proxy/GitHub': (acceptance.PROXY, [('DOMAIN-SUFFIX', 'github.com', ())]),
            'Proxy/Microsoft': (acceptance.PROXY, [('DOMAIN-SUFFIX', 'bing.com', ())]),
        }
        self.text_entries = []
        groups = {acceptance.AI: [], acceptance.PROXY: []}
        for theme, (policy, rules) in self.sources.items():
            relative = theme + '.list'
            for directory in (self.surge, self.clash):
                path = directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_rules(policy, rules), encoding='utf-8')
            self.text_entries.append((theme.replace('/', '-'), relative, policy, 'classical', 'text', False))
            groups[policy].extend(('+.' if typ == 'DOMAIN-SUFFIX' else '') + value
                                  for typ, value, _ in rules)
        (self.clash / 'classical.yaml').write_text(render_config(self.text_entries), encoding='utf-8')
        self.mrs_entries = []
        (self.clash / 'mrs').mkdir()
        for policy, name in ((acceptance.AI, 'AI'), (acceptance.PROXY, 'Proxy')):
            relative = f'mrs/{name}.mrs'
            # 真实官方内核编译，与生产的反解结果比对；不伪造二进制格式。
            binary = compile_mrs(groups[policy], 'domain', self.root / f'{name}.mrs', self.mihomo)
            (self.clash / relative).write_bytes(binary)
            self.mrs_entries.append((name, relative, policy, 'domain', 'mrs', False))
        (self.clash / 'mrs.yaml').write_text(render_config(self.mrs_entries), encoding='utf-8')

    def domain_values(self, selected_policy):
        return [('+.' if typ == 'DOMAIN-SUFFIX' else '') + value
                for policy, rules in self.sources.values() if policy == selected_policy
                for typ, value, _ in rules]

    def validate(self):
        return acceptance.validate_artifacts(self.surge, self.clash, self.mihomo)

    def test_valid_independent_service_contract_and_shared_ip(self):
        result = self.validate()
        self.assertEqual(result['scenarios'], len(acceptance.SERVICE_CASES) * 3 + 8)
        self.assertTrue(Path(result['evidence']).is_dir())

    def test_empty_text_policy_needs_no_mrs_provider(self):
        for directory in (self.surge, self.clash):
            (directory / 'Game.list').write_text(render_rules('🎮游戏', []), encoding='utf-8')
        self.text_entries.append(('Game', 'Game.list', '🎮游戏', 'classical', 'text', False))
        (self.clash / 'classical.yaml').write_text(render_config(self.text_entries), encoding='utf-8')
        self.assertEqual(self.validate()['scenarios'], len(acceptance.SERVICE_CASES) * 3 + 8)
        # 空组兼容不能掩盖缺失真实规则：增加一条文本域名仍必须拒绝。
        for directory in (self.surge, self.clash):
            (directory / 'Game.list').write_text(
                render_rules('🎮游戏', [('DOMAIN', 'game.example', ())]), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '全量语义覆盖不一致'):
            self.validate()

    def test_historical_ai_pollution_is_rejected_and_repair_passes(self):
        path = self.surge / 'AI/Gemini.list'
        original = path.read_text(encoding='utf-8')
        path.write_text(original + 'DOMAIN-SUFFIX,google.com\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '文本转换契约不一致'):
            self.validate()
        path.write_text(original, encoding='utf-8')
        self.assertEqual(self.validate()['scenarios'], len(acceptance.SERVICE_CASES) * 3 + 8)

    def test_matching_pollution_in_all_formats_still_fails_business_contract(self):
        # 同源三端一起被污染时，集合相等仍不能替代独立服务预期。
        for directory in (self.surge, self.clash):
            path = directory / 'AI/Gemini.list'
            path.write_text(path.read_text(encoding='utf-8') + 'DOMAIN-SUFFIX,google.com\n', encoding='utf-8')
        ai_domains = self.domain_values(acceptance.AI) + ['+.google.com']
        binary = compile_mrs(ai_domains, 'domain', self.root / 'polluted.mrs', self.mihomo)
        (self.clash / 'mrs/AI.mrs').write_bytes(binary)
        with self.assertRaisesRegex(ValueError, '服务归属验收失败'):
            self.validate()

    def test_real_ai_service_moved_to_proxy_in_all_formats_is_rejected(self):
        # 三端数据一致并不代表归属正确；此场景模拟聚合源把真实 AI 服务放到 Proxy。
        ai_policy, ai_rules = self.sources['AI/Others']
        cursor_rule = ('DOMAIN-SUFFIX', 'cursor.com', ())
        self.sources['AI/Others'] = (ai_policy, [rule for rule in ai_rules if rule != cursor_rule])
        self.sources['Proxy/Others'] = (acceptance.PROXY, [cursor_rule])
        for theme in ('AI/Others', 'Proxy/Others'):
            policy, rules = self.sources[theme]
            for directory in (self.surge, self.clash):
                (directory / (theme + '.list')).write_text(render_rules(policy, rules), encoding='utf-8')
        self.text_entries.append(('Proxy-Others', 'Proxy/Others.list', acceptance.PROXY, 'classical', 'text', False))
        (self.clash / 'classical.yaml').write_text(render_config(self.text_entries), encoding='utf-8')
        for policy, name in ((acceptance.AI, 'AI'), (acceptance.PROXY, 'Proxy')):
            binary = compile_mrs(self.domain_values(policy), 'domain', self.root / f'reversed-{name}.mrs', self.mihomo)
            (self.clash / f'mrs/{name}.mrs').write_bytes(binary)
        with self.assertRaisesRegex(ValueError, '服务归属验收失败.*cursor.com'):
            self.validate()

    def test_mrs_semantic_difference_is_detected(self):
        binary = compile_mrs(['unexpected.example'], 'domain', self.root / 'wrong.mrs', self.mihomo)
        (self.clash / 'mrs/AI.mrs').write_bytes(binary)
        with self.assertRaisesRegex(ValueError, '全量语义覆盖不一致'):
            self.validate()

    def test_shared_ip_matching_ai_cidr_cannot_override_google_host(self):
        # IP 同时真实存在于三端 AI 规则，错误引用顺序必须被独立业务预期抓出。
        for directory in (self.surge, self.clash):
            path = directory / 'AI/Gemini.list'
            path.write_text(path.read_text(encoding='utf-8') + 'IP-CIDR,192.0.2.0/24,no-resolve\n', encoding='utf-8')
        binary = compile_mrs(['192.0.2.0/24'], 'ipcidr', self.root / 'AI-ip.mrs', self.mihomo)
        (self.clash / 'mrs/AI-ip.mrs').write_bytes(binary)
        self.mrs_entries.insert(1, ('AI-ip', 'mrs/AI-ip.mrs', acceptance.AI, 'ipcidr', 'mrs', True))
        (self.clash / 'mrs.yaml').write_text(render_config(self.mrs_entries), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'google.com.*192.0.2.222'):
            self.validate()

    def test_mrs_reference_order_cannot_hide_google_specific_ai(self):
        (self.clash / 'mrs.yaml').write_text(render_config(list(reversed(self.mrs_entries))), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'gemini.google.com'):
            self.validate()

    def test_classical_reference_order_is_used_for_first_match(self):
        entries = sorted(self.text_entries, key=lambda entry: entry[0] != 'Proxy-Google')
        (self.clash / 'classical.yaml').write_text(render_config(entries), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'gemini.google.com'):
            self.validate()

    def test_surge_reference_order_is_read_from_real_rules_conf(self):
        entries = sorted(self.text_entries, key=lambda entry: entry[0] != 'Proxy-Google')
        (self.surge / 'rules.conf').write_text(''.join(
            f'RULE-SET,https://example.test/main/surge/{relative},{policy}\n'
            for _, relative, policy, *_ in entries) + f'FINAL,{acceptance.FINAL}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'gemini.google.com'):
            self.validate()

    def test_production_surge_config_is_required_when_requested(self):
        with self.assertRaisesRegex(ValueError, '缺少 Surge 实际引用配置'):
            acceptance.validate_artifacts(self.surge, self.clash, self.mihomo, require_surge_config=True)

    def test_surge_final_must_be_last_and_use_expected_policy(self):
        lines = ''.join(f'RULE-SET,https://example.test/main/surge/{relative},{policy}\n'
                        for _, relative, policy, *_ in self.text_entries)
        path = self.surge / 'rules.conf'
        for final in ('', 'FINAL,DIRECT\n'):
            with self.subTest(final=final):
                path.write_text(lines + final, encoding='utf-8')
                with self.assertRaisesRegex(ValueError, '末尾 FINAL'):
                    self.validate()
        path.write_text(f'FINAL,{acceptance.FINAL}\n' + lines + f'FINAL,{acceptance.FINAL}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '非法 Surge 引用'):
            self.validate()
        path.write_text(lines + f'FINAL,{acceptance.FINAL}\n', encoding='utf-8')
        self.assertEqual(self.validate()['scenarios'], len(acceptance.SERVICE_CASES) * 3 + 8)

    def test_google_suffix_requires_label_boundary(self):
        self.assertFalse(acceptance.matches(('DOMAIN-SUFFIX', 'google.com', ()),
                                            acceptance.Request('notgoogle.com')))
        self.assertTrue(acceptance.matches(('DOMAIN-SUFFIX', 'google.com', ()),
                                           acceptance.Request('www.google.com')))

    def test_ip_and_process_matchers_have_explicit_scope(self):
        self.assertTrue(acceptance.matches(('IP-CIDR6', '2001:db8::/32', ('no-resolve',)),
                                           acceptance.Request(ip='2001:db8::1')))
        self.assertFalse(acceptance.matches(('IP-CIDR', '192.0.2.0/24', ('no-resolve',)),
                                            acceptance.Request(ip='198.51.100.1')))
        rule = ('PROCESS-NAME', 'MicrosoftEdge', ())
        self.assertTrue(acceptance.matches(rule, acceptance.Request(process='MicrosoftEdge')))
        self.assertFalse(acceptance.matches(rule, acceptance.Request(process='microsoftedge')))
        self.assertTrue(acceptance.matches(rule, acceptance.Request(process='microsoftedge'), clash=True))
        self.assertFalse(acceptance.matches(('GEOIP', 'US', ()), acceptance.Request(ip='192.0.2.1')))

    def test_wide_browser_process_in_all_formats_is_rejected(self):
        for directory in (self.surge, self.clash):
            path = directory / 'AI/Gemini.list'
            path.write_text(path.read_text(encoding='utf-8') + 'PROCESS-NAME,MicrosoftEdge\n', encoding='utf-8')
        relative = 'mrs/AI-extra.list'
        (self.clash / relative).write_text(render_rules(acceptance.AI,
                                                       [('PROCESS-NAME', 'MicrosoftEdge', ())]), encoding='utf-8')
        self.mrs_entries.append(('AI-extra', relative, acceptance.AI, 'classical', 'text', False))
        (self.clash / 'mrs.yaml').write_text(render_config(self.mrs_entries), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '普通域名/进程误分类'):
            self.validate()


class CoverageTests(unittest.TestCase):
    def test_empty_groups_are_semantically_absent(self):
        empty = acceptance.Provider('Game', 'Game', '🎮游戏', ())
        self.assertEqual(acceptance.coverage([empty]), acceptance.coverage([]))

    def test_nonempty_groups_and_resolution_options_are_preserved(self):
        rule = ('IP-CIDR', '192.0.2.0/24', ('no-resolve',))
        provider = acceptance.Provider('Game', 'Game', '🎮游戏', (rule,))
        self.assertNotEqual(acceptance.coverage([provider]), acceptance.coverage([]))
        resolving = acceptance.Provider('Game', 'Game', '🎮游戏', (('IP-CIDR', '192.0.2.0/24', ()),))
        self.assertNotEqual(acceptance.coverage([provider]), acceptance.coverage([resolving]))


if __name__ == '__main__':
    unittest.main()
