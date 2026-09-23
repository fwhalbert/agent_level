"""Primary sources and the limits of their application to this project."""

ANTHROPIC_URL = 'https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents'
REFERENCES = [
    {'id': 'anthropic', 'title': 'Demystifying evals for AI agents',
     'publisher': 'Anthropic · 2026-01-09', 'url': ANTHROPIC_URL,
     'scope': '任务、trial、grader、transcript、outcome 和重复试验方法；不是 L0–L7 标准或认证。'},
    {'id': 'swebench', 'title': 'SWE-bench: Can Language Models Resolve Real-World GitHub Issues?',
     'publisher': 'Jimenez et al. · 2023', 'url': 'https://arxiv.org/abs/2310.06770',
     'scope': '以真实软件任务的解决结果评估能力；不支持本项目的调用量门槛。'},
    {'id': 'metr', 'title': 'Measuring AI Ability to Complete Long Software Tasks',
     'publisher': 'METR · 2025', 'url': 'https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/',
     'scope': '结合任务难度、完成概率和不确定性；human-equivalent time 不等于 Agent 运行时长。'},
    {'id': 'space', 'title': 'The SPACE of Developer Productivity',
     'publisher': 'Forsgren et al. · ACM Queue · 2021',
     'url': 'https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/',
     'scope': '生产力是多维的，活动量不能单独代表生产力。'},
    {'id': 'dora', 'title': 'DORA’s software delivery performance metrics',
     'publisher': 'DORA · 官方持续更新文档', 'url': 'https://dora.dev/guides/dora-metrics/',
     'scope': '通过交付吞吐与不稳定性观察实际结果；不是个人或 Agent 自主性等级。'},
    {'id': 'wilson', 'title': 'Confidence intervals for a binomial proportion',
     'publisher': 'NIST/SEMATECH · Statistical Methods',
     'url': 'https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm',
     'scope': '日常完整任务组使用 Wilson 区间描述抽样不确定性；不消除选择偏差或证明可靠性。'},
    {'id': 'agi', 'title': 'Levels of AGI for Operationalizing Progress on the Path to AGI',
     'publisher': 'Morris et al. · ICML 2024', 'url': 'https://deepmind.google/research/publications/66938/',
     'scope': '区分性能、通用性及自主性；不是本项目 L0–L7 的来源。'},
]

METHOD_NOTE = ('L0–L7 为项目经验规则，阈值未经统计校准。Anthropic 视图依据官方方法组织证据；'
               '自我改进对照与本地数据协议由本项目定义，不代表官方标准、认证或独立审计。')
