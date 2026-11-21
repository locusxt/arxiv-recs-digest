import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import digest
import research

class DigestTests(unittest.TestCase):
    def test_render_escapes_untrusted_html(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'SITE', Path(d) / 'index.html'):
            paper = dict(id='1234.56789', title='<script>alert(1)</script>', url='https://arxiv.org/abs/1234.56789', abstract='x', reason='r', summary='m', title_zh='中文', tags=[])
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

    def test_fulltext_review_does_not_require_exact_quotes(self):
        result = dict(worth_reading=True, score=90, title_zh='译文', summary='方法', reason='价值', tags=[], institutions=['公司'])
        paper = dict(id='1234.56789', title='paper', pdf_url='https://arxiv.org/pdf/1234.56789v1')
        with patch.object(research, 'pdf_pages', return_value=['full paper']), patch.object(research, 'ask', return_value=result):
            self.assertEqual(research.review(paper)['source_type'], 'pdf_fulltext')

    def test_shortlist_cannot_invent_papers(self):
        with patch.object(research, 'ask', return_value={'candidates': [{'id': 'invented', 'score': 100}, {'id': '1', 'score': 80}]}):
            self.assertEqual([p['id'] for p in research.shortlist([dict(id='1', title='t', abstract='a')])], ['1'])

    def test_balance_change_preserves_decimals(self):
        before = [{'currency': 'CNY', 'total_balance': '10.25'}]
        after = [{'currency': 'CNY', 'total_balance': '10.10'}]
        self.assertEqual(digest.balance_changes(before, after)[0]['decrease'], '0.15')

if __name__ == '__main__':
    unittest.main()
