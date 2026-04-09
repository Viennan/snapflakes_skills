# AGENTS

本文件定义本仓库中所有 skill 的统一维护规则。除非某个 skill 的局部文档另有补充说明，否则默认遵循以下约束。

## 1. Skill 目录命名

- 每个 skill 的维护目录必须位于仓库根目录下。
- 每个 skill 目录名称必须以 `skill_${skill_name}` 的形式命名。
- `skill_name` 由该 skill 的实际名称组成，例如：`skill_resource-hub-mgr`。
- 不得使用不带 `skill_` 前缀的目录名作为正式 skill 目录。

## 2. 测试临时目录

- 各个 skill 内，不依赖外部文件即可实现的简单单元测试，应维护在各自 skill 目录下的 `tests/` 目录中，例如 `skill_${skill_name}/tests/`。
- 这类测试通常包括可直接运行的 Python 单元测试，或其他不需要额外测试资产、外部目录结构、外部服务输入的轻量测试。
- 对 skill 进行测试时，如需在仓库内创建临时文件或临时目录，统一放在项目根目录的 `.tmp/` 下。
- 临时目录应按测试任务组织，目录名必须包含被测试的 skill 名称，便于追踪和清理。
- 推荐命名形式：
  - `.tmp/<test-task>-<skill_name>/`
  - `.tmp/<skill_name>-<test-task>/`
- 不要将测试过程中产生的临时目录散落在各个 `skill_*` 目录内部，除非该 skill 自身文档明确要求。

## 3. Python 运行环境隔离

- 如果某个 skill 包含 Python 脚本，则必须在该 skill 自己的目录下维护独立虚拟环境：`skill_${skill_name}/.venv`。
- 该 skill 的全部 Python 依赖都必须安装在该 `.venv` 中，不得安装到系统 Python 环境中。
- 不得要求调用方手动先激活全局或系统级 Python 环境后再运行 skill。
- 每个带 Python 脚本的 skill 应在自身目录下维护依赖清单，例如 `requirements.txt`，并由该 skill 的包装脚本负责安装。

## 4. Python 包装脚本要求

- 凡是依赖 Python 脚本运行的 skill，都必须提供一个包装脚本，统一负责 Python 执行入口。
- 包装脚本应放在 skill 目录内部，推荐路径为 `skill_${skill_name}/scripts/run_python.sh`。
- 调用 Python 脚本时，应优先通过包装脚本执行，而不是直接调用 `python` 或 `python3`。

包装脚本至少应负责以下事项：

- 检测 `skill_${skill_name}/.venv` 是否存在且可用。
- 当 `.venv` 不存在时，自动创建该虚拟环境。
- 检测依赖清单是否变更；如已变更，自动在 `.venv` 中安装或更新依赖。zheng de yong hu yun xu
- 使用 `.venv/bin/python` 执行真实的 Python 脚本。
- 将外部传入参数原样转发给真实脚本。

## 5. 参考实现

- `skill_resource-hub-mgr/scripts/run_python.sh` 是当前仓库中的参考实现。
- 新增或重构带 Python 脚本的 skill 时，应优先复用或对齐该实现的设计思路：
  - `.venv` 固定放在 skill 根目录下。
  - 由包装脚本统一完成环境检测、创建、依赖安装和脚本执行。
  - 根据 `requirements.txt` 变化决定是否重新安装依赖，避免污染系统环境。

## 6. dev_ref_docs 参考文档

- 各个 skill 目录下的 `dev_ref_docs/` 用于存放用户提供的、可供开发和维护该 skill 的参考文档。
- 维护或扩展某个 skill 时，可以按需查阅对应 `dev_ref_docs/` 下的文档，用于理解背景、实现约束、测试方式和外部依赖。
- 如果 `dev_ref_docs/` 中的内容与当前用户需求矛盾，或与更高优先级的权威内容冲突，应暂停当前任务并先向用户反馈，不要自行假设或强行继续实现。
- `dev_ref_docs/test_${skill_name}.md` 用于记录该 skill 的真实测试环境信息，例如付费 API 调用、高消耗操作、外部服务接入、或无法在简单单元测试内完成的测试流程。
- 使用 `dev_ref_docs/test_${skill_name}.md` 中描述的真实测试方案前，必须先征得用户允许。
- 未经用户明确同意，不得擅自执行会产生付费调用、明显资源消耗或外部副作用的真实环境测试。

## 7. 执行约定

- 为 skill 增加 Python 脚本时，同时补齐包装脚本与依赖清单，不要只提交裸 Python 文件。
- 为 skill 增加无需依赖外部文件的简单单元测试时，应优先放入该 skill 自己的 `tests/` 目录。
- 为 skill 编写测试时，如需构造输入、输出、缓存或中间产物，优先使用 `.tmp/` 下带 skill 名称的任务目录。
- 如需进行依赖 `dev_ref_docs/test_${skill_name}.md` 的真实环境测试，应先获得用户授权，再按文档执行。
- 在审查或维护 skill 时，应首先检查是否满足本文件中的目录命名、临时目录和 Python 环境隔离要求。
