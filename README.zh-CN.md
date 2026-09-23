# AI 工程评估（简版）

本工具读取本地 Claude Code / Codex 日志和任务验收记录，生成 L0–L7 工作方式、任务结果证据及改进前后对照评估。需要 Python 3.8+，运行时无第三方依赖。

```bash
python3 assess.py
python3 assess.py --project-dir ~/codes/my-project
python3 assess.py --eval-results results.json --evidence-root ./evidence
python3 assess.py --eval-results paired-results.json --evidence-root ./paired-evidence
```

默认在 `reports/YYYY-MM-DD/` 生成 TXT 和离线 HTML。网页默认英文，可切换中文，浏览器会记住选择。只有日志时，任务成功率为“证据不足”；L5–L7 属于自报证据，不能视作独立认证。改进对照要求同一冻结任务集的前后受控试验及本地可核验证据；本地核验仍不等于独立执行。

完整命令见 [English documentation](README.md)；独立评测步骤与数据协议见 [自我改进对照](IMPROVEMENT_EVALUATION.md)。
