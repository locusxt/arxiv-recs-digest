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

    def test_explanation_is_expandable_and_escaped(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'SITE', Path(d) / 'index.html'):
            paper = dict(id='1234.56789', title='T', title_zh='中文', url='https://arxiv.org/abs/1234.56789', tags=[], explanation=dict(problem='<script>bad</script>', method='方法', application='推测', caveat='限制'))
            digest.render({'days': [{'date': '2026-01-01', 'papers': [paper]}]})
            page = digest.SITE.read_text()
            self.assertIn('<details class="analysis">', page)
            self.assertIn('点击查看文章解析', page)
            self.assertLess(page.index('点击查看文章解析'), page.index('主要内容'))
            self.assertNotIn('<script>bad</script>', page)

    def test_same_day_is_idempotent(self):
        with tempfile.TemporaryDirectory() as d, patch.object(digest, 'DATA', Path(d) / 'history.json'), patch.object(digest, 'SITE', Path(d) / 'index.html'), patch.object(digest, 'fetch_candidates') as fetch:
            today = digest.dt.datetime.now(digest.ZoneInfo('Asia/Shanghai')).date().isoformat()
            digest.DATA.write_text(json.dumps({'days': [{'date': today, 'papers': []}]}))
            digest.main()
            fetch.assert_not_called()

    def test_fulltext_review_does_not_require_exact_quotes(self):
        result = dict(worth_reading=True, score=90, rubric=dict(fit=5,evidence=4,action=5), primary_topic='value', evidence=dict(page=1, finding='实验', quote='full paper excerpt'), title_zh='译文', summary='方法', reason='价值', tags=[], institutions=['公司'], explanation=dict(problem='问题', method='方法', application='应用', caveat='限制'))
        paper = dict(id='1234.56789', title='paper', pdf_url='https://arxiv.org/pdf/1234.56789v1')
        with patch.object(research, 'pdf_pages', return_value=['full paper excerpt']), patch.object(research, 'ask', return_value=result):
            self.assertEqual(research.review(paper)['source_type'], 'pdf_fulltext')

    def test_shortlist_cannot_invent_papers(self):
        with patch.object(research, 'ask', return_value={'candidates': [{'id': 'invented', 'score': 100}, {'id': '1', 'score': 80}]}):
            self.assertEqual([p['id'] for p in research.shortlist([dict(id='1', title='t', abstract='a')])], ['1'])

    def test_keyword_filter_preserves_retrieval_candidates(self):
        ranking = [dict(id=str(i), title='CTR ranking reranking GMV multi-objective', abstract='recommendation ranking', published='2026-01-01') for i in range(20)]
        retrieval = dict(id='retrieval', title='Candidate retrieval two-tower', abstract='semantic id retrieval', published='2026-01-01')
        self.assertIn('retrieval', [p['id'] for p in research.keyword_prefilter(ranking + [retrieval], limit=8, reserve=2)])
        self.assertGreater(research.keyword_score(ranking[0])[0], research.keyword_score(dict(title='A generic paper', abstract='about graphs'))[0])

    def test_industry_keyword_variants_and_word_boundaries(self):
        examples = {
            'Learning to Rank in Search': 'ranking',
            'Multi-task conversion rate prediction': 'value',
            'Counterfactual learning with exposure bias': 'training',
            'Collaborative filtering with hard negatives': 'retrieval',
            'Queries and relevance for search': 'search',
            'Personalization with sequential recommendation': 'recommendation',
            'Real-time nearline serving': 'systems',
            'Causal inference for recommendation': 'training',
            'Counterfactual recommendation': 'training',
            'DAU and user retention': 'growth',
            'LLM4Rec': 'llm4rec',
            'Reusable KV Memory for Efficient LLM Recommenders': 'llm4rec',
            'Generative recommendation': 'llm4rec',
        }
        for title, topic in examples.items():
            with self.subTest(title=title):
                self.assertIn(topic, research.keyword_score(dict(title=title, abstract=''))[1])
        self.assertNotIn('ranking', research.keyword_score(dict(title='Frank reads books', abstract=''))[1])
        self.assertNotIn('ranking', research.keyword_score(dict(title='Low-rank approximation for matrices', abstract=''))[1])
        self.assertIn('ranking', research.keyword_score(dict(title='Low-rank features for recommendation ranking', abstract=''))[1])
        self.assertNotIn('value', research.keyword_score(dict(title='A conversation about images', abstract=''))[1])

    def test_cached_rejections_and_successes_survive_reselection(self):
        papers = [dict(id=i, title=i, abstract='', pdf_url='https://arxiv.org/pdf/'+i+'v1') for i in ('1', '2')]
        accepted = dict(papers[0], score=85, primary_topic='ranking', rubric=dict(fit=5,evidence=4,action=4), reason='r')
        cache = {}
        with patch.object(research, 'shortlist', return_value=papers), patch.object(research, 'review', side_effect=[accepted, None]) as review:
            for _ in range(2):
                self.assertEqual(research.select(papers, cache, []), [accepted])
            self.assertEqual(review.call_count, 2)

    def test_diversity_only_breaks_close_scores(self):
        papers = [dict(id=str(i), score=s, primary_topic=t, rubric=dict(fit=5,evidence=4))
                  for i,(s,t) in enumerate([(91,'ranking'), (90,'value'), (85,'causal')])]
        self.assertEqual([p['id'] for p in research.finalists(papers, ['ranking'])], ['1','0','2'])

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

    def test_abstract_shortlist_uses_balanced_batches(self):
        papers = [dict(id=str(i), title='t', abstract='a') for i in range(60)]
        batch_sizes = []
        def fake_ask(system, content):
            batch = json.loads(content)
            batch_sizes.append(len(batch))
            return {'candidates': [{'id': p['id'], 'score': 80} for p in batch[:6]]}
        with patch.object(research, 'ask', side_effect=fake_ask):
            shortlist = research.shortlist(papers)
        self.assertEqual(batch_sizes, [30, 30])
        self.assertEqual(len(shortlist), 8)

    def test_medical_penalty_is_soft_and_contextual(self):
        clinical = dict(title='Uplift modelling for blood pressure monitoring', abstract='patient care')
        clinical_recs = dict(title='Recommendation ranking for patient care', abstract='clinical')
        score, groups = research.keyword_score(clinical)
        self.assertIn('training', groups)
        self.assertEqual(score, 0)
        self.assertGreater(research.keyword_score(clinical_recs)[0], 0)

    def test_balance_change_preserves_decimals(self):
        before = [{'currency': 'CNY', 'total_balance': '10.25'}]
        after = [{'currency': 'CNY', 'total_balance': '10.10'}]
        self.assertEqual(digest.balance_changes(before, after)[0]['decrease'], '0.15')

if __name__ == '__main__':
    unittest.main()
