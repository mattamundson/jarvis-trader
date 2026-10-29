// Security audit logging for sensitive operations
export interface AuditEntry {
  timestamp: string;
  action: string;
  actor_ip: string;
  actor_ua?: string;
  resource?: string;
  success: boolean;
  details?: Record<string, unknown>;
}

export function logAudit(entry: AuditEntry) {
  // Structured logging for audit events
  // In production, consider shipping to dedicated security log store (Datadog, Splunk)
  console.log(JSON.stringify({
    type: "security_audit",
    severity: entry.success ? "info" : "warning",
    ...entry
  }));
}

// Common audit actions
export function logAuthAttempt(ip: string, endpoint: string, success: boolean, details?: Record<string, unknown>) {
  logAudit({
    timestamp: new Date().toISOString(),
    action: "auth_attempt",
    actor_ip: ip,
    resource: endpoint,
    success,
    details
  });
}

export function logCronInvocation(ip: string, endpoint: string, authorized: boolean) {
  logAudit({
    timestamp: new Date().toISOString(),
    action: "cron_invocation",
    actor_ip: ip,
    resource: endpoint,
    success: authorized,
    details: { from_vercel: ip.startsWith("76.76.21.") }
  });
}

export function logIngestAttempt(ip: string, success: boolean, reason?: string) {
  logAudit({
    timestamp: new Date().toISOString(),
    action: "flow_ingest",
    actor_ip: ip,
    resource: "/api/flow/ingest",
    success,
    details: { reason }
  });
}
