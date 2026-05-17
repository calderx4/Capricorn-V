---
name: self-evolution
description: 自进化机制 — verifier cron 在任务产出连续不通过时自动纠偏。按 evolution_policy.md 策略执行。
available: true
---

# Self-Evolution

## 核心思想

自进化 = verifier cron 自动发现任务产出的质量问题 → 定位原因 → 修改规则 → 验证效果。

**前置条件**：阶段1 中用户和 Capricorn 已协商好 `evolution_policy.md`。自进化严格按策略执行，不做策略外的事。

## 触发入口

由 verifier cron 在每次验证时检测：

```
verifier cron 触发
    → quality_check 逐份检查产出质量
    → quality_signal record
    → 检测：某质量维度连续不通过次数 ≥ 触发阈值？
        → 是：进入纠偏流程
        → 否：输出质量汇总
```

## 纠偏流程

1. **收集上下文** — `quality_signal list` 读取最近检查结果，理解哪些产出在哪些维度失败
2. **定位问题** — 只输出一个"改动假设"，定位到单一问题点
3. **选择改动方式** — 每次仅允许三选一（见下方）
4. **检查权限** — 对照 `evolution_policy.md`，该改动是否在允许范围内
5. **执行改动** — bia_update / edit_file
6. **记录变更** — `changelog add`
7. **验证效果** — 下次 verifier cron 检查时评估是否改善

## 文件路径说明

纠偏操作涉及两类文件：workspace 文件（产出数据）和系统文件（skills/tools/prompts）。verifier cron 对 workspace 文件有读写权限，对系统文件只有通过 `bia_update` 和 `edit_file` 工具修改的权限。

### Workspace 文件（产出数据）

| 文件 | 路径 | 说明 | 操作工具 |
|------|------|------|----------|
| 任务列表 | `tasks.md` | 所有任务和状态 | `read_file` |
| 任务产出 | `reports/` | executor 产出的文件 | `read_file` |
| 质量信号 | `team/quality_signals/` | quality_check 结果 | `quality_signal` |
| 变更日志 | `team/changelog/` | 所有自动改动记录 | `changelog` |
| 进化策略 | `evolution_policy.md` | 纠偏权限和规则 | `read_file` |
| 对齐规则 | `alignment.md` | 质量标准和约束 | `read_file` |
| BIA 行为规则 | `bia.md` | 行为纠偏规则 | `bia_update` |

### 工具路径映射

| 工具 | 写入目标 | 说明 |
|------|----------|------|
| `quality_signal record` | `team/quality_signals/{id}.json` | 记录单次检查结果 |
| `quality_signal list` | 读取 `team/quality_signals/` | 查询历史信号 |
| `quality_signal summary` | 汇总 `team/quality_signals/` | 质量统计 |
| `changelog add` | `team/changelog/{id}.md` | 记录一次变更 |
| `changelog list` | 读取 `team/changelog/` | 查询变更历史 |
| `bia_update` | `bia.md`（workspace 根目录） | 追加或更新行为规则 |
| `quality_check` | 无写入，返回检查结果 | 按维度检查产出 |

### Skill 文件位置（通过工具间接访问）

| 文件 | 访问方式 | 说明 |
|------|----------|------|
| 任意 skill | `skill_view("{skill_name}")` | 加载 skill 内容 |
| 修改 skill | `skill_view()` 后用 `edit_file` | 不要直接拼路径 |

> 不要直接拼路径修改 skill 文件。先用 `skill_view()` 获取内容，再用 `edit_file` 修改。

## 三种改动方式

### 方式 1：修改 bia.md（行为纠偏规则）

适用场景：同类任务反复犯同类错误。

操作：`bia_update` 追加一条规则。格式：`- [场景] 当...时，必须...`

示例：
```
- [结构要求] 当产出超过 200 字时，必须包含至少一个标题
- [内容要求] 当涉及关键结论时，必须有具体数据支撑
- [重点标注] 当重点关注项占比 >30% 时，必须单独分析
```

限制：每次只允许添加或修改**一条**规则。即时生效。

### 方式 2：修改 skill（局部优化）

适用场景：skill 指令不够明确，导致执行偏差。

操作流程：
1. `skill_view("{skill_name}")` — 加载 skill 内容
2. `edit_file` — 修改 SKILL.md 中需要调整的部分

示例：
```
问题：执行 skill 没有要求标注依据来源
→ skill_view("table-analysis")
→ edit_file 追加步骤"标注每个结论的来源依据"
```

限制：每次只允许修改**一个** skill 的**一处**。即时生效。

### 方式 3：增加 workflow / tool

适用场景：现有工具无法完成某类操作。

操作：`write_file` 创建新文件。

限制：每次只允许新增**一个**。需要重启。必须 `changelog add` status=`pending_approval`。

## 关键约束

- **每次只改一个** — 不叠加，验证后再改下一个
- **检查 evolution_policy** — 不做策略外的改动
- **所有改动记录 changelog** — 可追溯、可回滚
- **纠偏后连续 2 次仍不改善** → 自动回滚 + changelog 记录

## 详细示例

完整的纠偏场景示例见 [steps/examples.md](steps/examples.md)。
