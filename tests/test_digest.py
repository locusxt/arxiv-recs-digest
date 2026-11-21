import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import digest


class DigestTests(unittest.TestCase):
    def test_selection_validates_ids_deduplicates_and_limits(self):
        candidates = [{'id': str(i), 'title': 'title', 'abstract': 'abstract'} for i in range(5)]
        def item(i):
            return dict(id=str(i), reason='r', method='m', application='a', limitations='l', tags=[])
        result = {'papers': [item(0), item(0), item(99), item(1), item(2), item(3)]}
        response = json.dumps({'choices': [{'message': {'content': json.dumps(result)}}]}).encode()
        with patch.dict('os.environ', {'DEEPSEEK_API_KEY': 'test'}), patch.object(digest, 'request', return_value=response):
            self.assertEqual([p['id'] for p in digest.select(candidates)], ['0', '1', '2'])

    def test_render_escapes_untrusted_html(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'SITE', Path(d) / 'index.html'):
            paper = dict(id='1234.56789', title='<script>alert(1)</script>', url='https://arxiv.org/abs/1234.56789', abstract='x', reason='r', method='m', application='a', limitations='l', tags=[])
            digest.render({'days': [{'date': '2026-01-01', 'papers': [paper]}]})
            result = digest.SITE.read_text()
            self.assertNotIn('<script>alert(1)</script>', result)
            self.assertIn('&lt;script&gt;', result)

    def test_same_day_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'DATA', Path(d) / 'history.json'), patch.object(digest, 'SITE', Path(d) / 'index.html'), patch.object(digest, 'fetch_candidates') as fetch:
            today = digest.dt.datetime.now(digest.ZoneInfo('Asia/Shanghai')).date().isoformat()
            digest.DATA.write_text(json.dumps({'days': [{'date': today, 'papers': []}]}))
            digest.main()
            fetch.assert_not_called()

if __name__ == '__main__':
    unittest.main()
