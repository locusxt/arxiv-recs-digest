#!/usr/bin/env python3
"""Daily arXiv digest with original-PDF grounded reviews."""
import datetime as dt
import html
import json
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'history.json'
SITE = ROOT / 'site' / 'index.html'
NS = {'a': 'http://www.w3.org/2005/Atom'}
QUERIES = [
    '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:recommendation OR all:recommender)',
    '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:ranking OR all:reranking OR all:re-ranking)',
    '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:"information retrieval" OR all:"search engine" OR all:"search ranking")',
    '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:"lifetime value" OR all:"conversion rate prediction" OR all:"click-through rate" OR all:"multi-objective recommendation")',
    '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:LLM4Rec OR all:"generative recommendation" OR all:"causal recommendation" OR all:"daily active users" OR all:DAU OR all:"user retention" OR all:"user engagement")',
]


def request(url, payload=None, headers=None):
    req = urllib.request.Request(url, data=payload, headers={'User-Agent': 'arxiv-recs-digest/1.0 (daily research digest)', **(headers or {})})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=90) as response:
                return response.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            if isinstance(exc, urllib.error.HTTPError) and exc.code not in (429, 500, 502, 503, 504):
                raise RuntimeError(f'HTTP {exc.code} from {urllib.parse.urlsplit(url).hostname}') from None
            if attempt == 2:
                raise RuntimeError(f'Request failed for {urllib.parse.urlsplit(url).hostname}') from None
            time.sleep(3 * (attempt + 1))


def title_key(title):
    return re.sub(r'[^a-z0-9]+', '', title.lower())


def fetch_candidates(seen, now, seen_titles=None):
    # A rolling window catches weekends, delayed announcements and transient failures.
    start = (now - dt.timedelta(days=7)).strftime('%Y%m%d%H%M')
    end = now.strftime('%Y%m%d%H%M')
    found, collected = [], set()
    seen_titles = seen_titles or set()
    collected_titles = set()
    for index, query in enumerate(QUERIES):
        if index:
            time.sleep(3)  # arXiv API asks clients to pause between requests.
        query = f'{query} AND submittedDate:[{start} TO {end}]'
        params = urllib.parse.urlencode({'search_query': query, 'start': 0, 'max_results': 200, 'sortBy': 'submittedDate', 'sortOrder': 'descending'})
        root = ET.fromstring(request('https://export.arxiv.org/api/query?' + params))
        for entry in root.findall('a:entry', NS):
            url = entry.findtext('a:id', '', NS)
            versioned_id = url.rsplit('/', 1)[-1]
            paper_id = re.sub(r'v\d+$', '', versioned_id)
            if not re.fullmatch(r'\d{4}\.\d{4,5}v\d+', versioned_id) or paper_id in seen or paper_id in collected:
                continue
            title = ' '.join(entry.findtext('a:title', '', NS).split())
            abstract = ' '.join(entry.findtext('a:summary', '', NS).split())
            key = title_key(title)
            if not title or not abstract or key in seen_titles or key in collected_titles:
                continue
            collected_titles.add(key)
            authors = [' '.join(author.findtext('a:name', '', NS).split()) for author in entry.findall('a:author', NS)]
            collected.add(paper_id)
            found.append({'id': paper_id, 'title': title, 'abstract': abstract, 'authors': [name for name in authors if name], 'published': entry.findtext('a:published', '', NS), 'url': 'https://arxiv.org/abs/' + versioned_id, 'pdf_url': 'https://arxiv.org/pdf/' + versioned_id})
    return found


def select(candidates):
    from research import select as select_research
    return select_research(candidates)


def render(history):
    esc = lambda value: html.escape(str(value), quote=True)
    sections = []
    for day in reversed(history['days']):
        cards = []
        for p in day['papers']:
            tags = ''.join(f'<span class="tag">{esc(t)}</span>' for t in p.get('tags', []))
            author_list = p.get('authors', [])
            authors = '、'.join(author_list[:3]) + (' 等' if len(author_list) > 3 else '') if author_list else '未记录'
            institutions = '、'.join(p.get('institutions', [])) or '未记录'
            title_zh = p.get('title_zh') or '中文标题未记录'
            summary = p.get('summary') or p.get('method', '未记录')
            reason = p.get('reason', '未记录')
            score = p.get('score')
            rating = (Decimal(str(score)) / 20).quantize(Decimal('0.1'), rounding=ROUND_HALF_UP) if isinstance(score, (int, float)) and not isinstance(score, bool) and 0 <= score <= 100 else None
            score_label = f'<span class="score">推荐评分 {rating} / 5</span>' if rating is not None else '<span class="score">暂无评分</span>'
            published = str(p.get('published', ''))[:10] or '未记录'
            explanation = p.get('explanation')
            if isinstance(explanation, dict) and all(explanation.get(k) for k in ('problem', 'method', 'application', 'caveat')):
                expl_blocks = ''.join(f'<div class="analysis-block"><h4>{label}</h4><p>{esc(explanation[key])}</p></div>' for label, key in [('研究问题', 'problem'), ('方法怎么做', 'method'), ('业务启发 · 推测', 'application'), ('阅读时注意', 'caveat')])
                expl_html = f'<details class="analysis"><summary><span class="show-label">点击查看文章解析</span><span class="hide-label">收起文章解析</span></summary><div class="analysis-body">{expl_blocks}<p class="analysis-note">基于论文原文生成，具体细节请结合原文核对。</p></div></details>'
            else:
                expl_html = '<p class="analysis-unavailable">这篇历史论文暂无详细解析。</p>'
            cards.append(f'''<article><div class="meta">{score_label}{tags}<span>{esc(p['id'])}</span></div><h3><a href="{esc(p['url'])}" target="_blank" rel="noopener noreferrer">{esc(title_zh)}</a></h3><p class="english">{esc(p['title'])}</p><p class="authors">作者：{esc(authors)}<br>机构：{esc(institutions)}<br>arXiv 首次提交：{esc(published)}（UTC）</p>{expl_html}<div class="details"><div><h4>主要内容</h4><p>{esc(summary)}</p></div><div><h4>推荐理由</h4><p>{esc(reason)}</p></div></div><p class="paper-link"><a href="{esc(p.get('pdf_url', p['url']))}" target="_blank" rel="noopener noreferrer">阅读论文 PDF</a></p></article>''')
        content = ''.join(cards) or '<div class="empty">当天没有达到筛选标准的新论文。</div>'
        runs = day.get('usage_runs', [])
        if runs:
            latest = runs[-1]
            amounts = '、'.join(f'{esc(b["currency"])} {esc(b["total_balance"])}' for b in latest.get('balance_after', [])) or '查询失败'
            total = sum(run.get('total_tokens', 0) for run in runs)
            prompt = sum(run.get('prompt_tokens', 0) for run in runs)
            completion = sum(run.get('completion_tokens', 0) for run in runs)
            changes = {}
            for run in runs:
                for item in run.get('balance_change', []):
                    try:
                        changes[item['currency']] = changes.get(item['currency'], Decimal('0')) + Decimal(item['decrease'])
                    except (InvalidOperation, KeyError):
                        pass
            change = '、'.join(f'{esc(currency)} {esc(value)}' for currency, value in changes.items()) or '无法计算'
            incomplete = '；此前运行未记录，用量不完整' if day.get('usage_incomplete') else ''
            usage_text = f'<details class="usage-detail"><summary>查看当日用量与余额</summary><p class="usage">当日已记录 {len(runs)} 次运行：{total} tokens（输入 {prompt} / 输出 {completion}）；账户余额减少合计 {change}；最新余额 {amounts}{incomplete}。余额变化可能包含其他调用或充值；失败运行可能未计入。</p></details>'
        else:
            usage_text = '<p class="usage">该日期的用量和余额未记录。</p>'
        sections.append(f'<section><div class="date"><h2>{esc(day["date"])}</h2><span>{len(day["papers"])} 篇精选 · {esc(day.get("candidates", 0))} 篇候选</span></div>{usage_text}{content}</section>')
    body = ''.join(sections) or '<div class="empty">首次工作流运行后，这里会出现论文精选。</div>'
    SITE.parent.mkdir(parents=True, exist_ok=True)
    SITE.write_text('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>推荐与搜索 · 论文雷达</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"PingFang SC",sans-serif;background:#0b111c;color:#e9eff8}*{box-sizing:border-box}body{margin:0}header{border-bottom:1px solid #253348;background:linear-gradient(120deg,#101d30,#0c1522);padding:3.5rem 1.5rem 3rem}.wrap{max-width:1000px;margin:auto}.eyebrow{color:#69e0c0;letter-spacing:.12em;font-weight:700;font-size:.9rem}h1{font-size:clamp(2rem,5vw,3.3rem);margin:.6rem 0}header p{color:#aebed1;line-height:1.8;max-width:700px}main{padding:1rem 1.5rem 5rem}.date{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-top:2rem;border-bottom:1px solid #29384b}.date span,.meta{color:#9fb2c8;font-size:.9rem}article,.empty{overflow-wrap:anywhere;background:#121e2d;border:1px solid #28394d;border-radius:12px;padding:1.5rem;margin-top:1rem}article h3{font-size:1.2rem;line-height:1.5;margin:1rem 0 .3rem}.english,.authors{color:#9fb2c8;margin-bottom:1rem}.usage{font-size:.9rem;margin-top:1rem;color:#9fb2c8}.paper-link{margin-top:1rem}a{color:#e8f4ff;text-decoration:none}a:hover{text-decoration:underline;color:#69e0c0}.meta{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}.score{color:#ffe09a;font-weight:700;margin-right:.3rem}.tag{background:#1c3b3b;color:#8ce8cb;padding:.25rem .55rem;border-radius:4px}.details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem 2rem}h4{color:#83dbc4;font-size:.9rem;margin:0 0 .4rem}p{line-height:1.75;margin:0;color:#c4d1df}details{margin-top:1.2rem}summary{cursor:pointer;color:#aebed1}summary:focus-visible,a:focus-visible{outline:3px solid #69e0c0;outline-offset:4px}.analysis{border:1px solid #60ddbf;border-radius:10px;background:#193d3b;overflow:hidden;margin:0 0 1.25rem}.analysis summary{display:flex;align-items:center;justify-content:space-between;min-height:52px;padding:.75rem 1rem;color:#b5ffe9;font-size:1rem;font-weight:700;list-style:none}.analysis summary::-webkit-details-marker{display:none}.analysis summary:after{content:'+';font-size:1.3rem}.analysis[open] summary:after{content:'−'}.hide-label{display:none}.analysis[open] .show-label{display:none}.analysis[open] .hide-label{display:inline}.analysis-body{padding:.2rem 1rem 1rem;border-top:1px solid #345467}.analysis-block{padding-top:1rem}.analysis-note{font-size:.9rem;color:#9fb2c8;margin-top:1rem}.analysis-unavailable{margin-top:1rem;color:#9fb2c8;font-size:.9rem}.usage-detail summary{min-height:44px;display:flex;align-items:center;color:#9fb2c8}.usage-detail .usage{margin-top:0}footer{color:#8296ac;margin-top:3rem;line-height:1.7}@media(max-width:650px){header{padding:2.2rem 1rem 2rem}main{padding:0 1rem 4rem}h1{font-size:2rem}.details{grid-template-columns:1fr;gap:1rem}.date{display:block;margin-top:1.5rem}.date span{display:block;padding-bottom:.8rem}article{padding:1rem;border-radius:12px}article h3{font-size:1.12rem}.english,.authors{font-size:.95rem}.meta{gap:.4rem}.tag{padding:.3rem .55rem}.paper-link a{display:inline-flex;align-items:center;min-height:44px}}
</style></head><body><header><div class="wrap"><div class="eyebrow">ARXIV · DAILY RESEARCH BRIEF</div><h1>推荐与搜索 · 论文雷达</h1><p>面向电商精排、价值建模与生成式重排，每天从近期论文中精选最多 3 篇。阅读 PDF 原文后筛选与解读，兼顾召回、搜索和全链路。</p></div></header><main class="wrap">''' + body + '''<footer>数据来自 arXiv，筛选和解读由 DeepSeek 生成；PDF 抽取和模型解读可能有误，请结合原文验证；北京时间每日更新。</footer></main></body></html>''', encoding='utf-8')


def get_balance():
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        return []
    try:
        data = json.loads(request('https://api.deepseek.com/user/balance', headers={'Authorization': 'Bearer ' + key}))
        return [{'currency': b['currency'], 'total_balance': b['total_balance']} for b in data.get('balance_infos', []) if isinstance(b.get('currency'), str) and isinstance(b.get('total_balance'), str)]
    except (RuntimeError, ValueError, KeyError, TypeError):
        print('Balance unavailable; continuing without it.')
        return []


def balance_changes(before, after):
    previous = {b['currency']: b['total_balance'] for b in before}
    changes = []
    for b in after:
        try:
            if b['currency'] in previous:
                amount = Decimal(previous[b['currency']]) - Decimal(b['total_balance'])
                if amount.is_finite():
                    changes.append({'currency': b['currency'], 'decrease': str(amount)})
        except (InvalidOperation, KeyError):
            continue
    return changes

def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    history = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {'days': []}
    # Explicitly refresh today after a prompt change, preserving all earlier days.
    previous_today = next((day for day in history['days'] if day['date'] == today), None)
    refresh_existing = os.environ.get('REFRESH_EXISTING') == 'true'
    if refresh_existing or os.environ.get('REFRESH_TODAY') == 'true':
        history['days'] = [day for day in history['days'] if day['date'] != today]
    # Reruns on the same day must be idempotent, including days with zero results.
    if any(day['date'] == today for day in history['days']):
        print('Already processed today; regenerating site.')
        render(history)
        return
    seen = set(history.get('recommended_ids', [])) | {p['id'] for day in history['days'] for p in day['papers']}
    # Same-day manual refresh can re-review its own papers, never older results.
    if previous_today and not any(day['date'] == today for day in history['days']):
        previous_ids = {p['id'] for p in previous_today['papers']}
        older_ids = {p['id'] for day in history['days'] for p in day['papers']}
        seen -= previous_ids - older_ids
    seen_titles = set(history.get('recommended_titles', [])) | {title_key(p.get('title', '')) for day in history['days'] for p in day['papers']}
    if previous_today and not any(day['date'] == today for day in history['days']):
        older_titles = {title_key(p.get('title', '')) for day in history['days'] for p in day['papers']}
        seen_titles -= {title_key(p.get('title', '')) for p in previous_today['papers']} - older_titles
    if refresh_existing:
        if not previous_today or not previous_today.get('papers'):
            raise RuntimeError('No existing papers for today to update')
        candidates = previous_today['papers']
    else:
        candidates = fetch_candidates(seen, now, seen_titles)
    from research import AUDIT, USAGE, review
    before = get_balance()
    if refresh_existing:
        papers = []
        for paper in candidates:
            result = review(paper)
            if result is None:
                raise RuntimeError('Existing paper no longer meets review criteria')
            papers.append(result)
    else:
        papers = select(candidates)
    after = get_balance()
    current = {**USAGE, 'balance_after': after, 'balance_change': balance_changes(before, after)}
    # Preserve completed earlier runs on the same date; old runs were not metered.
    previous_runs = previous_today.get('usage_runs', []) if previous_today else []
    runs = previous_runs + [current]
    history['days'].append({'date': today, 'candidates': previous_today.get('candidates', len(candidates)) if refresh_existing else len(candidates), 'papers': papers, 'usage_runs': runs, 'usage': current, 'usage_incomplete': bool(previous_today and (previous_today.get('usage_incomplete') or not previous_runs))})
    ever_recommended = set(history.get('recommended_ids', []))
    ever_recommended.update(p['id'] for day in history['days'] for p in day['papers'])
    if previous_today:
        ever_recommended.update(p['id'] for p in previous_today['papers'])
    history['recommended_ids'] = sorted(ever_recommended)
    ever_titles = set(history.get('recommended_titles', []))
    ever_titles.update(title_key(p.get('title', '')) for day in history['days'] for p in day['papers'])
    if previous_today:
        ever_titles.update(title_key(p.get('title', '')) for p in previous_today['papers'])
    history['recommended_titles'] = sorted(t for t in ever_titles if t)
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(history, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    render(history)
    if not refresh_existing:
        (DATA.parent / 'latest_audit.json').write_text(json.dumps({'date': today, **AUDIT}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(f'{today}: {len(candidates)} candidates, {len(papers)} selected')


if __name__ == '__main__':
    main()
