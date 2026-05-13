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
  // Define status configurations
  const statusConfig = {
    online: {
      label: 'Online',
      icon: Wifi,
      className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    },
    offline: {
      label: 'Offline',
      icon: WifiOff,
      className: 'bg-white/[0.04] text-zinc-400 border-white/10',
    },
    connecting: {
      label: 'Connecting',
      icon: Circle,
      className: 'bg-amber-50 text-amber-700 border-amber-200 animate-pulse',
    },
    error: {
      label: 'Error',
      icon: AlertCircle,
      className: 'bg-rose-50 text-rose-700 border-rose-200',
    },
    recording: {
      label: 'Recording',
      icon: Video,
      className: 'bg-red-50 text-red-700 border-red-200',
    },
    'not-recording': {
      label: 'Not Recording',
      icon: VideoOff,
      className: 'bg-white/[0.04] text-zinc-400 border-white/10',
    },
    active: {
      label: 'Active',
      icon: Circle,
      className: 'bg-emerald-50 text-emerald-700 border-emerald-200',
    },
    inactive: {
      label: 'Inactive',
      icon: Circle,
      className: 'bg-white/[0.04] text-zinc-400 border-white/10',
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
        'inline-flex items-center gap-1.5 text-xs font-medium text-red-600',
        className
      )}
    >
      <span className="relative flex h-2 w-2">
        <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-red-400 opacity-75"></span>
        <span className="relative inline-flex rounded-full h-2 w-2 bg-red-600"></span>
      </span>
      REC
    </span>
  );
};

export default StatusBadge;
