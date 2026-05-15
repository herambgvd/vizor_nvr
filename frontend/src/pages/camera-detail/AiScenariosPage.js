// =============================================================================
// AiScenariosPage — /cameras/:id/ai
// =============================================================================

import React from "react";
import { useOutletContext } from "react-router-dom";
import CameraAITab from "../../components/camera/CameraAITab";

const AiScenariosPage = () => {
  const { cameraId } = useOutletContext();
  return <CameraAITab cameraId={cameraId} />;
};

export default AiScenariosPage;
