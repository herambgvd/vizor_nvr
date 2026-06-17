import React from "react";
import TabPlaceholder from "./TabPlaceholder";

const JobsTab = ({ scenario }) => (
  <TabPlaceholder
    title="Scenario Jobs"
    description={`${scenario.name} job history will be read through the plugin gateway. Search job creation is wired in the Search tab.`}
  />
);

export default JobsTab;

