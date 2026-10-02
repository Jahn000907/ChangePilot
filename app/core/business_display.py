"""Chinese labels for business values in assistant-facing output."""

BUSINESS_VALUES = {
    "QUALIFIED": "已认证", "UNQUALIFIED": "未认证", "CONDITIONAL": "有条件认证",
    "RELEASED": "已发布", "PASS": "通过", "REVISE": "需要修订",
    "OPEN": "未完成", "IN_PROGRESS": "进行中", "COMPLETED": "已完成",
    "CANCELLED": "已取消", "ACTIVE": "有效", "DRAFT": "草稿",
    "PARTIALLY_RECEIVED": "部分收货", "BLOCKED": "已冻结",
    "PHASE_OUT": "逐步退出", "PENDING": "待执行", "RUNNING": "运行中",
    "WAITING_HUMAN": "等待人工审批", "SUCCEEDED": "成功", "FAILED": "失败",
    "APPROVE": "批准", "REJECT": "驳回", "APPROVED": "已批准",
    "REJECTED": "已驳回", "PLANNED": "计划中", "ON_HOLD": "已暂停",
    "PARTIAL": "部分完成", "NO_DATA": "暂无数据",
    "LAST_TIME_BUY": "末次采购", "CONFIRMED": "已确认",
    "PARTIALLY_DELIVERED": "部分交付",
}


def business_value(value: object) -> str:
    return BUSINESS_VALUES.get(str(value), str(value))
