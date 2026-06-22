// =============================================================================
// AI · ANPR · Events tab.
//
// For ANPR, the event log IS the plate-read log: every event is a plate read
// from the plugin /plates store. The Plates tab already renders exactly that
// table (with its filters, snapshots and list-hit badges), so the Events tab
// reuses it rather than duplicating the plate table. Scoped to ANPR only.
// =============================================================================

export { default } from "./PlatesTab";
