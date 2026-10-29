# Agent 使用说明

这是一个独立运行的 GUI Agent，支持代码编写、程序语言转换、Skill 蒸馏、模型选择、上下文导入、文件操作、终止、撤销和 LLM-as-a-judge 质量评审。

## 启动文件

- 推荐界面：`dist\Agent.exe`
- 标准中文界面：`dist\Agent_gui.exe`

## 界面布局

- 整个界面右侧有主滚动条，可以像 opencode 一样滚动整页。
- `上下文`、`任务`、`输出` 文本框也有独立滚动条。
- `输出` 区按对话形式显示 `你`、`Agent 准备执行`、`执行结果`、`LLM 评审`、`系统` 内容。
- `convert` 和 `skill` 模式支持流式输出，会像聊天界面一样逐步显示模型回复。
- `code` 模式隐藏原始 JSON 工具协议，使用伪流式可读进度显示每一步分析、动作、工具执行和评审阶段。
- 如果某个模型的 OpenAI-compatible 接口不返回标准 SSE 文本增量，界面会显示请求进度，并在完成后显示完整结果。

## 模型配置

- `模型来源`：选择 `Ollama Local`、`LM Studio Local`、`OpenAI`、`DeepSeek` 或 `Custom API`。
- `接口地址`：填写 OpenAI-compatible API 地址，例如 `http://localhost:11434/v1`。
- `模型`：手动填写模型 ID，或点击 `刷新模型` 从 `/models` 接口读取。
- `API 密钥`：使用外部 API 时填写，本地模型通常留空。
- `导入 opencode JSON`：导入 opencode 风格配置，自动读取 `model`、`provider.*.options.baseURL`、`provider.*.options.apiKey`。

## 功能模式

- `code`：读取、创建、写入、追加、删除文件，按任务实现代码，并进行工具循环和 LLM Judge 检查。
- `convert`：将一种编程语言转换为另一种语言，例如 C++ 转 Java，尽量保持行为、依赖和边界条件一致。
- `skill`：从上下文中蒸馏可复用 Skill。选择该模式且任务为空时，会自动填入完整 Skill 蒸馏提示词。

## 上下文

- 默认勾选 `自动读取工作目录`，Agent 会自动扫描工作目录内的常见源码、Markdown、文本和配置文件。
- `补充上下文` 文本框只用于额外说明，例如重点文件、设计要求、错误信息或转换规则。
- 点击 `添加上下文文件` 可以额外导入工作目录内外的文档或源码。
- 点击 `添加上下文目录` 可以额外批量导入目录内的 `.txt`、`.md`、`.py`、`.js`、`.ts`、`.tsx`、`.json`、`.yaml`、`.yml` 等文件。
- 访问工作目录外的上下文路径会弹窗确认。

## Skill

- 使用 `skill` 模式生成 Skill Markdown。
- 用 `添加 Skill 文件` 或 `添加 Skill 目录` 把 Skill 插入到当前 Agent 工作流。
- 已插入的 Skill 会应用到 `code` 和 `convert` 模式，并参与最终 LLM Judge 检查。

## 文件操作与安全

- Agent 可以在 `工作目录` 内创建、写入、追加和删除文件。
- 默认情况下，文件写入、追加、删除会弹窗确认。
- 勾选 `工作目录内直接写入` 后，工作目录内的写入、追加、删除不再重复确认。
- 访问工作目录外的文件或目录会弹窗确认。
- 修改、追加、删除工作目录外的文件会再次弹窗确认。
- 目录删除始终拒绝。

## 网页与依赖安装

- `允许网页` 默认开启，Agent 可在需要参考外部资料时读取网页。
- `允许安装包` 默认开启，Agent 可请求安装依赖。
- 安装命令限制为 `pip install`、`python -m pip install`、`npm install`、`pnpm add`、`yarn add`、`cargo add`、`go get`。

## LLM Judge

- `LLM 评审` 默认开启。
- 所有模式最终都会调用模型作为 Judge 检查需求覆盖、正确性、边界情况、Skill 一致性和输出清晰度。
- 如果 Judge 判定通过，保留原结果；如果不通过，返回 Judge 修订后的结果。

## 终止

- 点击 `终止` 会请求停止当前任务。
- 如果模型请求正在进行，会在当前请求或工具步骤结束后停止。
- 终止状态会显示在 `输出` 对话区。

## 撤销

- 点击 `撤销上次文件修改` 可以恢复最近一次由 Agent 执行的写入、追加或删除。
- 撤销基于文件快照，只影响 Agent 记录过的最近一次文件修改。
- 撤销结果会显示在 `输出` 对话区。

## 推荐流程

1. 打开 `dist\Agent.exe`。
2. 配置模型来源、接口地址、模型和 API 密钥。
3. 选择工作目录。
4. 保持 `自动读取工作目录` 开启，必要时填写补充上下文或添加额外上下文文件。
5. 如有 Skill，添加 Skill 文件或目录。
6. 选择 `code`、`convert` 或 `skill`。
7. 输入任务并点击 `运行 Agent`。
8. 根据弹窗确认外部路径访问或文件修改。
9. 在 `输出` 区查看可读对话、工具执行、Judge 和最终结果。

## 构建产物

- `dist\Agent.exe`：opencode 浅色风格 GUI。
- `dist\Agent_gui.exe`：标准中文 GUI。
- `build\Agent_build`：`Agent.exe` 构建目录。
- `build\Agent_gui_build`：`Agent_gui.exe` 构建目录。

## 源码文件

- `workflow_agent_core.py`：Agent 核心逻辑、模型调用、工具循环、自动上下文、撤销和 Judge。
- `workflow_agent_gui.py`：标准中文 GUI。
- `workflow_agent_opencode_gui.py`：opencode 浅色风格 GUI。
