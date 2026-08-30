"use client";

import { Component, ReactNode } from "react";

interface Props {
  children: ReactNode;
  // Label shown in the fallback so it's obvious which section broke —
  // e.g. "answer" vs "walkthrough" — without taking down the rest of the page.
  label: string;
}

interface State {
  error: Error | null;
}

/**
 * A rendering bug in one section (a malformed answer, an unexpected
 * walkthrough shape) used to take down the entire page with Next.js's
 * generic "Application error" screen — including the live trace panel that
 * had already rendered correctly above it. That's the opposite of this
 * feature's point: the walkthrough exists so a question is inspectable even
 * when something went wrong, so a bug in rendering IT must not erase
 * everything else already on the page. This boundary contains a crash to
 * just the section it wraps.
 */
export default class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error) {
    // eslint-disable-next-line no-console
    console.error(`[ErrorBoundary:${this.props.label}]`, error);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            border: "1px solid var(--border)",
            borderRadius: 10,
            padding: "14px 16px",
            fontSize: "0.85rem",
            color: "var(--ink-dim)",
            background: "var(--surface-2)",
          }}
        >
          Couldn&rsquo;t render the {this.props.label} — the data came back in a shape this page didn&rsquo;t expect. Check the browser console for details.
        </div>
      );
    }
    return this.props.children;
  }
}
