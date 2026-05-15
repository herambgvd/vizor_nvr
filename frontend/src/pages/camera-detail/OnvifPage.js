// =============================================================================
// OnvifPage — /cameras/:id/onvif
// =============================================================================

import React from "react";
import { useOutletContext } from "react-router-dom";
import { ONVIFSettingsPanel } from "../../components/nvr";

const OnvifPage = () => {
  const { cameraId } = useOutletContext();
  return (
    <div className="p-4 md:p-6 max-w-4xl">
      <ONVIFSettingsPanel cameraId={cameraId} />
    </div>
  );
};

export default OnvifPage;
