"""服务块路由、AI 单文件与独立覆盖验收；临时证据保留。"""
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
        self.surge, self.clash = self.root / 'surge', self.root / 'clash'
        self.mihomo = shutil.which('mihomo')
        self.sources = {}
        for domain, theme, policy in acceptance.SERVICE_CASES:
            theme = 'AI' if theme.startswith('AI/') else theme
            self.sources.setdefault(theme, (policy, []))[1].append(('DOMAIN', domain, ()))
        # 公共父域验证 Gemini 例外和源配置中 Google 先于 YouTube 的真实顺序。
        self.sources['Proxy/Google'][1].extend([('DOMAIN-SUFFIX', 'google.com', ()),
                                               ('DOMAIN-SUFFIX', 'googleapis.com', ())])
        self.text_entries = []
        for theme in acceptance.SERVICE_ORDER:
            if theme not in self.sources:
                continue
            policy, rules = self.sources[theme]
            relative = theme + '.list'
            for directory in (self.surge, self.clash):
                path = directory / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(render_rules(policy, rules), encoding='utf-8')
            self.text_entries.append((theme.replace('/', '-'), relative, policy, 'classical', 'text', False))
        self.mrs_entries = list(self.text_entries)
        (self.clash / 'mrs').mkdir()
        google = self.sources['Proxy/Google'][1]
        values = [('+.' if typ == 'DOMAIN-SUFFIX' else '') + value for typ, value, _ in google]
        binary = compile_mrs(values, 'domain', self.root / 'Google-domain.mrs', self.mihomo)
        (self.clash / 'mrs/Google-domain.mrs').write_bytes(binary)
        self.mrs_entries = [('Google-domain', 'mrs/Google-domain.mrs', acceptance.PROXY, 'domain', 'mrs', False)
                            if entry[0] == 'Proxy-Google' else entry for entry in self.mrs_entries]
        self.write_configs()

    def write_configs(self):
        (self.clash / 'classical.yaml').write_text(render_config(self.text_entries), encoding='utf-8')
        (self.clash / 'mrs.yaml').write_text(render_config(self.mrs_entries), encoding='utf-8')

    def validate(self):
        return acceptance.validate_artifacts(self.surge, self.clash, self.mihomo)

    def append_ai(self, line):
        for directory in (self.surge, self.clash):
            path = directory / 'AI.list'
            path.write_text(path.read_text(encoding='utf-8') + line + '\n', encoding='utf-8')

    def test_valid_single_ai_and_service_mrs(self):
        result = self.validate()
        self.assertGreater(result['scenarios'], len(acceptance.SERVICE_CASES))
        self.assertTrue(Path(result['evidence']).is_dir())
        self.assertFalse(result['asn_compiled'])

    def test_source_only_change_is_rejected(self):
        path = self.surge / 'AI.list'
        path.write_text(path.read_text(encoding='utf-8') + 'DOMAIN-SUFFIX,google.com\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '文本转换契约不一致'):
            self.validate()

    def test_matching_pollution_still_fails_independent_business_contract(self):
        self.append_ai('DOMAIN-SUFFIX,google.com')
        with self.assertRaisesRegex(ValueError, '服务归属验收失败'):
            self.validate()

    def test_mrs_semantic_difference_is_detected(self):
        binary = compile_mrs(['unexpected.example'], 'domain', self.root / 'wrong.mrs', self.mihomo)
        (self.clash / 'mrs/Google-domain.mrs').write_bytes(binary)
        with self.assertRaisesRegex(ValueError, '全量语义覆盖不一致'):
            self.validate()

    def test_ai_whole_group_precedes_google_domain(self):
        self.append_ai('IP-CIDR,192.0.2.0/24,no-resolve')
        self.validate()
        source, target, _ = acceptance.load_text(self.surge, self.clash)
        request = acceptance.Request('google.com', '192.0.2.222')
        self.assertEqual(acceptance.first_match(source, request), ('AI', acceptance.AI))
        self.assertEqual(acceptance.first_match(target, request, True), ('AI', acceptance.AI))

    def test_ai_process_precedes_google_domain(self):
        self.append_ai('PROCESS-NAME,ChatGPT')
        source, target, _ = acceptance.load_text(self.surge, self.clash)
        request = acceptance.Request('google.com', process='ChatGPT')
        self.assertEqual(acceptance.first_match(source, request), ('AI', acceptance.AI))
        self.assertEqual(acceptance.first_match(target, request, True), ('AI', acceptance.AI))

    def test_classical_wrong_reference_order_is_rejected(self):
        self.text_entries.reverse()
        self.write_configs()
        with self.assertRaisesRegex(ValueError, '服务引用顺序'):
            self.validate()

    def test_mrs_wrong_reference_order_is_rejected(self):
        self.mrs_entries.reverse()
        self.write_configs()
        with self.assertRaisesRegex(ValueError, '服务引用顺序'):
            self.validate()

    def test_surge_actual_reference_order_is_checked(self):
        entries = list(reversed(self.text_entries))
        (self.surge / 'rules.conf').write_text(''.join(
            f'RULE-SET,https://example.test/main/surge/{relative},{policy}\n'
            for _, relative, policy, *_ in entries) + f'FINAL,{acceptance.FINAL}\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '服务引用顺序'):
            self.validate()

    def test_production_surge_config_is_required(self):
        with self.assertRaisesRegex(ValueError, '缺少 Surge 实际引用配置'):
            acceptance.validate_artifacts(self.surge, self.clash, self.mihomo, require_surge_config=True)

    def test_surge_final_is_validated(self):
        path = self.surge / 'rules.conf'
        lines = ''.join(f'RULE-SET,https://example.test/main/surge/{relative},{policy}\n'
                        for _, relative, policy, *_ in self.text_entries)
        path.write_text(lines + 'FINAL,DIRECT\n', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, '末尾 FINAL'):
            self.validate()
        path.write_text(lines + f'FINAL,{acceptance.FINAL}\n', encoding='utf-8')
        self.validate()

    def test_google_output_group_cannot_be_replaced_by_general_proxy(self):
        for file in ('classical.yaml', 'mrs.yaml'):
            path = self.clash / file
            path.write_text(path.read_text().replace('🔍 谷歌服务', '🚀 节点选择'))
        with self.assertRaisesRegex(ValueError, '服务归属验收失败'):
            self.validate()

    def test_wide_browser_process_is_rejected(self):
        self.append_ai('PROCESS-NAME,MicrosoftEdge')
        with self.assertRaisesRegex(ValueError, '普通域名/进程误分类'):
            self.validate()

    def test_real_cidr_intersections_cover_both_address_families(self):
        ai = acceptance.Provider('AI', 'AI', acceptance.AI,
                                 (('IP-CIDR', '192.0.2.0/25', ('no-resolve',)),))
        google = acceptance.Provider('Google-ip', 'Proxy/Google', 'Google',
                                     (('IP-CIDR', '192.0.2.0/24', ('no-resolve',)),
                                      ('IP-CIDR6', '2001:db8::/32', ('no-resolve',))))
        others = acceptance.Provider('Others-extra', 'Proxy/Others', acceptance.PROXY,
                                     (('IP-CIDR', '192.0.2.0/25', ('no-resolve',)),
                                      ('IP-CIDR6', '2001:db8:1::/48', ('no-resolve',))))
        providers = [ai, google, others]
        result = acceptance.validate_proxy_overlaps(providers, providers, providers, self.root)
        self.assertEqual(result, {'overlap_scenarios': 2, 'overlap_ipv4': 1, 'overlap_ipv6': 1})
        # 合法前序 AI 不改变 Google 在代理集合内部的独立优先级。
        with self.assertRaisesRegex(ValueError, 'Google 真实重叠网段优先级错误'):
            acceptance.validate_proxy_overlaps(providers, providers, [ai, others, google], self.root)

    def test_provider_update_period_is_weekly(self):
        path = self.clash / 'mrs.yaml'
        path.write_text(path.read_text().replace('interval: 604800', 'interval: 86400'))
        with self.assertRaisesRegex(ValueError, '必须每周更新'):
            self.validate()

    def test_provider_url_must_match_validated_artifact(self):
        path = self.clash / 'mrs.yaml'
        path.write_text(path.read_text().replace('/clash/AI.list', '/clash/other.list'))
        with self.assertRaisesRegex(ValueError, 'URL 与本地产物路径不一致'):
            self.validate()

    def test_manifest_cannot_omit_existing_sources(self):
        (self.clash / 'manifest.json').write_text(
            '{"schema":1,"mihomo":"1.19.30","update_interval":604800,"sources":{},"artifacts":{}}')
        with self.assertRaisesRegex(ValueError, 'sources 文件集合不一致'):
            self.validate()

    def test_google_suffix_requires_label_boundary(self):
        rule = ('DOMAIN-SUFFIX', 'google.com', ())
        self.assertFalse(acceptance.matches(rule, acceptance.Request('notgoogle.com')))
        self.assertTrue(acceptance.matches(rule, acceptance.Request('www.google.com')))

    def test_ip_process_and_asn_matchers(self):
        self.assertTrue(acceptance.matches(('IP-CIDR6', '2001:db8::/32', ('no-resolve',)),
                                           acceptance.Request(ip='2001:db8::1')))
        rule = ('PROCESS-NAME', 'MicrosoftEdge', ())
        self.assertFalse(acceptance.matches(rule, acceptance.Request(process='microsoftedge')))
        self.assertTrue(acceptance.matches(rule, acceptance.Request(process='microsoftedge'), clash=True))
        self.assertTrue(acceptance.matches(('IP-ASN', '45102', ()), acceptance.Request(asn='45102')))
        self.assertFalse(acceptance.matches(('IP-ASN', '45102', ()), acceptance.Request(asn='13335')))


class CoverageTests(unittest.TestCase):
    def test_empty_groups_are_semantically_absent(self):
        self.assertEqual(acceptance.coverage([acceptance.Provider('Game', 'Game', '🎮游戏', ())]), {})

    def test_resolution_options_are_preserved(self):
        no_resolve = acceptance.Provider('Game', 'Game', '🎮游戏', (('IP-CIDR', '192.0.2.0/24', ('no-resolve',)),))
        resolving = acceptance.Provider('Game', 'Game', '🎮游戏', (('IP-CIDR', '192.0.2.0/24', ()),))
        self.assertNotEqual(acceptance.coverage([no_resolve]), acceptance.coverage([resolving]))


if __name__ == '__main__':
    unittest.main()
