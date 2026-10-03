"use client";

import { Component, type ReactNode } from "react";

import styles from "./MapErrorBoundary.module.css";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
  /** Bumped on reload so the map is built again from scratch. */
  attempt: number;
}

/** Keeps a map crash from taking the whole page down with it. */
export class MapErrorBoundary extends Component<Props, State> {
  state: State = { failed: false, attempt: 0 };

  static getDerivedStateFromError(): Partial<State> {
    return { failed: true };
  }

  componentDidCatch(error: unknown) {
    console.error("Map crashed", error);
  }

  private reload = () =>
    this.setState((s) => ({ failed: false, attempt: s.attempt + 1 }));

  render() {
    if (this.state.failed) {
      return (
        <div className={styles.fallback} role="alert">
          <p>The map hit a problem</p>
          <button type="button" className={styles.button} onClick={this.reload}>
            Reload map
          </button>
        </div>
      );
    }
    return <div key={this.state.attempt} className={styles.fill}>{this.props.children}</div>;
  }
}
