"""P8 rules: where each TLS server is told which key-exchange groups to use, and what it does by default.

The research question: software that SUPPORTS hybrid post-quantum key exchange (X25519MLKEM768) is not
the same as a deployment that NEGOTIATES it. Two things decide it:

  1. an explicit setting that lists the allowed groups. If the list has no ML-KEM group, post-quantum is
     switched off, however new the software is;
  2. no setting at all: then the software's own default applies, and that default differs per product.

Every default below is sourced; `DEFAULTS[...]["source"]` is printed in the study report.
"""
from __future__ import annotations

import re

# --------------------------------------------------------------------------- key-exchange groups
# Standardised hybrid / pure ML-KEM groups (IETF draft-ietf-tls-ecdhe-mlkem, draft-ietf-tls-mlkem).
PQ_GROUPS = {
    "x25519mlkem768", "secp256r1mlkem768", "secp384r1mlkem1024", "mlkem512", "mlkem768", "mlkem1024",
    "curvesm2mlkem768",
}
# The pre-standard Kyber draft (codepoint 0x6399). Browsers and servers are removing it.
DRAFT_GROUPS = {"x25519kyber768draft00", "x25519kyber768", "x25519kyber512draft00", "p256kyber768draft00"}
CLASSICAL_GROUPS = {
    "x25519", "x448", "p256", "p384", "p521", "prime256v1", "secp256r1", "secp384r1", "secp521r1",
    "curvep256", "curvep384", "curvep521", "ffdhe2048", "ffdhe3072", "ffdhe4096", "ffdhe6144", "ffdhe8192",
    "brainpoolp256r1", "brainpoolp384r1", "brainpoolp512r1", "secp256k1", "auto",
}


def normalise_group(name: str) -> str:
    """'tls.X25519MLKEM768', '"X25519MLKEM768"', '?X25519MLKEM768', 'P-256', 'x25519_mlkem768' -> one spelling."""
    n = name.strip().strip("\"'`,;[]{}()").lower()
    # Go constants carry a package name: tls.X25519, gotls.CurveP256, crypto/tls.X25519MLKEM768
    if re.fullmatch(r"[a-z0-9_/]+\.[a-z0-9_]+", n):
        n = n.rsplit(".", 1)[1]
    for prefix in ("?", "*", "-", "+"):
        while n.startswith(prefix):
            n = n[len(prefix):]
    return re.sub(r"[^a-z0-9]", "", n)


_SYNONYMS = {"prime256v1": "p256", "secp256r1": "p256", "curvep256": "p256", "secp384r1": "p384",
             "curvep384": "p384", "secp521r1": "p521", "curvep521": "p521"}


def canonical_list(values: list[str]) -> tuple[str, ...]:
    """One spelling per group, order kept, so lists copied between products can be compared."""
    return tuple(_SYNONYMS.get(n, n) for n in (normalise_group(v) for v in values) if n)


def classify_groups(values: list[str]) -> str:
    """Classify one explicit list of groups.

    pq_enabled   the list contains a standardised ML-KEM group
    draft_only   only the old Kyber draft, which is being removed everywhere
    pq_excluded  an explicit list with classical groups only: post-quantum is switched off
    auto         'auto' (nginx) = whatever the TLS library offers by default
    unresolved   a template variable or something we cannot read
    """
    norm = [normalise_group(v) for v in values if v.strip()]
    norm = [n for n in norm if n]
    if not norm:
        return "unresolved"
    if any(n in PQ_GROUPS for n in norm):
        return "pq_enabled"
    if any(n in DRAFT_GROUPS for n in norm):
        return "draft_only"
    if norm == ["auto"]:
        return "auto"
    if all(n in CLASSICAL_GROUPS for n in norm):
        return "pq_excluded"
    return "unresolved"


CLASS_TEXT = {
    "pq_enabled": "Post-quantum enabled: the list includes a hybrid ML-KEM group",
    "pq_excluded": "Post-quantum switched off: an explicit list with classical groups only",
    "draft_only": "Outdated: only the pre-standard Kyber draft, which is being removed",
    "auto": "Library default ('auto'): depends on the TLS library version",
    "unresolved": "Not readable (template variable or unknown value)",
    "default": "No setting: the product default applies",
    "pq_mesh_policy": "Mesh-wide post-quantum policy switched on",
}

# --------------------------------------------------------------------------- product defaults
# What happens when nothing is configured. "on" = X25519MLKEM768 offered/accepted by default.
DEFAULTS = {
    "envoy": {
        "pq_default": "off",
        "detail": "Envoy passes its own list X25519:P-256 (FIPS builds: P-256) to BoringSSL, so ML-KEM is opt-in.",
        "source": "https://github.com/envoyproxy/envoy/pull/44944",
    },
    "envoy-gateway": {
        "pq_default": "off",
        "detail": "Built on Envoy: without ecdhCurves the Envoy default X25519:P-256 applies.",
        "source": "https://github.com/envoyproxy/envoy/pull/44944",
    },
    "istio": {
        "pq_default": "off",
        "detail": "Gateways need meshConfig.tlsDefaults.ecdhCurves = X25519MLKEM768, or COMPLIANCE_POLICY=pqc.",
        "source": "https://docs.redhat.com/en/documentation/red_hat_openshift_service_mesh/3.3/html/installing/ossm-pqc-install",
    },
    "go": {
        "pq_default": "on (Go 1.24+)",
        "detail": "crypto/tls adds X25519MLKEM768 to the default CurvePreferences from Go 1.24 "
                  "(GODEBUG tlsmlkem=0 turns it off). An explicit CurvePreferences list replaces the default.",
        "source": "https://github.com/golang/go/issues/69985",
    },
    "caddy": {
        "pq_default": "on (built with Go 1.24+)",
        "detail": "Caddy uses Go crypto/tls defaults; an explicit `curves` list replaces them.",
        "source": "https://github.com/golang/go/issues/69985",
    },
    "traefik": {
        "pq_default": "on (built with Go 1.24+)",
        "detail": "Traefik uses Go crypto/tls defaults; TLSOption curvePreferences replaces them.",
        "source": "https://github.com/golang/go/issues/69985",
    },
    "nginx": {
        "pq_default": "depends on OpenSSL (3.5+: on)",
        "detail": "ssl_ecdh_curve defaults to 'auto', i.e. the OpenSSL default list, which includes X25519MLKEM768 "
                  "from OpenSSL 3.5. Naming X25519MLKEM768 makes nginx refuse to start on OpenSSL 3.0-3.4 "
                  "(3.0-3.2 even as ?X25519MLKEM768).",
        "source": "https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/",
    },
    "ingress-nginx": {
        "pq_default": "depends on OpenSSL (3.5+: on)",
        "detail": "The ConfigMap key ssl-ecdh-curve feeds nginx ssl_ecdh_curve (default auto).",
        "source": "https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/",
    },
    "haproxy": {
        "pq_default": "depends on OpenSSL (3.5+: on)",
        "detail": "Without `curves` / ssl-default-bind-curves HAProxy uses the TLS library default list.",
        "source": "https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/",
    },
    "apache": {
        "pq_default": "depends on OpenSSL (3.5+: on)",
        "detail": "Without SSLOpenSSLConfCmd Curves/Groups mod_ssl uses the OpenSSL default list.",
        "source": "https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/",
    },
}

DEFAULTS["aws-elb"] = {
    "pq_default": "off from API/IaC (on in the console)",
    "detail": "Policies with PQ in the name offer hybrid ML-KEM. A listener created in the console defaults to "
              "ELBSecurityPolicy-TLS13-1-2-Res-PQ-2025-09; one created with the CLI, CloudFormation or CDK "
              "defaults to ELBSecurityPolicy-2016-08, which has no ML-KEM.",
    "source": "https://docs.aws.amazon.com/elasticloadbalancing/latest/application/describe-ssl-policies.html",
}


def classify_aws_policy(name: str) -> str:
    """AWS ELB security policy names: post-quantum policies contain '-PQ-'."""
    n = name.strip().strip("\"'")
    if not n or "{{" in n or "${" in n or n.startswith(("var.", "local.", "$")):
        return "unresolved"
    if "-PQ-" in n.upper():
        return "pq_enabled"
    if n.startswith(("ELBSecurityPolicy", "ELBFIPSPolicy")):
        return "pq_excluded"
    return "unresolved"


# Settings that name OpenSSL groups and fail hard when OpenSSL does not know a name (nginx, HAProxy, Apache).
# OpenSSL knows the ML-KEM names from 3.5; the '?' prefix ("skip this group if it is missing") from 3.3.
# So a list that names ML-KEM stops the server from starting on OpenSSL 3.0-3.4 without '?',
# and on 3.0-3.2 even with '?'.  Source: SSL_CTX_set1_groups_list(3), HISTORY section.
OPENSSL_LIST_PRODUCTS = {"nginx", "ingress-nginx", "haproxy", "apache"}
OPENSSL_HISTORY_SOURCE = "https://manpages.debian.org/experimental/libssl-doc/SSL_CTX_set1_groups_list.3ssl.en.html"


def min_openssl(product: str, values: list[str]) -> str:
    """Oldest OpenSSL on which this group list still loads ('' when the list is safe everywhere)."""
    if product not in OPENSSL_LIST_PRODUCTS:
        return ""
    pq = [v for v in values if normalise_group(v) in PQ_GROUPS]
    if not pq:
        return ""
    return "3.3" if all(v.strip().strip("\"'").startswith("?") for v in pq) else "3.5"


def hard_fail_risk(product: str, values: list[str]) -> bool:
    """True when an OpenSSL-based server names an ML-KEM group: on older OpenSSL the whole list is
    rejected and the server does not start (a breakage risk, see P1)."""
    return bool(min_openssl(product, values))


# --------------------------------------------------------------------------- what a finding means in practice
OUTCOME_TEXT = {
    "on": "Post-quantum negotiated",
    "off_pinned": "Off: pinned to classical groups",
    "off_default": "Off: product default has no ML-KEM",
    "off_draft": "Off: only the withdrawn Kyber draft",
    "depends_library": "Depends on the TLS library version",
    "on_if_go124": "On if built with Go 1.24 or newer",
    "unknown": "Unknown (template or variable)",
}

_DEFAULT_OUTCOME = {
    "envoy": "off_default", "envoy-gateway": "off_default", "istio": "off_default", "aws-elb": "off_default",
    "go": "on_if_go124", "caddy": "on_if_go124", "traefik": "on_if_go124",
    "nginx": "depends_library", "ingress-nginx": "depends_library", "haproxy": "depends_library",
    "apache": "depends_library",
}


def outcome(product: str, kind: str, cls: str) -> str:
    """Combine the setting (or its absence) with the product default into what a client actually gets."""
    if kind == "default":
        return _DEFAULT_OUTCOME.get(product, "unknown")
    return {
        "pq_enabled": "on", "pq_mesh_policy": "on", "pq_excluded": "off_pinned", "draft_only": "off_draft",
        "auto": "depends_library", "unresolved": "unknown",
    }.get(cls, "unknown")


# --------------------------------------------------------------------------- what to change
_FIX = {
    "nginx": "ssl_ecdh_curve X25519MLKEM768:X25519:prime256v1:secp384r1;  (OpenSSL 3.5+), or delete the line "
             "to use the OpenSSL default",
    "ingress-nginx": 'ssl-ecdh-curve: "X25519MLKEM768:X25519:prime256v1:secp384r1"  (controller built with '
                     'OpenSSL 3.5+), or delete the key',
    "haproxy": "curves X25519MLKEM768:X25519:P-256  (OpenSSL 3.5+), or delete the setting",
    "apache": "SSLOpenSSLConfCmd Curves X25519MLKEM768:X25519:prime256v1:secp384r1  (OpenSSL 3.5+)",
    "envoy": "ecdh_curves: [X25519MLKEM768, X25519, P-256]",
    "envoy-gateway": "ClientTrafficPolicy spec.tls.ecdhCurves: [X25519MLKEM768, X25519, P-256]",
    "istio": "meshConfig.tlsDefaults.ecdhCurves: [X25519MLKEM768, X25519, P-256], or COMPLIANCE_POLICY=pqc",
    "go": "put tls.X25519MLKEM768 first in CurvePreferences, or delete CurvePreferences to use the Go 1.24+ default",
    "caddy": "delete the curves list so Caddy uses Go's default (ML-KEM when built with Go 1.24+)",
    "traefik": "delete curvePreferences so Traefik uses Go's default (ML-KEM when built with Go 1.24+)",
    "java": "add a hybrid ML-KEM group once your JDK supports one; this list leaves it out",
    "aws-elb": "use a policy with PQ in its name, e.g. ELBSecurityPolicy-TLS13-1-2-Res-PQ-2025-09",
}


def advice(product: str, kind: str, cls: str, values: list[str] | None = None) -> str:
    """One sentence: what to change so this endpoint negotiates hybrid post-quantum key exchange."""
    values = values or []
    fix = _FIX.get(product, "")
    if kind == "default":
        d = DEFAULTS.get(product)
        if not d:
            return ""
        if _DEFAULT_OUTCOME.get(product) == "off_default":
            return f"No setting, and the default has no ML-KEM. Add: {fix}" if fix else d["detail"]
        return d["detail"]
    if cls in ("pq_excluded", "draft_only"):
        return f"Post-quantum is switched off here. Change to: {fix}" if fix else "Add a hybrid ML-KEM group."
    if cls == "auto":
        return "Uses the TLS library default: ML-KEM is offered only with OpenSSL 3.5 or newer."
    if cls == "unresolved":
        return "The value comes from a template or variable. Check the rendered configuration."
    if cls in ("pq_enabled", "pq_mesh_policy"):
        need = min_openssl(product, values)
        if need:
            return (f"Post-quantum is on, but this list only loads on OpenSSL {need}+; on older OpenSSL the "
                    "server does not start.")
        return "Post-quantum is on."
    return ""
