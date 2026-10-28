import hashlib
import io
import json
import unittest
import urllib.error
from unittest.mock import patch

import main as report


SYSTEM_PROMPT = 'Return a JSON object using only the supplied facts.'
USER_PAYLOAD = {'title': 'Artist announces a new album'}
RESULT = {'summary': '艺人宣布发行新专辑。'}


def chat_response(result=RESULT):
    return {'choices': [{'message': {'content': json.dumps(result, ensure_ascii=False)}, 'finish_reason': 'stop'}]}


def responses_response(result=RESULT):
    return {
        'status': 'completed',
        'output': [
            {'type': 'reasoning', 'summary': []},
            {'type': 'message', 'role': 'assistant', 'status': 'completed', 'content': [
                {'type': 'output_text', 'text': json.dumps(result, ensure_ascii=False)}
            ]},
        ],
    }


def http_error(url, code):
    return urllib.error.HTTPError(url, code, 'private-provider-error', {}, io.BytesIO(b''))


class EndpointTests(unittest.TestCase):
    def setUp(self):
        item = patch.dict('os.environ', {'LLM_API_STYLE': 'auto'})
        item.start()
        self.addCleanup(item.stop)

    def test_root_and_v1_prefer_responses(self):
        for base in ('https://gateway.invalid', 'https://gateway.invalid/',
                     'https://gateway.invalid/v1', 'https://gateway.invalid/v1/'):
            with self.subTest(base=base), patch.object(report, 'OPENAI_BASE_URL', base):
                self.assertEqual(report.llm_endpoint_candidates(), [
                    ('responses', 'https://gateway.invalid/v1/responses'),
                    ('chat', 'https://gateway.invalid/v1/chat/completions'),
                ])

    def test_explicit_endpoint_selects_protocol_and_preserves_custom_prefix(self):
        for prefix in ('https://gateway.invalid/v1', 'https://gateway.invalid/proxy/v2'):
            for protocol, suffix, other_suffix in (
                ('responses', '/responses', '/chat/completions'),
                ('chat', '/chat/completions', '/responses'),
            ):
                with self.subTest(prefix=prefix, protocol=protocol), \
                     patch.object(report, 'OPENAI_BASE_URL', prefix + suffix + '/'):
                    candidates = report.llm_endpoint_candidates()
                    self.assertEqual(candidates[0], (protocol, prefix + suffix))
                    self.assertEqual(candidates[1][1], prefix + other_suffix)
                    self.assertEqual(candidates[1][0], 'chat' if protocol == 'responses' else 'responses')

    def test_protocol_can_be_pinned_for_service_testing(self):
        for style, suffix in [('responses', '/responses'), ('chat', '/chat/completions')]:
            with self.subTest(style=style), \
                 patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1'), \
                 patch.dict('os.environ', {'LLM_API_STYLE': style}):
                self.assertEqual(report.llm_endpoint_candidates(), [(style, 'https://gateway.invalid/v1' + suffix)])

    def test_url_without_scheme_defaults_to_https(self):
        with patch.object(report, 'OPENAI_BASE_URL', 'gateway.invalid/v1/responses'):
            self.assertEqual(report.llm_endpoint_candidates()[0],
                             ('responses', 'https://gateway.invalid/v1/responses'))


class LlmApiTests(unittest.TestCase):
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

    def call(self):
        return report.call_llm_json(SYSTEM_PROMPT, USER_PAYLOAD, self.state,
                                    self.diagnostics, 'item_enrichment', self.health)

    def assert_failed_without_cache(self):
        self.assertIn('item_enrichment', self.health.llm_failures)
        self.assertFalse(self.state.get('llm_cache'))
        self.assertNotIn('private-test-key', str(self.diagnostics))
        self.assertNotIn('private-provider-error', str(self.diagnostics))

    def test_responses_payload_and_reasoning_before_message(self):
        with patch.object(report, 'post_json', return_value=responses_response()) as post:
            self.assertEqual(self.call(), RESULT)
        url, payload = post.call_args.args
        self.assertEqual(url, 'https://gateway.invalid/v1/responses')
        self.assertEqual(payload['model'], 'test-model')
        self.assertEqual(payload['text']['format'], {'type': 'json_object'})
        self.assertIs(payload['store'], False)
        self.assertIs(payload['stream'], False)
        self.assertNotIn('messages', payload)
        self.assertNotIn('response_format', payload)
        self.assertNotIn('temperature', payload)
        self.assertEqual([message['role'] for message in payload['input']], ['system', 'user'])
        self.assertEqual(payload['input'][0]['content'], SYSTEM_PROMPT)
        self.assertEqual(json.loads(payload['input'][1]['content']), USER_PAYLOAD)
        self.assertFalse(self.health.llm_failures)
        self.assertEqual(self.health.llm_protocols['item_enrichment'], 'responses')

    def test_responses_concatenates_split_output_text(self):
        response = responses_response()
        response['output'][1]['content'] = [
            {'type': 'output_text', 'text': '{"summary":'},
            {'type': 'output_text', 'text': '"新专辑已公布。"}'},
        ]
        with patch.object(report, 'post_json', return_value=response):
            self.assertEqual(self.call(), {'summary': '新专辑已公布。'})

    def test_responses_accepts_gateway_top_level_output_text(self):
        response = {'status': 'completed', 'output_text': json.dumps(RESULT)}
        with patch.object(report, 'post_json', return_value=response):
            self.assertEqual(self.call(), RESULT)

    def test_responses_without_optional_status_is_supported(self):
        response = responses_response()
        del response['status']
        with patch.object(report, 'post_json', return_value=response):
            self.assertEqual(self.call(), RESULT)

    def test_responses_refusal_is_not_cached_even_with_top_level_text(self):
        response = responses_response()
        response['output'][1]['content'] = [{'type': 'refusal', 'refusal': 'Cannot comply'}]
        response['output_text'] = json.dumps(RESULT)
        with patch.object(report, 'post_json', return_value=response):
            self.assertIsNone(self.call())
        self.assert_failed_without_cache()

    def test_responses_non_completed_status_is_failure_even_with_valid_json(self):
        for status in ('incomplete', 'failed', 'cancelled', 'queued', 'in_progress'):
            with self.subTest(status=status):
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                response = responses_response()
                response['status'] = status
                with patch.object(report, 'post_json', return_value=response):
                    self.assertIsNone(self.call())
                self.assert_failed_without_cache()

    def test_responses_incomplete_message_is_failure(self):
        response = responses_response()
        response['output'][1]['status'] = 'incomplete'
        with patch.object(report, 'post_json', return_value=response):
            self.assertIsNone(self.call())
        self.assert_failed_without_cache()

    def test_empty_invalid_or_non_text_responses_are_failures(self):
        responses = (
            {}, [], {'output': []}, {'output_text': ''},
            {'output': [{'type': 'reasoning', 'summary': []}]},
            {'output': [{'type': 'message', 'role': 'assistant', 'content': []}]},
            {'output': [{'type': 'message', 'role': 'assistant', 'content': [
                {'type': 'output_text', 'text': []}
            ]}]},
            {'output_text': 'not JSON'},
        )
        for response in responses:
            with self.subTest(response=response):
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                with patch.object(report, 'post_json', return_value=response):
                    self.assertIsNone(self.call())
                self.assert_failed_without_cache()

    def test_chat_payload_and_content_parts_remain_supported(self):
        response = {'choices': [{'finish_reason': 'stop', 'message': {'content': [
            {'type': 'text', 'text': '{"summary":'},
            {'type': 'text', 'text': '"聊天接口正常。"}'},
        ]}}]}
        with patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1/chat/completions'), \
             patch.object(report, 'post_json', return_value=response) as post:
            self.assertEqual(self.call(), {'summary': '聊天接口正常。'})
        url, payload = post.call_args.args
        self.assertEqual(url, 'https://gateway.invalid/v1/chat/completions')
        self.assertEqual(payload['response_format'], {'type': 'json_object'})
        self.assertEqual(payload['messages'][0]['role'], 'system')
        self.assertNotIn('input', payload)
        self.assertIs(payload['stream'], False)
        self.assertEqual(self.health.llm_protocols['item_enrichment'], 'chat')

    def test_chat_truncation_or_refusal_cannot_be_cached_as_success(self):
        for response in (
            {'choices': [{'finish_reason': 'length', 'message': {'content': json.dumps(RESULT)}}]},
            {'choices': [{'finish_reason': 'content_filter', 'message': {'content': json.dumps(RESULT)}}]},
            {'choices': [{'message': {'refusal': 'Cannot comply', 'content': json.dumps(RESULT)}}]},
        ):
            with self.subTest(response=response):
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                with patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1'), \
                     patch.object(report, 'post_json', return_value=response):
                    self.assertIsNone(self.call())
                self.assert_failed_without_cache()

    def test_404_and_405_switch_to_other_protocol_in_both_directions(self):
        for first, second, base in (
            ('responses', 'chat', 'https://gateway.invalid/custom/responses'),
            ('chat', 'responses', 'https://gateway.invalid/custom/chat/completions'),
        ):
            for status in (404, 405):
                with self.subTest(first=first, status=status):
                    self.state = {}
                    self.health = report.ReportHealth('2026-10-28')
                    fallback = chat_response() if second == 'chat' else responses_response()
                    error = http_error(base, status)
                    try:
                        with patch.object(report, 'OPENAI_BASE_URL', base), \
                             patch.object(report, 'post_json', side_effect=[error, fallback]) as post:
                            self.assertEqual(self.call(), RESULT)
                    finally:
                        error.close()
                    self.assertEqual(post.call_count, 2)
                    first_payload = post.call_args_list[0].args[1]
                    second_payload = post.call_args_list[1].args[1]
                    self.assertIn('input' if first == 'responses' else 'messages', first_payload)
                    self.assertIn('input' if second == 'responses' else 'messages', second_payload)
                    self.assertFalse(self.health.llm_failures)
                    self.assertNotIn('private-provider-error', str(self.diagnostics))

    def test_model_not_found_404_does_not_switch_protocol(self):
        bodies = [
            {'error': {'code': 'model_not_found'}},
            {'error': {'code': 'model_not_supported'}},
            {'error': {'type': 'model_not_found'}},
            {'code': 'model_not_found'},
        ]
        for payload in bodies:
            with self.subTest(payload=payload):
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                error = urllib.error.HTTPError('https://gateway.invalid/v1/responses', 404,
                                               'private-provider-error', {}, io.BytesIO(json.dumps(payload).encode()))
                try:
                    with patch.object(report, 'post_json', side_effect=error) as post:
                        self.assertIsNone(self.call())
                finally:
                    error.close()
                self.assertEqual(post.call_count, 1)
                self.assert_failed_without_cache()

    def test_auth_rate_limit_service_errors_or_timeout_do_not_switch_protocol(self):
        for status in (400, 401, 403, 429, 500, 503):
            with self.subTest(status=status):
                self.state = {}
                self.health = report.ReportHealth('2026-10-28')
                error = http_error('https://gateway.invalid', status)
                try:
                    with patch.object(report, 'post_json', side_effect=error) as post:
                        self.assertIsNone(self.call())
                finally:
                    error.close()
                self.assertEqual(post.call_count, 1)
                self.assert_failed_without_cache()
        self.state = {}
        self.health = report.ReportHealth('2026-10-28')
        with patch.object(report, 'post_json', side_effect=TimeoutError) as post:
            self.assertIsNone(self.call())
        self.assertEqual(post.call_count, 1)
        self.assert_failed_without_cache()

    def test_pinned_protocol_does_not_switch_on_404(self):
        error = http_error('https://gateway.invalid/v1/responses', 404)
        try:
            with patch.dict('os.environ', {'LLM_API_STYLE': 'responses'}), \
                 patch.object(report, 'post_json', side_effect=error) as post:
                self.assertIsNone(self.call())
        finally:
            error.close()
        self.assertEqual(post.call_count, 1)
        self.assert_failed_without_cache()

    def test_invalid_protocol_fails_before_network_request(self):
        with patch.dict('os.environ', {'LLM_API_STYLE': 'unknown'}), \
             patch.object(report, 'post_json') as post:
            self.assertIsNone(self.call())
        post.assert_not_called()
        self.assertIn('LLM_API_STYLE', str(self.health.llm_failures))

    def test_valid_response_is_reused_only_for_same_service(self):
        with patch.object(report, 'post_json', return_value=responses_response()) as post:
            self.assertEqual(self.call(), RESULT)
            self.assertEqual(self.call(), RESULT)
            self.assertEqual(post.call_count, 1)
            self.assertEqual(self.health.llm_protocols['item_enrichment'], 'cache')
            with patch.object(report, 'OPENAI_BASE_URL', 'https://other.invalid/v1/responses'):
                self.assertEqual(self.call(), RESULT)
            self.assertEqual(post.call_count, 2)

    def test_normalized_trailing_slash_uses_same_service_cache(self):
        with patch.object(report, 'post_json', return_value=responses_response()) as post:
            self.assertEqual(self.call(), RESULT)
            with patch.object(report, 'OPENAI_BASE_URL', 'https://gateway.invalid/v1/responses/'):
                self.assertEqual(self.call(), RESULT)
            self.assertEqual(post.call_count, 1)

    def test_legacy_cache_cannot_hide_new_configuration_failure(self):
        legacy_basis = {
            'namespace': 'item_enrichment', 'model': 'test-model',
            'system_prompt': SYSTEM_PROMPT, 'payload': USER_PAYLOAD,
        }
        key = hashlib.sha256(json.dumps(legacy_basis, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        self.state = {'llm_cache': {key: {'summary': '旧服务缓存'}}}
        with patch.object(report, 'post_json', side_effect=TimeoutError) as post:
            self.assertIsNone(self.call())
        post.assert_called_once()
        self.assertIn('item_enrichment', self.health.llm_failures)
        self.assertEqual(len(self.state['llm_cache']), 1)


if __name__ == '__main__':
    unittest.main()
