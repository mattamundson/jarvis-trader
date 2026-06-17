"use client";
import useSWR from "swr";
import { fetchEngine } from "@/lib/api";

export interface ResearchEntry {
  id: number;
  date: string;
  category: "CRITICAL" | "FINDING" | "IMPROVEMENT" | "VERDICT" | "NOTE";
  status: "Active" | "Resolved" | "Archived";
  entry: string;
  instrument: string | null;
  tags: string[];
  created_at: string;
  updated_at: string;
}

export interface CreateEntryPayload {
  date: string;
  category: string;
  status?: string;
  entry: string;
  instrument?: string;
  tags?: string[];
}

const fetcher = (url: string) => fetchEngine<ResearchEntry[]>(url);

export function useJournal(filters?: {
  category?: string;
  status?: string;
  instrument?: string;
  limit?: number;
}) {
  const params = new URLSearchParams();
  if (filters?.category) params.set("category", filters.category);
  if (filters?.status) params.set("status", filters.status);
  if (filters?.instrument) params.set("instrument", filters.instrument);
  if (filters?.limit) params.set("limit", String(filters.limit));

  const key = `/research-journal/entries?${params.toString()}`;
  const { data, error, isLoading, mutate } = useSWR<ResearchEntry[]>(key, fetcher, {
    refreshInterval: 60_000,
  });

  const createEntry = async (payload: CreateEntryPayload) => {
    // Optimistic: we'll revalidate after
    await fetchEngine("/research-journal/entries", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    } as RequestInit);
    await mutate();
  };

  const updateEntry = async (id: number, updates: { status?: string; entry?: string }) => {
    await fetchEngine(`/research-journal/entries/${id}`, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(updates),
    } as RequestInit);
    await mutate();
  };

  return {
    entries: data ?? [],
    isLoading,
    isOffline: !!error,
    error,
    createEntry,
    updateEntry,
    mutate,
  };
}
