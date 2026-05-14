// =============================================================================
// Status Badge Component - Camera and Recording Status
// =============================================================================
// Displays status indicators with appropriate colors and icons.
// =============================================================================

import React from 'react';
import { Circle, AlertCircle, Wifi, WifiOff, Video, VideoOff } from 'lucide-react';
import { cn } from '../../lib/utils';

/**
 * Status Badge Component
 * Displays a styled badge for various status types.
 */
export const StatusBadge = ({ 
  status, 
  variant = 'default',
  showIcon = true,
  className 
}) => {
  // Define status configurations — dark-theme aware. Uses semantic
  // token shades (success/warning/destructive) at 15% bg + 30% border.
  const statusConfig = {
    online: {
      label: 'Online',
      icon: Wifi,
      className: 'bg-success/15 text-success border-success/30',
    },
    offline: {
      label: 'Offline',
      icon: WifiOff,
      className: 'bg-card/60 text-muted-foreground border-border',
    },
    connecting: {
      label: 'Connecting',
      icon: Circle,
      className: 'bg-warning/15 text-warning border-warning/30 animate-pulse',
    },
    error: {
      label: 'Error',
      icon: AlertCircle,
      className: 'bg-destructive/15 text-destructive border-destructive/30',
    },
    recording: {
      label: 'Recording',
      icon: Video,
      className: 'bg-destructive/15 text-destructive border-destructive/30',
    },
    'not-recording': {
      label: 'Not Recording',
      icon: VideoOff,
      className: 'bg-card/60 text-muted-foreground border-border',
    },
    active: {
      label: 'Active',
      icon: Circle,
      className: 'bg-success/15 text-success border-success/30',
    },
    inactive: {
      label: 'Inactive',
      icon: Circle,
      className: 'bg-card/60 text-muted-foreground border-border',
    },
  };

  const config = statusConfig[status] || statusConfig.offline;
  const Icon = config.icon;

  return (
    <span
      data-testid={`status-badge-${status}`}
      className={cn(
        'inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-medium border',
        config.className,
        className
      )}
    >
      {showIcon && <Icon className="h-3 w-3" />}
      {config.label}
    </span>
  );
};

/**
 * Recording Indicator Component
 * Animated dot indicator for recording status.
 */
export const RecordingIndicator = ({ isRecording, className }) => {
  if (!isRecording) return null;

  return (
    <span
      data-testid="recording-indicator"
      className={cn(
        'inline-flex items-center gap-1.5 text-xs font-medium text-destructive',
        className
      )}
    >
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-destructive opacity-75"></span>
        <span className="relative inline-flex rounded-full h-2 w-2 bg-destructive"></span>
      </span>
      REC
    </span>
  );
};

export default StatusBadge;
