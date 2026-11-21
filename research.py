"""Two-stage selection and evidence-grounded reading of original PDFs."""
import io
import json
import os
import re
from pypdf import PdfReader

import digest

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


SCREEN_PROMPT = '''你是大型电商推荐和搜索技术负责人，服务一位负责全链路的推荐算法工程师；其直接工作是精排阶段的价值建模、重排生成，也希望了解召回、搜索与系统前沿。根据标题和摘要进行初筛，选出最多5篇值得阅读全文的候选，也可选0篇。直接解决长期价值/GMV/CVR、样本选择偏差、多目标优化、精排、生成式列表重排的论文通常优先；有扎实方法或工业经验的召回、检索、特征与实时服务同样欢迎。不要仅因有LLM、工业或数据集名称而高分。评分0-100反映潜在技术价值和关联度，不能把摘要结论当作已验证。输出JSON对象 {"candidates":[{"id":"原始id","score":整数,"reason":"初筛理由"}]}。只用提供的id。'''
REVIEW_PROMPT = """你是大型电商推荐/搜索资深研究员。读者负责推荐全链路，重点是精排价值建模和生成式重排，也关注召回、检索和系统。仔细阅读PDF全文后判断是否值得读，可以不推荐。只依据原文，不编造事实或结果；将线上A/B、离线评估和仿真严格区分；不将端到端收益归因于没有单独验证的模块。机构仅依据原文作者署名页，无法确认写“原文未说明”，不要把数据集所属公司写成作者公司。输出严格JSON：{\"worth_reading\":true或false,\"score\":0到100整数,\"title_zh\":\"标题中文翻译\",\"authors\":[\"原文作者姓名，按原顺序\"],\"institutions\":[\"作者所属公司或机构\"],\"summary\":\"主要内容，中文2句以内，说明方法和最重要的实验结论及证据边界\",\"reason\":\"推荐理由，中文1句，说明对电商推荐工程师的具体价值和关键限制\",\"tags\":[\"3到5个中文关键词\"]}。不要输出原文摘录，论文事实与迁移推测分清。对于文本不足以判断的论文设置worth_reading为false。"""


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


def shortlist(candidates):
    scores = {}
    for offset in range(0, len(candidates), 50):
        batch = candidates[offset:offset + 50]
        data = [{'id': p['id'], 'title': p['title'], 'abstract': p['abstract']} for p in batch]
        results = ask(SCREEN_PROMPT, json.dumps(data, ensure_ascii=False)).get('candidates')
        if not isinstance(results, list):
            raise RuntimeError('Invalid shortlist response')
        allowed = {p['id'] for p in batch}
        for item in results:
            if isinstance(item, dict) and item.get('id') in allowed and isinstance(item.get('score'), (int, float)) and not isinstance(item['score'], bool):
                scores[item['id']] = max(scores.get(item['id'], 0), min(100, item['score']))
    return sorted((p for p in candidates if p['id'] in scores), key=lambda p: scores[p['id']], reverse=True)[:12]


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
    error = None
    for attempt in range(2):
        try:
            extra = '' if not attempt else '\n上次输出格式有误，请严格按要求输出完整JSON。'
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
    if not isinstance(result.get('score'), (int, float)) or isinstance(result['score'], bool) or not 0 <= result['score'] <= 100:
        raise ValueError('Invalid score')
    tags = result.get('tags') if isinstance(result.get('tags'), list) else []
    institutions = result.get('institutions') if isinstance(result.get('institutions'), list) else []
    authors = result.get('authors') if isinstance(result.get('authors'), list) else []
    authors = paper.get('authors') or [x for x in authors if isinstance(x, str)]
    return {**paper, 'authors': authors, **{k: result[k] for k in required}, 'score': result['score'], 'tags': [x for x in tags if isinstance(x, str)][:5], 'institutions': [x for x in institutions if isinstance(x, str)][:10], 'source_type': 'pdf_fulltext', 'pdf_pages': len(pages)}


def select(candidates):
    if not candidates:
        return []
    selected, failures, reviewed = [], [], 0
    for paper in shortlist(candidates):
        try:
            result = review(paper)
            reviewed += 1
            if result:
                selected.append(result)
        except (ValueError, RuntimeError, OSError) as exc:
            failures.append(f"{paper['id']}: {exc}")
    if failures:
        print('Papers skipped (full text/review validation): ' + '; '.join(failures))
    if not reviewed and failures:
        raise RuntimeError('No shortlisted papers could be reviewed; retry the workflow')
    return sorted(selected, key=lambda p: p['score'], reverse=True)[:3]
