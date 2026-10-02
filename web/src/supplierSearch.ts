/** Convert a supplier picker label to the code sent to the Data Center API. */
export function supplierSearchValue(value: string): string {
  return value.trim().replace(/^.+\(\s*(SUP-[A-Z0-9-]+)\s*\)$/i, "$1");
}
