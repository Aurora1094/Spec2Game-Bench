# Core-15 与 Full-150

候选模型在默认配置 `configs/examples/qwen37_main.yaml` 的 `models` 中维护；Judge 路由独立配置。一个候选可以省略 `--model`，多个候选必须明确选择。模型在所选通道的每个实例上各生成一次，四阶段输出上限为 4000、7000、5000、2000 tokens，每个请求最多两次尝试，中间等待两秒。

| 选择 | 实例 | 正常生成请求 | 单次输出上限合计 | 人工答卷记录 |
|---|---:|---:|---:|---:|
| Core-15 | 15 | 60 | 270,000 | 150 |
| Full-150 | 150 | 600 | 2,700,000 | 1,500 |
| 同一模型独立运行两条通道 | 165 | 660 | 2,970,000 | 1,650 |

上限不是预计用量。每阶段两次尝试均用满时上限翻倍；以后显式恢复生成的周期另计。Full 包含每家族的基础版及九个变体。变体仅接收自身的规格和检查点，以及本实例前置生成阶段所需的代码。Core 与 Full 不复用候选、采样、compiler 缓存或评分。

## 配置候选

例如向 `models` 添加条目即可，不需要新增 Judge 策略分支。模型 ID 和推理参数应以供应商实际支持为准：

```yaml
models:
  - id: gpt_5_6_terra
    name: GPT-5.6 Terra
    provider: openrouter
    model: openai/gpt-5.6-terra
    api_style: chat_completions
    api_key_env: OPENROUTER_API_KEY
    base_url: https://openrouter.ai/api/v1
    reasoning:
      effort: none
```

密钥只放在环境变量中。增加未选中的候选不会改变已有 run 的模型快照；修改已选模型、规格、生成或评测策略需要新的 run。规格或合同输入变化也需要新 round。

## 查看与运行

从项目目录执行。以下命令假设 `OPENROUTER_API_KEY` 和安装了 Pygame 的 `CODE2PLAY_PYTHON` 已设置。工作区可通过 `--workspace` 或 `CODE2PLAY_WORKSPACE` 指定；默认位于当前用户目录下的 `Code2Play-Workspace`。新任务与请求使用短目录名，不绑定某个用户名或盘符。

```powershell
python main.py plan --model gpt_5_6_terra --track core15
python main.py plan --model gpt_5_6_terra --track full150
python main.py preflight --model gpt_5_6_terra --track full150 --live
```

不带 `--candidate` 的 `plan` 不调用 API。`--game snake` 在 Core 选择一个基础实例，在 Full 选择 Snake 的十个实例；`--variant base` 或 `var01` 至 `var09` 可进一步限定一个实例。变体参数必须与游戏家族一起使用；Core 只接受基础版。

先试跑固定变体，分别使用新的 run/round：

```powershell
python main.py benchmark --model gpt_5_6_terra --track full150 --game snake --variant var09 --run-id pilot-snake --round-id pilot-snake
python main.py benchmark --model gpt_5_6_terra --track full150 --game whack_a_mole --variant var06 --run-id pilot-mole --round-id pilot-mole
python main.py benchmark --model gpt_5_6_terra --track full150 --game mini_zelda --variant var09 --run-id pilot-zelda --round-id pilot-zelda
```

子集试跑不进入正式榜单。正式两条通道可共享同一轮次的 150 个合同：

```powershell
python main.py contract build --track full150 --round-id study
python main.py benchmark --model gpt_5_6_terra --track core15 --run-id terra-core --round-id study
python main.py benchmark --model gpt_5_6_terra --track full150 --run-id terra-full --round-id study
```

每个合同通过校验后立即保存。出现 `needs_contracts` 时，重复原来的合同命令只补缺失项；合同齐全后才锁定 manifest。一个已锁定的 Core 轮次不能原地扩为 Full，需要新 round。共享的是评测定义，生成及评测请求仍逐候选计费。

`needs_rescore` 可重复同一 benchmark 命令恢复缺失评测阶段；`needs_regeneration` 必须显式追加 `--resume-generation`，保留已完成的前置文件。普通候选语法或功能缺陷按既有规则评分，没有 semantic repair。

## 状态、结果和预算

```powershell
python main.py status --run-id terra-full
python main.py report --run-ids terra-core terra-full
python main.py budget --model gpt_5_6_terra --track full150 --reference-run-ids pilot-snake pilot-mole pilot-zelda
```

状态输出包含真实候选和证据目录。任务目录使用短 ID，完整实例名与模型名保存在 `run_state.json`、矩阵和结果中。`track_report.json` 包含覆盖率、分维度分数、家族内比较以及真实 API 用量。`report` 按通道及兼容的评测设置分组；历史未标注通道的结果独立展示。

Core 对 15 个基础实例等权平均。Full 先平均每家族十个实例，再平均十五个家族。缺失任何官方分数的完整通道不获得正式排名，正常完成的低分及零分必须计入。Full 的鲁棒性分析使用本次 Full 自己生成的基础版；变体编号只表示源文档顺序。

预算区分生成、文本 Judge、视觉 Judge和共享合同，使用试跑中的实际 usage/cost。文本 Judge 按检查点数量、视觉 Judge 按动态检查点数量外推，结果仍受证据大小和批次数影响。无试跑数据时只列输出上限，不填写虚构费用。相同目标模型优先使用 provider 实际 cost；估算其他模型时可传入 `--prices` 指向项目外的价格快照：

```json
{
  "as_of": "填写核实价格的日期",
  "models": {
    "供应商/模型": {
      "input_usd_per_million": 0,
      "output_usd_per_million": 0,
      "cached_input_usd_per_million": 0
    }
  }
}
```

模板中的零值必须替换为实际单价。`budget --round-id study` 可扣除该轮次已有的共享合同。图片包含在 provider 输入计费中；无法单列图片 tokens 时保留空值。重试计入实测消耗，生成的额外恢复周期另有字段。

初始化失败的候选可以提供生成用量样本；其未完整执行的 Judge 工作不用于外推全链路 Judge 预算。缺少 usage 的请求也不能被当作零费用。

## 数据维护和人工问卷

`benchmark/catalog.yaml` 保存基础家族及 135 个变体索引。每个实例包含完整 `spec.md`、`checkpoints.jsonl`、`game.yaml`；变体另有 `variation.json` 保存来源差异、已修改和新增检查点、基础对应关系。`benchmark/variant_source_audit.json` 记录外部文档来源和地图/标题修正。最终 DOCX 决定玩法，XLSX 只作差异参考；原压缩包不入仓库。

转换器 `scripts/import_variants.py --archive <外部ZIP路径>` 与维护的 `scripts/variant_rules.py` 可重建变体数据。正式评测直接读取已提交 JSONL，不调用模型生成评测标准。检查点总量通过 `validate` 实际统计。

基础检查点已按最终 DOCX 修正，并由 `benchmark/checkpoint_corrections.json` 记录修正版本、旧值、新值和来源章节。`maze_runner.D2.5.02` 在倒计时同帧归零时为 `lost`，`arena_shooter.D2.5.05` 与 `mini_zelda.D2.5.02` 在同帧 HP 归零时为 `game_over`；Maze 与 Mini Zelda 的普通胜利检查点也已拆出不发生同帧失败的前置条件。`variant_source_audit.json` 记录已解决的复核结果，`scripts/import_variants.py --rebuild-existing` 可从已提交的审计记录和规则重新物化变体。Arena 的 `var09` 是最终 DOCX 明确规定的胜利优先例外，其他 Arena 变体维持失败优先。

每个实例导出十条人工记录：五个 D2 锚点、整体视觉质量、两个动态反馈场景，以及同一 D4.3 场景的证据有效性和动作选择。锚点预先固定；缺失证据保留 `cannot_rate`。公开字段兼容现有动态网页，模型信息、自动得分和答案保存在私有映射，人工答卷不改变自动总分。

```powershell
python main.py human export --task-dir "状态报告里的task_dir" --output-dir "项目外问卷目录" --blind-id candidate-001
python main.py human validate --bundle-dir "导出返回的public_bundle目录"
python -m pytest
python main.py validate
python main.py smoke --track full150
python -m ruff check src scripts tests
```
