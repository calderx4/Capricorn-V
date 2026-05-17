# 自进化纠偏示例（数据分析）

> 本文件记录完整的纠偏场景，供 verifier cron 参考如何执行自进化。

---

## 示例 1：报告缺少对比分析（bia_update）

### 触发条件

verifier cron 连续 3 次在 `has_comparison` 维度不通过：

```
quality_signal list →
  P3-001: has_comparison=false
  P3-002: has_comparison=false
  P3-003: has_comparison=false
```

### 纠偏步骤

**1. 定位问题**

读取最近的 3 份报告：
```
read_file("reports/phase3/P3-001_ORDER_PREDICTION_20260517.md")
read_file("reports/phase3/P3-002_ANOMALY_DETECTION_20260517.md")
read_file("reports/phase3/P3-003_TREND_FORECAST_20260517.md")
```

发现：报告只描述了预测结果，没有与历史数据对比。

**2. 执行纠偏**

```
bia_update(content="- [对比分析] 当产出包含预测结果时，必须包含与历史实际值的对比数据（如上月/去年同期）")
```

**3. 记录变更**

```
changelog add(
  type="bia",
  description="追加规则：预测类报告必须包含与历史实际值的对比",
  reason="has_comparison 连续 3 次不通过（P3-001, P3-002, P3-003）",
  status="active"
)
```

**4. 验证**

下次 executor 执行时，bia.md 中的新规则会被读取，报告应包含对比数据。

---

## 示例 2：skill 缺少异常标注步骤（edit_file）

### 触发条件

verifier cron 连续 3 次在 `has_anomaly` 维度不通过：

```
quality_signal list →
  P2-003: has_anomaly=false
  P2-004: has_anomaly=false
  P2-005: has_anomaly=false
```

### 纠偏步骤

**1. 定位问题**

读取失败的报告，发现链路分析报告没有标注异常环节。

**2. 查看相关 skill**

```
skill_view("table-analysis")
```

发现 skill 的执行步骤中没有"标注异常值"这一步。

**3. 执行纠偏**

```
edit_file(
  file="table-analysis/SKILL.md",
  old="## 执行步骤\n1. 读取数据\n2. 统计分布\n3. 生成报告",
  new="## 执行步骤\n1. 读取数据\n2. 统计分布\n3. 标注异常值（偏离均值 2σ 以上的数据点）\n4. 生成报告"
)
```

> 注意：实际 edit_file 调用时路径为 skill 在 workspace 中的路径。skill_view 会返回完整路径。

**4. 记录变更**

```
changelog add(
  type="skill",
  description="修改 table-analysis SKILL.md：增加异常标注步骤",
  reason="has_anomaly 连续 3 次不通过（P2-003, P2-004, P2-005）",
  status="active"
)
```

---

## 示例 3：缺少跨表关联工具（方式 3 — 需要 approval）

### 触发条件

executor 多次在单表分析任务中手动做跨表关联，效率低且容易出错。

### 纠偏步骤

**1. 创建新 workflow**

```
write_file(
  path="workflows/cross_table_analysis/__init__.py",
  content="..."
)
```

**2. 记录为待审批**

```
changelog add(
  type="workflow",
  description="新增 cross_table_analysis workflow",
  reason="发现跨表关联分析反复出现，需要专用工具",
  status="pending_approval"
)
```

**3. 等待审批**

不会自动生效。需要用户在 Phase 3（人工介入）时审批。

---

## 示例 4：完整的质量信号 → 纠偏 → 验证 循环

### 时间线

```
T+0h: executor 执行 P4-001（规则引擎分析）
      → 产出报告 reports/phase4/P4-001_RULE_ENGINE_20260517.md
      → quality_check 自检：pass

T+4h: verifier cron 执行
      → quality_check(P4-001): has_comparison=false（缺少通过/拒绝规则对比）
      → quality_signal record: {task_id: "P4-001", status: "fail", fail_items: ["has_comparison"]}

T+8h: executor 执行 P4-002（企业风险分级）
      → quality_check 自检：pass

T+8h: verifier cron 执行
      → quality_check(P4-002): has_comparison=false
      → quality_signal record: {task_id: "P4-002", status: "fail", fail_items: ["has_comparison"]}
      → 检测：has_comparison 连续 2 次 → 未达阈值，继续观察

T+12h: executor 执行 P4-003（策略建议）
       → quality_check 自检：pass

T+12h: verifier cron 执行
       → quality_check(P4-003): has_comparison=false
       → quality_signal record: {task_id: "P4-003", status: "fail", fail_items: ["has_comparison"]}
       → 检测：has_comparison 连续 3 次 → 达到阈值！

       → 纠偏：
         1. read_file 读取 P4-001, P4-002, P4-003
         2. 分析：Phase 4 报告只列出了规则，没有对比不同规则的优劣
         3. bia_update: "- [对比分析] 当涉及多种规则或策略时，必须包含各方案的对比（准确率/覆盖率/适用场景）"
         4. changelog add: type=bia, reason="has_comparison 连续 3 次（P4-001~P4-003）"

T+16h: executor 执行修正后的任务（如有待执行）
       → 产出包含规则对比 → quality_check: has_comparison=true ✅

T+20h: verifier cron 验证
       → quality_check: pass ✅
       → 纠偏成功，记录 improvement
```
