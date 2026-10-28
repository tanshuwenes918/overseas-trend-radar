import copy
import hashlib
import io
import json
import tempfile
import unittest
import urllib.error
from datetime import date, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from unittest.mock import patch
from zoneinfo import ZoneInfo

import main as report


WEBHOOK = 'https://example.invalid/feishu-secret'


def news_item():
    return report.NewsItem(
        source_key='test', source_name='Test Music', section='head_releases',
        title='Artist announces a new album', link='https://example.invalid/news',
        summary='The album arrives in June with twelve tracks.',
        published_at=datetime(2026, 10, 27, 12, tzinfo=ZoneInfo('Asia/Shanghai')),
        priority=100, tag='专辑', score=100, business_score=10,
    )


class TranslationTests(unittest.TestCase):
    def test_legacy_original_cache_cannot_pass_as_translation(self):
        text = 'Artist releases an album'
        old_key = hashlib.sha256(f'title|{text}'.encode()).hexdigest()
        state = {'translation_cache': {old_key: text}}
        with patch.object(report, 'REMOTE_TRANSLATION_ENABLED', True), \
             patch.object(report, 'DEEPL_API_KEY', ''), \
             patch.object(report, 'translate_via_google_unofficial', side_effect=TimeoutError):
            result = report.translate_verified(text, state, 'title')
        self.assertFalse(result.verified)
        self.assertEqual(len(state['translation_cache']), 1)

    def test_only_successful_translation_is_cached(self):
        state = {}
        with patch.object(report, 'REMOTE_TRANSLATION_ENABLED', True), \
             patch.object(report, 'DEEPL_API_KEY', ''), \
             patch.object(report, 'translate_via_google_unofficial', return_value='艺人发行新专辑') as translator:
            first = report.translate_verified('New album', state, 'title')
            second = report.translate_verified('New album', state, 'title')
        self.assertTrue(first.verified)
        self.assertEqual(first, second)
        self.assertEqual(translator.call_count, 1)

    def test_original_with_some_chinese_is_not_assumed_translated(self):
        with patch.object(report, 'REMOTE_TRANSLATION_ENABLED', False):
            result = report.translate_verified('Artist 北京 announces new album', {}, 'title')
        self.assertFalse(result.verified)

    def test_unchanged_or_non_chinese_response_is_not_success(self):
        for value in ('New album', 'Untranslated words', ''):
            with self.subTest(value=value), \
                 patch.object(report, 'REMOTE_TRANSLATION_ENABLED', True), \
                 patch.object(report, 'DEEPL_API_KEY', ''), \
                 patch.object(report, 'translate_via_google_unofficial', return_value=value):
                state = {}
                self.assertFalse(report.translate_verified('New album', state, 'title').verified)
                self.assertEqual(state['translation_cache'], {})

    def test_untranslated_summary_invalidates_item_even_if_title_succeeds(self):
        sections = report.empty_report_sections()
        item = news_item()
        sections['head_releases'] = [item]
        with patch.object(report, 'translate_verified', side_effect=[
            report.TranslationResult('艺人发行专辑', True),
            report.TranslationResult(item.summary, False, '请求超时'),
        ]):
            report.enrich_cn_summaries(sections, {}, [])
        self.assertFalse(item.translation_verified)
        self.assertIn('请求超时', item.translation_error)


class DeliveryTests(unittest.TestCase):
    def test_accept_modern_and_legacy_success_receipts(self):
        for receipt in ({'code': 0}, {'StatusCode': 0}, {'code': '0', 'StatusCode': 0}):
            with self.subTest(receipt=receipt):
                report.validate_feishu_response(receipt)

    def test_reject_business_error_missing_or_conflicting_codes(self):
        for receipt in ({'code': 19024}, {'StatusCode': 1}, {'code': 0, 'StatusCode': 1},
                        {}, {'msg': 'success'}, {'code': None}, {'code': False}, [], {'code': {}}):
            with self.subTest(receipt=receipt), self.assertRaises(ValueError):
                report.validate_feishu_response(receipt)

    def test_timeout_is_unconfirmed_and_not_retried(self):
        health = report.ReportHealth('2026-10-28')
        with patch.object(report.urllib.request, 'urlopen', side_effect=TimeoutError) as send:
            self.assertEqual(report.deliver_payload({}, WEBHOOK, health), 3)
        self.assertEqual(send.call_count, 1)
        self.assertEqual(health.delivery, 'unconfirmed')
        self.assertNotIn(WEBHOOK, str(health.errors))

    def test_real_http_200_business_rejection_is_failure(self):
        received = []

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                received.append(json.loads(self.rfile.read(int(self.headers['Content-Length']))))
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.end_headers()
                self.wfile.write(b'{"code":19024,"msg":"keyword missing"}')

            def log_message(self, *args):
                pass

        server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        thread = Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            health = report.ReportHealth('2026-10-28')
            code = report.deliver_payload({'msg_type': 'text'}, f'http://127.0.0.1:{server.server_port}', health)
            self.assertEqual(code, 3)
            self.assertEqual(health.delivery, 'rejected')
            self.assertIn('19024', str(health.errors))
            self.assertEqual(len(received), 1)
        finally:
            server.shutdown()
            thread.join()
            server.server_close()

    def test_error_reasons_do_not_disclose_request_secrets(self):
        error = urllib.error.HTTPError('https://secret.invalid/key', 401, 'secret-api-key', {}, None)
        self.assertEqual(report.error_reason(error), 'HTTP 401：认证失败，请检查 API Key')
        error.close()


class PipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = Path(self.temp.name)
        self.sent = []
        self.model_calls = []
        self.receipt = {'code': 0}
        self.failing_stage = None
        self.malformed_stage = None
        self.translation_ok = True
        self.sections = report.empty_report_sections()
        self.sections['head_releases'] = [news_item()]
        patches = [
            patch.object(report, 'DATA_DIR', self.data),
            patch.object(report, 'STATE_PATH', self.data / 'state.json'),
            patch.object(report, 'OPENAI_API_KEY', 'test-key'),
            patch.object(report, 'OPENAI_BASE_URL', 'https://example.invalid/v1'),
            patch.object(report, 'OPENAI_MODEL', 'test-model'),
            patch.object(report, 'fetch_section_items', side_effect=lambda *a, **k: copy.deepcopy(self.sections)),
            patch.object(report, 'fetch_holiday_items', return_value={'today': [], 'week': [], 'advance': []}),
            patch.object(report, 'fetch_price_alerts', return_value=[]),
            patch.object(report, 'enrich_article_excerpts'),
            patch.object(report, 'translate_verified', side_effect=self.translate),
            patch.object(report, 'post_json', side_effect=self.post),
            patch.dict('os.environ', {'LLM_API_STYLE': 'auto', 'FEISHU_WEBHOOK_URL': WEBHOOK, 'GITHUB_STEP_SUMMARY': str(self.data / 'summary.md')}),
            patch('sys.stdout', new_callable=io.StringIO),
        ]
        for item in patches:
            item.start()
            self.addCleanup(item.stop)

    def translate(self, text, state, namespace):
        if not self.translation_ok:
            return report.TranslationResult(text, False, '请求超时')
        return report.TranslationResult('直接翻译标题' if namespace.endswith(':title') else '直接翻译摘要，包含发行时间与曲目数量。', True)

    def post(self, url, payload, **kwargs):
        if url == WEBHOOK:
            self.sent.append(payload)
            return self.receipt
        self.model_calls.append((url, payload))
        messages = payload.get('messages', payload.get('input'))
        content = json.loads(messages[-1]['content'])
        if 'goal' in content:
            stage = 'item_enrichment'
            result = {'items': [dict(id=item['id'], cn_title='模型加工标题', summary_zh='模型加工摘要，介绍专辑的发行安排。') for item in content['items']]}
        elif 'section_limits' in content:
            stage = 'editorial_selection'
            result = {'items': [dict(id='item_1', section='head_releases', cn_title='模型精选标题', summary_zh='模型精选摘要，介绍专辑的具体安排。')]}
        else:
            stage = 'action_plan'
            result = {'app_actions': ['为这张专辑准备推荐位。'], 'social_actions': [], 'localization_actions': [], 'watchouts': []}
        if self.failing_stage == stage:
            error = urllib.error.HTTPError(url, 401, 'secret-key-must-not-leak', {}, None)
            error.close()
            raise error
        if self.malformed_stage == stage:
            result = {}
        if 'input' in payload:
            return {'status': 'completed', 'output': [{'type': 'message', 'role': 'assistant',
                'content': [{'type': 'output_text', 'text': json.dumps(result, ensure_ascii=False)}]}]}
        return {'choices': [{'message': {'content': json.dumps(result, ensure_ascii=False)}}]}

    def run_report(self, *extra):
        with patch('sys.argv', ['main.py', '--date', '2026-10-28', *extra]):
            code = report.main()
        status = json.loads((self.data / 'run_status.json').read_text())
        return code, status

    def saved_state(self):
        return json.loads((self.data / 'state.json').read_text())

    def test_normal_report_is_sent_and_date_recorded(self):
        code, status = self.run_report('--send')
        self.assertEqual(code, 0)
        self.assertEqual(status['mode'], 'normal')
        self.assertEqual(status['delivery'], 'sent')
        self.assertEqual(self.saved_state()['delivery']['last_sent_date'], '2026-10-28')
        self.assertIn('模型精选标题', json.dumps(self.sent[0], ensure_ascii=False))
        self.assertNotIn('直接翻译版', json.dumps(self.sent[0], ensure_ascii=False))

    def test_responses_configuration_processes_all_model_stages(self):
        with patch.object(report, 'OPENAI_BASE_URL', 'https://example.invalid/v1/responses'):
            code, status = self.run_report('--send')
        self.assertEqual(code, 0)
        self.assertEqual(status['mode'], 'normal')
        self.assertEqual(status['delivery'], 'sent')
        self.assertEqual(len(self.model_calls), 3)
        self.assertTrue(all(url.endswith('/responses') for url, _ in self.model_calls))
        self.assertTrue(all('input' in payload and 'messages' not in payload for _, payload in self.model_calls))
        self.assertIn('模型精选标题', json.dumps(self.sent[0], ensure_ascii=False))
        self.assertIn('【运营建议】', json.dumps(self.sent[0], ensure_ascii=False))

    def test_llm_failure_at_each_stage_sends_only_verified_direct_translation(self):
        for stage in ('item_enrichment', 'editorial_selection', 'action_plan'):
            with self.subTest(stage=stage):
                self.failing_stage = stage
                code, status = self.run_report('--send')
                self.assertEqual(code, 0)
                self.assertEqual(status['mode'], 'direct_translation')
                self.assertIn('HTTP 401', status['llm_failures'][stage])
                message = json.dumps(self.sent[-1], ensure_ascii=False)
                self.assertIn('直接翻译版', message)
                self.assertIn('直接翻译标题', message)
                self.assertNotIn('模型精选标题', message)
                self.assertNotIn('模型加工标题', message)
                self.assertNotIn('【运营建议】', message)
                self.assertNotIn('secret-key-must-not-leak', (self.data / 'diagnostics.json').read_text())
                # Cached successful model results must not conceal the next stage's failure.
                (self.data / 'state.json').unlink()

    def test_malformed_llm_outputs_cannot_be_reported_as_normal(self):
        for stage in ('item_enrichment', 'editorial_selection', 'action_plan'):
            with self.subTest(stage=stage):
                self.malformed_stage = stage
                code, status = self.run_report('--dry-run')
                self.assertEqual(code, 0)
                self.assertEqual(status['mode'], 'direct_translation')
                self.assertIn(stage, status['llm_failures'])
                self.assertEqual(self.sent, [])
                (self.data / 'state.json').unlink()

    def test_llm_and_translation_failure_send_only_failure_notice_and_return_error(self):
        self.failing_stage = 'item_enrichment'
        self.translation_ok = False
        code, status = self.run_report('--send')
        self.assertEqual(code, 5)
        self.assertEqual(status['mode'], 'failed')
        self.assertEqual(status['delivery'], 'failure_notice_sent')
        self.assertTrue(status['translation_failures'])
        self.assertEqual(len(self.sent), 1)
        self.assertEqual(self.sent[0]['msg_type'], 'text')
        self.assertIn('HTTP 401', self.sent[0]['content']['text'])
        self.assertIn('请求超时', self.sent[0]['content']['text'])
        self.assertNotIn('last_sent_date', self.saved_state().get('delivery', {}))
        self.assertFalse((self.data / 'last_report.md').exists())

    def test_failed_translation_is_ok_when_model_successfully_processes_news(self):
        self.translation_ok = False
        code, status = self.run_report('--send')
        self.assertEqual(code, 0)
        self.assertEqual(status['mode'], 'normal')

    def test_business_rejection_does_not_record_delivery_and_can_be_retried(self):
        self.receipt = {'code': 19024}
        code, status = self.run_report('--send', '--skip-if-already-sent')
        self.assertEqual(code, 3)
        self.assertEqual(status['delivery'], 'rejected')
        self.assertNotIn('last_sent_date', self.saved_state().get('delivery', {}))
        self.receipt = {'code': 0}
        code, status = self.run_report('--send', '--skip-if-already-sent')
        self.assertEqual(code, 0)
        self.assertEqual(len(self.sent), 2)
        self.assertEqual(status['delivery'], 'sent')

    def test_missing_receipt_is_unconfirmed_and_not_recorded(self):
        self.receipt = {'msg': 'success'}
        code, status = self.run_report('--send')
        self.assertEqual(code, 3)
        self.assertEqual(status['delivery'], 'unconfirmed')
        self.assertNotIn('last_sent_date', self.saved_state().get('delivery', {}))

    def test_missing_webhook_is_not_attempted(self):
        with patch.dict('os.environ', {'FEISHU_WEBHOOK_URL': ''}):
            code, status = self.run_report('--send')
        self.assertEqual(code, 2)
        self.assertEqual(status['delivery'], 'not_attempted')
        self.assertEqual(self.sent, [])

    def test_missing_model_configuration_uses_verified_translation_with_notice(self):
        with patch.object(report, 'OPENAI_API_KEY', ''):
            code, status = self.run_report('--send')
        self.assertEqual(code, 0)
        self.assertEqual(status['mode'], 'direct_translation')
        self.assertIn('配置不完整', str(status['llm_failures']))

    def test_dry_run_never_sends_even_failure_notice(self):
        self.failing_stage = 'item_enrichment'
        self.translation_ok = False
        code, status = self.run_report('--dry-run')
        self.assertEqual(code, 5)
        self.assertEqual(status['delivery'], 'not_attempted')
        self.assertEqual(self.sent, [])

    def test_confirmed_duplicate_skips_before_fetching(self):
        (self.data / 'state.json').write_text(json.dumps({'delivery': {'last_sent_date': '2026-10-28'}}))
        with patch.object(report, 'fetch_section_items') as fetch:
            code, status = self.run_report('--send', '--skip-if-already-sent')
        self.assertEqual(code, 0)
        self.assertEqual(status['delivery'], 'already_sent')
        fetch.assert_not_called()
        self.assertEqual(self.sent, [])

    def test_unexpected_error_leaves_stage_and_does_not_send(self):
        with patch.object(report, 'fetch_section_items', side_effect=RuntimeError('private-details')):
            code, status = self.run_report('--send')
        self.assertEqual(code, 1)
        self.assertEqual(status['stage'], 'fetching')
        self.assertNotIn('private-details', str(status))
        self.assertEqual(self.sent, [])

    def test_news_and_holidays_share_total_budget_before_quality_check(self):
        for section in report.REPORT_SECTION_ORDER:
            if section in {'holiday_events', 'ops_suggestions'}:
                continue
            self.sections[section] = []
            for index in range(6):
                item = news_item()
                item.section = section
                item.title = f'Music film album news {section} {index}'
                item.link += f'/{section}/{index}'
                item.score += index
                self.sections[section].append(item)
        holidays = {'today': [
            {'name': f'Holiday {index}', 'country_name': '测试国家', 'date': date(2026, 10, 28), 'days_left': 0}
            for index in range(10)
        ], 'week': [], 'advance': []}
        self.failing_stage = 'item_enrichment'
        with patch.object(report, 'fetch_holiday_items', return_value=holidays):
            code, status = self.run_report('--send')
        self.assertEqual(code, 0)
        self.assertEqual(status['mode'], 'direct_translation')
        selected = json.loads((self.data / 'final_selected.json').read_text())
        self.assertEqual(len(selected), 26)
        self.assertEqual(len(selected) + 10, report.MAX_REPORT_ITEMS)

    def test_quality_failure_still_blocks_formal_report(self):
        with patch.object(report, 'validate_report_quality', return_value=['缺少合格信源']):
            code, status = self.run_report('--send')
        self.assertEqual(code, 4)
        self.assertIn('缺少合格信源', status['errors'])
        self.assertEqual(self.sent, [])
        self.assertNotIn('last_sent_date', self.saved_state().get('delivery', {}))


if __name__ == '__main__':
    unittest.main()
