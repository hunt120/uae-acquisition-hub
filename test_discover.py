import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError

import discover


def response(data):
    return io.BytesIO(json.dumps(data).encode())


def model(name, method='generateContent'):
    return {'name': f'models/{name}', 'supportedGenerationMethods': [method]}


def generation(companies, finish='STOP'):
    return {'candidates': [{
        'finishReason': finish,
        'content': {'parts': [{'text': json.dumps({'companies': companies})}]},
    }]}


@patch.dict(os.environ, {'GEMINI_API_KEY': 'test-key'})
class GeminiTests(unittest.TestCase):
    def test_paginates_and_reuses_working_model_after_404(self):
        first = model('gemini-9.2-flash')
        second = model('gemini-9.1-flash')
        missing = HTTPError('https://example.invalid', 404, 'test error', {}, None)
        with patch('discover.urllib.request.urlopen', side_effect=[
            response({'models': [first, model('gemini-99-image')], 'nextPageToken': 'next page'}),
            response({'models': [second, model('gemini-99-flash', 'countTokens')]}),
            missing, response(generation([])), response(generation([])),
        ]) as request:
            client = discover.Gemini()
            items = [{'title': 'Imdaad is hiring in Dubai - Publisher'}]
            self.assertEqual(discover.gemini_batch(client, items), [])
            self.assertEqual(discover.gemini_batch(client, items), [])
        requests = [args[0] for args, _ in request.call_args_list]
        self.assertIn('pageToken=next+page', requests[1].full_url)
        self.assertTrue(requests[2].full_url.endswith(first['name'] + ':generateContent'))
        self.assertTrue(requests[3].full_url.endswith(second['name'] + ':generateContent'))
        self.assertEqual(requests[3].full_url, requests[4].full_url)
        for sent in requests:
            self.assertNotIn('test-key', sent.full_url)
            self.assertEqual(sent.get_header('X-goog-api-key'), 'test-key')
        body = json.loads(requests[3].data)
        self.assertNotIn('Publisher', body['contents'][0]['parts'][0]['text'])

    def test_falls_back_when_generation_times_out(self):
        with patch('discover.urllib.request.urlopen', side_effect=[
            response({'models': [model('gemini-9-flash'), model('gemini-8-flash')]}),
            TimeoutError('test-key'), response(generation([])),
        ]) as request:
            client = discover.Gemini()
            self.assertEqual(discover.gemini_batch(client, []), [])
        self.assertEqual(request.call_count, 3)
        self.assertEqual(client.model, 'models/gemini-8-flash')

    def test_all_models_missing_is_fatal(self):
        missing = HTTPError('https://example.invalid', 404, 'test-key', {}, None)
        with patch('discover.urllib.request.urlopen', side_effect=[
            response({'models': [model('gemini-9-flash')]}), missing,
        ]):
            with self.assertRaisesRegex(RuntimeError, 'HTTP 404 for every compatible'):
                discover.Gemini().generate({})

    def test_non_model_error_does_not_switch_models_or_leak_provider_message(self):
        denied = HTTPError('https://example.invalid', 403, 'test-key', {}, None)
        with patch('discover.urllib.request.urlopen', side_effect=[
            response({'models': [model('gemini-9-flash'), model('gemini-8-flash')]}), denied,
        ]) as request:
            with self.assertRaisesRegex(RuntimeError, '^Gemini generation returned HTTP 403$'):
                discover.Gemini().generate({})
        self.assertEqual(request.call_count, 2)

    def test_incomplete_and_invalid_output_are_fatal(self):
        item = {'title': 'Imdaad hires workers in Dubai'}
        for result in (generation([], 'MAX_TOKENS'), generation([{'index': 7}]), {'candidates': []}):
            with self.subTest(result=result), patch.object(discover.Gemini, 'generate', return_value=result):
                client = object.__new__(discover.Gemini)
                with self.assertRaisesRegex(RuntimeError, 'incomplete or invalid'):
                    discover.gemini_batch(client, [item])


class ExtractionTests(unittest.TestCase):
    def test_rejects_false_companies_and_accepts_explicit_subjects(self):
        cases = [
            ('Imdaad', 'Imdaad to hire 50 employees in Dubai', 'hiring', True),
            ('Acme Logistics LLC', 'Dubai-based Acme Logistics LLC opens a warehouse', 'expansion', True),
            ('UAE Employers', 'UAE employers plan to hire staff', 'hiring', False),
            ('Global Retail Group', 'Global Retail Group opens a Dubai store', 'expansion', False),
            ('Imdaad', 'Imdaad is hiring in Dubai', 'expansion', False),
            ('Dubai Taxi Company', 'Dubai Taxi Company to train 400 employees in AI', 'hiring', False),
            ('DataFlow Group', 'DMW and DataFlow Group sign agreement to launch DREAM platform', 'expansion', False),
            ('Emaar', 'Emaar launches an app to help shoppers find its nearest store', 'expansion', False),
            ('Imdaad', 'Report: UAE hiring rises, says Imdaad', 'hiring', False),
            ('Imdaad Hires Workers', 'Imdaad hires workers in Dubai', 'hiring', False),
            ('Emaar', 'Emaar Hospitality LLC opens a hotel in Dubai', 'expansion', False),
            ('Emaar', 'Emaar launches new partnership with a hotel in Dubai', 'expansion', False),
        ]
        for name, headline, event, expected in cases:
            with self.subTest(headline=headline):
                self.assertEqual(discover.valid_company(name, headline, event), expected)

    def test_existing_file_survives_later_batch_failure(self):
        old = b'{"signals":[],"prospects":[{"name":"Imdaad"}]}\n'
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'signals.json'
            path.write_bytes(old)
            rss = b'<rss><channel></channel></rss>'
            with patch.multiple(discover, OUT=path, QUERIES=['query']), \
                    patch('discover.urllib.request.urlopen', return_value=io.BytesIO(rss)), \
                    patch('discover.ai_extract', side_effect=RuntimeError('AI batch 2 failed: HTTP 404')):
                with self.assertRaisesRegex(SystemExit, 'AI batch 2 failed'):
                    discover.main()
            self.assertEqual(path.read_bytes(), old)


if __name__ == '__main__':
    unittest.main()
