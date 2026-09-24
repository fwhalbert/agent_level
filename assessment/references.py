"""Primary sources and the limits of their application to this project."""

ANTHROPIC_URL = 'https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents'
REFERENCES = [
    {'id': 'anthropic', 'title': 'Demystifying evals for AI agents',
     'publisher': 'Anthropic · 2026-01-09', 'url': ANTHROPIC_URL,
     'scope': 'Task, trial, grader, transcript, outcome, and repeated-trial methods; not an L0–L7 standard or certification.'},
    {'id': 'swebench', 'title': 'SWE-bench: Can Language Models Resolve Real-World GitHub Issues?',
     'publisher': 'Jimenez et al. · 2023', 'url': 'https://arxiv.org/abs/2310.06770',
     'scope': 'Measures real software task outcomes; does not support this project’s call-count thresholds.'},
    {'id': 'metr', 'title': 'Measuring AI Ability to Complete Long Software Tasks',
     'publisher': 'METR · 2025', 'url': 'https://metr.org/blog/2025-03-19-measuring-ai-ability-to-complete-long-tasks/',
     'scope': 'Relates task difficulty, completion probability, and uncertainty; human-equivalent time is not agent runtime.'},
    {'id': 'space', 'title': 'The SPACE of Developer Productivity',
     'publisher': 'Forsgren et al. · ACM Queue · 2021',
     'url': 'https://www.microsoft.com/en-us/research/publication/the-space-of-developer-productivity-theres-more-to-it-than-you-think/',
     'scope': 'Productivity has multiple dimensions; activity volume alone does not measure it.'},
    {'id': 'dora', 'title': 'DORA’s software delivery performance metrics',
     'publisher': 'DORA · Official living documentation', 'url': 'https://dora.dev/guides/dora-metrics/',
     'scope': 'Measures delivery throughput and instability; not a person or agent autonomy level.'},
    {'id': 'wilson', 'title': 'Confidence intervals for a binomial proportion',
     'publisher': 'NIST/SEMATECH · Statistical Methods',
     'url': 'https://www.itl.nist.gov/div898/handbook/prc/section2/prc241.htm',
     'scope': 'Uses Wilson intervals for sampling uncertainty in complete daily groups; does not remove selection bias or prove reliability.'},
    {'id': 'agi', 'title': 'Levels of AGI for Operationalizing Progress on the Path to AGI',
     'publisher': 'Morris et al. · ICML 2024', 'url': 'https://deepmind.google/research/publications/66938/',
     'scope': 'Distinguishes performance, generality, and autonomy; not the source of this project’s L0–L7 scale.'},
]

METHOD_NOTE = ('L0–L7 are project heuristics with uncalibrated thresholds. The Anthropic view follows '
               'its published method; the improvement comparison and local data format are project-defined. '
               'None is an official standard, certification, or independent audit.')
