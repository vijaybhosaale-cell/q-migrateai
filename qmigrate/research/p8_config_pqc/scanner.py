"""P8 scanner: find where TLS servers are told which key-exchange groups to use, and classify each place.

Two kinds of finding:

* explicit  a setting that lists groups (Envoy ecdh_curves, nginx ssl_ecdh_curve, Go CurvePreferences...).
            Its class comes from rules.classify_groups: pq_enabled, pq_excluded, draft_only, auto, unresolved.
* default   a TLS listener in a file that sets no groups at all, so the product default decides
            (Envoy, Istio: off; Go, Caddy, Traefik: on from Go 1.24; nginx, HAProxy, Apache: OpenSSL version).

The scanner only reads text. It never runs, renders or downloads anything.
"""
from __future__ import annotations

import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from qmigrate.research.p8_config_pqc import rules

MAX_BYTES = 1_000_000
CONFIG_EXT = {".yaml", ".yml", ".json", ".conf", ".cfg", ".tpl", ".tmpl", ".toml", ".j2", ".template", ".go",
              ".md", ".rst", ".properties", ".caddyfile", ".txt", ".tf", ".hcl"}
CONFIG_NAMES = {"caddyfile", "nginx.conf", "haproxy.cfg", "httpd.conf", "ssl.conf", "envoy.yaml", "dockerfile"}
SKIP_DIRS = {".git", "node_modules", "vendor", "third_party", "dist", "build", ".venv", "__pycache__"}


@dataclass
class Finding:
    path: str
    line: int
    product: str
    kind: str                  # explicit | default
    setting: str
    values: list[str] = field(default_factory=list)
    cls: str = ""
    category: str = ""         # deploy | chart | example | docs | test | source
    hard_fail_risk: bool = False
    min_openssl: str = ""      # oldest OpenSSL that accepts this list (OpenSSL-based servers naming ML-KEM)
    snippet: str = ""

    def row(self) -> dict:
        d = asdict(self)
        d["values"] = " ".join(self.values)
        return d


# --------------------------------------------------------------------------- helpers
def category(path: str) -> str:
    p = path.replace("\\", "/").lower()
    name = p.rsplit("/", 1)[-1]
    if (re.search(r"(^|/)(tests?|testdata|testutils?|testing|e2e|fixtures?|integration|conformance|golden|hack)(/|$)", p) or name.endswith("_test.go")
            or ".test." in name or name.startswith("test_")):
        return "test"
    if name.endswith((".md", ".rst", ".txt")) or re.search(r"(^|/)(docs?|site|website|content|changelogs?|release-?notes)(/|$)", p):
        return "docs"
    if re.search(r"(^|/)(examples?|samples?|demo|quickstart|tutorials?)(/|$)", p):
        return "example"
    if re.search(r"(^|/)(charts?|helm)(/|$)", p) or name in ("values.yaml", "values.yml") or "/templates/" in p:
        return "chart"
    if name.endswith(".go"):
        return "source"
    return "deploy"


def _split(value: str) -> list[str]:
    v = value.strip().rstrip(";").strip()
    v = v.split(" #", 1)[0].strip()
    if v.startswith("[") and v.endswith("]"):
        v = v[1:-1]
    return [t for t in re.split(r"[\s,:]+", v.replace('"', " ").replace("'", " ")) if t]


def _templated(value: str) -> bool:
    return "{{" in value or "}}" in value or "${" in value or "%{" in value or value.strip().startswith("$")


def _values(lines: list[str], i: int, rest: str) -> list[str]:
    """The values written after `key:` on line i: inline (`[a, b]`, `a:b`), a bracket list spread over
    several lines, or a YAML block list on the following lines."""
    rest = rest.strip()
    if rest.startswith(("|", ">")):
        return []
    if rest.startswith("[") and "]" not in rest:
        buf, j = rest, i
        while "]" not in buf and j + 1 < len(lines) and j - i < 30:
            j += 1
            buf += " " + lines[j].strip()
        rest = buf[:buf.index("]") + 1] if "]" in buf else buf
    if rest:
        return _split(rest)
    return _yaml_list_after(lines, i)[0]


def _yaml_list_after(lines: list[str], i: int) -> tuple[list[str], int]:
    """Values of `key:` written as a YAML block list on the following lines."""
    base = len(lines[i]) - len(lines[i].lstrip())
    out, j = [], i + 1
    while j < len(lines):
        s = lines[j]
        if not s.strip() or s.strip().startswith("#"):
            j += 1
            continue
        ind = len(s) - len(s.lstrip())
        st = s.strip()
        if st.startswith("- ") and ind >= base:
            out.append(st[2:].strip().strip("\"'"))
            j += 1
            continue
        break
    return out, j


def _is_schema(lines: list[str], i: int) -> bool:
    """A CRD / JSON-schema / docs-table description of the field, not a value."""
    nxt = " ".join(l.strip() for l in lines[i + 1:i + 4])
    return bool(re.search(r"\b(description|type|items|x-kubernetes|properties)\s*:", nxt)) or "| " in lines[i]


# --------------------------------------------------------------------------- detectors
def _explicit(path: str, product: str, setting: str, line: int, values: list[str], raw: str) -> Finding:
    cls = "unresolved" if any(_templated(v) for v in values) or not values else rules.classify_groups(values)
    return Finding(path=path, line=line, product=product, kind="explicit", setting=setting, values=values, cls=cls,
                   category=category(path), hard_fail_risk=rules.hard_fail_risk(product, values),
                   min_openssl=rules.min_openssl(product, values),
                   snippet=raw.strip()[:200])


def scan_text(path: str, text: str) -> list[Finding]:
    out: list[Finding] = []
    lines = text.splitlines()
    low_path = path.lower()
    name = os.path.basename(low_path)
    is_go = name.endswith(".go")
    is_caddy = name == "caddyfile" or name.endswith((".caddyfile", "caddyfile.j2")) or "caddyfile" in name

    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith(("#", "//", ";")):
            continue
        n = i + 1

        # Envoy (YAML / JSON): ecdh_curves
        m = re.search(r'["\']?ecdh_curves["\']?\s*:(.*)$', raw)
        if m and not is_go and not _is_schema(lines, i):
            out.append(_explicit(path, "envoy", "ecdh_curves", n, _values(lines, i, m.group(1)), raw))
            continue

        # Envoy Gateway / Istio (camelCase): ecdhCurves
        m = re.search(r'["\']?ecdhCurves["\']?\s*:(.*)$', raw)
        if m and not is_go and not _is_schema(lines, i):
            ctx = " ".join(lines[max(0, i - 8):i]).lower()
            product = "istio" if ("tlsdefaults" in ctx or "istio" in low_path or "meshconfig" in ctx) else "envoy-gateway"
            out.append(_explicit(path, product, "ecdhCurves", n, _values(lines, i, m.group(1)), raw))
            continue

        # Istio mesh-wide policy
        if "COMPLIANCE_POLICY" in raw:
            window = " ".join(lines[i:i + 3])
            mm = re.search(r'COMPLIANCE_POLICY["\']?\s*(?:[:=]\s*|\s*\n?.*?value\s*:\s*)["\']?([A-Za-z0-9_-]+)', window)
            if mm and mm.group(1).lower() == "pqc":
                out.append(Finding(path=path, line=n, product="istio", kind="explicit", setting="COMPLIANCE_POLICY",
                                   values=["pqc"], cls="pq_mesh_policy", category=category(path), snippet=s[:200]))
                continue

        # nginx: ssl_ecdh_curve
        m = re.search(r'\bssl_ecdh_curve\s+([^;\n]+);?', raw)
        if m:
            out.append(_explicit(path, "nginx", "ssl_ecdh_curve", n, _split(m.group(1)), raw))
            continue

        # ingress-nginx ConfigMap key
        m = re.search(r'^\s*["\']?ssl-ecdh-curve["\']?\s*:\s*(.+)$', raw)
        if m and "|" not in raw:
            out.append(_explicit(path, "ingress-nginx", "ssl-ecdh-curve", n, _split(m.group(1)), raw))
            continue

        # HAProxy
        m = re.search(r'\bssl-default-(bind|server)-curves\s+(\S+)', raw)
        if m:
            out.append(_explicit(path, "haproxy", f"ssl-default-{m.group(1)}-curves", n, _split(m.group(2)), raw))
            continue
        m = re.search(r'^\s*(bind|server)\s.*\bcurves\s+(\S+)', raw)
        if m and ("haproxy" in low_path or name.endswith(".cfg")):
            out.append(_explicit(path, "haproxy", f"{m.group(1)} ... curves", n, _split(m.group(2)), raw))
            continue

        # Apache mod_ssl
        m = re.search(r'\bSSLOpenSSLConfCmd\s+(Curves|Groups)\s+(\S+)', raw, re.I)
        if m:
            out.append(_explicit(path, "apache", f"SSLOpenSSLConfCmd {m.group(1)}", n, _split(m.group(2)), raw))
            continue

        # Caddy (Caddyfile): curves inside a tls block
        if is_caddy:
            m = re.match(r'^\s*curves\s+(.+)$', raw)
            if m:
                out.append(_explicit(path, "caddy", "tls curves", n, _split(m.group(1)), raw))
                continue

        # Traefik TLS options: curvePreferences
        m = re.search(r'["\']?curvePreferences["\']?\s*[:=](.*)$', raw)
        if m and not is_go and not _is_schema(lines, i):
            out.append(_explicit(path, "traefik", "curvePreferences", n, _values(lines, i, m.group(1)), raw))
            continue

        # Go crypto/tls: CurvePreferences
        if is_go:
            m = re.search(r'\bCurvePreferences\s*(?::|=)\s*(.*)$', raw)
            if m and "//" not in raw[:raw.find("CurvePreferences")]:
                rest = m.group(1)
                block = rest
                j = i
                while block.count("{") > block.count("}") and j + 1 < len(lines) and j - i < 20:
                    j += 1
                    block += " " + lines[j].strip()
                inner = re.search(r'\{(.*)\}', block)
                if inner:
                    vals = [t for t in re.split(r"[\s,]+", inner.group(1)) if t]
                else:
                    vals = [rest.strip().rstrip(",")]          # a variable: decided elsewhere
                f = _explicit(path, "go", "tls.Config.CurvePreferences", n, vals, raw)
                if not inner:
                    f.cls = "unresolved"
                out.append(f)
                continue

        # AWS load balancer TLS policy: Kubernetes annotations, Terraform, CloudFormation
        m = re.search(r'(alb\.ingress\.kubernetes\.io/ssl-policy|aws-load-balancer-ssl-negotiation-policy|'
                      r'\b\w*ssl_?policy)["\']?\s*:?=?\s*["\']?([A-Za-z0-9${}._-]+)', raw, re.I)
        if m and ("ELB" in m.group(2) or "{" in m.group(2) or m.group(2).startswith(("var.", "local."))):
            cls = rules.classify_aws_policy(m.group(2))
            out.append(Finding(path=path, line=n, product="aws-elb", kind="explicit", setting=m.group(1),
                               values=[m.group(2)], cls=cls, category=category(path), snippet=s[:200]))
            continue

        # TLS guideline data (Mozilla ssl-config-generator `tls_curves`), the source many configs are copied from
        m = re.search(r'"tls_curves"\s*:\s*(.*)$', raw)
        if m:
            out.append(_explicit(path, "guideline", "tls_curves", n, _values(lines, i, m.group(1)), raw))
            continue

        # Java system property
        m = re.search(r'jdk\.tls\.namedGroups\s*[=:]\s*["\']?([^"\'\s]+)', raw)
        if m:
            out.append(_explicit(path, "java", "jdk.tls.namedGroups", n, _split(m.group(1)), raw))
            continue

    out += _defaults(path, text, out)
    return out


# --------------------------------------------------------------------------- TLS listeners left on defaults
def _first_line(text: str, pattern: str) -> int:
    m = re.search(pattern, text, re.M)
    return text[:m.start()].count("\n") + 1 if m else 1


def _defaults(path: str, text: str, found: list[Finding]) -> list[Finding]:
    """One 'default' finding per file that clearly terminates TLS but sets no groups for that product."""
    name = os.path.basename(path.lower())
    has = {f.product for f in found}
    out: list[Finding] = []

    def add(product: str, setting: str, pattern: str):
        out.append(Finding(path=path, line=_first_line(text, pattern), product=product, kind="default",
                           setting=setting, cls="default", category=category(path)))

    if name.endswith(".go"):
        if re.search(r"&?tls\.Config\{", text) and "go" not in has and not name.endswith("_test.go"):
            add("go", "tls.Config without CurvePreferences", r"tls\.Config\{")
        return out
    # a real Envoy listener config names the typed TLS context; changelogs and metadata only mention the word
    envoy_tls = r"transport_sockets\.tls\.v3\.DownstreamTlsContext"
    if re.search(envoy_tls, text) and "envoy" not in has:
        add("envoy", "DownstreamTlsContext without ecdh_curves", envoy_tls)
    if re.search(r"^\s*listen\s+[^;]*\bssl\b", text, re.M) and "nginx" not in has:
        add("nginx", "listen ... ssl without ssl_ecdh_curve", r"^\s*listen\s+[^;]*\bssl\b")
    if ("haproxy" in path.lower() or name.endswith(".cfg")) and re.search(r"^\s*bind\s[^\n]*\bssl\b[^\n]*\bcrt\b", text, re.M) \
            and "haproxy" not in has:
        add("haproxy", "bind ... ssl crt without curves", r"^\s*bind\s[^\n]*\bssl\b")
    if re.search(r"^\s*SSLEngine\s+on", text, re.M | re.I) and "apache" not in has:
        add("apache", "SSLEngine on without Curves/Groups", r"^\s*SSLEngine\s+on")
    return out


# --------------------------------------------------------------------------- trees
def iter_files(root: Path):
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for fn in filenames:
            p = Path(dirpath) / fn
            low = fn.lower()
            if p.suffix.lower() in CONFIG_EXT or low in CONFIG_NAMES or "caddyfile" in low or low.startswith("nginx"):
                try:
                    if p.stat().st_size <= MAX_BYTES and not p.is_symlink():
                        yield p
                except OSError:
                    continue


def scan_tree(root: Path, label: str | None = None) -> tuple[list[Finding], int]:
    """Scan every config-like file under root. Returns (findings, files scanned). Paths are relative and
    prefixed with `label` (the repository name) so results from many repositories can be merged."""
    root = Path(root)
    findings: list[Finding] = []
    count = 0
    for p in iter_files(root):
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        count += 1
        if not re.search(r"ecdh|curve|tls_curves|COMPLIANCE_POLICY|tls\.Config|DownstreamTlsContext|listen|bind|SSLEngine|namedGroups|"
                         r"ssl-policy|ssl_?policy|negotiation-policy",
                         text, re.I):
            continue
        rel = str(p.relative_to(root)).replace("\\", "/")
        findings += scan_text(f"{label}/{rel}" if label else rel, text)
    return findings, count
