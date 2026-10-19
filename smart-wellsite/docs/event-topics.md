# 智慧井场事件 Topic 清单

## Topic 规范

格式：`wellsite/{site_id}/{domain}/{event_type}`

通配符：
- `*` 匹配单层 topic
- `#` 匹配多层 topic（类似 MQTT 的 `#`）

## Topic 列表

### 感知层 - 传感器数据

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/sensor/{device_id}/{param_type}` | 原始传感器数据 | `{timestamp, value, quality, unit}` |
| `wellsite/{site_id}/sensor_anomaly/{device_id}/{anomaly_type}` | 传感器异常 | `{device_id, anomaly_type, severity, value, threshold, window_summary}` |
| `wellsite/{site_id}/indicator/{device_id}/{indicator_type}` | 示功图等指标数据 | `{device_id, indicator_type, load[], displacement[], timestamp}` |
| `wellsite/{site_id}/indicator_anomaly/{device_id}/{anomaly_type}` | 指标异常 | `{device_id, anomaly_type, severity, indicator_value, threshold}` |

### 分析层 - 诊断

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/diagnosis/{fault_type}` | 设备故障诊断结果 | `{well_id, device_id, fault_type, confidence, evidence[], recommendation}` |
| `wellsite/{site_id}/diagnosis/updated/{device_id}` | 诊断结果更新 | `{device_id, old_fault, new_fault, updated_by}` |

### 执行层 - 告警

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/alert/{level}` | 分级告警 | `{alert_uid, level, title, description, device_id, confidence, source_agent}` |
| `wellsite/{site_id}/alert/acknowledged/{alert_uid}` | 告警确认 | `{alert_uid, acknowledged_by, timestamp}` |
| `wellsite/{site_id}/alert/resolved/{alert_uid}` | 告警关闭 | `{alert_uid, resolved_by, resolution, timestamp}` |

### 执行层 - 工单

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/workorder/created` | 工单创建 | `{order_uid, alert_id, title, priority, device_id}` |
| `wellsite/{site_id}/workorder/assigned` | 工单分配 | `{order_uid, assignee, assigned_by}` |
| `wellsite/{site_id}/workorder/processing` | 工单处理中 | `{order_uid, actions_taken, updated_by}` |
| `wellsite/{site_id}/workorder/resolved` | 工单完成 | `{order_uid, resolution, resolved_by}` |
| `wellsite/{site_id}/workorder/closed` | 工单关闭 | `{order_uid, actual_cause, closed_by}` |

### 交互层 - 控制指令

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/control/requested` | 控制指令请求（待确认） | `{request_id, action, target, params, reason, requested_by}` |
| `wellsite/{site_id}/control/approved` | 控制指令已批准 | `{request_id, approved_by, timestamp}` |
| `wellsite/{site_id}/control/rejected` | 控制指令被拒绝 | `{request_id, rejected_by, reason}` |
| `wellsite/{site_id}/control/executed` | 控制指令已执行 | `{request_id, action, target, result, executed_by}` |

### 阶段二 - 视频 / 环境

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/video/detection` | 视频检测结果 | `{camera_id, objects[], confidence, frame_ts}` |
| `wellsite/{site_id}/environment/{param}` | 环境监测 | `{param, value, unit, quality}` |
| `wellsite/{site_id}/environment/alert/{type}` | 环境告警 | `{type, value, threshold, severity}` |

### 阶段三 - 生产优化

| Topic | 说明 | Payload Schema |
|-------|------|---------------|
| `wellsite/{site_id}/optimization/suggestion` | 生产优化建议 | `{well_id, suggestions[], expected_improvement}` |
| `wellsite/{site_id}/safety/risk_assessment` | 安全风险评估 | `{site_id, risk_level, risk_items[], mitigation}` |
| `wellsite/{site_id}/feedback/submitted` | 人工反馈提交 | `{feedback_id, target_diagnosis, feedback_type, content}` |
