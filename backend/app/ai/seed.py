# =============================================================================
# AI Scenario Seeder
#
# Populates `ai_scenarios` with the catalog of capabilities the platform
# can run. Called from app.main lifespan startup. Idempotent — uses slug
# as the natural key.
#
# Each entry pairs to a Metropolis Perception / Behavior Analytics /
# Microservice pipeline configuration. The `requires_models` list
# references NGC pretrained model slugs that must be deployed before
# the scenario is usable.
#
# SKU/Tier control:
#   `tier` field gates which scenarios are available on which license
#   tier (free / pro / business / enterprise). Allows selling individual
#   scenarios as add-ons.
#
# `status` field tracks build readiness:
#   ga       — generally available, ship-ready (Phase 1+)
#   beta     — works but needs polish (Phase 2)
#   planned  — designed but not built yet (Phase 3+)
# =============================================================================

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.ai.models import AIScenario


logger = logging.getLogger(__name__)


# Phase 1 ships scenarios marked `tier="pro"` + `status="ga"` first.
# Everything else is in catalog so customers see roadmap; backend
# returns `unavailable` until status flips to ga.

SCENARIOS: list[dict[str, Any]] = [

    # ──────────────────────────────────────────────────────────────────
    # PHASE 1 — Ship now (FRS + People Counting)
    # ──────────────────────────────────────────────────────────────────

    {
        "slug": "frs",
        "name": "Face Recognition (FRS)",
        "description": (
            "Identify enrolled people from a watchlist gallery in real time. "
            "Uses NVIDIA FaceDetectIR + ArcFace embeddings against the Qdrant "
            "gallery. Supports liveness, group-based access alerts, attendance "
            "tracking, and cross-camera person re-identification when paired "
            "with the Cross-Cam ReID scenario."
        ),
        "category": "person",
        "tier": "pro",
        "status": "ga",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.6,
            "match_threshold": 0.55,
            "liveness_enabled": True,
            "min_face_size_px": 40,
            "emit_unknown_faces": False,
            "watchlist_groups": [],
            "roi_polygon": None,
            "emit_attendance_events": True,
        },
        "requires_models": ["facedetect_ir", "facial_landmarks", "arcface"],
        "use_cases": ["watchlist", "attendance", "vip_detection", "blacklist", "office_access"],
        "module_tabs": ["persons", "live", "events", "attendance", "investigate", "groups", "analytics"],
        "camera_config_schema": {
            "fields": [
                {"key": "enabled", "label": "Enable on this camera", "type": "toggle"},
                {"key": "rois", "label": "Detection ROI", "type": "roi_polygon", "multi": True},
                {"key": "similarity_threshold", "label": "Match threshold", "type": "slider",
                 "min": 0.30, "max": 0.99, "step": 0.01, "default": 0.55},
                {"key": "min_face_px", "label": "Min face size (px)", "type": "number", "min": 40, "max": 400, "default": 80},
                {"key": "max_pose_deg", "label": "Max pose angle (deg)", "type": "number", "min": 10, "max": 60, "default": 30},
                {"key": "liveness_required", "label": "Require liveness check", "type": "toggle", "default": True},
                {"key": "alert_group_ids", "label": "Alert groups (watchlist)", "type": "group_multiselect"},
                {"key": "attendance_enabled", "label": "Track attendance", "type": "toggle", "default": False},
                {"key": "attendance_role", "label": "Attendance role", "type": "select",
                 "options": [{"value": "entry", "label": "Entry"}, {"value": "exit", "label": "Exit"}, {"value": "both", "label": "Both"}]},
            ],
        },
    },

    {
        "slug": "people_counting",
        "name": "People Counting & Occupancy",
        "description": (
            "Count people entering/exiting zones, measure live occupancy, "
            "track dwell time, generate heatmaps. Built on PeopleNet "
            "detection + NvDCF tracker + Behavior Analytics microservice "
            "(zones, lines, dwell aggregator)."
        ),
        "category": "behavior",
        "tier": "pro",
        "status": "ga",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "confidence_threshold": 0.55,
            "zones": [],
            "lines": [],
            "occupancy_limit": None,
            "emit_heatmap": True,
            "heatmap_resolution": 32,
            "dwell_threshold_seconds": 30,
        },
        "requires_models": ["peoplenet"],
        "use_cases": [
            "retail_footfall", "queue_management", "occupancy_compliance",
            "smart_building", "event_crowd", "facility_planning",
        ],
        "module_tabs": ["live", "events", "analytics"],
        "camera_config_schema": {
            "fields": [
                {"key": "enabled", "label": "Enable on this camera", "type": "toggle"},
                {"key": "zones", "label": "Counting Zones", "type": "zones_panel"},
                {"key": "detection_confidence", "label": "Detection confidence", "type": "slider",
                 "min": 0.05, "max": 0.95, "step": 0.05, "default": 0.35},
                {"key": "min_track_frames", "label": "Min track frames", "type": "number",
                 "min": 1, "max": 30, "default": 4},
                {"key": "line_crossing_enabled", "label": "Enable line crossing", "type": "toggle", "default": True},
                {"key": "crowd_counting_enabled", "label": "Enable crowd counting", "type": "toggle", "default": True},
            ],
        },
    },

    # ──────────────────────────────────────────────────────────────────
    # PHASE 2 — Next wave (PPE + LPR + Behavior rules)
    # ──────────────────────────────────────────────────────────────────

    {
        "slug": "ppe",
        "name": "PPE Compliance",
        "description": (
            "Detect missing or improperly worn personal protective equipment "
            "(helmet, vest, mask, gloves, safety glasses). Built on PeopleNet "
            "+ TAO-trained PPE classifier SGIE. Compliance dashboard tracks "
            "violations per zone, per shift, per worker."
        ),
        "category": "safety",
        "tier": "business",
        "status": "ga",
        "metropolis_service": "perception",
        "default_config": {
            "enabled": True,
            "required_items": ["helmet", "vest"],
            "detection_confidence": 0.45,
            "violation_grace_frames": 15,
            "rois": [],
            "snapshot_violations": True,
        },
        "requires_models": ["peoplenet", "ppe_classifier"],
        "use_cases": ["manufacturing", "construction", "warehouse", "mining"],
        "module_tabs": ["live", "events", "analytics"],
        "camera_config_schema": {
            "fields": [
                {"key": "enabled", "label": "Enable on this camera", "type": "toggle"},
                {"key": "required_items", "label": "Required PPE items", "type": "multi_checkbox",
                 "options": [
                    {"value": "helmet", "label": "Helmet"},
                    {"value": "vest", "label": "Hi-vis vest"},
                    {"value": "mask", "label": "Mask"},
                    {"value": "gloves", "label": "Gloves"},
                    {"value": "goggles", "label": "Safety goggles"},
                    {"value": "boots", "label": "Safety boots"},
                 ]},
                {"key": "detection_confidence", "label": "Confidence", "type": "slider",
                 "min": 0.05, "max": 0.95, "step": 0.05, "default": 0.45},
                {"key": "violation_grace_frames", "label": "Grace frames", "type": "number",
                 "min": 1, "max": 120, "default": 15},
                {"key": "rois", "label": "ROI polygons", "type": "roi_polygon", "multi": True},
                {"key": "snapshot_violations", "label": "Snapshot violations", "type": "toggle", "default": True},
            ],
        },
    },

    {
        "slug": "lpr",
        "name": "License Plate Recognition (ANPR/LPR)",
        "description": (
            "Detect and OCR vehicle license plates. Multi-region support "
            "(US, EU, IN, GCC, custom). Built on NVIDIA LPDNet + LPRNet. "
            "Includes watchlist alerts, parking integration, gate access "
            "control, and vehicle entry/exit logs."
        ),
        "category": "vehicle",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.7,
            "region": "IN",
            "watchlist_alerts_enabled": False,
            "min_plate_size_px": 60,
            "roi_polygon": None,
            "emit_vehicle_attrs": True,
        },
        "requires_models": ["lpdnet", "lprnet_in"],
        "use_cases": ["parking", "gate_access", "traffic_enforcement", "toll", "fleet_tracking"],
    },

    {
        "slug": "intrusion",
        "name": "Zone Intrusion Detection",
        "description": (
            "Alert when people or vehicles enter forbidden zones, optionally "
            "during configured time windows (after-hours intrusion). "
            "Built on PeopleNet + Behavior Analytics zone-entry rules."
        ),
        "category": "security",
        "tier": "pro",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "zones": [],
            "schedule": None,
            "min_dwell_seconds": 1.0,
            "object_classes": ["person"],
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["perimeter_security", "after_hours_alert", "restricted_area"],
    },

    {
        "slug": "line_crossing",
        "name": "Line Crossing & Tripwire",
        "description": (
            "Count or alert when objects cross a defined virtual line in a "
            "specified direction. Useful for entries, exits, traffic counts, "
            "and trip-wire alarms."
        ),
        "category": "behavior",
        "tier": "pro",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "lines": [],
            "track_directions": True,
            "object_classes": ["person", "vehicle"],
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["entry_count", "perimeter_tripwire", "vehicle_count"],
    },

    {
        "slug": "loitering",
        "name": "Loitering Detection",
        "description": (
            "Alert when a person stays inside a zone longer than a configured "
            "threshold. Common for ATM monitoring, retail shrinkage, public "
            "safety hot spots."
        ),
        "category": "security",
        "tier": "pro",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "zones": [],
            "loitering_seconds": 30,
            "object_classes": ["person"],
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["atm_monitoring", "retail_shrinkage", "public_safety"],
    },

    {
        "slug": "object_left_behind",
        "name": "Abandoned Object",
        "description": (
            "Detect stationary objects (bag, package) left behind in a zone "
            "for longer than a threshold. Built on detection + tracker "
            "stationary heuristics."
        ),
        "category": "security",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "zones": [],
            "abandonment_seconds": 60,
            "object_classes": ["bag", "box", "suitcase"],
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["airport", "train_station", "public_venue"],
    },

    {
        "slug": "object_removed",
        "name": "Object Removed",
        "description": (
            "Alert when a tracked object is removed from a defined zone "
            "(e.g., exhibits in a museum, products on a shelf). Built on "
            "tracker-based stationary-object disappearance heuristics."
        ),
        "category": "security",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "zones": [],
            "removal_seconds": 5,
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["museum", "retail_shelf", "warehouse_inventory"],
    },

    # ──────────────────────────────────────────────────────────────────
    # PHASE 3 — Differentiators (advanced AI from Metropolis bundle)
    # ──────────────────────────────────────────────────────────────────

    {
        "slug": "vehicle_analytics",
        "name": "Vehicle Analytics",
        "description": (
            "Detect vehicles and classify type (car/truck/bus/motorcycle), "
            "color, make, model. Built on NVIDIA TrafficCamNet + attribute "
            "SGIEs (VehicleType, VehicleColor, VehicleMake)."
        ),
        "category": "vehicle",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.6,
            "track_attributes": ["type", "color", "make"],
        },
        "requires_models": ["trafficcamnet", "vehicle_type", "vehicle_color", "vehicle_make"],
        "use_cases": ["smart_city", "parking", "toll", "fleet"],
    },

    {
        "slug": "action_recognition",
        "name": "Action Recognition",
        "description": (
            "Detect human actions: running, fighting, falling, throwing, "
            "climbing, walking. Built on NVIDIA ActionRecognitionNet. "
            "Powerful for public safety, manufacturing safety, and elder care."
        ),
        "category": "behavior",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.65,
            "actions_of_interest": ["fighting", "falling"],
            "min_action_duration_seconds": 1.0,
        },
        "requires_models": ["action_recognition_net"],
        "use_cases": ["public_safety", "elder_care", "factory_safety", "schools"],
    },

    {
        "slug": "cross_cam_reid",
        "name": "Cross-Camera Re-Identification (MTMC)",
        "description": (
            "Track the same person across multiple cameras using ReIDNet "
            "appearance embeddings + the Metropolis MTMC (Multi-Target "
            "Multi-Camera) microservice. Enables global person journey "
            "search and forensic investigations."
        ),
        "category": "person",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "mtmc",
        "default_config": {
            "embedding_similarity_threshold": 0.7,
            "track_window_seconds": 60,
            "min_track_length_frames": 10,
        },
        "requires_models": ["reidnet"],
        "use_cases": ["investigation", "vip_tracking", "lost_person", "shopper_journey"],
    },

    {
        "slug": "vizor_query",
        "name": "Semantic Video Search",
        "description": (
            "Natural-language search across the video archive. Generates "
            "captions and SigLIP embeddings per detection; queries via "
            "vector similarity in Qdrant (or Metropolis Visual Search). "
            "Examples: 'show me red truck at gate Tuesday 3pm', 'person "
            "wearing yellow jacket near loading dock'."
        ),
        "category": "search",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "visual_search",
        "default_config": {
            "embedding_model": "siglip",
            "caption_sample_rate_seconds": 5,
            "save_thumbnails": True,
        },
        "requires_models": ["siglip"],
        "use_cases": ["forensics", "investigation", "retail_audit", "compliance"],
    },

    {
        "slug": "anomaly",
        "name": "Anomaly Detection",
        "description": (
            "Unsupervised anomaly detection per camera. Learns a 7-day "
            "behavioral baseline; flags deviations (unusual motion, "
            "unusual presence at unusual time, atypical scene layout). "
            "Differentiator vs competitors — most rivals offer only "
            "rule-based intrusion."
        ),
        "category": "security",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "learning_period_days": 7,
            "score_threshold": 0.85,
            "min_anomaly_duration_seconds": 3,
        },
        "requires_models": ["anomaly_autoencoder"],
        "use_cases": ["after_hours", "unusual_behavior", "edge_case_detection"],
    },

    {
        "slug": "crowd_density",
        "name": "Crowd Density Estimation",
        "description": (
            "Estimate crowd density per pixel/zone; trigger alarms at "
            "overcrowding thresholds. Built on dense-people-detection "
            "model + density-map regression. Suited to large public "
            "venues, transit hubs."
        ),
        "category": "behavior",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "zones": [],
            "density_thresholds": {"low": 0.3, "medium": 0.6, "high": 0.85},
        },
        "requires_models": ["dense_peoplenet"],
        "use_cases": ["transit_hub", "stadium", "festival", "smart_city"],
    },

    {
        "slug": "pose_classification",
        "name": "Pose Classification",
        "description": (
            "Classify human pose (standing, sitting, lying, crouching, "
            "kneeling, bending). Useful for fall detection, ergonomic "
            "monitoring, customer engagement analytics."
        ),
        "category": "person",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.6,
            "poses_of_interest": ["lying", "crouching"],
        },
        "requires_models": ["bodypose", "pose_classification"],
        "use_cases": ["fall_detection", "elder_care", "ergonomics", "retail"],
    },

    {
        "slug": "gaze_emotion",
        "name": "Gaze & Emotion Estimation",
        "description": (
            "Estimate gaze direction and emotion (happy/neutral/angry/"
            "surprised/sad) from face. Useful for retail customer "
            "experience analytics, attention measurement, kiosks."
        ),
        "category": "person",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "track_gaze_zones": [],
            "emotion_smoothing_seconds": 2,
        },
        "requires_models": ["facial_landmarks", "gaze_estimation", "emotion_net"],
        "use_cases": ["retail_cx", "advertising_attention", "kiosk_ux"],
    },

    {
        "slug": "smoke_fire",
        "name": "Smoke & Fire Detection",
        "description": (
            "Visual-based smoke and fire detection. Complementary to "
            "traditional sensors; provides camera-feed verification before "
            "dispatching response."
        ),
        "category": "safety",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.8,
            "min_duration_seconds": 5,
        },
        "requires_models": ["smoke_fire_detector"],
        "use_cases": ["industrial", "warehouse", "datacenter", "forest"],
    },

    {
        "slug": "weapon_detection",
        "name": "Weapon Detection",
        "description": (
            "Detect handheld weapons (firearm, knife) in real time. Trained "
            "on multi-region datasets via TAO fine-tuning."
        ),
        "category": "security",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "confidence_threshold": 0.85,
            "alert_severity": "critical",
        },
        "requires_models": ["weapon_detector"],
        "use_cases": ["schools", "transit", "public_venue", "banking"],
    },

    # ──────────────────────────────────────────────────────────────────
    # FUTURE — Phase 3-4+ vertical-specific scenarios
    # ──────────────────────────────────────────────────────────────────

    {
        "slug": "queue_analytics",
        "name": "Queue Analytics",
        "description": (
            "Measure queue length, wait time, abandonment rate at checkout/"
            "service counters. Built on PeopleNet + queue-line definition."
        ),
        "category": "behavior",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "queue_zones": [],
            "wait_threshold_seconds": 120,
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["retail_checkout", "service_counter", "boarding_gate"],
    },

    {
        "slug": "social_distancing",
        "name": "Social Distancing",
        "description": (
            "Measure inter-person distance; flag violations. Useful for "
            "healthcare, transit during pandemic, regulated spaces."
        ),
        "category": "safety",
        "tier": "business",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "min_distance_meters": 1.5,
            "violation_dwell_seconds": 3,
        },
        "requires_models": ["peoplenet"],
        "use_cases": ["healthcare", "transit", "compliance"],
    },

    {
        "slug": "vehicle_speed",
        "name": "Vehicle Speed Estimation",
        "description": (
            "Estimate vehicle speed via tracker + camera calibration. "
            "Surface speeding alerts for traffic enforcement, parking "
            "lots, and warehouse forklifts."
        ),
        "category": "vehicle",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "perception",
        "default_config": {
            "calibration_meters_per_pixel": 0.1,
            "speed_limit_kmh": 30,
        },
        "requires_models": ["trafficcamnet"],
        "use_cases": ["traffic_enforcement", "warehouse_safety", "parking"],
    },

    {
        "slug": "wrong_way_detection",
        "name": "Wrong-Way Driving Detection",
        "description": (
            "Detect vehicles moving against allowed flow direction. Smart "
            "city, highway, parking."
        ),
        "category": "vehicle",
        "tier": "enterprise",
        "status": "planned",
        "metropolis_service": "behavior_analytics",
        "default_config": {
            "allowed_directions": [],
            "min_vehicle_speed_kmh": 5,
        },
        "requires_models": ["trafficcamnet"],
        "use_cases": ["highway", "smart_city", "parking_garage"],
    },
]


async def seed_ai_scenarios(db: AsyncSession) -> int:
    """Insert or update the catalog of scenarios.

    Returns the count of new rows inserted (existing rows are updated
    in-place for changed name / description / requires_models, but the
    admin-edited default_config is preserved).
    """
    inserted = 0
    updated = 0
    for entry in SCENARIOS:
        existing = await db.execute(
            select(AIScenario).where(AIScenario.slug == entry["slug"])
        )
        row = existing.scalar_one_or_none()
        if row is None:
            scenario = AIScenario(
                slug=entry["slug"],
                name=entry["name"],
                description=entry["description"],
                default_config=entry.get("default_config", {}),
                requires_models=entry.get("requires_models", []),
                enabled=entry.get("status", "ga") == "ga",
                category=entry.get("category"),
                tier=entry.get("tier", "pro"),
                status=entry.get("status", "ga"),
                metropolis_service=entry.get("metropolis_service"),
                use_cases=entry.get("use_cases"),
                module_tabs=entry.get("module_tabs"),
                camera_config_schema=entry.get("camera_config_schema"),
            )
            db.add(scenario)
            inserted += 1
        else:
            row.name = entry["name"]
            row.description = entry["description"]
            row.requires_models = entry.get("requires_models", [])
            row.category = entry.get("category")
            row.tier = entry.get("tier", "pro")
            row.status = entry.get("status", "ga")
            row.metropolis_service = entry.get("metropolis_service")
            row.use_cases = entry.get("use_cases")
            row.module_tabs = entry.get("module_tabs")
            row.camera_config_schema = entry.get("camera_config_schema")
            updated += 1
            # Don't overwrite admin-edited default_config

    if inserted or updated:
        logger.info("Seeded AI scenarios: %d inserted, %d updated", inserted, updated)
    await db.commit()
    return inserted
