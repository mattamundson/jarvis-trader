// Tier 1 (honesty/provenance) component tests — Phase 9.2, P9-2.
//
// `SystemFreshnessStrip` (components/SystemFreshnessStrip.tsx) is the
// always-on operator strip surfacing engine reachability and shared
// WebSocket state. It sources data through `useEngineStatus()` and
// `useEngineWebSocketContext()`, both mocked here so the render-layer
// honesty contract (does it render sensibly for healthy vs. degraded state)
// is isolated from real network/WS behavior.
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

vi.mock("@/hooks/useEngineStatus", () => ({
  useEngineStatus: vi.fn(),
}));
vi.mock("@/lib/engine-websocket-context", () => ({
  useEngineWebSocketContext: vi.fn(),
}));
// Network-adjacent hooks the strip also consumes — mocked so no fetch/WS/SWR
// poll ever leaves the test.
vi.mock("swr", () => ({
  default: vi.fn(() => ({
    data: undefined,
    error: undefined,
    isLoading: false,
    isValidating: false,
    mutate: vi.fn(),
  })),
}));
vi.mock("@/lib/masterApi", () => ({
  fetchMasterStatus: vi.fn(),
  aggregationBannerState: vi.fn(() => ({ degraded: false, reason: "healthy" })),
}));
vi.mock("@/hooks/useVercelDeployHealth", () => ({
  useVercelDeployHealth: vi.fn(() => ({ data: undefined })),
}));

import { useEngineStatus } from "@/hooks/useEngineStatus";
import { useEngineWebSocketContext } from "@/lib/engine-websocket-context";
import { SystemFreshnessStrip } from "@/components/SystemFreshnessStrip";

const mockedUseEngineStatus = vi.mocked(useEngineStatus);
const mockedUseEngineWebSocketContext = vi.mocked(useEngineWebSocketContext);

function mockWs(isConnected: boolean, isPolling = false) {
  mockedUseEngineWebSocketContext.mockReturnValue({
    isConnected,
    isPolling,
    lastEvent: null,
    subscribe: vi.fn(() => () => {}),
    connect: vi.fn(),
    disconnect: vi.fn(),
  });
}

describe("SystemFreshnessStrip", () => {
  it("renders a healthy state: engine online, WS connected", () => {
    mockedUseEngineStatus.mockReturnValue({
      isOnline: true,
      lastChecked: new Date(),
    });
    mockWs(true);

    render(<SystemFreshnessStrip />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/Engine online/i)).toBeInTheDocument();
    expect(screen.getByText(/WS connected/i)).toBeInTheDocument();
  });

  it("renders a degraded state: engine offline, WS disconnected", () => {
    mockedUseEngineStatus.mockReturnValue({
      isOnline: false,
      lastChecked: null,
    });
    mockWs(false);

    render(<SystemFreshnessStrip />);

    expect(screen.getByRole("status")).toBeInTheDocument();
    expect(screen.getByText(/Engine offline/i)).toBeInTheDocument();
    expect(screen.getByText(/WS disconnected/i)).toBeInTheDocument();
  });

  it("degraded state never claims 'Engine online' or 'WS connected'", () => {
    mockedUseEngineStatus.mockReturnValue({
      isOnline: false,
      lastChecked: null,
    });
    mockWs(false);

    render(<SystemFreshnessStrip />);

    expect(screen.queryByText(/Engine online/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/^WS connected/i)).not.toBeInTheDocument();
  });

  it("renders a polling state: WS disconnected but the strip says 'polling', never 'connected'", () => {
    mockedUseEngineStatus.mockReturnValue({
      isOnline: true,
      lastChecked: new Date(),
    });
    mockWs(false, true);

    render(<SystemFreshnessStrip />);

    expect(screen.getByText(/polling/i)).toBeInTheDocument();
    expect(screen.queryByText(/WS connected/i)).not.toBeInTheDocument();
  });
});
