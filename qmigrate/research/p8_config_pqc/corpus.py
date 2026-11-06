"""P8 corpus: real, public repositories that ship TLS configuration people copy into production.

Each repository is cloned shallow (one commit, no history, no tags) and the exact commit is recorded,
so anyone can re-run the study on the same files:

    python -m qmigrate.research.p8_config_pqc.study --clone

The list covers the places a TLS listener's key-exchange groups are usually decided:
proxies and meshes, ingress controllers, Helm charts, copy-paste config templates, Go infrastructure
and AWS load-balancer infrastructure-as-code.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path

# (repository, kind). kind is used to group results in the report.
REPOS: list[tuple[str, str]] = [
    # proxies, gateways, service meshes
    ("envoyproxy/envoy", "proxy"),
    ("envoyproxy/gateway", "gateway"),
    ("istio/istio", "mesh"),
    ("cilium/cilium", "mesh"),
    ("hashicorp/consul", "mesh"),
    ("emissary-ingress/emissary", "gateway"),
    ("projectcontour/contour", "gateway"),
    ("kgateway-dev/kgateway", "gateway"),
    ("apache/apisix", "gateway"),
    ("traefik/traefik", "proxy"),
    ("caddyserver/caddy", "proxy"),
    # Kubernetes ingress controllers
    ("kubernetes/ingress-nginx", "ingress"),
    ("nginx/kubernetes-ingress", "ingress"),
    ("haproxytech/kubernetes-ingress", "ingress"),
    ("Kong/kubernetes-ingress-controller", "ingress"),
    # Helm charts
    ("bitnami/charts", "chart"),
    ("prometheus-community/helm-charts", "chart"),
    ("grafana/helm-charts", "chart"),
    ("argoproj/argo-helm", "chart"),
    ("traefik/traefik-helm-chart", "chart"),
    ("haproxytech/helm-charts", "chart"),
    ("Kong/charts", "chart"),
    # configuration templates that people copy
    ("mozilla/ssl-config-generator", "template"),
    ("h5bp/server-configs-nginx", "template"),
    ("h5bp/server-configs-apache", "template"),
    ("nginx-proxy/nginx-proxy", "template"),
    ("linuxserver/docker-swag", "template"),
    ("NginxProxyManager/nginx-proxy-manager", "template"),
    ("certbot/certbot", "template"),
    # Go infrastructure (crypto/tls servers)
    ("kubernetes/kubernetes", "infra"),
    ("etcd-io/etcd", "infra"),
    ("hashicorp/vault", "infra"),
    ("prometheus/prometheus", "infra"),
    ("minio/minio", "infra"),
    ("cert-manager/cert-manager", "infra"),
    # AWS load balancers as code
    ("terraform-aws-modules/terraform-aws-alb", "iac"),
    ("kubernetes-sigs/aws-load-balancer-controller", "iac"),
]


@dataclass
class Checkout:
    repo: str
    kind: str
    path: Path
    sha: str
    error: str = ""


def default_dir() -> Path:
    return Path(os.environ.get("QM_CORPUS_DIR", Path.home() / ".cache" / "qmigrate" / "p8-corpus"))


def _git(*args: str, cwd: Path | None = None, timeout: int = 600) -> str:
    r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout,
                       env={**os.environ, "GIT_TERMINAL_PROMPT": "0"})
    if r.returncode != 0:
        raise RuntimeError(r.stderr.strip().splitlines()[-1] if r.stderr.strip() else f"git {args[0]} failed")
    return r.stdout.strip()


def fetch(repo: str, kind: str, base: Path, refresh: bool = False) -> Checkout:
    """Shallow-clone one repository (or reuse an existing clone) and return its exact commit."""
    dest = base / repo.replace("/", "__")
    try:
        if not (dest / ".git").exists():
            dest.parent.mkdir(parents=True, exist_ok=True)
            # Files over 1 MB are never scanned, so they are not downloaded either.
            _git("clone", "--depth", "1", "--single-branch", "--no-tags", "--filter=blob:limit=1m",
                 f"https://github.com/{repo}.git", str(dest))
        elif refresh:
            _git("fetch", "--depth", "1", "origin", "HEAD", cwd=dest)
            _git("reset", "--hard", "FETCH_HEAD", cwd=dest)
        return Checkout(repo, kind, dest, _git("rev-parse", "HEAD", cwd=dest))
    except (RuntimeError, subprocess.TimeoutExpired, OSError) as e:
        return Checkout(repo, kind, dest, "", error=str(e)[:200])


def fetch_all(base: Path | None = None, refresh: bool = False, repos=None, workers: int = 6) -> list[Checkout]:
    from concurrent.futures import ThreadPoolExecutor
    base = Path(base or default_dir())
    repos = repos or REPOS
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(lambda rk: fetch(rk[0], rk[1], base, refresh), repos))
