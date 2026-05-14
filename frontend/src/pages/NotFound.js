// =============================================================================
// 404 Not Found Page
// =============================================================================

import React from "react";
import { Link, useNavigate } from "react-router-dom";
import { Home, ArrowLeft } from "lucide-react";
import { Button } from "../components/ui/button";

const NotFound = () => {
  const navigate = useNavigate();
  return (
    <div className="min-h-screen flex items-center justify-center bg-card">
      <div className="text-center max-w-md px-6">
        <p
          className="text-7xl font-bold text-slate-200 mb-4"
          style={{ fontFamily: "Manrope, sans-serif" }}
        >
          404
        </p>
        <h1
          className="text-2xl font-bold text-white mb-2"
          style={{ fontFamily: "Manrope, sans-serif" }}
        >
          Page Not Found
        </h1>
        <p className="text-muted-foreground mb-8 text-sm">
          The page you're looking for doesn't exist or has been moved.
        </p>
        <div className="flex items-center justify-center gap-3">
          <Button variant="outline" onClick={() => navigate(-1)}>
            <ArrowLeft className="h-4 w-4 mr-2" />
            Go Back
          </Button>
          <Button asChild className="bg-primary hover:bg-primary/60">
            <Link to="/">
              <Home className="h-4 w-4 mr-2" />
              Dashboard
            </Link>
          </Button>
        </div>
      </div>
    </div>
  );
};

export default NotFound;
