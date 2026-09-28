const BUSINESS_ZONE = "Asia/Shanghai";

export function businessDateShanghai(now = new Date()): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: BUSINESS_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
  }).formatToParts(now);
  const field = (name: string) => parts.find((part) => part.type === name)?.value || "";
  return `${field("year")}-${field("month")}-${field("day")}`;
}

export function formatShanghaiTime(value: string): string {
  // Legacy offset-free database timestamps are UTC; new API values carry an offset.
  const normalized = /(?:Z|[+-]\d{2}:?\d{2})$/i.test(value) ? value : `${value}Z`;
  const instant = new Date(normalized);
  if (Number.isNaN(instant.getTime())) return "时间不可用";
  return new Intl.DateTimeFormat("zh-CN", {
    timeZone: BUSINESS_ZONE, year: "numeric", month: "2-digit", day: "2-digit",
    hour: "2-digit", minute: "2-digit", hour12: false,
  }).format(instant) + "（北京时间）";
}

export function formatQuantity(value: string | number): string {
  const text = String(value);
  if (!/^-?\d+(?:\.\d+)?$/.test(text)) return text;
  return text.includes(".") ? text.replace(/0+$/, "").replace(/\.$/, "") : text;
}
