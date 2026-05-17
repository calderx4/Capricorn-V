# 自进化纠偏示例

> 本文件记录完整的纠偏场景，供 verifier cron 参考如何执行自进化。

---

## 示例 1：产出缺少对比分析（bia_update）

### 触发条件

verifier cron 连续 3 次在 `has_comparison` 维度不通过：

```
quality_signal list →
  T-005: has_comparison=false
  T-006: has_comparison=false
  T-007: has_comparison=false
```

### 纠偏步骤

**1. 定位问题**

读取最近的 3 份产出：
```
read_file("reports/T-005.md")
read_file("reports/T-006.md")
read_file("reports/T-007.md")
```

发现：产出只描述了结果，没有与基准数据或历史数据对比。

**2. 执行纠偏**

```
bia_update(content="- [对比分析] 当产出包含结论时，必须包含与基准或历史数据的对比")
```

**3. 记录变更**

```
changelog add(
  type="bia",
  description="追加规则：产出必须包含与基准或历史数据的对比",
  reason="has_comparison 连续 3 次不通过（T-005, T-006, T-007）",
  status="active"
)
```

**4. 验证**

下次 executor 执行时，bia.md 中的新规则会被读取，产出应包含对比数据。

---

## 示例 2：skill 缺少关键步骤（edit_file）

### 触发条件

verifier cron 连续 3 次在某个质量维度不通过。

### 纠偏步骤

**1. 定位问题**

读取失败的产出，发现缺少某个分析环节。

**2. 查看相关 skill**

```
skill_view("core-analysis")
```

发现 skill 的执行步骤中缺少该环节。

**3. 执行纠偏**

```
edit_file(
  file="core-analysis/SKILL.md",
  old="...",
  new="..."（在适当位置插入缺失步骤）
)
```

> 注意：skill_view 会返回 skill 的完整路径，edit_file 使用该路径。

**4. 记录变更**

```
changelog add(
  type="skill",
  description="修改 core-analysis SKILL.md：增加缺失的分析步骤",
  reason="某维度连续 3 次不通过",
  status="active"
)
```

---

## 示例 3：缺少专用工具（方式 3 — 需要 approval）

### 触发条件

executor 多次在任务中手动执行某类操作，效率低且容易出错。

### 纠偏步骤

**1. 创建新 workflow**

```
write_file(
  path="workflows/{workflow_name}/__init__.py",
  content="..."
)
```

**2. 记录为待审批**

```
changelog add(
  type="workflow",
  description="新增 {workflow_name} workflow",
  reason="某类操作反复出现，需要专用工具",
  status="pending_approval"
)
```

**3. 等待审批**

不会自动生效。需要用户在 Phase 3（人工介入）时审批。

---

## 示例 4：完整的质量信号 → 纠偏 → 验证 循环

### 时间线

```
T+0h: executor 执行任务 T-010
      → 产出 reports/T-010.md
      → quality_check 自检：pass

T+4h: verifier cron 执行
      → quality_check(T-010): has_comparison=false
      → quality_signal record: {task_id: "T-010", status: "fail", fail_items: ["has_comparison"]}

T+8h: executor 执行任务 T-011
      → quality_check 自检：pass

T+8h: verifier cron 执行
      → quality_check(T-011): has_comparison=false
      → quality_signal record: {task_id: "T-011", status: "fail", fail_items: ["has_comparison"]}
      → 检测：has_comparison 连续 2 次 → 未达阈值，继续观察

T+12h: executor 执行任务 T-012
       → quality_check 自检：pass

T+12h: verifier cron 执行
       → quality_check(T-012): has_comparison=false
       → quality_signal record: {task_id: "T-012", status: "fail", fail_items: ["has_comparison"]}
       → 检测：has_comparison 连续 3 次 → 达到阈值！

       → 纠偏：
         1. read_file 读取 T-010, T-011, T-012
         2. 分析：产出缺少与基准的对比
         3. bia_update: "- [对比分析] 当产出包含结论时，必须包含与基准或历史数据的对比"
         4. changelog add: type=bia, reason="has_comparison 连续 3 次（T-010~T-012）"

T+16h: executor 执行修正后的任务
       → 产出包含对比数据 → quality_check: has_comparison=true ✅

T+20h: verifier cron 验证
       → quality_check: pass ✅
       → 纠偏成功，记录 improvement
```
