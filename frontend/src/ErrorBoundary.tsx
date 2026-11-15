import { Component, type ReactNode } from 'react';

export class ErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (this.state.failed) return <section className="error" role="alert">
      <h2>We could not display this result.</h2>
      <p>Your page is still available. Open a saved case to recover, or ask the backend owner to check the response contract.</p>
      <a href="?source=saved">Open saved cases</a>
    </section>;
    return this.props.children;
  }
}
