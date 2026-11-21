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

    def test_keyword_filter_preserves_retrieval_candidates(self):
        ranking = [dict(id=str(i), title='CTR ranking reranking GMV multi-objective', abstract='recommendation ranking', published='2026-01-01') for i in range(20)]
        retrieval = dict(id='retrieval', title='Candidate retrieval two-tower', abstract='semantic id retrieval', published='2026-01-01')
        self.assertIn('retrieval', [p['id'] for p in research.keyword_prefilter(ranking + [retrieval], limit=8, reserve=2)])
        self.assertGreater(research.keyword_score(ranking[0])[0], research.keyword_score(dict(title='A generic paper', abstract='about graphs'))[0])

    def test_title_normalization(self):
        self.assertEqual(digest.title_key('Learning-to Rank!'), digest.title_key('Learning to Rank'))

    def test_display_five_point_score_and_date(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'SITE', Path(d) / 'index.html'):
            paper = dict(id='1234.56789', title='T', title_zh='中', url='https://arxiv.org/abs/1234.56789', score=85, published='2026-11-19T07:40:54Z', authors=['a','b','c','d'], tags=[])
            digest.render({'days': [{'date': '2026-11-21', 'papers': [paper]}]})
            page = digest.SITE.read_text()
            self.assertIn('推荐评分 4.3 / 5', page)
            self.assertIn('2026-11-19（UTC）', page)
            self.assertIn('a、b、c 等', page)

    def test_balance_change_preserves_decimals(self):
        before = [{'currency': 'CNY', 'total_balance': '10.25'}]
        after = [{'currency': 'CNY', 'total_balance': '10.10'}]
        self.assertEqual(digest.balance_changes(before, after)[0]['decrease'], '0.15')

if __name__ == '__main__':
    unittest.main()
