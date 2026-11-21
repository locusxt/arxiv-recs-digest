"""Two-stage selection and evidence-grounded reading of original PDFs."""
import io
import json
import os
import re
from pypdf import PdfReader

import digest

SCREEN_PROMPT = '''你是大型电商推荐和搜索技术负责人，服务一位负责全链路的推荐算法工程师；其直接工作是精排阶段的价值建模、重排生成，也希望了解召回、搜索与系统前沿。根据标题和摘要进行初筛，选出最多5篇值得阅读全文的候选，也可选0篇。直接解决长期价值/GMV/CVR、样本选择偏差、多目标优化、精排、生成式列表重排的论文通常优先；有扎实方法或工业经验的召回、检索、特征与实时服务同样欢迎。不要仅因有LLM、工业或数据集名称而高分。评分0-100反映潜在技术价值和关联度，不能把摘要结论当作已验证。输出JSON对象 {"candidates":[{"id":"原始id","score":整数,"reason":"初筛理由"}]}。只用提供的id。'''
REVIEW_PROMPT = '''你是大型电商推荐/搜索资深研究员，读者负责全链路，重点是精排价值建模和生成式重排，也希望拓宽召回、检索和系统视野。请仔细阅读下面论文的PDF全文文本（按PDF页码标记，公式或表格可能提取不完整），独立判断是否值得其阅读，客观且严格。可判定不值得：不要为了凑数推荐。只依赖原文，不猜测缺失数字、因果关系、实验对象和生产条件。区分绝对百分点与相对百分比；区分线上实验验证了哪个组件，别把整体系统上线效果归因于未做线上消融的模块。引用页码时必须是PDF的实际页码。引用内容必须是原文中连续的英文短句，原样复制且不得修改字符；挑选分别支持方法、实验结果和限制的3条证据，每条 quote 至少35字符，每条 page 是数字。全文未显示的信息写“原文未说明”，文字抽取不清楚也明确指出。业务迁移是假设，不能写成论文结论。判断产业价值须考虑实际场景/目标、对照基线是否足够强、数据或线上实验的证据强度、计算和服务开销、可以实施的最小验证。输出JSON：{"worth_reading":true或false,"score":0到100整数,"reason":"一句话结论和匹配程度","method":"核心机制、目标函数或训练与推理过程","evidence_result":"数据集、基线、具体结果；区分离线、线上和指标","application":"明确标记为业务迁移假设，说明具体落点和前提","limitations":"可信度、消融与部署限制；若没有则原文未说明","experiment":"在电商中可执行的最小离线及线上验证与护栏","tags":["中文标签"],"citations":[{"page":页码,"quote":"英文原文连续摘录"},{"page":页码,"quote":"英文原文连续摘录"},{"page":页码,"quote":"英文原文连续摘录"}]}。如果论文没有足够文本或证据请设置worth_reading为false。输出中文，保留专有名词，严格JSON。'''


def ask(system, content, max_tokens=4000):
    key = os.environ.get('DEEPSEEK_API_KEY')
    if not key:
        raise RuntimeError('DEEPSEEK_API_KEY is not set')
    payload = json.dumps({'model': os.environ.get('DEEPSEEK_MODEL', 'deepseek-chat'), 'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}], 'response_format': {'type': 'json_object'}, 'temperature': 0.1, 'max_tokens': max_tokens}, ensure_ascii=False).encode()
    response = json.loads(digest.request('https://api.deepseek.com/chat/completions', payload, {'Authorization': 'Bearer ' + key, 'Content-Type': 'application/json'}))
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


def pdf_pages(paper_id):
    raw = digest.request('https://arxiv.org/pdf/' + paper_id)
    if len(raw) > 25 * 1024 * 1024:
        raise ValueError('PDF exceeds 25 MB')
    pdf = PdfReader(io.BytesIO(raw))
    if not 2 <= len(pdf.pages) <= 50:
        raise ValueError('PDF page count outside supported range')
    pages = [page.extract_text() or '' for page in pdf.pages]
    if sum(len(p) for p in pages) < 5000 or sum(len(p) for p in pages) > 250000:
        raise ValueError('PDF text too short or too long for a reliable review')
    return pages


def normalized(text):
    return re.sub(r'\s+', ' ', text).strip()


def review(paper):
    pages = pdf_pages(paper['id'])
    fulltext = '\n\n'.join(f'--- PDF PAGE {i} ---\n{text}' for i, text in enumerate(pages, 1))
    content = f"标题：{paper['title']}\narXiv ID：{paper['id']}\n以下为论文PDF原文：\n{fulltext}"
    error = None
    for attempt in range(2):
        try:
            extra = '' if not attempt else '\n上一次输出未通过格式或引文校验。请严格输出完整字段，citations 必须是至少三条不同的、从对应页逐字复制的原文短句；无足够原文证据则 worth_reading 为 false。'
            result = ask(REVIEW_PROMPT, content + extra, max_tokens=5000)
            return validate_review(paper, pages, result)
        except (ValueError, RuntimeError) as exc:
            error = exc
    raise ValueError(f'Review failed after retry: {error}')


def validate_review(paper, pages, result):
    if not isinstance(result.get('worth_reading'), bool):
        raise ValueError('Missing worth_reading boolean')
    if not result['worth_reading']:
        return None
    required = ('reason', 'method', 'evidence_result', 'application', 'limitations', 'experiment')
    if any(not isinstance(result.get(k), str) or not result[k].strip() for k in required):
        raise ValueError('Review missing required fields')
    if not isinstance(result.get('score'), (int, float)) or isinstance(result['score'], bool) or not 0 <= result['score'] <= 100:
        raise ValueError('Invalid score')
    citations = result.get('citations')
    if not isinstance(citations, list):
        raise ValueError('Missing evidence')
    verified = []
    for citation in citations:
        if not isinstance(citation, dict):
            continue
        page, quote = citation.get('page'), citation.get('quote')
        if isinstance(page, int) and not isinstance(page, bool) and 1 <= page <= len(pages) and isinstance(quote, str) and len(normalized(quote)) >= 35 and normalized(quote) in normalized(pages[page - 1]):
            evidence = {'page': page, 'quote': normalized(quote)}
            if evidence not in verified:
                verified.append(evidence)
    if len(verified) < 3:
        raise ValueError('Fewer than three verified PDF quotations')
    tags = result.get('tags') if isinstance(result.get('tags'), list) else []
    return {**paper, **{k: result[k] for k in required}, 'score': result['score'], 'tags': [x for x in tags if isinstance(x, str)][:5], 'citations': verified[:5], 'source_type': 'pdf_fulltext', 'pdf_pages': len(pages)}


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
