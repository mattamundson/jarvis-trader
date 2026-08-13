'use client';

import { POLL_INTERVAL } from "@/lib/polling-config";

import useSWR from 'swr';
import { fetchEngine } from '@/lib/api';
import type { JarvisEvent, EventsResponse } from '@/lib/api';

export function EventsFeedWidget() {
  const { data, isLoading, error } = useSWR<EventsResponse>(
    '/events/recent',
    fetchEngine,
    { refreshInterval: POLL_INTERVAL.FAST }
  );

  if (error) {
    return (
      <div className="rounded-lg border border-red-200 bg-red-50 p-4">
        <p className="text-sm text-red-700">Failed to load events</p>
      </div>
    );
  }

  const events = data?.events || [];

  return (
    <div className="rounded-lg border border-slate-200 bg-white">
      <div className="border-b border-slate-200 px-4 py-3">
        <h3 className="text-sm font-semibold text-slate-900">JARVIS Events</h3>
      </div>

      <div className="max-h-72 overflow-y-auto">
        {events.length === 0 ? (
          <div className="flex items-center justify-center px-4 py-8">
            <p className="text-sm text-slate-500">No events yet</p>
          </div>
        ) : (
          <div className="divide-y divide-slate-200">
            {events.slice(0, 25).map((event: JarvisEvent) => (
              <div
                key={event.id}
                className="flex items-start gap-3 px-4 py-3 text-sm hover:bg-slate-50"
              >
                <div className="flex-shrink-0 pt-0.5">
                  <SeverityBadge severity={event.severity} />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-xs text-slate-500">
                      {formatTime(event.timestamp)}
                    </span>
                    <span className="font-semibold text-slate-700 uppercase text-xs">
                      {event.type}
                    </span>
                    {event.symbol && (
                      <span className="font-mono text-xs text-slate-600">
                        {event.symbol}
                      </span>
                    )}
                  </div>
                  <p className="mt-1 text-slate-600 break-words">
                    {event.message}
                  </p>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {isLoading && (
        <div className="border-t border-slate-200 bg-slate-50 px-4 py-2">
          <p className="text-xs text-slate-500">Loading...</p>
        </div>
      )}
    </div>
  );
}

function SeverityBadge({ severity }: { severity: string }) {
  const variants: Record<string, { bg: string; text: string }> = {
    info: { bg: 'bg-blue-100', text: 'text-blue-700' },
    warn: { bg: 'bg-yellow-100', text: 'text-yellow-700' },
    critical: { bg: 'bg-red-100', text: 'text-red-700' },
  };

  const variant = variants[severity] || variants.info;

  return (
    <span className={`inline-flex items-center rounded px-2 py-1 text-xs font-medium ${variant.bg} ${variant.text}`}>
      {severity === 'info' && '●'}
      {severity === 'warn' && '⚠'}
      {severity === 'critical' && '✕'}
    </span>
  );
}

function formatTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleTimeString('en-US', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
      hour12: false,
    });
  } catch {
    return '??:??:??';
  }
}
