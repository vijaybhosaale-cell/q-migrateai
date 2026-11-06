"""Cloud connector interface.

A connector turns one cloud account into the platform's standard inventory:

    {"assets": [asset, ...], "edges": [{"source", "target", "relation"}, ...]}

Each asset is a dict with: asset_id, cloud, region, application, owner_team,
service_type, usage, protocol, algorithm, exposure, data_sensitivity (1-5),
retention_years, business_criticality (1-5), clients_support_pqc, and
optionally analyst_label (only the simulator has those).

Rules every connector must follow:
  * read-only: list and describe calls only, never create/update/delete;
  * metadata only: key types, algorithms, certificates, TLS settings;
    never file contents, secrets or customer data.
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class ConnectorNotReady(Exception):
    """Raised by connectors that are documented but not implemented yet."""


class CloudConnector(ABC):
    provider: str = ""
    title: str = ""

    def __init__(self, config: dict):
        self.config = config or {}

    @abstractmethod
    def test(self) -> dict:
        """Check the credentials. Returns {"ok": bool, "status": str, "message": str}."""

    @abstractmethod
    def discover(self, run_index: int = 0) -> dict:
        """Return the standard inventory. run_index counts earlier successful scans."""
