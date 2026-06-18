"""Qdrant package — face-vector store (client + upsert/search/delete)."""
from . import store  # noqa: F401
from .store import client, delete_by, search, upsert  # noqa: F401
