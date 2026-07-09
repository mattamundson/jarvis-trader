"use client";

import useSWR from "swr";
import { Card, CardHeader, CardTitle, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { fetchHealthBackupStatus } from "@/lib/api";

const REFRESH_MS = 5 * 60_000; // backups run nightly -- no need to poll fast

// engine/backup/db_backup.py stamps last_backup via datetime.utcnow().isoformat(),
// which is naive (no trailing Z/offset). new Date() on a no-offset ISO string
// parses as the BROWSER's local timezone, not UTC -- for US users that silently
// undercounts elapsed hours (a stale backup can misreport as fresh). Force UTC
// interpretation by appending Z when no offset is already present.
function parseUtc(ts: string): Date {
  const hasOffset = /Z$|[+-]\d{2}:\d{2}$/.test(ts);
  return new Date(hasOffset ? ts : `${ts}Z`);
}

function fmtDate(ts: string | null): string {
  if (!ts) return "never";
  try {
    return parseUtc(ts).toLocaleString("en-US", {
      month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    });
  } catch {
    return ts;
  }
}

function hoursSince(ts: string | null): number | null {
  if (!ts) return null;
  const parsed = parseUtc(ts).getTime();
  if (Number.isNaN(parsed)) return null;
  return (Date.now() - parsed) / (1000 * 60 * 60);
}

function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / (1024 * 1024)).toFixed(1)} MB`;
}

export function BackupHealthWidget() {
  const { data, isLoading, error } = useSWR(
    "health-backup-status",
    fetchHealthBackupStatus,
    { refreshInterval: REFRESH_MS }
  );

  const staleHours = data ? hoursSince(data.last_backup) : null;
  // Nightly job: > 30h since last backup means at least one run was missed.
  // No backup EVER (last_backup null) is the worst case, not "no news is good
  // news" -- must read as stale, not as a clean/default OK.
  const isStale = data != null && (staleHours == null || staleHours > 30);

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle>Backup Health</CardTitle>
          <Badge variant={error ? "static" : "live"}>{error ? "static" : "live"}</Badge>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading ? (
          <p className="text-xs text-muted-foreground/50 animate-pulse">Loading…</p>
        ) : error ? (
          <p className="text-xs text-red-400/70 italic">
            Backup status unavailable — engine may be unreachable
          </p>
        ) : (
          <>
            <div className="grid grid-cols-2 gap-3 text-sm">
              <div>
                <p className="text-xs text-muted-foreground">Last Backup</p>
                <p className="font-mono font-semibold text-xs">
                  {fmtDate(data!.last_backup)}
                </p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Backup Count</p>
                <p className="font-mono font-semibold">{data!.backup_count}</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Retention</p>
                <p className="font-mono font-semibold">{data!.retention_days} days</p>
              </div>
              <div>
                <p className="text-xs text-muted-foreground">Status</p>
                <Badge variant={isStale ? "bear" : "bull"}>
                  {isStale ? "STALE" : "OK"}
                </Badge>
              </div>
            </div>

            <div className="rounded-md border border-warn/30 bg-warn/5 px-3 py-2">
              <p className="text-[11px] text-warn">
                Backups are local-disk only (data/backups/) — no offsite/S3 copy,
                and no restore has been drilled/tested from this dashboard.
              </p>
            </div>

            {data!.available_backups.length > 0 && (
              <div className="space-y-1 pt-1">
                <p className="text-[10px] text-muted-foreground uppercase tracking-wider">
                  Recent files
                </p>
                {data!.available_backups.slice(-5).reverse().map((f) => (
                  <div key={f.filename} className="flex items-center justify-between text-[11px]">
                    <span className="text-muted-foreground truncate">{f.filename}</span>
                    <span className="text-foreground/70 tabular-nums shrink-0 ml-2">
                      {fmtBytes(f.size_bytes)}
                    </span>
                  </div>
                ))}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
