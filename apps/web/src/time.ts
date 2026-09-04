/** SQLite timestamps without an offset represent UTC, never browser local time. */
export function formatUtcTimestamp(value: string): string {
  const explicitZone = /(?:Z|[+-]\d{2}:\d{2})$/i.test(value)
  const date = new Date(explicitZone ? value : `${value}Z`)
  return Number.isNaN(date.getTime()) ? '未知时间' : date.toLocaleString()
}
