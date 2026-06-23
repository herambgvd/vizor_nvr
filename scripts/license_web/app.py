#!/usr/bin/env python3
"""Vizor NVR License Generator — support-team web UI.

Run:
    python3 scripts/license_web/app.py

Open:
    http://127.0.0.1:5055

This is intentionally standalone: Flask + SQLite + the existing
scripts/sign_license.py signing helpers. It stores client workspaces under
vendor-keys/<client-slug>/ by default:

    vendor-keys/gvd/private.pem
    vendor-keys/gvd/public.b64
    vendor-keys/gvd/licenses/GVD-20260623-001.lic
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from flask import (
    Flask,
    abort,
    flash,
    make_response,
    redirect,
    render_template,
    request,
    send_file,
    url_for,
)

SCRIPT_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from sign_license import (  # noqa: E402
    FEATURE_OPTION_CHOICES,
    MAX_CHANNELS,
    SCENARIO_CHOICES,
    TIER_CHOICES,
    _build_payload,
    _next_license_id,
    _save_keypair,
    _slugify,
    _write_signed_license,
)

PRODUCT_MODULES = [
    {
        "key": "recording",
        "label": "Recording",
        "description": "On-request/manual recording, schedules, event clips.",
        "kind": "core",
    },
    {
        "key": "playback",
        "label": "Playback",
        "description": "Timeline playback, export, bookmarks and recording review.",
        "kind": "core",
    },
    {
        "key": "frs",
        "label": "FRS",
        "description": "Face recognition module.",
        "kind": "scenario",
    },
    {
        "key": "ppe",
        "label": "PPE",
        "description": "Helmet/vest compliance monitoring.",
        "kind": "scenario",
    },
    {
        "key": "anpr",
        "label": "ANPR",
        "description": "Automatic number plate recognition.",
        "kind": "scenario",
    },
    {
        "key": "people_counting",
        "label": "People Counting",
        "description": "People counting scenario.",
        "kind": "scenario",
    },
    {
        "key": "suspect_search",
        "label": "Suspect Search",
        "description": "Archive search with image/query filters.",
        "kind": "scenario",
    },
]

DEFAULT_FEATURES = ["recording", "playback"]


def create_app(
    db_path: Path | None = None,
    clients_root: Path | None = None,
) -> Flask:
    app = Flask(__name__)
    app.secret_key = os.getenv("LICENSE_WEB_SECRET", "vizor-license-dev-secret")
    app.config["DB_PATH"] = Path(
        db_path
        or os.getenv("LICENSE_WEB_DB")
        or (SCRIPT_DIR / "license_web.sqlite3")
    )
    app.config["CLIENTS_ROOT"] = Path(
        clients_root
        or os.getenv("LICENSE_CLIENTS_ROOT")
        or (REPO_ROOT / "vendor-keys")
    )
    init_db(app)

    @app.template_filter("dt")
    def _dt(value: str | None) -> str:
        if not value:
            return "—"
        return value.replace("T", " ").split(".")[0]

    @app.template_filter("json_pretty")
    def _json_pretty(value) -> str:
        if isinstance(value, str):
            try:
                value = json.loads(value)
            except Exception:
                return value
        return json.dumps(value or {}, indent=2, sort_keys=True)

    @app.get("/")
    def index():
        db = get_db(app)
        clients = db.execute(
            """
            SELECT c.*,
                   COUNT(l.id) AS license_count,
                   MAX(l.created_at) AS last_license_at
            FROM clients c
            LEFT JOIN licenses l ON l.client_id = c.id
            GROUP BY c.id
            ORDER BY c.created_at DESC
            """
        ).fetchall()
        recent = db.execute(
            """
            SELECT l.*, c.name AS client_name, c.slug AS client_slug
            FROM licenses l
            JOIN clients c ON c.id = l.client_id
            ORDER BY l.created_at DESC
            LIMIT 8
            """
        ).fetchall()
        return render_template("index.html", clients=clients, recent=recent)

    @app.get("/favicon.ico")
    def favicon():
        return make_response("", 204)

    @app.route("/clients/new", methods=["GET", "POST"])
    def new_client():
        if request.method == "POST":
            name = clean(request.form.get("name"))
            if not name:
                flash("Client name is required.", "error")
                return redirect(url_for("new_client"))
            slug = clean(request.form.get("slug")) or _slugify(name)
            slug = _slugify(slug)
            key_dir = app.config["CLIENTS_ROOT"] / slug
            generate_key = request.form.get("generate_key") == "on"
            private_key = key_dir / "private.pem"
            public_key = key_dir / "public.b64"

            db = get_db(app)
            existing = db.execute("SELECT id FROM clients WHERE slug = ?", (slug,)).fetchone()
            if existing:
                flash(f"Client folder '{slug}' already exists.", "error")
                return redirect(url_for("new_client"))

            if generate_key:
                if private_key.exists() and public_key.exists():
                    # Common support-team flow: CLI/wizard already created
                    # vendor-keys/<slug>/, but the web DB is fresh. Reuse it
                    # instead of crashing the Flask process with SystemExit.
                    flash(f"Existing keypair found for '{slug}', reusing it.", "success")
                else:
                    try:
                        _save_keypair(key_dir)
                    except SystemExit as exc:
                        flash(str(exc), "error")
                        return redirect(url_for("new_client"))
            else:
                key_dir.mkdir(parents=True, exist_ok=True)

            db.execute(
                """
                INSERT INTO clients(name, slug, key_dir, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (name, slug, str(key_dir), now_iso()),
            )
            db.commit()
            flash(f"Client created: {name}", "success")
            return redirect(url_for("client_detail", client_id=db.execute("SELECT last_insert_rowid()").fetchone()[0]))

        return render_template("client_form.html")

    @app.get("/clients/<int:client_id>")
    def client_detail(client_id: int):
        client = get_client(app, client_id)
        if not client:
            abort(404)
        db = get_db(app)
        licenses = db.execute(
            "SELECT * FROM licenses WHERE client_id = ? ORDER BY created_at DESC",
            (client_id,),
        ).fetchall()
        key_dir = Path(client["key_dir"])
        return render_template(
            "client_detail.html",
            client=client,
            licenses=licenses,
            has_private_key=(key_dir / "private.pem").exists(),
            public_key=(key_dir / "public.b64").read_text().strip()
            if (key_dir / "public.b64").exists()
            else "",
        )

    @app.post("/clients/<int:client_id>/keypair")
    def create_keypair(client_id: int):
        client = get_client(app, client_id)
        if not client:
            abort(404)
        force = request.form.get("force") == "on"
        try:
            _save_keypair(Path(client["key_dir"]), force=force)
        except SystemExit as exc:
            flash(str(exc), "error")
        else:
            flash("Keypair generated.", "success")
        return redirect(url_for("client_detail", client_id=client_id))

    @app.get("/clients/<int:client_id>/public-key")
    def download_public_key(client_id: int):
        client = get_client(app, client_id)
        if not client:
            abort(404)
        path = Path(client["key_dir"]) / "public.b64"
        if not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=f"{client['slug']}-public.b64")

    @app.route("/clients/<int:client_id>/licenses/new", methods=["GET", "POST"])
    def new_license(client_id: int):
        client = get_client(app, client_id)
        if not client:
            abort(404)
        key_dir = Path(client["key_dir"])
        private_key = key_dir / "private.pem"
        if not private_key.exists():
            flash("Generate this client's keypair before creating a license.", "error")
            return redirect(url_for("client_detail", client_id=client_id))

        if request.method == "POST":
            form = parse_license_form(request.form)
            errors = validate_license_form(form)
            if errors:
                for error in errors:
                    flash(error, "error")
                return render_license_form(client, form)

            payload_args = SimpleNamespace(
                customer=form["customer"],
                license_id=form["license_id"],
                expires=form["expires"],
                tier=form["tier"],
                camera_limit=form["camera_limit"],
                ai_camera_limit=form["ai_camera_limit"],
                scenarios=",".join(form["scenarios"]),
                features=",".join(form["features"]),
                feature_options=form["feature_options"],
                hardware_fingerprint=form["hardware_fingerprint"] or None,
            )
            payload = _build_payload(payload_args)
            out_path = key_dir / "licenses" / f"{payload['license_id']}.lic"
            if out_path.exists() and request.form.get("overwrite") != "on":
                flash("License ID already exists. Check overwrite to replace it.", "error")
                return render_license_form(client, form)

            _write_signed_license(private_key, payload, out_path)

            db = get_db(app)
            db.execute(
                """
                INSERT INTO licenses(
                    client_id, license_id, customer, expires_at, tier,
                    camera_limit, ai_camera_limit, hardware_fingerprint,
                    features_json, scenarios_json, feature_options_json,
                    license_path, payload_path, created_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    client_id,
                    payload["license_id"],
                    payload["customer"],
                    payload["expires_at"],
                    payload["tier"],
                    payload["camera_limit"],
                    payload["ai_camera_limit"],
                    payload["hardware_fingerprint"] or "",
                    json.dumps(payload["features"]),
                    json.dumps(payload["scenarios"]),
                    json.dumps(payload.get("feature_options") or {}),
                    str(out_path),
                    str(out_path.with_suffix(".payload.json")),
                    now_iso(),
                ),
            )
            db.commit()
            license_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
            flash("License generated successfully.", "success")
            return redirect(url_for("license_detail", license_db_id=license_id))

        defaults = default_license_form(app, client)
        return render_license_form(client, defaults)

    @app.get("/licenses/<int:license_db_id>")
    def license_detail(license_db_id: int):
        lic = get_license(app, license_db_id)
        if not lic:
            abort(404)
        return render_template("license_detail.html", lic=lic)

    @app.get("/licenses/<int:license_db_id>/download")
    def download_license(license_db_id: int):
        lic = get_license(app, license_db_id)
        if not lic:
            abort(404)
        path = Path(lic["license_path"])
        if not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    @app.get("/licenses/<int:license_db_id>/payload")
    def download_payload(license_db_id: int):
        lic = get_license(app, license_db_id)
        if not lic:
            abort(404)
        path = Path(lic["payload_path"])
        if not path.exists():
            abort(404)
        return send_file(path, as_attachment=True, download_name=path.name)

    return app


def init_db(app: Flask) -> None:
    app.config["DB_PATH"].parent.mkdir(parents=True, exist_ok=True)
    app.config["CLIENTS_ROOT"].mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(app.config["DB_PATH"])
    db.executescript(
        """
        CREATE TABLE IF NOT EXISTS clients (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            slug TEXT NOT NULL UNIQUE,
            key_dir TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS licenses (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            client_id INTEGER NOT NULL REFERENCES clients(id) ON DELETE CASCADE,
            license_id TEXT NOT NULL,
            customer TEXT NOT NULL,
            expires_at TEXT,
            tier TEXT NOT NULL,
            camera_limit INTEGER NOT NULL,
            ai_camera_limit INTEGER NOT NULL,
            hardware_fingerprint TEXT,
            features_json TEXT NOT NULL,
            scenarios_json TEXT NOT NULL,
            feature_options_json TEXT NOT NULL,
            license_path TEXT NOT NULL,
            payload_path TEXT NOT NULL,
            created_at TEXT NOT NULL
        );

        CREATE INDEX IF NOT EXISTS ix_licenses_client ON licenses(client_id);
        """
    )
    db.close()


def get_db(app: Flask) -> sqlite3.Connection:
    db = sqlite3.connect(app.config["DB_PATH"])
    db.row_factory = sqlite3.Row
    return db


def get_client(app: Flask, client_id: int):
    return get_db(app).execute("SELECT * FROM clients WHERE id = ?", (client_id,)).fetchone()


def get_license(app: Flask, license_db_id: int):
    return get_db(app).execute(
        """
        SELECT l.*, c.name AS client_name, c.slug AS client_slug, c.key_dir AS client_key_dir
        FROM licenses l
        JOIN clients c ON c.id = l.client_id
        WHERE l.id = ?
        """,
        (license_db_id,),
    ).fetchone()


def clean(value: str | None) -> str:
    return (value or "").strip()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_license_form(app: Flask, client) -> dict:
    return {
        "customer": client["name"],
        "license_id": _next_license_id(client["slug"], app.config["CLIENTS_ROOT"]),
        "expires": "2027-12-31",
        "tier": "business",
        "camera_limit": 8,
        "ai_camera_limit": 8,
        "hardware_fingerprint": "",
        "features": DEFAULT_FEATURES.copy(),
        "scenarios": [],
        "feature_options": {},
        "overwrite": False,
    }


def parse_license_form(form) -> dict:
    features = normalize_modules(form.getlist("features"))
    scenarios = [f for f in features if f in SCENARIO_CHOICES]
    feature_options = {}
    if "frs" in features:
        feature_options["frs"] = normalize_options(form.getlist("frs_options"), "frs")
    return {
        "customer": clean(form.get("customer")),
        "license_id": clean(form.get("license_id")),
        "expires": clean(form.get("expires")),
        "tier": clean(form.get("tier")) or "business",
        "camera_limit": int(form.get("camera_limit") or 0),
        "ai_camera_limit": int(form.get("ai_camera_limit") or 0),
        "hardware_fingerprint": clean(form.get("hardware_fingerprint")),
        "features": features,
        "scenarios": scenarios,
        "feature_options": feature_options,
        "overwrite": form.get("overwrite") == "on",
    }


def normalize_modules(values: list[str]) -> list[str]:
    allowed = {m["key"] for m in PRODUCT_MODULES}
    out = []
    for value in values:
        v = clean(value).lower().replace("-", "_").replace(" ", "_")
        if v in allowed and v not in out:
            out.append(v)
    return out


def normalize_options(values: list[str], feature: str) -> list[str]:
    allowed = set(FEATURE_OPTION_CHOICES.get(feature, []))
    out = []
    for value in values:
        v = clean(value).lower().replace("-", "_").replace(" ", "_")
        if v in allowed and v not in out:
            out.append(v)
    return out


def validate_license_form(form: dict) -> list[str]:
    errors = []
    if not form["customer"]:
        errors.append("Customer is required.")
    if not form["license_id"]:
        errors.append("License ID is required.")
    if form["tier"] not in TIER_CHOICES:
        errors.append("Invalid tier.")
    if not (1 <= form["camera_limit"] <= MAX_CHANNELS):
        errors.append(f"Camera limit must be between 1 and {MAX_CHANNELS}.")
    if not (0 <= form["ai_camera_limit"] <= MAX_CHANNELS):
        errors.append(f"AI camera limit must be between 0 and {MAX_CHANNELS}.")
    if "frs" not in form["features"] and form["feature_options"].get("frs"):
        errors.append("FRS sub-features require the FRS module.")
    return errors


def render_license_form(client, form):
    return render_template(
        "license_form.html",
        client=client,
        form=form,
        modules=PRODUCT_MODULES,
        tiers=TIER_CHOICES,
        frs_options=FEATURE_OPTION_CHOICES["frs"],
        max_channels=MAX_CHANNELS,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default=os.getenv("LICENSE_WEB_HOST", "127.0.0.1"))
    parser.add_argument("--port", type=int, default=int(os.getenv("LICENSE_WEB_PORT", "5055")))
    parser.add_argument("--db", default=os.getenv("LICENSE_WEB_DB"))
    parser.add_argument("--clients-root", default=os.getenv("LICENSE_CLIENTS_ROOT"))
    args = parser.parse_args()

    app = create_app(
        db_path=Path(args.db) if args.db else None,
        clients_root=Path(args.clients_root) if args.clients_root else None,
    )
    print(f"DB: {app.config['DB_PATH']}")
    print(f"Clients root: {app.config['CLIENTS_ROOT']}")
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
