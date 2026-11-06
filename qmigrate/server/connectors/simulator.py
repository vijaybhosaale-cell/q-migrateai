"""Demo connector: reads a synthetic estate from the cloud simulator service.

config: {"profile": "generic" | "bank" | "hospital", "seed": int, "assets": int,
         "simulate_changes": bool}
With simulate_changes, every later scan adds one new application (new keys,
certificates and endpoints), so continuous monitoring and alerts can be shown.
"""
from __future__ import annotations

import requests

from qmigrate.server.connectors.base import CloudConnector


class SimulatorConnector(CloudConnector):
    provider = "simulator"
    title = "Demo cloud (simulator)"

    def __init__(self, config: dict, simulator_url: str = "inprocess"):
        super().__init__(config)
        self.simulator_url = simulator_url

    def _params(self, run_index: int) -> dict:
        drift = run_index if self.config.get("simulate_changes", True) else 0
        return {"profile": self.config.get("profile", "generic"), "seed": int(self.config.get("seed", 42)),
                "n": int(self.config.get("assets", 400)), "drift": drift}

    def test(self) -> dict:
        if self.simulator_url == "inprocess":
            return {"ok": True, "status": "connected", "message": "Built-in simulator (in-process)."}
        try:
            r = requests.get(f"{self.simulator_url}/health", timeout=5)
            r.raise_for_status()
            return {"ok": True, "status": "connected", "message": f"Simulator reachable at {self.simulator_url}."}
        except requests.RequestException as exc:
            return {"ok": False, "status": "error", "message": f"Simulator not reachable: {exc}"}

    def discover(self, run_index: int = 0) -> dict:
        p = self._params(run_index)
        if self.simulator_url == "inprocess":
            from qmigrate.simulator.generator import generate
            return generate(p["seed"], p["n"], p["profile"], p["drift"])
        r = requests.get(f"{self.simulator_url}/estate", params=p, timeout=60)
        r.raise_for_status()
        return r.json()
