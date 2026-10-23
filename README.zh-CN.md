# Agent Level

[![Tests](https://github.com/fwhalbert/agent_level/actions/workflows/test.yml/badge.svg)](https://github.com/fwhalbert/agent_level/actions/workflows/test.yml)

[English](README.md) | [简体中文](README.zh-CN.md)

Agent Level 基于 **Claude Code 和 Codex** 的本地活动与任务证据，
分析人和 Agent 如何分担工程工作。

## 能做什么

- **了解工作方式：** 查看 L0–L7 候选等级、判断依据和缺少的条件。
- **查看任务结果：** 汇总预先登记的验收检查结果。
- **对比改进效果：** 在同一冻结任务集上对比工作流变更。
- **查看使用情况：** 展示每日 Token 用量、模型与角色占比和缓存使用。
- **检查验证覆盖：** 区分最后编辑后的验证、历史工作流信号和日志采集缺口。

支持中英文离线 HTML 报告，也可导出文本、Markdown 和 JSON。
报告包含汇总信息和不透明诊断引用，不包含原始对话或源码。

**本地分析 · 不上传源码 · 基于证据 · 中英文报告**

![L0–L7：从人工控制到系统自主](docs/assets/agent-level.svg)

## 快速开始

需要 Git 和 Python 3.9+，支持 Linux / macOS，运行时无第三方依赖。
克隆源码后，为 Codex 执行一次全局配置：

```bash
git clone https://github.com/fwhalbert/agent_level.git
cd agent_level
./agent-level setup
```

Setup 在 `~/.codex/AGENTS.md` 中添加指向本仓库 `AGENTS.md` 的绝对路径引用，
保留已有个人规则。不安装包、不创建虚拟环境、不配置 hook，也不写入项目配置。
可通过 `--codex-home /path/to/codex-home` 或 `CODEX_HOME` 指定其他全局配置目录。

开启新的 Codex 会话后，Agent 按引用的[记录流程](AGENTS.md)直接调用本仓库的记录器，
验收证据仍保存在被评估的工作区。可从任意目录生成报告：

```bash
python3 /absolute/path/to/agent_level/agent-level --project-dir "/absolute/path/to/your project"
```

在浏览器打开输出的 `file://` 链接；报告默认保存在所选项目的
`out/agent_level/YYYY-MM-DD/agent-level.html`。任务完成后重新运行命令更新报告。

需要从内网其他设备访问时，加上 `--serve`：

```bash
python3 /absolute/path/to/agent_level/agent-level --project-dir "/absolute/path/to/your project" --serve
```

打开输出的 `http://<内网IP>:8000/...` 链接。服务默认监听所有 IPv4 网卡，
仅提供生成的 HTML 报告。保持命令运行，按 Ctrl+C 停止；可用 `--port 8080`
更换端口，或用 `--host 127.0.0.1` 限制为本机访问。多网卡机器可将链接中的 IP
替换为其他设备能访问的内网 IP，所选端口需能从该设备连通。

macOS 支持 Apple Command Line Tools 提供的 Python 3.9，路径含空格时加引号。
请保留本工具源码目录，移动后重新运行 setup。
仅分析用法、Claude Code 配置和旧项目安装迁移见[配置指南](docs/SETUP.md)，
或运行 `./agent-level --help`。

## L0–L7 框架

| 等级 | 工程工作方式 | 人的角色 |
|---|---|---|
| L0 — 手工工程 | 人实现并验证 | 开发者 |
| L1 — AI 辅助 | AI 建议，人整合 | 开发者 |
| L2 — 交互式编码 | AI 修改，人决定步骤 | 步骤决策者 |
| L3 — Agent 编码 | 人提出任务，Agent 修改并尝试验证 | 任务发起者 |
| L4 — Agent 优先 | 修改/验证流程跨会话、跨天持续出现 | 监督者 |
| L5 — 自主工程 | Agent 接任务、交付、修复 CI、跟踪结果 | 需求与验收负责人 |
| L6 — 自我改进 | 系统改进提示词、工具和流程，具备评估与回滚 | 改进与治理负责人 |
| L7 — 受治理的递归改进 | 在人的治理下研发后续系统 | 研究与治理负责人 |

`DEFAULT` 表示 L0 默认基线，包括没有匹配日志时。`OBSERVED` 表示日志支持 L1–L4 候选等级，
不代表任务成功。L5–L7 保留为 `NOT VERIFIED` 参考定义，任务验收结果单独评估。

项目自定义规则集 **1.0** 描述工作流自主程度，不衡量开发者水平或模型智力，也不是行业标准。
[完整定义与阈值](docs/AGENT_LEVEL_L0-L7.md)。

## 参考资料

- [配置与任务记录](docs/SETUP.md)
- [任务评估与 JSON 协议](docs/ANTHROPIC.md)
- [工作流指标、冻结标准与人工复核](docs/WORKFLOW_METRICS.md)
- [改进前后对照](docs/IMPROVEMENT_EVALUATION.md)
- [OpenAI 指南与实现范围](docs/OPENAI.md)
- [方法、一手来源与限制](docs/REFERENCES.md)
- [架构](docs/ARCHITECTURE.md)
- [贡献指南](CONTRIBUTING.md) · [安全报告](SECURITY.md) · [MIT 许可证](LICENSE)
