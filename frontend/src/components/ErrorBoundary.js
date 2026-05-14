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

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-card">
          <div className="text-center max-w-md px-6">
            <div className="mx-auto mb-6 p-4 bg-red-50 rounded-full w-fit">
              <AlertCircle className="h-10 w-10 text-red-500" />
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
              <pre className="text-xs text-left bg-card/40 border border-border rounded-lg p-3 mb-6 overflow-auto max-h-32 text-zinc-400">
                {this.state.error.message}
              </pre>
            )}
            <Button
              onClick={() => window.location.reload()}
              className="bg-primary hover:bg-primary/60"
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
