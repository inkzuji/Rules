"""服务归属验收：输入来源和历史类别不能覆盖已确认的业务边界。"""
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import build
from rules import parse_rules


class OwnershipTests(unittest.TestCase):
    def assert_owner(self, best, rule, policy, theme):
        self.assertIn(rule[:2], best)
        self.assertEqual(best[rule[:2]][1:3], (policy, theme))

    def test_general_google_domains_in_ai_sources_belong_to_google(self):
        domains = ('google.com', 'www.google.com', 'accounts.google.com', 'mail.google.com',
                   'googleapis.com', 'googleusercontent.com', 'gstatic.com', 'gmail.com',
                   'recaptcha.net')
        for kind in ('DOMAIN', 'DOMAIN-SUFFIX'):
            for domain in domains:
                with self.subTest(kind=kind, domain=domain):
                    best = {}
                    rule = (kind, domain, ())
                    build.merge(best, '🤖️AI', [rule])
                    self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Google')

    def test_specific_ai_domains_override_general_company_sources(self):
        examples = (
            ('ai.studio', 'Proxy/Google', 'AI/Gemini'),
            ('www.copilot-stg.com', 'Proxy/Microsoft', 'AI/Copilot'),
            ('gemini.google.com', 'Proxy/Google', 'AI/Gemini'),
            ('gemini.google', 'Proxy/Google', 'AI/Gemini'),
            ('business.gemini.google', 'Proxy/Google', 'AI/Gemini'),
            ('aistudio.google.com', 'Proxy/Google', 'AI/Gemini'),
            ('generativelanguage.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('generativeai.google', 'Proxy/Google', 'AI/Gemini'),
            ('flow.google', 'Proxy/Google', 'AI/Gemini'),
            ('jules.google', 'Proxy/Google', 'AI/Gemini'),
            ('opal.google', 'Proxy/Google', 'AI/Gemini'),
            ('aicode.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('aida.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('aiplatform.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('antigravity.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('antigravity-pa.googleapis.com', 'Proxy/Google', 'AI/Gemini'),
            ('antigravity.google', 'Proxy/Google', 'AI/Gemini'),
            ('gemini.gstatic.com', 'Proxy/Google', 'AI/Gemini'),
            ('copilot.microsoft.com', 'Proxy/Microsoft', 'AI/Copilot'),
            ('sydney.bing.com', 'Proxy/Microsoft', 'AI/Copilot'),
            ('api.githubcopilot.com', 'Proxy/GitHub', 'AI/Copilot'),
            ('copilot-proxy.githubusercontent.com', 'Proxy/GitHub', 'AI/Copilot'),
            ('copilotprodattachments.blob.core.windows.net', 'Proxy/Microsoft', 'AI/Copilot'),
            ('grazie.aws.intellij.net', 'Proxy/Dev', 'AI/Others'),
            ('codewhisperer.us-east-1.amazonaws.com', 'Proxy/Dev', 'AI/Others'),
            ('q.us-east-1.amazonaws.com', 'Proxy/Dev', 'AI/Others'),
            ('ppl-ai-file-upload.s3.amazonaws.com', 'Proxy/Dev', 'AI/Others'),
            ('coderabbit.gallery.vsassets.io', 'Proxy/Microsoft', 'AI/Others'),
            ('production-openaicom-storage.azureedge.net', 'Proxy/Microsoft', 'AI/OpenAI'),
            ('openaicomproductionae4b.blob.core.windows.net', 'Proxy/Microsoft', 'AI/OpenAI'),
        )
        for domain, source_theme, expected in examples:
            with self.subTest(domain=domain):
                rule = ('DOMAIN-SUFFIX', domain, ())
                best = {}
                build.merge(best, '🚀节点选择', [rule], source_theme)
                self.assert_owner(best, rule, '🤖️AI', expected)

    def test_youtube_service_domains_override_google_parent_and_ai_source(self):
        for domain in ('youtube.com', 'youtubei.googleapis.com', 'youtube.googleapis.com',
                       'googlevideo.com', 'ytimg.com', 'youtu.be'):
            for policy, source in (('🤖️AI', None), ('🚀节点选择', 'Proxy/Google')):
                with self.subTest(domain=domain, source=source):
                    rule = ('DOMAIN-SUFFIX', domain, ())
                    best = {}
                    build.merge(best, policy, [rule], source)
                    self.assert_owner(best, rule, '🚀节点选择', 'Proxy/YouTube')

    def test_general_microsoft_and_github_domains_do_not_become_copilot(self):
        for domain, expected in (('bing.com', 'Proxy/Microsoft'),
                                 ('www.bing.com', 'Proxy/Microsoft'),
                                 ('microsoft.com', 'Proxy/Microsoft'),
                                 ('github.com', 'Proxy/GitHub'),
                                 ('api.github.com', 'Proxy/GitHub'),
                                 ('githubusercontent.com', 'Proxy/GitHub')):
            with self.subTest(domain=domain):
                rule = ('DOMAIN-SUFFIX', domain, ())
                best = {}
                build.merge(best, '🤖️AI', [rule], 'AI/Copilot')
                self.assert_owner(best, rule, '🚀节点选择', expected)

    def test_historical_ai_misclassification_is_corrected_without_current_duplicate(self):
        root = Path(tempfile.mkdtemp(prefix='rules-ownership-history-'))
        path = root / 'AI' / 'Others.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🤖️AI\nDOMAIN-SUFFIX,google.com\n'
                        'DOMAIN-SUFFIX,bing.com\nDOMAIN-SUFFIX,github.com\n', encoding='utf-8')
        with mock.patch.object(build, 'fetch', return_value='DOMAIN-SUFFIX,openai.com\n'):
            best, _ = build.collect(root, [('current-ai', '🤖️AI', 'AI/OpenAI')])
        for domain, expected in (('google.com', 'Proxy/Google'), ('bing.com', 'Proxy/Microsoft'),
                                 ('github.com', 'Proxy/GitHub')):
            self.assert_owner(best, ('DOMAIN-SUFFIX', domain, ()), '🚀节点选择', expected)
        artifacts = build.surge_artifacts(best)
        self.assertNotIn(b'google.com', artifacts['AI/Others.list'])
        self.assertIn(b'DOMAIN-SUFFIX,google.com', artifacts['Proxy/Google.list'])

    def test_current_service_source_corrects_historical_ai_ip(self):
        for kind, network in (('IP-CIDR', '192.0.2.0/24'), ('IP-CIDR6', '2001:db8::/32')):
            with self.subTest(kind=kind):
                best = {}
                old = (kind, network, ())
                current = (kind, network, ('no-resolve',))
                build.merge(best, '🤖️AI', [old], 'AI/Others', historical=True)
                build.merge(best, '🚀节点选择', [current], 'Proxy/Google')
                self.assert_owner(best, current, '🚀节点选择', 'Proxy/Google')
                self.assertEqual(best[current[:2]][3], current)

    def test_equally_explicit_unknown_service_conflicts_are_rejected_in_both_orders(self):
        rule = ('IP-CIDR', '192.0.2.0/24', ('no-resolve',))
        for first, second in (('Proxy/Google', 'Proxy/Netflix'), ('Proxy/Netflix', 'Proxy/Google')):
            with self.subTest(first=first):
                best = {}
                build.merge(best, '🚀节点选择', [rule], first)
                with self.assertRaises(ValueError):
                    build.merge(best, '🚀节点选择', [rule], second)

    def test_named_service_source_beats_developer_aggregate_in_both_orders(self):
        developer = ('https://rules.example/Dev.txt', '🚀节点选择', 'Proxy/Dev')
        microsoft = ('https://rules.example/Microsoft.txt', '🚀节点选择', 'Proxy/Microsoft')
        text = 'DOMAIN-SUFFIX,service.vendor.example\nIP-CIDR,192.0.2.0/24,no-resolve\n'
        for sources in ((developer, microsoft), (microsoft, developer)):
            with self.subTest(first=sources[0][0]):
                root = Path(tempfile.mkdtemp(prefix='rules-ownership-evidence-'))
                with mock.patch.object(build, 'fetch', return_value=text):
                    best, _ = build.collect(root, sources)
                for rule in parse_rules(text):
                    self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Microsoft')

    def test_collect_rejects_unknown_domain_claimed_by_two_named_services(self):
        google = ('https://rules.example/Google.txt', '🚀节点选择', 'Proxy/Google')
        microsoft = ('https://rules.example/Microsoft.txt', '🚀节点选择', 'Proxy/Microsoft')
        for sources in ((google, microsoft), (microsoft, google)):
            with self.subTest(first=sources[0][0]):
                root = Path(tempfile.mkdtemp(prefix='rules-ownership-conflict-'))
                with mock.patch.object(build, 'fetch', return_value='DOMAIN-SUFFIX,unknown-vendor.example\n'), \
                     self.assertRaises(ValueError):
                    build.collect(root, sources)

    def test_shared_public_dependencies_do_not_become_ai(self):
        examples = (
            ('sentry.io', 'Proxy/Dev'), ('intercom.io', 'Proxy/Dev'),
            ('statsig.com', 'Proxy/Dev'), ('arkoselabs.com', 'Proxy/Dev'),
            ('livekit.cloud', 'Proxy/Dev'), ('hcaptcha.com', 'Proxy/Dev'),
            ('px-cloud.net', 'Proxy/Dev'), ('sheerid.com', 'Proxy/Dev'),
            ('id.me', 'Proxy/Dev'), ('withpersona.com', 'Proxy/Dev'),
            ('stripe.com', 'Proxy/Others'), ('paypal.com', 'Proxy/Others'),
            ('envato.com', 'Proxy/Others'),
        )
        for domain, expected in examples:
            with self.subTest(domain=domain):
                rule = ('DOMAIN-SUFFIX', domain, ())
                best = {}
                build.merge(best, '🤖️AI', [rule], 'AI/OpenAI')
                self.assert_owner(best, rule, '🚀节点选择', expected)

    def test_known_ai_services_keep_owner_across_generic_aggregate_order(self):
        examples = (
            ('cursor.com', 'AI/Others'), ('cursor.sh', 'AI/Others'),
            ('perplexity.ai', 'AI/Others'), ('perplexity.com', 'AI/Others'),
            ('pplx.ai', 'AI/Others'), ('huggingface.co', 'AI/Others'), ('hf.co', 'AI/Others'),
            ('x.ai', 'AI/Others'), ('grok.com', 'AI/Others'),
            ('midjourney.com', 'AI/Others'), ('suno.ai', 'AI/Others'), ('suno.com', 'AI/Others'),
            ('poe.com', 'AI/Others'), ('codeium.com', 'AI/Others'),
            ('windsurf.com', 'AI/Others'), ('ollama.com', 'AI/Others'),
            ('claude.dev', 'AI/Others'), ('claude.site', 'AI/Others'),
            ('gemini.google.com', 'AI/Gemini'), ('generativelanguage.googleapis.com', 'AI/Gemini'),
        )
        for domain, expected in examples:
            for policies in (('🤖️AI', '🚀节点选择'), ('🚀节点选择', '🤖️AI')):
                with self.subTest(domain=domain, first=policies[0]):
                    rule = ('DOMAIN-SUFFIX', domain, ())
                    best = {}
                    for policy in policies:
                        build.merge(best, policy, [rule])
                    self.assert_owner(best, rule, '🤖️AI', expected)

    def test_shared_telemetry_and_login_domains_cannot_force_ai(self):
        for domain in ('browser-intake-datadoghq.com', 'in.appcenter.ms',
                       'services.bingapis.com', 'auth.meta.com'):
            with self.subTest(domain=domain):
                rule = ('DOMAIN-SUFFIX', domain, ())
                best = {}
                build.merge(best, '🤖️AI', [rule])
                self.assertIn(rule[:2], best)
                self.assertNotEqual(best[rule[:2]][1], '🤖️AI')

    def test_developer_aggregate_updates_parameters_without_replacing_historical_service(self):
        root = Path(tempfile.mkdtemp(prefix='rules-ownership-history-evidence-'))
        path = root / 'Proxy' / 'Microsoft.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🚀节点选择\nIP-CIDR,192.0.2.0/24\n'
                        'DOMAIN-SUFFIX,service.vendor.example\n', encoding='utf-8')
        text = 'IP-CIDR,192.0.2.0/24,no-resolve\nDOMAIN-SUFFIX,service.vendor.example\n'
        with mock.patch.object(build, 'fetch', return_value=text):
            best, _ = build.collect(root, [('https://rules.example/Dev.txt', '🚀节点选择', 'Proxy/Dev')])
        for rule in parse_rules(text):
            self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Microsoft')
            self.assertEqual(best[rule[:2]][3], rule)

    def test_historical_payment_domains_are_corrected_without_current_duplicate(self):
        root = Path(tempfile.mkdtemp(prefix='rules-ownership-payment-history-'))
        path = root / 'AI' / 'Others.list'
        path.parent.mkdir()
        text = 'DOMAIN-SUFFIX,paypal.ca\nDOMAIN,secure.paypal.ca\nDOMAIN-SUFFIX,envato.com\n'
        path.write_text('# 策略: 🤖️AI\n' + text, encoding='utf-8')
        with mock.patch.object(build, 'fetch', return_value='DOMAIN-SUFFIX,openai.com\n'):
            best, _ = build.collect(root, [('current-ai', '🤖️AI', 'AI/OpenAI')])
        artifacts = build.surge_artifacts(best)
        for rule in parse_rules(text):
            self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Others')
            self.assertNotIn(rule[1].encode(), artifacts['AI/Others.list'])

    def test_cross_policy_network_containment_is_reported_for_both_address_families(self):
        examples = (('IP-CIDR', '192.0.2.0/24', '192.0.2.1/32'),
                    ('IP-CIDR6', '2001:db8::/32', '2001:db8::1/128'))
        for kind, parent, child in examples:
            with self.subTest(kind=kind):
                best = {}
                build.merge(best, '🤖️AI', [(kind, parent, ('no-resolve',))], 'AI/OpenAI')
                build.merge(best, '🚀节点选择', [(kind, child, ('no-resolve',))], 'Proxy/Google')
                conflicts = build.network_conflicts(best)
                self.assertEqual(len(conflicts), 1)
                self.assertEqual({tuple(entry) for entry in conflicts[0].values()},
                                 {('AI/OpenAI', parent), ('Proxy/Google', child)})

    def test_overlapping_service_networks_with_same_policy_do_not_report_route_conflict(self):
        for kind, parent, child in (('IP-CIDR', '192.0.2.0/24', '192.0.2.1/32'),
                                     ('IP-CIDR6', '2001:db8::/32', '2001:db8::1/128')):
            with self.subTest(kind=kind):
                best = {}
                build.merge(best, '🚀节点选择', [(kind, parent, ())], 'Proxy/Google')
                build.merge(best, '🚀节点选择', [(kind, child, ())], 'Proxy/Microsoft')
                self.assertEqual(build.network_conflicts(best), [])

    def test_only_fully_covered_fallback_networks_are_discarded(self):
        examples = (
            ('IP-CIDR', ('192.0.2.0/24', '192.0.4.0/25'),
             '192.0.2.0/25', ('192.0.3.0/24', '192.0.4.0/24')),
            ('IP-CIDR6', ('2001:db8::/32', '2001:dbb:1::/48'),
             '2001:db8:1::/48', ('2001:db9::/48', '2001:dbb::/32')),
        )
        for kind, specific_networks, covered, retained in examples:
            with self.subTest(kind=kind):
                best = build.Selections()
                for network in specific_networks:
                    build.merge(best, 'DIRECT', [(kind, network, ('no-resolve',))], 'Direct')
                for network in (covered, *retained):
                    build.merge(best, '🚀节点选择', [(kind, network, ('no-resolve',))], 'Proxy/Others')
                build.discard_covered_fallbacks(best)
                self.assertNotIn((kind, covered), best)
                for network in retained:
                    self.assert_owner(best, (kind, network, ('no-resolve',)), '🚀节点选择', 'Proxy/Others')
                for network in specific_networks:
                    self.assert_owner(best, (kind, network, ('no-resolve',)), 'DIRECT', 'Direct')

    def test_shared_cloud_asn_and_general_processes_cannot_force_ai(self):
        for rule in parse_rules('IP-ASN,14061,no-resolve\nIP-ASN,20473,no-resolve\n'
                                'PROCESS-NAME,MicrosoftEdge\nPROCESS-NAME,VSCode\n'
                                'PROCESS-NAME,Code Helper\n'):
            with self.subTest(rule=rule):
                best = {}
                build.merge(best, '🤖️AI', [rule])
                if rule[:2] in best:
                    self.assertNotEqual(best[rule[:2]][1], '🤖️AI')

    def test_unknown_ai_aggregate_ips_use_general_proxy_without_exclusive_evidence(self):
        for kind, network in (('IP-CIDR', '192.0.2.0/24'), ('IP-CIDR6', '2001:db8::/32')):
            rule = (kind, network, ('no-resolve',))
            with self.subTest(kind=kind, evidence='aggregate'):
                best = {}
                build.merge(best, '🤖️AI', [rule])
                self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Others')
            with self.subTest(kind=kind, evidence='specific'):
                best = {}
                build.merge(best, '🤖️AI', [rule], 'AI/OpenAI')
                self.assert_owner(best, rule, '🤖️AI', 'AI/OpenAI')

    def test_shared_cloudflare_addresses_do_not_become_ai_even_in_specific_source(self):
        for kind, network in (('IP-CIDR', '104.18.0.0/16'),
                               ('IP-CIDR6', '2606:4700::/32')):
            with self.subTest(kind=kind):
                rule = (kind, network, ('no-resolve',))
                best = {}
                build.merge(best, '🤖️AI', [rule], 'AI/OpenAI')
                self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Cloudflare')

    def test_broad_company_and_ai_keywords_are_not_published(self):
        examples = (('google', '🤖️AI'), ('bing', '🤖️AI'), ('github', '🤖️AI'),
                    ('openai', '🤖️AI'), ('generativelanguage.googleapis', '🤖️AI'),
                    ('google', '🚀节点选择'), ('bing', '🚀节点选择'), ('github', '🚀节点选择'))
        for keyword, policy in examples:
            with self.subTest(keyword=keyword, policy=policy):
                rule = ('DOMAIN-KEYWORD', keyword, ())
                best = {}
                build.merge(best, policy, [rule])
                self.assertNotIn(rule[:2], best)

    def test_unrelated_domain_names_do_not_inherit_google_or_ai_owner(self):
        for domain in ('google.example', 'notgoogle.com', 'google.com.example', 'bing.example'):
            with self.subTest(domain=domain):
                rule = ('DOMAIN-SUFFIX', domain, ())
                best = {}
                build.merge(best, '🚀节点选择', [rule])
                self.assert_owner(best, rule, '🚀节点选择', 'Proxy/Others')

    def test_valid_historical_service_rules_are_retained(self):
        root = Path(tempfile.mkdtemp(prefix='rules-ownership-preserved-'))
        path = root / 'AI' / 'Gemini.list'
        path.parent.mkdir()
        path.write_text('# 策略: 🤖️AI\nDOMAIN-SUFFIX,gemini.google.com\n', encoding='utf-8')
        with mock.patch.object(build, 'fetch', return_value='DOMAIN-SUFFIX,google.com\n'):
            best, _ = build.collect(root, [('current-google', '🚀节点选择', 'Proxy/Google')])
        self.assert_owner(best, ('DOMAIN-SUFFIX', 'gemini.google.com', ()), '🤖️AI', 'AI/Gemini')


if __name__ == '__main__':
    unittest.main()
