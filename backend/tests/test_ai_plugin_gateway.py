import pytest

from app.ai.core.registry import ManifestError, validate_manifest
from app.ai.core.router import is_proxy_route_allowed


def test_proxy_route_allows_declared_exact_and_template_paths():
    manifest = {
        "proxy_routes": [
            {"method": "POST", "path": "/jobs/search"},
            {"method": "GET", "path": "/jobs/{job_id}/results"},
        ]
    }

    assert is_proxy_route_allowed(manifest, "POST", "jobs/search")
    assert is_proxy_route_allowed(manifest, "GET", "jobs/abc-123/results")


def test_proxy_route_rejects_undeclared_method_or_path():
    manifest = {"proxy_routes": [{"method": "GET", "path": "/jobs/{job_id}"}]}

    assert not is_proxy_route_allowed(manifest, "DELETE", "jobs/abc-123")
    assert not is_proxy_route_allowed(manifest, "GET", "admin/secrets")


def test_manifest_tabs_alias_populates_module_tabs():
    manifest = {"slug": "suspect-search", "name": "Suspect Search", "tabs": ["search", "jobs"]}

    validate_manifest(manifest)

    assert manifest["module_tabs"] == ["search", "jobs"]


def test_manifest_rejects_invalid_proxy_routes():
    manifest = {"slug": "suspect-search", "name": "Suspect Search", "proxy_routes": "wide-open"}

    with pytest.raises(ManifestError):
        validate_manifest(manifest)

