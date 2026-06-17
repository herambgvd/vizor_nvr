# Vizor AI Scenario Plugins

Scenario plugins are Docker services that register a `scenario.json` manifest
with the NVR backend. The NVR owns cameras, recordings, users, license checks,
audit, event log, and proxy auth. Plugins own scenario-specific inference,
indexing, jobs, model loading, and reports.

Current first plugin: `suspect-search`, archive-only search foundation.

