"""Real data connector: the public websites of real organisations.

Measures, live and read-only, each site's TLS key exchange (including whether it already accepts the
post-quantum hybrid X25519MLKEM768), its certificate chain and the cloud that hosts it.
See qmigrate/realdata/collector.py for exactly what is sent over the network.

config: {"source": "finance" | "health" | "tranco" | "custom", "top": int, "domains": "a.com, b.org"}
"""
from __future__ import annotations

import socket

from qmigrate.server.connectors.base import CloudConnector


class PublicWebConnector(CloudConnector):
    provider = "public"
    title = "Public websites (real data)"

    def test(self) -> dict:
        try:
            socket.create_connection(("tranco-list.eu", 443), timeout=5).close()
        except OSError as exc:
            return {"ok": False, "status": "error", "message": f"No internet connection: {exc}"}
        from qmigrate.realdata.collector import targets_for
        try:
            domains, sector = targets_for(self.config)
        except Exception as exc:  # noqa: BLE001
            return {"ok": False, "status": "error", "message": str(exc)}
        if not domains:
            return {"ok": False, "status": "error", "message": "Add at least one domain."}
        return {"ok": True, "status": "connected",
                "message": f"Internet reachable. {len(domains)} websites will be checked ({sector['label']})."}

    def discover(self, run_index: int = 0) -> dict:
        from qmigrate.realdata.collector import collect
        return collect(self.config)
