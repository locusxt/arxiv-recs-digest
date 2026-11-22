"""Two-stage selection and evidence-grounded reading of original PDFs."""
import hashlib
import io
import json
import os
import re
from pypdf import PdfReader
from pypdf.errors import PdfReadError

import digest

AUDIT = {}

USAGE = {'calls': 0, 'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0, 'prompt_cache_hit_tokens': 0, 'prompt_cache_miss_tokens': 0, 'missing_usage': 0}

def record_usage(usage):
    USAGE['calls'] += 1
    if not isinstance(usage, dict):
        USAGE['missing_usage'] += 1
        return
    for field in ('prompt_tokens', 'completion_tokens', 'total_tokens', 'prompt_cache_hit_tokens', 'prompt_cache_miss_tokens'):
        value = usage.get(field)
        if isinstance(value, int) and value >= 0:
            USAGE[field] += value


SCREEN_PROMPT = '''你是大型电商推荐和搜索技术负责人，服务一位负责全链路的推荐算法工程师；其直接工作是精排阶段的价值建模、重排生成，也关注因果推断、DAU与留存、LLM4Rec，以及召回、搜索与系统前沿。根据标题和摘要进行初筛，选出最多6篇值得阅读全文的候选，也可选0篇。直接解决长期价值/GMV/CVR、样本选择偏差、多目标优化、精排、生成式列表重排、推荐与增长相关的因果推断、用户活跃留存、LLM4Rec的论文通常优先；有扎实方法或工业经验的召回、检索、特征与实时服务同样欢迎。不要仅因有LLM、工业或数据集名称而高分。评分0-100反映潜在技术价值和关联度，不能把摘要结论当作已验证。输出JSON对象 {"candidates":[{"id":"原始id","score":整数,"reason":"初筛理由"}]}。只用提供的id。'''
REVIEW_PROMPT = """你是大型电商推荐/搜索资深研究员。读者负责推荐全链路，重点是精排价值建模、生成式重排、因果推断、DAU增长与用户留存、LLM4Rec，也关注召回、检索和系统，以及能明确迁移到这些场景的高效Transformer、MoE和多模态表征。仔细阅读PDF全文后判断是否值得读，可以不推荐。只依据原文，不编造事实或结果；明确核对策略是按用户、会话还是按请求产生，不得混淆配置生成和在线读取的粒度；将线上A/B、离线评估和仿真严格区分；不将端到端收益归因于没有单独验证的模块。机构仅依据原文作者署名页，无法确认写“原文未说明”，不要把数据集所属公司写成作者公司。输出严格JSON：{\"worth_reading\":true或false,\"title_zh\":\"标题中文翻译\",\"authors\":[\"原文作者姓名，按原顺序\"],\"institutions\":[\"作者所属公司或机构\"],\"summary\":\"主要内容，中文2句以内，说明方法和最重要的实验结论及证据边界\",\"reason\":\"推荐理由，中文1句，说明对电商推荐工程师的具体价值和关键限制\",\"explanation\":{\"problem\":\"要解决什么问题，用一句大白话说明，避免重复论文标题\",\"method\":\"方法怎么做：用通俗中文写3至4句、总长尽量不超过180字，按输入、关键步骤和输出讲清楚；避免公式、参数名、英文缩写堆砌，必须使用术语时紧跟白话解释；不要罗列工程细节\",\"application\":\"电商推荐可能如何借鉴，明确标记为推测\",\"caveat\":\"一句话说明主要证据限制\"},\"tags\":[\"3到5个中文关键词\"]}。不要输出原文摘录，论文事实与迁移推测分清。对于文本不足以判断的论文设置worth_reading为false。"""

REVIEW_PROMPT += """对值得读的论文，另返回 rubric 对象，fit、evidence、action 三项各取整数0至5。fit 从泛相关、可迁移到直接解决读者任务；evidence 从缺乏对照、单一实验到与核心主张匹配且有充分对照的验证；action 从模糊灵感到可指出输入、对照和评价指标的可行试验。另给 primary_topic，取 value/ranking/retrieval/search/recommendation/systems/training/causal/growth/llm4rec 之一。另给 evidence 对象，page 是输入中 PDF PAGE 的整数页码，finding 是一句中文，说明该页支持的实验类型、结论或局限，quote 是该页连续的一小段可核对的原文。只引用你实际看到的文字。"""


def ask(system, content, max_tokens=4000):
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY is not set')
    payload = json.dumps({'model': os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}], 'response_format': {'type': 'json_object'}, 'temperature': 0.1, 'max_tokens': max_tokens}, ensure_ascii=False).encode()
    response = json.loads(digest.request('https://api.deepseek.com/chat/completions', payload, {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}))
    record_usage(response.get('usage'))
    choice = response['choices'][0]
    if choice.get('finish_reason') != 'stop':
        raise RuntimeError('DeepSeek response incomplete')
    try:
        result = json.loads(choice['message']['content'])
    except (ValueError, TypeError) as exc:
        raise RuntimeError('Invalid DeepSeek JSON response') from exc
    if not isinstance(result, dict):
        raise RuntimeError('DeepSeek did not return a JSON object')
    return result


# Local ranking is deliberately a broad relevance filter, not the final rating.
TOPICS = {
    # Domain-weighted signals; broad words alone should not dominate selection.
    'value': (5, [r'\blifetime[ -]value\b', r'\blong[ -]term[ -]value\b', r'\b(?:ltv|clv|gmv|cvr|ctcvr)\b', r'\bconversion(?:[ -]rate|[ -]prediction)?\b', r'\bmulti[ -](?:objective|task)\b', r'\bdelayed[ -](?:feedback|conversion)\b', r'\b(?:revenue|purchase|value)[ -](?:prediction|model(?:ing|ling)?)\b']),
    'ranking': (4, [r'\bre[ -]?rank(?:ing|er|ers)?\b', r'(?<!low-)(?<!low )\brank(?:ing|er|ers|ed)?\b(?![ -]one\b)', r'\bslate(?:s)?\b', r'\bwhole[ -]page\b', r'\bpage[ -]optimization\b', r'\blistwise\b', r'\bpairwise\b', r'\bclick[ -]through(?:[ -]rate)?\b', r'\bctr\b', r'\blearning[ -]to[ -]rank\b']),
    'retrieval': (3, [r'\bretriev(?:al|er|ers|e|ing)\b', r'\brecall\b', r'\bcandidate[ -](?:generation|retrieval|selection)\b', r'\btwo[ -]tower\b', r'\bsemantic[ -]id(?:s)?\b', r'\bcollaborative[ -]filtering\b', r'\b(?:negative[ -]sampl(?:ing|es)|hard[ -]negative(?:s)?)\b']),
    'search': (3, [r'\bsearch(?:ing)?\b', r'\bquer(?:y|ies)\b', r'\binformation[ -]retrieval\b', r'\brelevance\b', r'\bquery[ -](?:understanding|intent|rewrit(?:ing|e))\b']),
    'recommendation': (3, [r'\brecommend(?:ation|er|ers|ations)\b', r'\bpersonaliz(?:ation|ed)\b', r'\bsequential[ -](?:recommendation|model(?:ing|ling)?)\b', r'\buser[ -](?:interest|intent|behavior|behaviour)\b', r'\b(?:session|interest)[ -]based\b']),
    'systems': (2, [r'\bonline[ -]serving\b', r'\breal[ -]time\b', r'\blatency\b', r'\bnear[ -]?line\b', r'\bproduction[ -]system\b', r'\blarge[ -]scale\b', r'\bmodel[ -]distillation\b', r'\bdistill(?:ation|ed)?\b']),
    'growth': (3, [r'\bdau\b', r'\bdaily[ -]active[ -]users?\b', r'\buser[ -](?:retention|engagement|growth|reactivation|churn)\b', r'\bchurn[ -]prediction\b', r'\b(?:long[ -]term|daily)[ -]engagement\b']),
    'llm4rec': (4, [r'\bllm4rec\b', r'\bllm[ -](?:recommend(?:ation|er|ers|ations)|ranking|retrieval)\b', r'\bllm[ -](?:based|driven|powered)[ -](?:recommendation|recommender|ranking|retrieval)\b', r'\b(?:generative|language[ -]model)[ -](?:recommendation|recommender|ranking|retrieval)\b', r'\blarge[ -]language[ -]models?[ -]for[ -](?:recommendation|ranking|retrieval)\b']),
    'causal': (4, [r'\b(?:causal inference|counterfactual|uplift|treatment effects?|off[ -]policy evaluation|online experiments?|a/b test(?:s|ing)?)\b']),
    'training': (2, [r'\b(?:selection|position|exposure|popularity)[ -]bias\b', r'\bcold[ -]start\b', r'\b(?:exploration|exploitation)\b', r'\b(?:bandit|bandits)\b', r'\b(?:uplift|counterfactual|causal)[ -](?:model(?:ing|ling)?|inference|learning|effect(?:s)?)\b', r'\b(?:causal|counterfactual)[ -](?:recommendation|ranking|inference)\b', r'\b(?:treatment[ -]effect|propensity[ -]score|inverse[ -]propensity[ -]scor(?:ing|e))\b', r'\bcontrastive[ -]learning\b', r'\b(?:a/b|ab)[ -]test(?:ing)?\b']),
}



def keyword_score(paper):
    title = paper.get('title', '').lower()
    abstract = paper.get('abstract', '').lower()
    score, groups = 0, set()
    for topic, (weight, patterns) in TOPICS.items():
        hits = sum(bool(re.search(pattern, abstract)) for pattern in patterns)
        title_hits = sum(bool(re.search(pattern, title)) for pattern in patterns)
        if topic == 'causal' and not re.search(r'\b(?:users?|recommend\w*|ranking|click\w*|retention|engagement|exposure|conversion|online (?:experiments?|a/b)|advertising)\b', title + ' ' + abstract):
            continue
        if hits or title_hits:
            groups.add(topic)
            score += weight * (min(hits, 3) + 2 * min(title_hits, 2))
    # Soft penalty for domain-specific work without an explicit recommender context.
    # It remains eligible, since methods can still transfer across domains.
    domain_text = title + ' ' + abstract
    unrelated_domain = re.search(r'\b(?:clinical|patient|patients|medical|biomedical|blood pressure|drug discovery|disease)\b', domain_text)
    rec_context = re.search(r'\b(?:recommend(?:ation|er|ations|ers)|search engine|e[ -]?commerce|advertis(?:ing|ement)|click[ -]through|ctr|cvr)\b', domain_text)
    if unrelated_domain and not rec_context:
        score = max(0, score - 10)
    return score, groups


def keyword_prefilter(candidates, limit=60, reserve=4, scores=None):
    if scores is None:
        scores = {p['id']: keyword_score(p) for p in candidates}
    ranked = sorted(candidates, key=lambda p: (scores[p['id']][0], p.get('published', '')), reverse=True)
    # Reserve room for different pipeline stages before filling remaining slots.
    chosen, seen = [], set()
    for topic in ('value', 'causal', 'ranking', 'retrieval', 'search', 'recommendation', 'systems', 'training', 'growth', 'llm4rec'):
        count = 0
        for paper in ranked:
            if len(chosen) >= limit or count >= reserve:
                break
            if paper['id'] not in seen and topic in scores[paper['id']][1]:
                chosen.append(paper)
                seen.add(paper['id'])
                count += 1
    for paper in ranked:
        if len(chosen) >= limit:
            break
        if paper['id'] not in seen:
            chosen.append(paper)
            seen.add(paper['id'])
    return sorted(chosen, key=lambda p: (scores[p['id']][0], p.get('published', '')), reverse=True)


def shortlist(candidates):
    scores = {}
    # Share highly ranked papers across batches competing for six nominations.
    batches = (len(candidates) + 29) // 30
    for offset in range(batches):
        batch = candidates[offset::batches]
        data = [{'id': p['id'], 'title': p['title'], 'abstract': p['abstract']} for p in batch]
        results = ask(SCREEN_PROMPT, json.dumps(data, ensure_ascii=False)).get('candidates')
        if not isinstance(results, list):
            raise RuntimeError('Invalid shortlist response')
        allowed = {p['id'] for p in batch}
        for item in results:
            if isinstance(item, dict) and item.get('id') in allowed and isinstance(item.get('score'), (int, float)) and not isinstance(item['score'], bool):
                scores[item['id']] = max(scores.get(item['id'], 0), min(100, item['score']))
    result = sorted((p for p in candidates if p['id'] in scores), key=lambda p: scores[p['id']], reverse=True)[:8]
    AUDIT['abstract_candidates'] = [{'id': p['id'], 'score': scores[p['id']]} for p in candidates if p['id'] in scores]
    AUDIT['shortlist'] = [{'id': p['id'], 'score': scores[p['id']]} for p in result]
    return result


def pdf_pages(pdf_url):
    raw = digest.request(pdf_url)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError('PDF exceeds 25 MB')
    pdf = PdfReader(io.BytesIO(raw))
    if not 2 <= len(pdf.pages) <= 50:
        raise ValueError('PDF page count outside supported range')
    pages = [page.extract_text() or '' for page in pdf.pages]
    if sum(len(p) for p in pages) < 5000 or sum(len(p) for p in pages) > 250000:
        raise ValueError('PDF text too short or too long for a reliable review')
    return pages


def review(paper):
    pages = pdf_pages(paper['pdf_url'])
    fulltext = '\n\n'.join(f'--- PDF PAGE {i} ---\n{text}' for i, text in enumerate(pages, 1))
    content = f"标题：{paper['title']}\narXiv ID：{paper['id']}\n以下为论文PDF原文：\n{fulltext}"
    content += "\n首页 summary 只用一句话讲方法，尽量不超过50个汉字。reason 用一句话讲可借鉴之处及关键限制，尽量不超过45字。实验数字和基线比较放入展开的 evidence.finding。"
    error = None
    for attempt in range(2):
        try:
            extra = '' if not attempt else f'\n上次校验反馈：{error}。请检查对应字段，quote 须从所标 PDF PAGE 逐字复制，返回完整 JSON。'
            return validate_review(paper, pages, ask(REVIEW_PROMPT, content + extra, max_tokens=2500))
        except (ValueError, RuntimeError) as exc:
            error = exc
    raise ValueError(f'Review failed after retry: {error}')


def validate_review(paper, pages, result):
    if not isinstance(result.get('worth_reading'), bool):
        raise ValueError('Missing worth_reading boolean')
    if not result['worth_reading']:
        return None
    required = ('title_zh', 'summary', 'reason')
    if any(not isinstance(result.get(k), str) or not result[k].strip() for k in required):
        raise ValueError('Review missing required fields')
    explanation = result.get('explanation')
    if not isinstance(explanation, dict) or any(not isinstance(explanation.get(k), str) or not explanation[k].strip() for k in ('problem', 'method', 'application', 'caveat')):
        raise ValueError('Review missing explanation')
    rubric = result.get('rubric')
    weights = {'fit': 8, 'evidence': 7, 'action': 5}
    if not isinstance(rubric, dict) or any(type(rubric.get(k)) is not int or not 0 <= rubric[k] <= 5 for k in weights):
        raise ValueError('Invalid review rubric')
    topic = result.get('primary_topic')
    if not isinstance(topic, str) or topic not in TOPICS:
        raise ValueError('Invalid primary topic')
    evidence = result.get('evidence')
    if not isinstance(evidence, dict):
        raise ValueError('Missing PDF evidence')
    page, quote, finding = (evidence.get(k) for k in ('page', 'quote', 'finding'))
    if type(page) is not int or not 1 <= page <= len(pages) or not isinstance(finding, str) or not finding.strip():
        raise ValueError('Invalid evidence page or finding')
    normalize = lambda text: ''.join(text.casefold().split())
    if not isinstance(quote, str) or len(normalize(quote)) < 12 or normalize(quote) not in normalize(pages[page - 1]):
        raise ValueError('Evidence excerpt absent from cited page')
    tags = result.get('tags') if isinstance(result.get('tags'), list) else []
    institutions = result.get('institutions') if isinstance(result.get('institutions'), list) else []
    authors = result.get('authors') if isinstance(result.get('authors'), list) else []
    authors = paper.get('authors') or [x for x in authors if isinstance(x, str)]
    return {**paper, 'authors': authors, 'explanation': explanation, **{k: result[k] for k in required}, 'score': sum(weights[k] * rubric[k] for k in weights), 'rubric': rubric, 'primary_topic': topic, 'evidence': {'page': page, 'finding': finding}, 'tags': [x for x in tags if isinstance(x, str)][:5], 'institutions': [x for x in institutions if isinstance(x, str)][:10], 'source_type': 'pdf_fulltext', 'pdf_pages': len(pages)}


def coverage_topic(paper):
    # Broad ranking labels hide different engineering problems. Use the same
    # title signals for today's candidates and pre-rubric history.
    title = paper.get('title', '').lower()
    for topic, pattern in (
        ('calibration', r'calibrat'),
        ('bundling', r'\bbundl'),
        ('reranking', r'whole.page|re.ranking|reranking'),
        ('ctr', r'\bctr\b|click.through'),
    ):
        if re.search(pattern, title):
            return topic
    return paper.get('primary_topic') or next(iter(paper.get('tags', [])), 'other')


def finalists(papers, recent_topics):
    remaining = list(papers)
    chosen = []
    topics = list(recent_topics)
    while remaining and len(chosen) < 3:
        best = max(p['score'] for p in remaining)
        near = [p for p in remaining if p['score'] >= best - 2]
        winner = max(near, key=lambda p: (-topics.count(coverage_topic(p)), p['score'], p['rubric']['evidence'], p['rubric']['fit'], p['id']))
        chosen.append(winner)
        topics.append(coverage_topic(winner))
        remaining.remove(winner)
    return chosen


def select(candidates, cache, recent_topics, checkpoint=None):
    if not candidates:
        AUDIT.update({'candidates': [], 'prefilter': [], 'shortlist': [], 'reviews': []})
        return []
    selected, failures, reviewed = [], [], 0
    scores = {p['id']: keyword_score(p) for p in candidates}
    AUDIT['candidates'] = [{'id': p['id'], 'title': p['title'], 'abstract': p['abstract'], 'published': p.get('published', ''), 'keyword_score': scores[p['id']][0], 'topics': sorted(scores[p['id']][1])} for p in candidates]
    filtered = keyword_prefilter(candidates, scores=scores)
    AUDIT['prefilter'] = [p['id'] for p in filtered]
    AUDIT['reviews'] = []
    print(f'Keyword prefilter: {len(candidates)} -> {len(filtered)} candidates')
    for paper in shortlist(filtered):
        try:
            signature = hashlib.sha256((REVIEW_PROMPT + os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat')).encode()).hexdigest()
            key = signature + '/' + paper['pdf_url'].rsplit('/', 1)[-1]
            cached = key in cache
            if not cached:
                cache[key] = review(paper)
            result = cache[key]
            reviewed += 1
            AUDIT['reviews'].append({'id': paper['id'], 'cached': cached, 'status': 'eligible' if result else 'rejected', 'score': result.get('score') if result else None, 'reason': result.get('reason') if result else None})
            if result:
                selected.append(result)
        except (ValueError, RuntimeError, OSError, PdfReadError) as exc:
            failures.append(f"{paper['id']}: {exc}")
            AUDIT['reviews'].append({'id': paper['id'], 'status': 'error', 'error': str(exc)})
            continue
        if not cached and checkpoint:
            checkpoint(cache)
    if failures:
        print('Papers skipped (full text/review validation): ' + '; '.join(failures))
    if not reviewed and failures:
        raise RuntimeError('No shortlisted papers could be reviewed; retry the workflow')
    result = finalists(selected, recent_topics)
    AUDIT['eligible'] = [{k: p[k] for k in ('id', 'rubric', 'primary_topic', 'score')} for p in selected]
    AUDIT['recent_topics'] = recent_topics
    AUDIT['selected'] = [p['id'] for p in result]
    return result
