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
            paper = dict(id='1234.56789', title='<script>alert(1)</script>', url='https://arxiv.org/abs/1234.56789', abstract='x', reason='r', method='m', application='a', limitations='l', tags=[])
            digest.render({'days': [{'date': '2026-01-01', 'papers': [paper]}]})
            result = digest.SITE.read_text()
            self.assertNotIn('<script>alert(1)</script>', result)
            self.assertIn('&lt;script&gt;', result)
            self.assertIn('仅基于摘要', result)

    def test_same_day_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'DATA', Path(d) / 'history.json'), patch.object(digest, 'SITE', Path(d) / 'index.html'), patch.object(digest, 'fetch_candidates') as fetch:
            today = digest.dt.datetime.now(digest.ZoneInfo('Asia/Shanghai')).date().isoformat()
            digest.DATA.write_text(json.dumps({'days': [{'date': today, 'papers': []}]}))
            digest.main()
            fetch.assert_not_called()

    def test_evidence_must_match_actual_page(self):
        quotes = [f'This is valid quotation number {i} copied directly from the paper.' for i in range(3)]
        result = dict(worth_reading=True, score=90, reason='r', method='m', evidence_result='e', application='a', limitations='l', experiment='x', tags=[], citations=[{'page': 1, 'quote': quote} for quote in quotes])
        paper = dict(id='1234.56789', title='paper')
        with patch.object(research, 'pdf_pages', return_value=[' '.join(quotes), 'another page']), patch.object(research, 'ask', return_value=result):
            self.assertEqual(len(research.review(paper)['citations']), 3)
            result['citations'][0]['page'] = 2
            with self.assertRaises(ValueError):
                research.review(paper)

    def test_shortlist_cannot_invent_papers(self):
        with patch.object(research, 'ask', return_value={'candidates': [{'id': 'invented', 'score': 100}, {'id': '1', 'score': 80}]}):
            self.assertEqual([p['id'] for p in research.shortlist([dict(id='1', title='t', abstract='a')])], ['1'])

if __name__ == '__main__':
    unittest.main()
