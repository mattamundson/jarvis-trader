// Pure transforms for the /alerts/stats engine endpoint.
//
// WHY: engine/routers/alerts_router.py's GET /alerts/stats returns
// {stats: [{alert_type, status, count}, ...], total} -- a flat grouped-count
// array, not a {by_type, by_status, by_channel, total} breakdown. GT-03:
// the dashboard's Alert Log widget (components/AlertSummaryWidget.tsx) was
// coded against the wrong shape, so `stats.by_status?.failed` was always
// `undefined` and the widget rendered "All OK, 0 Failed" even when a real
// 38.8% of alerts had failed. WhatsAppStatusCard.tsx already consumes the
// real {stats, total} shape correctly (see its `AlertStats` interface) --
// this file gives AlertSummaryWidget the same correct read, as a pure
// function so the aggregation is unit-testable without mounting React.

export interface AlertStatCount {
  alert_type: string;
  status: string;
  count: number;
}

export interface AlertStatsRaw {
  stats: AlertStatCount[];
  total: number;
}

export interface AlertStatusCounts {
  sent: number;
  failed: number;
  pending: number;
  total: number;
}

/** Sum per-(type,status) rows from the real /alerts/stats payload into
 * status totals. Unknown statuses are ignored (not folded into any bucket)
 * so a new status value can't silently inflate "sent" or "failed". */
export function summarizeAlertStatusCounts(
  raw: AlertStatsRaw | null | undefined,
): AlertStatusCounts {
  const rows = raw?.stats ?? [];
  let sent = 0;
  let failed = 0;
  let pending = 0;
  for (const row of rows) {
    switch (row.status) {
      case "sent":
        sent += row.count;
        break;
      case "failed":
        failed += row.count;
        break;
      case "pending":
        pending += row.count;
        break;
      default:
        break;
    }
  }
  return { sent, failed, pending, total: raw?.total ?? 0 };
}
