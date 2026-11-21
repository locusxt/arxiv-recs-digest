# 推荐与搜索 · 论文雷达

每天北京时间 08:30 使用 GitHub Actions 检索 arXiv 近 7 天投稿。论文覆盖推荐、搜索、召回和系统，重点关注电商精排价值建模与生成式重排。先由 DeepSeek 基于标题摘要初筛，再下载候选论文 PDF、提取每页原文，让模型基于全文判断价值、解读方法、实验、局限和可执行的业务验证，最后精选最多 3 篇。网页附可点击的 PDF 页码和逐字校验的英文证据；业务迁移是推测，需自行验证。无法提取全文或无法核对至少 3 条原文证据的论文不会作为全文解读发布。

按不含版本号的 arXiv ID 对历史入选论文去重。每天重复运行默认只重新生成网页，不重新筛选。手动触发时可勾选 `refresh_today` 重新生成当天，保留更早的历史和去重记录。失败不会记录当天结果，可以在 Actions 页面重试。

## 配置

1. 仓库 Settings → Secrets and variables → Actions 添加 `DEEPSEEK_API_KEY`。
2. Settings → Pages 将 Source 设为 **GitHub Actions**。
3. 在 Actions → Daily paper digest 手动执行一次；此后每日自动运行，定时任务可能延迟。

公开仓库的论文结果、原文短摘录和个人筛选偏好均为公开。DeepSeek API 按实际用量计费，全文解读会比摘要筛选消耗更多 token。每个主题最多取最近 200 篇，超出时可能遗漏；候选初筛分批进行，最多阅读全文 12 篇。PDF 文字抽取不能完整识别部分公式、图表及扫描版，可能漏选或错读；引用的存在性校验不等于验证模型推理正确，重要结论请查原文。仅接受 2–50 页、文本长度在限定范围内且可成功解析的 PDF。

本地运行：`python3 -m venv .venv && .venv/bin/pip install -r requirements.txt`，通过环境变量安全传入 `DEEPSEEK_API_KEY` 后运行 `.venv/bin/python digest.py`。`REFRESH_TODAY=true` 可重新生成当天。测试：`.venv/bin/python -m unittest discover -s tests`。数据保存在 `data/history.json`，须保留以维持去重。
