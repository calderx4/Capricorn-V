# 步骤 2.1：创建执行 Cron

> 用 `cron create` 创建 role=executor 的定时任务，自动从 tasks.md 领取任务执行。

## Capricorn 应该做什么

1. **读取 tasks.md** — 确认待执行任务列表和优先级
2. **创建执行 Cron** — 调用 `cron create`：

```
cron create
  name: "任务执行"
  schedule: "every 1h"
  role: "executor"
  prompt: |
    读取 tasks.md，找到第一个状态为"待执行"的高优先级任务。
    完整执行该任务。
    将产出文件写入 reports/ 目录。
    在 tasks.md 中标记该任务为"已完成"。
```

**关键：必须传 `role: executor`**。这样 cron 会使用 executor 角色模板（自带 workspace、tools、skills 注入），prompt 只需写简短触发语。不要把执行细节写进 prompt。

3. **验证运行** — 确认第一个任务能正常完成

## 完成标志

- [ ] executor cron 已创建（role=executor）
- [ ] 第一个任务正常执行完成
- [ ] 产出文件正常输出

---

# 步骤 2.2：创建验证 Cron

> 用 `cron create` 创建 role=verifier 的定时任务，自动验证产出质量并纠偏。

## Capricorn 应该做什么

1. **确认 verifier cron** — 系统会自动注册一个 `每日质量验收` 的 verifier cron（role=verifier，每天 18:00）。确认它已存在：

```
cron list
```

2. **如果需要更高频率** — 可以额外创建一个：

```
cron create
  name: "质量验证与纠偏"
  schedule: "0 */4 * * *"
  role: "verifier"
  prompt: |
    执行质量验证流程。
```

> 注：verifier 角色的完整指令在角色模板中，包括：扫描已完成产出 → quality_check → quality_signal record → 连续不通过时 bia_update 纠偏 → changelog 记录。prompt 只需写简短触发语。

3. **验证运行** — 确认能正确读取产出并输出质量检查结果

## 自进化机制

verifier cron 内置的纠偏流程：

```
每次验证：
  1. 扫描已完成的产出
  2. 调用 quality_check 检查质量
  3. 记录 quality_signal

发现连续不通过（某维度 ≥ 3 次）：
  1. 分析最近几份产出缺什么
  2. 选择一种修正方式（每次只改一个）：
     - bia_update 追加行为纠偏规则
     - edit_file 修改 skill
  3. changelog 记录变更
  4. 下次执行时验证是否改善
```

纠偏效果传播链：
- bia.md → 每次对话/Cron 都读取 → 即时生效
- skill 修改 → 下次 skill_view 时读取 → 即时生效
- 新 workflow/tool → 需要重启 → 记录为 pending_approval

## 完成标志

- [ ] verifier cron 已存在（role=verifier）
- [ ] 能正确验证产出质量
- [ ] quality_signal 正常记录
- [ ] 连续不通过时能自动纠偏

---

# 步骤 2.3：持续运行

> 阶段 2 的常态：executor 执行 + verifier 验证 + 自动纠偏。

## 运行循环

```
executor cron（每小时）        verifier cron（每天或每4小时）
    │                              │
    ├─ 读 tasks.md                 ├─ 扫描已完成产出
    ├─ 取下一个待执行任务           ├─ quality_check 逐份检查
    ├─ 执行任务，写产出             ├─ quality_signal record
    ├─ quality_check 自检           ├─ 发现连续不通过 → bia_update
    └─ 标记任务完成                 └─ changelog 记录变更
```

## 状态追踪

| 产出 | 位置 | 说明 |
|------|------|------|
| 任务产出 | `reports/` | executor 每次执行产出 |
| 质量信号 | `team/quality_signals/` | verifier 每次验证记录 |
| 纠偏规则 | `bia.md` | verifier 发现模式问题时写入 |
| 变更日志 | `team/changelog/` | 所有自动改动记录 |
| 任务进度 | `tasks.md` | executor 标记完成状态 |

## 退出条件

- 所有 tasks.md 中的任务完成 → 自然结束
- 用户主动发起对话 → 进入 Phase 3（人工介入）
