"use client";

import { Component, type ReactNode } from "react";

interface Props {
  /** Short label shown in the fallback so the user knows which panel failed. */
  name?: string;
  children: ReactNode;
}

interface State {
  hasError: boolean;
  message: string;
}

/**
 * Per-widget error boundary.
 *
 * The dashboard renders 30+ live widgets side by side. Without isolation, a
 * single widget throwing during render (e.g. a malformed engine payload) unwinds
 * the whole React tree and blanks the page to the route-level `app/error.tsx`
 * fallback. Wrapping an individual widget in this boundary contains the failure
 * to that one card — the rest of the dashboard keeps updating.
 */
export class WidgetErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, message: "" };
  }

  static getDerivedStateFromError(error: unknown): State {
    return {
      hasError: true,
      message: error instanceof Error ? error.message : String(error),
    };
  }

  componentDidCatch(error: unknown) {
    // Surface in the browser console for debugging; never rethrow.
    // eslint-disable-next-line no-console
    console.error(`[WidgetErrorBoundary${this.props.name ? `:${this.props.name}` : ""}]`, error);
  }

  render() {
    if (this.state.hasError) {
      return (
        <div className="rounded border border-zinc-800 bg-zinc-950/60 p-3">
          <p className="text-xs text-rose-400">
            {this.props.name ? `${this.props.name} ` : "Widget "}failed to render
          </p>
          <p className="mt-1 break-all font-mono text-[10px] text-zinc-600">
            {this.state.message}
          </p>
        </div>
      );
    }
    return this.props.children;
  }
}

export default WidgetErrorBoundary;
