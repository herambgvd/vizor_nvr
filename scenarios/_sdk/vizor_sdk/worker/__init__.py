"""Vizor AI worker framework (ported from vizor-gpu, single-tenant).

An async-first, per-camera task orchestrator with a Redis-Streams control plane.
A scenario subclasses `BaseWorker`, implements `process_frame`, and the framework
handles the per-camera lifecycle, watchdog restarts, heartbeat, event emission
(with disk-spool fallback), and graceful shutdown.

Why this exists: nvr's previous live path called Triton over HTTP with no network
timeout, so a slow Triton blocked every recognition thread forever and events
froze. This framework uses gRPC + a hard per-call `asyncio.wait_for` timeout, plus
circuit breakers and a Redis event bus, so events never break.

Single-tenant: the vizor-gpu `tenant_id` scoping is dropped — fixed collection /
bucket / stream names, matching how nvr already stores data.
"""
from __future__ import annotations

from .protocol import Command, Event, EventMedia, Status, ScenarioManifest, SubFeature
from .worker import BaseWorker, control_stream, status_stream, dlq_stream, EVENTS_STREAM
from .triton_client import TritonClient, default_grpc_url
from .circuit_breaker import CircuitBreaker, CircuitOpenError
from .inference_gateway import InferenceGateway

__all__ = [
    "Command",
    "Event",
    "EventMedia",
    "Status",
    "ScenarioManifest",
    "SubFeature",
    "BaseWorker",
    "control_stream",
    "status_stream",
    "dlq_stream",
    "EVENTS_STREAM",
    "TritonClient",
    "default_grpc_url",
    "CircuitBreaker",
    "CircuitOpenError",
    "InferenceGateway",
]
