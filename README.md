# 推荐与搜索 · 论文雷达

每天北京时间 08:30 通过 GitHub Actions 检索 arXiv 近 7 天投稿，覆盖推荐、搜索、召回和系统，重点关注电商精排价值建模、生成式重排、因果推断、DAU 与用户留存、LLM4Rec。先对标题和摘要做本地关键词加权评分，保留价值建模、排序、召回、搜索、系统等方向的候选，最多 120 篇；再由 DeepSeek 按摘要筛选并阅读全文，选出最多 3 篇。页面以中文、英文标题、作者、机构、关键词、arXiv 首次提交日期、5 分制推荐评分、主要内容、推荐理由和链接呈现。事实和结论以原文为准，模型可能出错；PDF 提取可能遗漏公式、图表。

页面公开显示当日已记录运行的 DeepSeek token 用量、运行期间账户余额变化及最新余额。余额变化是账户级数字，可能受其他任务、充值、延迟结算影响，不能等同于精确账单；历史未记录用量、失败或中断的运行不会完整计入。运行前后任一次查询失败时无法计算对应余额变化。请以 DeepSeek 账单为准。公开仓库与网页对任何人可见。

以不含版本号的 arXiv ID 和规范化后的相同标题对历史入选论文去重，包含被手动重选替换的论文；不保证识别不同标题的相似论文，同一天重复运行不会重新筛选；手动触发时可勾选 `refresh_today` 重新生成当天，保留更早历史和当天已记录的用量。

## 关键词与筛选

本地初筛同时匹配标题和摘要，按主题分组加权，并为价值建模、排序、召回、搜索、推荐、系统、因果训练、用户活跃与 LLM4Rec 等方向保留候选。关键词参考 [Algorithm-Practice-in-Industry 的旧版会议论文筛选](https://github.com/Doragd/Algorithm-Practice-in-Industry/blob/main/legacy/conf.py)，另补充 LTV、延迟反馈和生成式重排等电商场景术语；其当前 arXiv 主线使用大模型粗排和精排。没有把 user、item 等过宽泛的词单独设置为高权重，也没有硬性排除隐私、公平性等可能相关的研究。关键词和权重在 `research.py` 的 `TOPICS` 中。

初筛使用词边界并覆盖部分单复数和连字符变化，仍可能遗漏不同写法。arXiv 检索限制于 cs.IR、cs.LG、cs.AI 和脚本中的查询表达式；通用基础模型论文如未被这些查询召回，提示词不会使其自动进入候选。

## 配置

1. 在仓库 Actions Secrets 添加 `DEEPSEEK_API_KEY`。
2. 将 GitHub Pages Source 设为 **GitHub Actions**。
3. 在 Actions → Daily paper digest 手动执行一次，此后每日自动运行。定时任务可能延迟。

每个主题最多检索最近 200 篇，关键词初筛最多保留 120 篇，DeepSeek 摘要筛选后最多阅读全文 12 篇；关键词规则可能遗漏不使用常见术语的论文；无法提取全文的论文会跳过。DeepSeek 按实际用量计费。

本地：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`，通过环境变量安全传入 `DEEPSEEK_API_KEY` 后运行 `.venv/bin/python digest.py`。测试：`.venv/bin/python -m unittest discover -s tests`。数据保存在 `data/history.json`，须保留以维持去重。
