# 推荐与搜索 · 论文雷达

每天北京时间 08:30 通过 GitHub Actions 检索 arXiv 近 7 天投稿，覆盖推荐、搜索、召回和系统，重点关注电商精排价值建模与生成式重排。DeepSeek 先按摘要初筛，再阅读候选 PDF 全文，筛选最多 3 篇。页面以中文、英文标题、作者、机构、关键词、主要内容、推荐理由和链接呈现。事实和结论以原文为准，模型可能出错；PDF 提取可能遗漏公式、图表。

页面公开显示当日已记录运行的 DeepSeek token 用量、运行期间账户余额变化及最新余额。余额变化是账户级数字，可能受其他任务、充值、延迟结算影响，不能等同于精确账单；历史未记录用量、失败或中断的运行不会完整计入。运行前后任一次查询失败时无法计算对应余额变化。请以 DeepSeek 账单为准。公开仓库与网页对任何人可见。

以不含版本号的 arXiv ID 对历史入选论文去重，同一天重复运行不会重新筛选；手动触发时可勾选 `refresh_today` 重新生成当天，保留更早历史和当天已记录的用量。

## 配置

1. 在仓库 Actions Secrets 添加 `DEEPSEEK_API_KEY`。
2. 将 GitHub Pages Source 设为 **GitHub Actions**。
3. 在 Actions → Daily paper digest 手动执行一次，此后每日自动运行。定时任务可能延迟。

每个主题最多检索最近 200 篇，候选初筛分批进行，最多阅读全文 12 篇；无法提取全文的论文会跳过。DeepSeek 按实际用量计费。

本地：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`，通过环境变量安全传入 `DEEPSEEK_API_KEY` 后运行 `.venv/bin/python digest.py`。测试：`.venv/bin/python -m unittest discover -s tests`。数据保存在 `data/history.json`，须保留以维持去重。
