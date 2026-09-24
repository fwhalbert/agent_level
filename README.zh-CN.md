# AI 工程评估（简版）

本工具读取本地 Claude Code / Codex 日志和任务验收记录，生成 L0–L7 工作方式、任务结果证据及改进前后对照评估。需要 Python 3.10+，运行时无第三方依赖。

一条命令同时安装到工作区 venv，并接入 `AGENTS.md`、`CLAUDE.md` 和会话提示 hooks；缺少 `CLAUDE.md` 时会创建并写入 `@AGENTS.md`。在本工具源码目录运行以下命令，将 `/path/to/workspace` 替换为自己的工作区路径：

```bash
python3 bootstrap.py --project-dir /path/to/workspace
cd /path/to/workspace
source .venv/bin/activate
agent-level-assess
```

已有 `project/venv` 时会使用它，否则创建 `project/.venv`；其他位置可用 `--venv PATH` 指定。复用已有 `venv` 时使用 `source venv/bin/activate`。bootstrap 完成后会打印实际环境对应的激活命令。每个终端会话激活一次（bash/zsh），之后统一用 `agent-level-assess`，本工具源码目录和其他工作区的用法相同；用 `deactivate` 退出环境。未激活时仍可用命令的完整路径运行。`--project-dir` 不带路径时使用当前目录。bootstrap 将评估命令安装到 venv，并在工作区 `AGENTS.md` 写入 `@源仓库绝对路径/AGENTS.md`，直接引用本仓库当前的规则文件。旧版复制的正文和规则链接会迁移为引用，保留周围的项目指令。源仓库需要保持可访问；移动仓库后重新运行 bootstrap 即可更新引用。`CLAUDE.md` 通过 `@AGENTS.md` 引用工作区指令。

更换 venv 后重新运行 bootstrap，会更新会话提示 hook 的命令路径；重复执行不会重复添加配置。hook 会跟随规则引用检查是否启用，只显示提示；代理仍需读取并执行引用文件中的任务记录流程。Codex 对新 hook 可能仍要求信任确认。bootstrap 不在项目根目录放脚本；激活后从项目根目录运行 `agent-level-assess` 即默认只评估该项目。venv 中也提供 `agent_level_assess.py` 命令别名。旧版生成且未改动的项目根目录脚本会被删除，自有脚本会保留。

只安装命令、不接入工作区时，可直接使用 pip：

```bash
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -e .
agent-level-assess --project-dir /path/to/workspace
```

单独执行 `python3 -m pip install` 只安装 Python 包和 venv 中的命令，不会自动选择并修改某个工作区。已有虚拟环境时，先 `source /path/to/venv/bin/activate`，再用 `python3 -m pip install -e /path/to/agent_level` 安装，即可直接运行 `agent-level-assess` 或 `agent-level-record`。默认报告写入当前工作目录的 `out/agent_level/`；用 `-o` 指定位置。以下示例均假设已激活环境：

```bash
agent-level-assess
agent-level-assess --project-dir /path/to/workspace
agent-level-assess --eval-results results.json --evidence-root ./evidence
agent-level-assess --eval-results paired-results.json --evidence-root ./paired-evidence
agent-level-assess --project-dir /path/to/workspace --model GPT-6-Sol --effort xhigh
```

默认在 `out/agent_level/YYYY-MM-DD/` 生成一个离线 HTML 文件，合并展示所选来源视图。如需 TXT 和 HTML 两份文件，可显式指定 `--format txt+html`。运行时会在 stderr 用英文显示任务记录、日志扫描、评估和报告生成进度；`--format json -o -` 的 stdout 仍是纯 JSON。网页默认英文，可切换中文，浏览器会记住选择。只有日志时，任务成功率为“证据不足”；L5–L7 属于自报证据，不能视作独立认证。改进对照要求同一冻结任务集的前后受控试验及本地可核验证据；本地核验仍不等于独立执行。

每条新任务记录分别保存 `model` 与 `reasoning_effort`。评估时可用 `--model`、`--effort`（或 `--reasoning-effort`）筛选任务证据；这两个参数不筛选历史日志的 L0–L7 等级。旧记录缺少 effort 时，已知模型按官方文档中的默认档位归类；没有明确默认值的模型仍为 `unknown`，显式记录的 `unknown` 也不会覆盖。默认档位只是旧记录的归类假设，不能证明当时运行环境未覆盖该设置。

Codex 使用 `functions.exec` 时，会话日志只记录外层 JavaScript 调用，不提供可信的内部工具执行轨迹。报告会把等级可见性标为 `partial`，并列出无法展开的调用次数；不会仅凭 JS 文本或打印的输出推定修改、构建或测试已经执行。评估这类 Codex 任务时，应在任务开始前登记验收标准、结束时运行 recorder，并在“任务结果评估”查看成功、失败和未知结果。这些任务结果不改变历史日志的 L0–L7 等级。若要可靠地评定内部调用对应的 L3/L4，需要 Codex 运行时提供每次内部工具执行的会话标识、时间戳、工具名称和执行结果；旧日志无法还原这些信息。

完整命令见 [English documentation](README.md)；独立评测步骤与数据协议见 [自我改进对照](docs/IMPROVEMENT_EVALUATION.md)。

验收日志在采集时限制为 16 MiB；超限会终止验收进程组并记录 unknown。本地核验同时检查日志文件哈希，以及 journal 与 grader 的退出码是否一致。测试使用 `python3 -m unittest discover -s tests -v`。设置 `AGENT_LEVEL_TEST_WHEELHOUSE` 为包含 `setuptools>=64` 和 `wheel` 安装包的目录，可同时运行真实临时 venv 安装测试；未设置时会明确跳过该项。
