// =============================================================================
// SettingsPage — /cameras/:id/settings
// =============================================================================

import React from "react";
import { useOutletContext } from "react-router-dom";
import { SlidersHorizontal } from "lucide-react";
import { CameraSettingsPanel, LinkageRuleBuilder } from "../../components/nvr";
import { usePermissions } from "../../hooks/usePermissions";

const SettingsPage = () => {
  const { cameraId } = useOutletContext();
  const { canManage } = usePermissions();

  // go2rtc snapshot URL — kept for legacy panel that takes it as a prop
  const GO2RTC_URL =
    process.env.REACT_APP_GO2RTC_URL || "http://localhost:1984";
  const snapshotUrl = `${GO2RTC_URL}/api/frame.jpeg?src=${encodeURIComponent(cameraId)}`;

  if (!canManage) {
    return (
      <div className="p-6 text-center">
        <SlidersHorizontal className="h-10 w-10 text-muted-foreground mx-auto mb-3" />
        <p className="text-muted-foreground">
          You don't have permission to configure cameras.
        </p>
      </div>
    );
  }

  return (
    <div className="p-4 md:p-6 space-y-8 max-w-4xl">
      <CameraSettingsPanel cameraId={cameraId} snapshotUrl={snapshotUrl} />
      <div className="border-t border-border pt-6">
        <LinkageRuleBuilder />
      </div>
    </div>
  );
};

export default SettingsPage;
