# AI 工程评估

[English](README.md) | [简体中文](README.zh-CN.md)

**面向 AI 辅助软件工程的开源实证评估框架。** 基于 Claude Code / Codex 的本地会话日志与任务验收证据，从人机协作模式、任务完成可靠性和工作流改进效果三个维度，分析 AI Agent 在真实工程场景中的表现。

项目将工程活动转化为可追溯的评估结果，帮助开发者、团队与研究者识别自动化边界、验证任务交付，并在固定任务集上比较提示词、工具与协作流程的改进效果。数据在本地处理，报告可离线查看，为 AI 工程实践的持续改进与实证研究提供依据。

## 能做什么

- **了解工作方式**：给出 L0–L7 候选等级，展示判断依据和缺少的条件。
- **查看任务结果**：根据预先登记的验收检查，统计成功、失败、未知和未运行的任务。
- **对比改进效果**：在固定任务集上，对比提示词、工具或工作流不同版本的任务结果。
- **查看使用情况**：展示每日 Token 用量、模型占比和缓存使用，支持 Claude Code、Codex 及合并视图。
- **生成本地报告**：提供可切换中英文的离线 HTML，也可导出文本、Markdown 和 JSON。报告只包含汇总信息，不包含原始对话或源码。

需要 **Python 3.10+**，运行时无第三方依赖。有历史日志就可以先看工作方式；任务验收统计需要额外的任务记录。

## 现支持的评估方法与标准

本项目没有采用统一的行业等级标准。目前支持以下方法和数据协议：

| 方法 / 协议 | 回答什么问题 | 当前支持范围 |
|---|---|---|
| 项目自定义 L0–L7，规则集 1.0 | 人和 AI 如何分工完成工程工作？ | L0 默认达成；日志支持 L1–L4 候选等级；L5–L7 仅展示参考定义 |
| 参考 Anthropic 的 Agent 评估方法 | 任务是否达到验收标准？重复执行是否可靠？ | 日常任务验收结果；完整受控重复试验组的 pass@1、pass@k、pass^k |
| 本地任务结果协议 1.0 / 1.1 | 如何记录和导入任务证据？ | JSON 导入；1.1 增加日常任务记录及可选的改进对照 |
| 项目自定义改进对照 | 修改工作流后，自主完成任务的效果是否改善？ | 同一冻结任务集的前后配对结果、退步项和证据状态 |

Anthropic 方法可用于 Claude Code 和 Codex 的任务证据；**L0–L7 不是 Anthropic 官方分级**，评估结果也不是官方认证。OpenAI 评估指南、SWE-bench、METR 等作为参考资料，不是本工具额外实现的评分标准。详见 [References](#references)。

## Quick start

以下步骤适用于 **Linux / macOS 的 bash 或 zsh**。请先安装 Git 和 Python 3.10+，并在同一个终端依次执行。安装阶段可能需要联网下载 Python 构建工具。

下载本工具，将 `workspace_dir` 改为要评估的项目的绝对路径：

```bash
git clone https://github.com/fwhalbert/agent_level.git
cd agent_level
workspace_dir="/absolute/path/to/your-project"
python3 bootstrap.py --project-dir "$workspace_dir" --venv "$workspace_dir/.venv"
source "$workspace_dir/.venv/bin/activate"
cd "$workspace_dir"
agent-level-assess
```

安装脚本会安装命令，在 `AGENTS.md`、`CLAUDE.md` 中引用任务记录指令，并配置会话提示 hook。原有项目指令会保留，报告目录会加入 `.gitignore`。

在浏览器打开终端输出的 `file://` 链接即可离线查看中英文报告，默认路径为 `out/agent_level/YYYY-MM-DD/ai-engineering-assessment.html`。没有匹配日志时，等级默认为 L0；任务结果统计需要验收记录。

在目标项目开启新的 Claude Code 或 Codex 会话，照常交给它工程任务。代理按 [记录流程](AGENTS.md) 在工作前登记验收标准，结束后运行检查并记录结果。hook 只显示 “Auto eval enabled.”；Codex 的新 hook 可能需要先在 `/hooks` 中审阅并信任。

任务完成后，再运行 `agent-level-assess` 更新报告。每个新终端先激活虚拟环境。请保留本工具源码目录，移动目录或更换虚拟环境后重新运行安装脚本。完整命令参数可通过 `agent-level-assess --help` 查看。

## Level L0–L7 介绍

L0–L7 描述的是**人和 AI 的工程分工**。数字越高，代表不同程度的任务委托和系统能力；应根据自己的工作选择合适的方式。

| 等级 | 名称 | 通俗理解 | 人的主要角色 |
|---|---|---|---|
| L0 | 手工工程（Manual Engineering） | 人完成实现与验证，AI 至多提供参考 | 开发者 |
| L1 | AI 辅助编码（AI-assisted Coding） | AI 解释、建议、生成代码片段，由人整合 | 开发者 |
| L2 | 交互式 AI 编码（Interactive AI Coding） | AI 直接改文件，人频繁决定下一步做什么 | 步骤决策者 |
| L3 | Agent 编码（Agent Coding） | 人提出任务，Agent 修改代码并尝试验证 | 任务发起者 |
| L4 | Agent 优先工程（Agent-first Engineering） | 修改与验证流程在多个会话、多天持续出现 | 监督者 |
| L5 | 自主工程（Autonomous Engineering） | Agent 接任务、交付修改、修复 CI，并跟踪结果 | 需求与验收负责人 |
| L6 | 自我改进工程系统（Self-improving Engineering System） | 根据结果改进提示词、工具或流程，并具备评估和回滚机制 | 改进与治理负责人 |
| L7 | 受治理的递归自我改进（Governed Recursive Self-Improvement） | 在人的治理下，研究、构建、评估和部署下一代系统 | 研究与治理负责人 |

**读报告时注意三个状态：** `DEFAULT` 表示 L0 默认达成，无需日志或人工确认；`OBSERVED` 是日志支持某个候选等级，不代表任务已通过验收；`NOT VERIFIED` 表示尚未证实所需行为；L5–L7 仅保留参考定义，不自动评定。达到更高等级后 L0 仍保持达成，L7 属于可选的研究方向。

具体阈值与证据要求见 [等级规则与日志观察边界](docs/AGENT_LEVEL_L0-L7.md)。

## References

- [L0–L7 定义与观察规则](docs/AGENT_LEVEL_L0-L7.md)：等级含义、阈值、证据状态及局限。
- [Anthropic 方法与 JSON 协议](docs/ANTHROPIC.md)：任务、评分器、验收结果和重复试验统计。
- [改进前后对照评估](docs/IMPROVEMENT_EVALUATION.md)：受控对照步骤及证据要求。
- [OpenAI 评估指南与项目范围](docs/OPENAI.md)：指南与当前实现的对应关系及缺口。
- [完整参考文献](docs/REFERENCES.md)：Anthropic、OpenAI、SWE-bench、METR、SPACE、DORA、DeepMind 和 NIST 的一手来源，以及各自适用的范围。

这些资料为评估方法提供参考，不代表对本项目等级阈值的验证或官方背书。
