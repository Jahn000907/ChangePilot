const values: Record<string, string> = {
  ACTIVE: "正常", BLOCKED: "已冻结", PHASE_OUT: "逐步退出",
  QUALIFIED: "已认证", UNQUALIFIED: "未认证", CONDITIONAL: "有条件认证",
  RELEASED: "已发布", PASS: "通过", REVISE: "需要修订",
  OPEN: "进行中", PARTIALLY_RECEIVED: "部分收货", COMPLETED: "已完成",
  CANCELLED: "已取消", DRAFT: "草稿", PENDING: "待执行",
  RUNNING: "运行中", WAITING_HUMAN: "等待人工审批", SUCCEEDED: "成功",
  FAILED: "失败", STARTED: "已开始", APPROVE: "批准", REJECT: "驳回",
  APPROVED: "已批准", REJECTED: "已驳回", ON_HOLD: "已暂停",
  PARTIAL: "部分完成", PLANNED: "已计划", LAST_TIME_BUY: "最后采购期",
  EOL: "已停产", CONFIRMED: "已确认", PARTIALLY_DELIVERED: "部分交付",
};

export function businessStatus(value: string): string {
  return values[value] || value;
}
