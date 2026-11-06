"""P8: the config scanner finds key-exchange settings and classifies them correctly."""
from __future__ import annotations

from qmigrate.research.p8_config_pqc import rules
from qmigrate.research.p8_config_pqc.scanner import category, scan_text


def one(path, text, kind="explicit"):
    fs = [f for f in scan_text(path, text) if f.kind == kind]
    assert len(fs) == 1, [f.row() for f in fs]
    return fs[0]


# ------------------------------------------------------------------ group rules
def test_group_names_are_normalised():
    assert rules.normalise_group("tls.X25519MLKEM768") == "x25519mlkem768"
    assert rules.normalise_group('"?X25519MLKEM768"') == "x25519mlkem768"
    assert rules.normalise_group("P-256") == "p256"
    assert rules.normalise_group("gotls.CurveP256") == "curvep256"
    assert rules.normalise_group("crypto/tls.X25519MLKEM768") == "x25519mlkem768"


def test_classification():
    assert rules.classify_groups(["X25519MLKEM768", "X25519", "P-256"]) == "pq_enabled"
    assert rules.classify_groups(["X25519", "P-256"]) == "pq_excluded"
    assert rules.classify_groups(["X25519Kyber768Draft00", "X25519"]) == "draft_only"
    assert rules.classify_groups(["auto"]) == "auto"
    assert rules.classify_groups(["MyCustomCurve"]) == "unresolved"


def test_oldest_openssl_that_accepts_the_list():
    assert rules.min_openssl("nginx", ["X25519MLKEM768", "X25519"]) == "3.5"
    assert rules.min_openssl("nginx", ["?X25519MLKEM768", "X25519"]) == "3.3"   # '?' exists from 3.3
    assert rules.min_openssl("nginx", ["X25519", "prime256v1"]) == ""
    assert rules.min_openssl("envoy", ["X25519MLKEM768"]) == ""                # BoringSSL, not OpenSSL
    assert rules.hard_fail_risk("haproxy", ["?X25519MLKEM768"]) and not rules.hard_fail_risk("go", ["X25519MLKEM768"])


# ------------------------------------------------------------------ products
def test_envoy_yaml_inline_and_block_lists():
    f = one("envoy.yaml", "tls_params:\n  ecdh_curves: [X25519, P-256]\n")
    assert (f.product, f.cls, f.values) == ("envoy", "pq_excluded", ["X25519", "P-256"])
    f = one("envoy.yaml", "tls_params:\n  ecdh_curves:\n  - X25519MLKEM768\n  - X25519\n")
    assert f.cls == "pq_enabled"


def test_envoy_json_multiline_array():
    f = one("bootstrap.json", '{"tls_params": {"ecdh_curves": [\n  "X25519",\n  "P-256"\n]}}')
    assert f.cls == "pq_excluded" and f.values == ["X25519", "P-256"]


def test_crd_schema_is_not_a_setting():
    text = "ecdhCurves:\n  description: ECDHCurves specifies the curves\n  items:\n    type: string\n  type: array\n"
    assert [f for f in scan_text("crd.yaml", text) if f.kind == "explicit"] == []


def test_envoy_gateway_and_istio():
    f = one("ctp.yaml", "kind: ClientTrafficPolicy\nspec:\n  tls:\n    ecdhCurves:\n    - X25519MLKEM768\n")
    assert (f.product, f.cls) == ("envoy-gateway", "pq_enabled")
    f = one("istio-values.yaml", "meshConfig:\n  tlsDefaults:\n    ecdhCurves:\n    - X25519\n    - P-256\n")
    assert (f.product, f.cls) == ("istio", "pq_excluded")
    f = one("istio.yaml", "pilot:\n  env:\n    - name: COMPLIANCE_POLICY\n      value: pqc\n")
    assert f.cls == "pq_mesh_policy"


def test_nginx_and_ingress_nginx():
    f = one("nginx.conf", "server {\n  listen 443 ssl;\n  ssl_ecdh_curve X25519:prime256v1:secp384r1;\n}\n")
    assert (f.product, f.cls) == ("nginx", "pq_excluded")
    f = one("nginx.conf", "ssl_ecdh_curve X25519MLKEM768:X25519;\n")
    assert f.cls == "pq_enabled" and f.hard_fail_risk
    f = one("configmap.yaml", 'data:\n  ssl-ecdh-curve: "auto"\n')
    assert (f.product, f.cls) == ("ingress-nginx", "auto")


def test_nginx_template_value_is_unresolved():
    f = one("nginx.conf.tpl", "ssl_ecdh_curve {{ .Values.curves }};\n")
    assert f.cls == "unresolved"


def test_haproxy_apache_caddy_traefik_java():
    assert one("haproxy.cfg", "global\n  ssl-default-bind-curves X25519:P-256\n").cls == "pq_excluded"
    assert one("haproxy.cfg", "frontend fe\n  bind :443 ssl crt /c.pem curves X25519MLKEM768:X25519\n").cls == "pq_enabled"
    assert one("ssl.conf", "SSLOpenSSLConfCmd Curves X25519:secp384r1\n").cls == "pq_excluded"
    assert one("Caddyfile", "example.com {\n  tls {\n    curves x25519 secp256r1\n  }\n}\n").cls == "pq_excluded"
    assert one("tls.yaml", "tls:\n  options:\n    default:\n      curvePreferences:\n        - CurveP521\n        - CurveP384\n").cls == "pq_excluded"
    assert one("app.properties", "jdk.tls.namedGroups=x25519,secp256r1\n").cls == "pq_excluded"


def test_go_curve_preferences():
    code = 'cfg := &tls.Config{\n\tMinVersion: tls.VersionTLS12,\n\tCurvePreferences: []tls.CurveID{\n\t\ttls.X25519,\n\t\ttls.CurveP256,\n\t},\n}\n'
    f = one("server.go", code)
    assert (f.product, f.cls) == ("go", "pq_excluded")
    f = one("server.go", "c := &tls.Config{CurvePreferences: []tls.CurveID{tls.X25519MLKEM768, tls.X25519}}\n")
    assert f.cls == "pq_enabled"
    f = one("server.go", "c := &tls.Config{CurvePreferences: curves}\n")
    assert f.cls == "unresolved"


def test_defaults_are_reported_when_tls_has_no_groups():
    f = one("server.go", "c := &tls.Config{MinVersion: tls.VersionTLS13}\n", kind="default")
    assert f.product == "go"
    f = one("nginx.conf", "server {\n  listen 443 ssl;\n  ssl_certificate /c.pem;\n}\n", kind="default")
    assert f.product == "nginx"
    f = one("envoy.yaml", "transport_socket:\n  typed_config:\n    '@type': type.googleapis.com/envoy.extensions."
                          "transport_sockets.tls.v3.DownstreamTlsContext\n", kind="default")
    assert f.product == "envoy"
    assert [f for f in scan_text("server_test.go", "x := &tls.Config{}\n") if f.kind == "default"] == []


def test_comments_are_ignored():
    assert scan_text("nginx.conf", "# ssl_ecdh_curve X25519;\n") == []


def test_categories():
    assert category("istio/tests/integration/x.yaml") == "test"
    assert category("envoy/docs/root/config.yaml") == "docs"
    assert category("gateway/examples/kubernetes/tls.yaml") == "example"
    assert category("bitnami/charts/nginx/templates/cm.yaml") == "chart"
    assert category("haproxy/haproxy.cfg") == "deploy"
    assert category("kgateway/pkg/translator/testutils/outputs/tls.yaml") == "test"
    assert category("envoy/changelogs/1.25.0.yaml") == "docs"


def test_envoy_default_needs_a_real_tls_context():
    """Changelogs and metadata files that only mention the word are not listeners."""
    assert scan_text("meta.yaml", "security_posture: DownstreamTlsContext is robust\n") == []


def test_aws_load_balancer_policies():
    f = one("ingress.yaml", "annotations:\n  alb.ingress.kubernetes.io/ssl-policy: ELBSecurityPolicy-TLS13-1-2-2021-06\n")
    assert (f.product, f.cls) == ("aws-elb", "pq_excluded")
    f = one("main.tf", 'resource "aws_lb_listener" "https" {\n  ssl_policy = "ELBSecurityPolicy-TLS13-1-2-PQ-2025-09"\n}\n')
    assert f.cls == "pq_enabled"
    assert one("variables.tf", "  ssl_policy = var.listener_ssl_policy\n").cls == "unresolved"


def test_guideline_lists_and_comparison():
    f = one("docs/guidelines/6.0.json", '{"configurations": {"intermediate": {\n  "tls_curves": ["X25519MLKEM768", "X25519", "prime256v1", "secp384r1"],\n  "tls_versions": ["TLSv1.2"]}}}')
    assert (f.product, f.cls) == ("guideline", "pq_enabled")
    # the same list in three spellings
    assert rules.canonical_list(["X25519", "prime256v1", "secp384r1"]) == \
        rules.canonical_list(["x25519", "secp256r1", "P-384"]) == \
        rules.canonical_list(["tls.X25519", "tls.CurveP256", "tls.CurveP384"])


def test_aws_policy_default_in_go_source():
    f = one("pkg/config/controller_config.go", '\tdefaultSSLPolicy                                 = "ELBSecurityPolicy-2016-08"\n')
    assert (f.product, f.cls, f.category) == ("aws-elb", "pq_excluded", "source")


def test_advice_says_what_to_change():
    assert "X25519MLKEM768" in rules.advice("nginx", "explicit", "pq_excluded", ["X25519"])
    assert "PQ" in rules.advice("aws-elb", "explicit", "pq_excluded", ["ELBSecurityPolicy-2016-08"])
    assert "OpenSSL 3.5+" in rules.advice("nginx", "explicit", "pq_enabled", ["X25519MLKEM768"])
    assert rules.advice("envoy", "default", "default").startswith("No setting")
    assert rules.advice("go", "explicit", "pq_enabled", ["tls.X25519MLKEM768"]) == "Post-quantum is on."
