import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { SWRConfig } from "swr";
import type { ReactNode } from "react";

vi.mock("@/lib/api", () => ({
  fetchEngineNoRetry: vi.fn(),
}));

import { fetchEngineNoRetry } from "@/lib/api";
import { useEngineStatus } from "@/hooks/useEngineStatus";

const mockedFetch = vi.mocked(fetchEngineNoRetry);

function Cache({ children }: { children: ReactNode }) {
  return <SWRConfig value={{ provider: () => new Map() }}>{children}</SWRConfig>;
}

function Probe({ name }: { name: string }) {
  const { lastChecked } = useEngineStatus();
  return <span data-testid={name}>{lastChecked ? "stamped" : "none"}</span>;
}

describe("useEngineStatus", () => {
  beforeEach(() => {
    mockedFetch.mockReset();
  });

  it("stamps lastChecked for every subscriber of the shared /health key", async () => {
    mockedFetch.mockResolvedValue({ status: "ok" });

    render(
      <Cache>
        <Probe name="first" />
        <Probe name="second" />
      </Cache>,
    );

    await waitFor(() => {
      expect(screen.getByTestId("first")).toHaveTextContent("stamped");
      expect(screen.getByTestId("second")).toHaveTextContent("stamped");
    });
  });
});
