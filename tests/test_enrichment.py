import copy
import io
import json
import unittest
import urllib.error
from dataclasses import asdict
from datetime import datetime
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main as report


def make_sections(count=30):
    sections = report.empty_report_sections()
    section_names = ['head_releases', 'music_ai_industry', 'social_trends', 'culture_art', 'politics']
    for index in range(count):
        section = section_names[min(index // 6, len(section_names) - 1)]
        sections[section].append(report.NewsItem(
            source_key=f'source_{index + 1}', source_name=f'Music source {index + 1}',
            section=section, title=f'Original news {index + 1}',
            link=f'https://news.invalid/{index + 1}', summary=f'Original details {index + 1}',
            published_at=datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('Asia/Shanghai')),
            priority=100, tag='新闻', score=100, cn_title=f'原始直译标题{index + 1}',
            cn_summary=f'原始直译摘要{index + 1}，包含新闻的基础信息。',
            translation_verified=True,
        ))
    return sections


def all_items(sections):
    return [item for items in sections.values() for item in items]


def enriched(item_id):
    return {
        'id': item_id,
        'cn_title': f'模型加工新闻标题{item_id}',
        'summary_zh': f'这条新闻（{item_id}）说明艺人新作即将发布，并介绍了专辑曲目、发行时间和平台安排，相关细节来自输入材料，可供团队规划后续内容时参考。',
    }


def output_for(ids):
    return {'items': [enriched(item_id) for item_id in ids]}


def responses_body(result):
    return {
        'status': 'completed',
        'output': [{'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
            {'type': 'output_text', 'text': json.dumps(result, ensure_ascii=False)}
        ]}],
    }


class EnrichmentRepairTests(unittest.TestCase):
    def setUp(self):
        self.sections = make_sections()
        self.state = {}
        self.health = report.ReportHealth('2026-10-28')
        self.diagnostics = []
        self.calls = []
        for item in (
            patch.object(report, 'OPENAI_API_KEY', 'private-test-key'),
            patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1/responses'),
            patch.object(report, 'OPENAI_MODEL', 'test-model'),
            patch.dict('os.environ', {'LLM_API_STYLE': 'auto'}),
        ):
            item.start()
            self.addCleanup(item.stop)

    def input_payload(self, url, payload):
        self.assertEqual(url, 'https://gateway.invalid/v1/responses')
        self.assertIn('input', payload)
        messages = payload['input']
        self.calls.append(copy.deepcopy(payload))
        return json.loads(messages[-1]['content'])

    def run_enrichment(self):
        report.enrich_items_with_llm(self.sections, self.state, self.diagnostics, self.health)

    def test_30_inputs_missing_item_21_repairs_only_that_id_then_commits_all(self):
        originals = [asdict(item) for item in all_items(self.sections)]
        expected_ids = [f'item_{index}' for index in range(1, 31)]
        initial_result = output_for([item_id for item_id in expected_ids if item_id != 'item_21'])

        def post(url, payload, **kwargs):
            user = self.input_payload(url, payload)
            requested_ids = [item['id'] for item in user['items']]
            if len(self.calls) == 1:
                self.assertEqual(requested_ids, expected_ids)
                return responses_body(initial_result)
            self.assertEqual(len(self.calls), 2)
            self.assertEqual(requested_ids, ['item_21'])
            self.assertEqual([asdict(item) for item in all_items(self.sections)], originals)
            return responses_body(output_for(requested_ids))

        with patch.object(report, 'post_json', side_effect=post):
            self.run_enrichment()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.health.llm_failures)
        for item, item_id in zip(all_items(self.sections), expected_ids):
            self.assertEqual(item.cn_title, enriched(item_id)['cn_title'])
            self.assertEqual(item.cn_summary, enriched(item_id)['summary_zh'])
        self.assertNotIn(initial_result, list(self.state['llm_cache'].values()))
        self.assertIn(output_for(['item_21']), list(self.state['llm_cache'].values()))

    def test_invalid_and_duplicate_outputs_repair_only_problem_ids(self):
        self.sections = make_sections(3)
        cases = {
            'missing_chinese_title': output_for(['item_1', 'item_3']),
            'duplicate_id': output_for(['item_1', 'item_2', 'item_2', 'item_3']),
            'title_repeated_as_summary': output_for(['item_1', 'item_2', 'item_3']),
        }
        cases['missing_chinese_title']['items'].append(
            {'id': 'item_2', 'cn_title': 'Untranslated title', 'summary_zh': '这是一条有效中文摘要。'}
        )
        cases['title_repeated_as_summary']['items'][1]['summary_zh'] = cases['title_repeated_as_summary']['items'][1]['cn_title']
        for name, initial_result in cases.items():
            with self.subTest(case=name):
                self.sections = make_sections(3)
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                self.calls = []

                def post(url, payload, **kwargs):
                    user = self.input_payload(url, payload)
                    ids = [item['id'] for item in user['items']]
                    if len(self.calls) == 1:
                        return responses_body(initial_result)
                    self.assertEqual(ids, ['item_2'])
                    return responses_body(output_for(ids))

                with patch.object(report, 'post_json', side_effect=post):
                    self.run_enrichment()
                self.assertEqual(len(self.calls), 2)
                self.assertFalse(self.health.llm_failures)
                self.assertTrue(all(item.cn_title.startswith('模型加工') for item in all_items(self.sections)))

    def test_unrepaired_output_keeps_valid_ai_items_and_drops_only_missing_news(self):
        self.sections = make_sections(3)
        originals = list(all_items(self.sections))
        missing_original = asdict(originals[1])

        def post(url, payload, **kwargs):
            user = self.input_payload(url, payload)
            if len(self.calls) == 1:
                return responses_body(output_for(['item_1', 'item_3']))
            self.assertEqual([item['id'] for item in user['items']], ['item_2'])
            return responses_body({'items': []})

        with patch.object(report, 'post_json', side_effect=post):
            self.run_enrichment()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.health.llm_failures)
        self.assertIn('item_enrichment', self.health.llm_warnings)
        kept = all_items(self.sections)
        self.assertEqual([item.link for item in kept], ['https://news.invalid/1', 'https://news.invalid/3'])
        self.assertEqual([item.cn_title for item in kept], [enriched('item_1')['cn_title'], enriched('item_3')['cn_title']])
        self.assertEqual(asdict(originals[1]), missing_original)
        self.assertFalse(self.state.get('llm_cache'))

    def test_repair_http_failure_keeps_valid_ai_results_without_full_fallback(self):
        self.sections = make_sections(3)
        error = urllib.error.HTTPError('https://gateway.invalid/v1/responses', 503,
                                       'private-provider-detail', {}, io.BytesIO(b''))

        def post(url, payload, **kwargs):
            user = self.input_payload(url, payload)
            if len(self.calls) == 1:
                return responses_body(output_for(['item_1', 'item_3']))
            self.assertEqual([item['id'] for item in user['items']], ['item_2'])
            raise error

        try:
            with patch.object(report, 'post_json', side_effect=post):
                self.run_enrichment()
        finally:
            error.close()
        self.assertEqual(len(self.calls), 2)
        self.assertFalse(self.health.llm_failures)
        self.assertIn('item_enrichment', self.health.llm_warnings)
        kept = all_items(self.sections)
        self.assertEqual([item.link for item in kept], ['https://news.invalid/1', 'https://news.invalid/3'])
        self.assertTrue(all(item.cn_title.startswith('模型加工') for item in kept))
        self.assertNotIn('private-provider-detail', str(self.diagnostics))

    def test_zero_usable_results_after_bounded_repair_fails_without_mutation(self):
        self.sections = make_sections(3)
        originals = [asdict(item) for item in all_items(self.sections)]

        def post(url, payload, **kwargs):
            user = self.input_payload(url, payload)
            self.assertEqual([item['id'] for item in user['items']], ['item_1', 'item_2', 'item_3'])
            return responses_body({'items': []})

        with patch.object(report, 'post_json', side_effect=post):
            self.run_enrichment()
        self.assertEqual(len(self.calls), 2)
        self.assertIn('item_enrichment', self.health.llm_failures)
        self.assertEqual([asdict(item) for item in all_items(self.sections)], originals)
        self.assertFalse(self.state.get('llm_cache'))

    def test_first_http_failure_does_not_make_pointless_repair_request(self):
        originals = [asdict(item) for item in all_items(self.sections)]
        error = urllib.error.HTTPError('https://gateway.invalid/v1/responses', 503,
                                       'private-provider-detail', {}, io.BytesIO(b''))
        try:
            with patch.object(report, 'post_json', side_effect=error) as post:
                self.run_enrichment()
        finally:
            error.close()
        post.assert_called_once()
        self.assertIn('item_enrichment', self.health.llm_failures)
        self.assertEqual([asdict(item) for item in all_items(self.sections)], originals)
        self.assertFalse(self.state.get('llm_cache'))
        self.assertNotIn('private-provider-detail', str(self.diagnostics))

    def test_successful_full_enrichment_is_cacheable(self):
        self.sections = make_sections(3)

        def post(url, payload, **kwargs):
            user = self.input_payload(url, payload)
            return responses_body(output_for([item['id'] for item in user['items']]))

        with patch.object(report, 'post_json', side_effect=post) as post_mock:
            self.run_enrichment()
            self.sections = make_sections(3)
            self.health = report.ReportHealth('2026-10-28')
            self.run_enrichment()
        post_mock.assert_called_once()
        self.assertFalse(self.health.llm_failures)
        self.assertEqual(self.health.llm_protocols['item_enrichment'], 'cache')
        self.assertTrue(all(item.cn_title.startswith('模型加工') for item in all_items(self.sections)))


class LlmCacheValidationTests(unittest.TestCase):
    def setUp(self):
        self.state = {}
        self.health = report.ReportHealth('2026-10-28')
        self.diagnostics = []
        for item in (
            patch.object(report, 'OPENAI_API_KEY', 'private-test-key'),
            patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1/responses'),
            patch.object(report, 'OPENAI_MODEL', 'test-model'),
            patch.dict('os.environ', {'LLM_API_STYLE': 'auto'}),
        ):
            item.start()
            self.addCleanup(item.stop)

    @staticmethod
    def full_coverage(result):
        entries = result.get('items')
        return isinstance(entries, list) and len(entries) == 2 and {entry.get('id') for entry in entries} == {'item_1', 'item_2'}

    def call(self):
        return report.call_llm_json(
            'Return one JSON result per item.', {'items': [{'id': 'item_1'}, {'id': 'item_2'}]},
            self.state, self.diagnostics, 'cache_validation', self.health,
            cache_validator=self.full_coverage,
        )

    def test_fresh_partial_is_returned_for_repair_but_not_cached(self):
        partial = output_for(['item_1'])
        with patch.object(report, 'post_json', return_value=responses_body(partial)) as post:
            self.assertEqual(self.call(), partial)
        post.assert_called_once()
        self.assertFalse(self.state.get('llm_cache'))
        self.assertFalse(self.health.llm_failures)

    def test_invalid_cached_partial_is_discarded_and_replaced_by_fresh_full_result(self):
        full = output_for(['item_1', 'item_2'])
        with patch.object(report, 'post_json', return_value=responses_body(full)):
            self.assertEqual(self.call(), full)
        key = next(iter(self.state['llm_cache']))
        self.state['llm_cache'][key] = output_for(['item_1'])
        self.health = report.ReportHealth('2026-10-28')
        with patch.object(report, 'post_json', return_value=responses_body(full)) as post:
            self.assertEqual(self.call(), full)
        post.assert_called_once()
        self.assertEqual(self.state['llm_cache'][key], full)
        self.assertEqual(self.health.llm_protocols['cache_validation'], 'responses')

    def test_invalid_cached_partial_is_not_retained_when_fresh_request_fails(self):
        full = output_for(['item_1', 'item_2'])
        with patch.object(report, 'post_json', return_value=responses_body(full)):
            self.assertEqual(self.call(), full)
        key = next(iter(self.state['llm_cache']))
        self.state['llm_cache'][key] = output_for(['item_1'])
        self.health = report.ReportHealth('2026-10-28')
        with patch.object(report, 'post_json', side_effect=TimeoutError) as post:
            self.assertIsNone(self.call())
        post.assert_called_once()
        self.assertNotIn(key, self.state['llm_cache'])
        self.assertIn('cache_validation', self.health.llm_failures)


if __name__ == '__main__':
    unittest.main()
