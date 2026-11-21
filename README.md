# 推荐与搜索 · 论文雷达

每天北京时间 08:30，通过 GitHub Actions 检索 arXiv 最近 7 天的新投稿，DeepSeek 根据电商精排、价值建模、生成式重排及搜索排序筛选至多 3 篇，生成 GitHub Pages 网页。结果基于标题和摘要，业务启发是推测，建议查阅原文。已推荐论文按无版本号 arXiv ID 永久去重；每天重复运行不会重复选择或产生额外 API 调用。

## 配置

1. 在仓库 Settings → Secrets and variables → Actions 中添加 `DEEPSEEK_API_KEY`。
2. 在 Settings → Pages 中将 Build and deployment 的 Source 设为 **GitHub Actions**。
3. 在 Actions → Daily paper digest 中手动执行一次，之后每天自动运行。Actions 定时任务可能因 GitHub 负载延迟。
4. 访问部署任务输出的 Pages URL。网页和提交历史的可见性取决于仓库及 Pages 设置；公开站点任何人均可访问。

可选设置 Actions 变量不生效；如需更换模型，请修改 workflow 中的 `DEEPSEEK_MODEL` 环境变量或脚本默认值。DeepSeek API 按实际使用计费；候选最多 200 篇，按提交时间排序，较繁忙时可能遗漏窗口中较早论文。未入选的论文仍可能在后续七天内再次参与筛选。arXiv 的发布节奏、索引延迟和搜索表达式都会影响覆盖率。

本地运行：`DEEPSEEK_API_KEY=... python3 digest.py`（建议通过安全的环境变量管理方式提供密钥，不要提交密钥）。Python 3.9+，无需第三方依赖。测试：`python3 -m unittest discover -s tests`。

数据记录在 `data/history.json`；请保留此文件以维持跨天去重。失败不会记录当天结果，可在 Actions 页面重试。
