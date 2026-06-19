// =============================================================================
// Error Boundary - React Error Boundary Component
// =============================================================================
// Catches JavaScript errors in child component tree and displays fallback UI.
// =============================================================================

import React from 'react';
import { AlertCircle, RefreshCw } from 'lucide-react';
import { Button } from '../components/ui/button';

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error) {
    return { hasError: true, error };
  }

  componentDidCatch(error, errorInfo) {
    console.error('ErrorBoundary caught:', error, errorInfo);
  }

  componentDidUpdate(prevProps) {
    // When resetKey changes (e.g. route navigation), clear the error so the
    // boundary re-renders its children instead of staying stuck on the
    // fallback. Lets the operator navigate away from a crashed page.
    if (
      this.state.hasError &&
      prevProps.resetKey !== this.props.resetKey
    ) {
      this.setState({ hasError: false, error: null });
    }
  }

  reset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError) {
      // Custom localized fallback — keeps the surrounding shell alive instead
      // of blanking the whole app. Called with (error, reset).
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div className="min-h-screen flex items-center justify-center bg-[var(--console-bg)]">
          <div className="text-center max-w-md px-6">
            <div className="mx-auto mb-6 p-4 rounded-full w-fit" style={{ backgroundColor: 'var(--console-raised)' }}>
              <AlertCircle className="h-10 w-10" style={{ color: 'var(--console-rec)' }} />
            </div>
            <h1
              className="text-2xl font-bold text-white mb-2"
              style={{ fontFamily: 'Manrope, sans-serif' }}
            >
              Something went wrong
            </h1>
            <p className="text-muted-foreground mb-6 text-sm">
              An unexpected error occurred. Please try refreshing the page.
            </p>
            {this.state.error && (
              <pre className="text-xs text-left border border-[var(--console-border)] rounded-lg p-3 mb-6 overflow-auto max-h-32" style={{ backgroundColor: 'var(--console-raised)', color: 'var(--console-muted)' }}>
                {this.state.error.message}
              </pre>
            )}
            <Button
              onClick={() => window.location.reload()}
              className="text-white hover:opacity-90"
              style={{ backgroundColor: 'var(--console-accent)' }}
            >
              <RefreshCw className="h-4 w-4 mr-2" />
              Reload Page
            </Button>
          </div>
        </div>
      );
    }

    return this.props.children;
  }
}

export default ErrorBoundary;
