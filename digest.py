#!/usr/bin/env python3
"""Daily arXiv digest. All model claims are grounded only in supplied abstracts."""
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
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / 'history.json'
SITE = ROOT / 'site' / 'index.html'
NS = {'a': 'http://www.w3.org/2005/Atom'}
QUERY = '(cat:cs.IR OR cat:cs.LG OR cat:cs.AI) AND (all:"recommender systems" OR all:"recommendation" OR all:"ranking" OR all:"reranking" OR all:"information retrieval" OR all:"search engine")'


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


def fetch_candidates(seen, now):
    # A rolling window catches weekends, delayed announcements and transient failures.
    start = (now - dt.timedelta(days=7)).strftime('%Y%m%d%H%M')
    end = now.strftime('%Y%m%d%H%M')
    query = f'{QUERY} AND submittedDate:[{start} TO {end}]'
    params = urllib.parse.urlencode({'search_query': query, 'start': 0, 'max_results': 200, 'sortBy': 'submittedDate', 'sortOrder': 'descending'})
    root = ET.fromstring(request('https://export.arxiv.org/api/query?' + params))
    found = []
    for entry in root.findall('a:entry', NS):
        url = entry.findtext('a:id', '', NS)
        paper_id = re.sub(r'v\d+$', '', url.rsplit('/', 1)[-1])
        if not re.fullmatch(r'\d{4}\.\d{4,5}', paper_id) or paper_id in seen:
            continue
        title = ' '.join(entry.findtext('a:title', '', NS).split())
        abstract = ' '.join(entry.findtext('a:summary', '', NS).split())
        if not title or not abstract:
            continue
        found.append({'id': paper_id, 'title': title, 'abstract': abstract, 'published': entry.findtext('a:published', '', NS), 'url': 'https://arxiv.org/abs/' + paper_id})
    return found


def select(candidates):
    if not candidates:
        return []
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY is not set')
    system = '''你是资深电商推荐与搜索算法研究员。用户负责大规模电商推荐精排阶段价值建模、重排生成，兼顾搜索。只依据给出的标题和摘要，从候选中严格挑选最多3篇有明确可迁移价值的论文，也可以选0篇。优先长期价值/转化价值/多目标建模、精排、生成式重排、列表级优化、搜索排序及工业实践。不要编造实验数据、架构细节或结论。摘要无法确认的内容明确写“摘要未说明”。输出严格 JSON 对象 {"papers":[{"id":"...","reason":"为何值得关注","method":"摘要中可确认的方法","application":"电商场景的潜在应用，明确为推测","limitations":"摘要未覆盖的验证点","tags":["标签"]}]}，所有文字用中文。只使用给定 id，不要输出其他文字。'''
    content = json.dumps([{'id': p['id'], 'title': p['title'], 'abstract': p['abstract']} for p in candidates], ensure_ascii=False)
    body = json.dumps({'model': os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}], 'response_format': {'type': 'json_object'}, 'temperature': 0.2, 'max_tokens': 3000}, ensure_ascii=False).encode()
    response = json.loads(request('https://api.deepseek.com/chat/completions', body, {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}))
    result = json.loads(response['choices'][0]['message']['content'])
    by_id = {p['id']: p for p in candidates}
    selected = []
    used = set()
    for item in result['papers']:
        if not isinstance(item, dict) or item.get('id') not in by_id or item['id'] in used:
            continue
        if any(not isinstance(item.get(k), str) or not item[k].strip() for k in ('reason', 'method', 'application', 'limitations')):
            continue
        used.add(item['id'])
        tags = item.get('tags', [])
        selected.append({**by_id[item['id']], **{k: item[k] for k in ('reason', 'method', 'application', 'limitations')}, 'tags': [x for x in tags if isinstance(x, str)][:5] if isinstance(tags, list) else []})
        if len(selected) == 3:
            break
    return selected


def render(history):
    esc = lambda value: html.escape(str(value), quote=True)
    sections = []
    for day in reversed(history['days']):
        cards = []
        for p in day['papers']:
            tags = ''.join(f'<span class="tag">{esc(t)}</span>' for t in p['tags'])
            blocks = ''.join(f'<div><h4>{label}</h4><p>{esc(p[key])}</p></div>' for label, key in [('推荐理由','reason'),('论文方法','method'),('业务启发 · 推测','application'),('待验证','limitations')])
            cards.append(f'''<article><div class="meta">{tags}<span>{esc(p['id'])}</span></div><h3><a href="{esc(p['url'])}" target="_blank" rel="noopener noreferrer">{esc(p['title'])}</a></h3><div class="details">{blocks}</div><details><summary>查看原始摘要</summary><p lang="en">{esc(p['abstract'])}</p></details></article>''')
        content = ''.join(cards) or '<div class="empty">当天没有达到筛选标准的新论文。</div>'
        sections.append(f'<section><div class="date"><h2>{esc(day["date"])}</h2><span>{len(day["papers"])} 篇精选 · {esc(day.get("candidates", 0))} 篇候选</span></div>{content}</section>')
    body = ''.join(sections) or '<div class="empty">首次工作流运行后，这里会出现论文精选。</div>'
    SITE.parent.mkdir(parents=True, exist_ok=True)
    SITE.write_text('''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>推荐与搜索 · 论文雷达</title><style>
:root{color-scheme:dark;font-family:system-ui,-apple-system,"PingFang SC",sans-serif;background:#0b111c;color:#e9eff8}*{box-sizing:border-box}body{margin:0}header{border-bottom:1px solid #253348;background:linear-gradient(120deg,#101d30,#0c1522);padding:3.5rem 1.5rem 3rem}.wrap{max-width:1000px;margin:auto}.eyebrow{color:#69e0c0;letter-spacing:.12em;font-weight:700;font-size:.9rem}h1{font-size:clamp(2rem,5vw,3.3rem);margin:.6rem 0}header p{color:#aebed1;line-height:1.8;max-width:700px}main{padding:1rem 1.5rem 5rem}.date{display:flex;align-items:baseline;justify-content:space-between;gap:1rem;margin-top:2rem;border-bottom:1px solid #29384b}.date span,.meta{color:#9fb2c8;font-size:.9rem}article,.empty{background:#121e2d;border:1px solid #28394d;border-radius:12px;padding:1.5rem;margin-top:1rem}article h3{font-size:1.2rem;line-height:1.5;margin:1rem 0 1.4rem}a{color:#e8f4ff;text-decoration:none}a:hover{text-decoration:underline;color:#69e0c0}.meta{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}.tag{background:#1c3b3b;color:#8ce8cb;padding:.25rem .55rem;border-radius:4px}.details{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:1rem 2rem}h4{color:#83dbc4;font-size:.9rem;margin:0 0 .4rem}p{line-height:1.75;margin:0;color:#c4d1df}details{border-top:1px solid #29384b;margin-top:1.2rem;padding-top:1rem}summary{cursor:pointer;color:#aebed1}details p{margin-top:1rem;font-size:.95rem}footer{color:#8296ac;margin-top:3rem;line-height:1.7}@media(max-width:650px){.details{grid-template-columns:1fr}.date{display:block}.date span{display:block;padding-bottom:.8rem}article{padding:1.2rem}}
</style></head><body><header><div class="wrap"><div class="eyebrow">ARXIV · DAILY RESEARCH BRIEF</div><h1>推荐与搜索 · 论文雷达</h1><p>面向电商精排、价值建模与生成式重排，每天从近期论文中精选最多 3 篇。基于摘要解读，业务应用为推测。</p></div></header><main class="wrap">''' + body + '''<footer>数据来自 arXiv，筛选和解读由 DeepSeek 生成。请结合原文验证；北京时间每日更新。</footer></main></body></html>''', encoding='utf-8')


def main():
    now = dt.datetime.now(dt.timezone.utc)
    today = now.astimezone(ZoneInfo('Asia/Shanghai')).date().isoformat()
    history = json.loads(DATA.read_text(encoding='utf-8')) if DATA.exists() else {'days': []}
    # Reruns on the same day must be idempotent, including days with zero results.
    if any(day['date'] == today for day in history['days']):
        print('Already processed today; regenerating site.')
        render(history)
        return
    seen = {p['id'] for day in history['days'] for p in day['papers']}
    candidates = fetch_candidates(seen, now)
    papers = select(candidates)
    history['days'].append({'date': today, 'candidates': len(candidates), 'papers': papers})
    DATA.parent.mkdir(parents=True, exist_ok=True)
    DATA.write_text(json.dumps(history, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    render(history)
    print(f'{today}: {len(candidates)} candidates, {len(papers)} selected')


if __name__ == '__main__':
    main()
