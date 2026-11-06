# P8 · Supported is not switched on

Scan date 2026-11-06. 37 public repositories, 79,593 configuration and Go files, 581 findings. Every repository is pinned to the commit in `corpus.json`; every finding links to its line in `findings.csv`.

## Headline

* **147** places set the TLS key-exchange groups explicitly; **39** of them are in configuration people deploy or copy, or in shipped Go code.
* Of the 13 that can be read, **12** (92.3%) pin a classical-only list. On those endpoints post-quantum key exchange stays off even after the software is upgraded to a version that supports ML-KEM.
* **1** (7.7%) include a hybrid ML-KEM group.
* **0** nginx, HAProxy or Apache settings name an ML-KEM group. Such a list is rejected, and the server does not start, on OpenSSL 3.0–3.4 (3.0–3.2 even with the `?` prefix).

The numbers are small because most projects never set the groups at all (the "No setting" column): for them the product default decides, which is why the defaults table at the end matters as much as the pinned lists.

| Where | Explicit settings | Readable | PQ on | Pinned classical | Pinned % | No setting |
|---|---|---|---|---|---|---|
| Configs, charts, examples | 7 | 5 | 0 | 5 | 100.0% | 40 |
| Shipped Go code | 32 | 8 | 1 | 7 | 87.5% | 124 |
| Tests and docs | 108 | 49 | 12 | 37 | 75.5% | 237 |

## Observations

* **Certbot's Apache plugin** ships `current-options-ssl-apache.conf` with `SSLOpenSSLConfCmd Curves X25519:prime256v1:secp384r1`. The file says it is based on ssl-config.mozilla.org and that Certbot manages it. The list is identical to an earlier Mozilla guideline, while Mozilla's newest guideline puts X25519MLKEM768 first. A server Certbot configured keeps post-quantum off even after OpenSSL is upgraded to 3.5.
* **h5bp server-configs-nginx**, a widely copied nginx boilerplate, pins `ssl_ecdh_curve` to classical lists in both its balanced and strict policies. That overrides the OpenSSL 3.5 default, which would have offered ML-KEM.
* **AWS Load Balancer Controller** uses `ELBSecurityPolicy-2016-08` when an Ingress has no `ssl-policy` annotation (`defaultSSLPolicy` in its Go source), and the Terraform ALB module's examples use `ELBSecurityPolicy-TLS13-1-2-Res-2021-06`. Neither is a PQ policy. AWS's own console now defaults to `ELBSecurityPolicy-TLS13-1-2-Res-PQ-2025-09`, but listeners created through the API, CloudFormation or CDK still default to `ELBSecurityPolicy-2016-08`: the same load balancer gets post-quantum or not depending on the tool that created it.
* **Compliance modes can switch post-quantum off.** Istio's FIPS 140-2 and 140-3 modes set CurvePreferences to P-256 (and P-384) only. Only its separate `pqc` policy offers ML-KEM. FIPS and post-quantum are not exclusive: AWS ships FIPS policies with PQ (for example `ELBSecurityPolicy-TLS13-1-2-FIPS-PQ-2025-09`).
* **Code generators spread pinned lists.** Cilium's four go-swagger-generated API servers all carry `CurvePreferences: []tls.CurveID{tls.CurveP256}` from the generator template, which replaces Go's default (the default includes ML-KEM from Go 1.24).

## What TLS endpoints outside tests and docs get

Explicit settings and TLS configurations with no setting (where the product default decides) together. Go `tls.Config` values include clients as well as servers:

| Outcome | Findings |
|---|---|
| On if built with Go 1.24 or newer | 126 |
| Depends on the TLS library version | 33 |
| Unknown (template or variable) | 27 |
| Off: pinned to classical groups | 12 |
| Off: product default has no ML-KEM | 5 |
| Post-quantum negotiated | 1 |

## Explicit settings by product

| Product | pq_enabled | pq_excluded | draft_only | auto | unresolved | pq_mesh_policy | Default without a setting |
|---|---|---|---|---|---|---|---|
| apache | 0 | 1 | 0 | 0 | 0 | 0 | depends on OpenSSL (3.5+: on) |
| aws-elb | 0 | 21 | 0 | 0 | 1 | 0 | off from API/IaC (on in the console) |
| envoy | 1 | 0 | 0 | 0 | 0 | 0 | off |
| envoy-gateway | 2 | 12 | 0 | 0 | 36 | 0 | off |
| go | 7 | 10 | 0 | 0 | 36 | 0 | on (Go 1.24+) |
| istio | 0 | 0 | 0 | 0 | 0 | 3 | off |
| nginx | 0 | 2 | 0 | 0 | 1 | 0 | depends on OpenSSL (3.5+: on) |
| traefik | 0 | 3 | 0 | 0 | 11 | 0 | on (built with Go 1.24+) |

## Explicit settings by file category

Categories come from the file path (tests/, docs/, examples/, charts/ ...).

| Category | pq_enabled | pq_excluded | draft_only | auto | unresolved | pq_mesh_policy |
|---|---|---|---|---|---|---|
| chart | 0 | 0 | 0 | 0 | 1 | 0 |
| deploy | 0 | 3 | 0 | 0 | 1 | 0 |
| docs | 1 | 10 | 0 | 0 | 7 | 0 |
| example | 0 | 2 | 0 | 0 | 0 | 0 |
| source | 1 | 7 | 0 | 0 | 24 | 0 |
| test | 8 | 27 | 0 | 0 | 52 | 3 |

## Per repository

| Repository | Kind | Commit | Files | Explicit | PQ on | Pinned classical | No setting |
|---|---|---|---|---|---|---|---|
| envoyproxy/envoy | proxy | `37b20cf873b4` | 1785 | 1 | 1 | 0 | 26 |
| envoyproxy/gateway | gateway | `3e91fbc9781c` | 7148 | 44 | 0 | 9 | 53 |
| istio/istio | mesh | `c533e83a50a3` | 5635 | 23 | 10 | 6 | 25 |
| cilium/cilium | mesh | `00354062bc9e` | 7130 | 4 | 0 | 4 | 34 |
| hashicorp/consul | mesh | `c711a9f2bab4` | 2870 | 1 | 0 | 0 | 8 |
| emissary-ingress/emissary | gateway | `00def85caebb` | 1028 | 1 | 0 | 0 | 9 |
| projectcontour/contour | gateway | `aa8615298f19` | 2554 | 0 | 0 | 0 | 4 |
| kgateway-dev/kgateway | gateway | `1989318ba332` | 2682 | 7 | 2 | 3 | 56 |
| apache/apisix | gateway | `77055643b8db` | 710 | 0 | 0 | 0 | 3 |
| traefik/traefik | proxy | `e237cc4e64db` | 2028 | 17 | 0 | 2 | 8 |
| caddyserver/caddy | proxy | `f4d9826bf2a1` | 722 | 3 | 0 | 0 | 3 |
| kubernetes/ingress-nginx | ingress | `dbb11b92ddb7` | 912 | 1 | 0 | 0 | 17 |
| nginx/kubernetes-ingress | ingress | `4d69ce362b71` | 1972 | 0 | 0 | 0 | 27 |
| haproxytech/kubernetes-ingress | ingress | `60ac0251db88` | 695 | 0 | 0 | 0 | 1 |
| Kong/kubernetes-ingress-controller | ingress | `5fa96bf06f2f` | 898 | 0 | 0 | 0 | 6 |
| bitnami/charts | chart | `893617002038` | 3859 | 0 | 0 | 0 | 2 |
| prometheus-community/helm-charts | chart | `4384d7213121` | 1123 | 0 | 0 | 0 | 0 |
| grafana/helm-charts | chart | `80d6bc92a466` | 463 | 0 | 0 | 0 | 0 |
| argoproj/argo-helm | chart | `c8930a23d8ab` | 324 | 0 | 0 | 0 | 0 |
| traefik/traefik-helm-chart | chart | `419535d48b0c` | 160 | 5 | 0 | 1 | 0 |
| haproxytech/helm-charts | chart | `aeac27a9040a` | 185 | 0 | 0 | 0 | 1 |
| Kong/charts | chart | `7f0ed3cf6476` | 305 | 0 | 0 | 0 | 0 |
| mozilla/ssl-config-generator | template | `99178dcaf7e1` | 15 | 0 | 0 | 0 | 0 |
| h5bp/server-configs-nginx | template | `d2f2c3e2fac7` | 41 | 2 | 0 | 2 | 4 |
| h5bp/server-configs-apache | template | `f9feb463fe13` | 54 | 0 | 0 | 0 | 2 |
| nginx-proxy/nginx-proxy | template | `bff2cddfece8` | 154 | 0 | 0 | 0 | 3 |
| linuxserver/docker-swag | template | `24000edb531a` | 12 | 0 | 0 | 0 | 0 |
| NginxProxyManager/nginx-proxy-manager | template | `ea7e7468dfa6` | 406 | 0 | 0 | 0 | 3 |
| certbot/certbot | template | `138defe9c7c6` | 424 | 1 | 0 | 1 | 23 |
| kubernetes/kubernetes | infra | `671745e4ffcf` | 21831 | 6 | 0 | 0 | 31 |
| etcd-io/etcd | infra | `cda871cc9521` | 1212 | 0 | 0 | 0 | 5 |
| hashicorp/vault | infra | `81bb5d42e1ff` | 5800 | 0 | 0 | 0 | 27 |
| prometheus/prometheus | infra | `62aca1806f5b` | 1272 | 0 | 0 | 0 | 0 |
| minio/minio | infra | `7aac2a2c5b7c` | 1052 | 9 | 0 | 0 | 8 |
| cert-manager/cert-manager | infra | `8a358469e26a` | 1099 | 0 | 0 | 0 | 5 |
| terraform-aws-modules/terraform-aws-alb | iac | `6c6e48c10d45` | 44 | 6 | 0 | 6 | 0 |
| kubernetes-sigs/aws-load-balancer-controller | iac | `46813afa652c` | 989 | 16 | 0 | 15 | 7 |

## Examples of pinned classical lists outside tests and docs

* [istio/istio/pkg/model/fips.go:61](https://github.com/istio/istio/blob/c533e83a50a37fcb47a535c4fb66679fcd963b71/pkg/model/fips.go#L61) · go · `gotls.CurveP256`
* [istio/istio/pkg/model/fips.go:75](https://github.com/istio/istio/blob/c533e83a50a37fcb47a535c4fb66679fcd963b71/pkg/model/fips.go#L75) · go · `gotls.CurveP256 gotls.CurveP384`
* [cilium/cilium/api/v1/server/server.go:511](https://github.com/cilium/cilium/blob/00354062bc9e4197116db27ed6c3feb03aca0543/api/v1/server/server.go#L511) · go · `tls.CurveP256`
* [h5bp/server-configs-nginx/h5bp/tls/policy_balanced.conf:20](https://github.com/h5bp/server-configs-nginx/blob/d2f2c3e2fac76f429adb738894499b8fb756d2f3/h5bp/tls/policy_balanced.conf#L20) · nginx · `X25519 prime256v1 secp521r1 secp384r1`
* [h5bp/server-configs-nginx/h5bp/tls/policy_strict.conf:47](https://github.com/h5bp/server-configs-nginx/blob/d2f2c3e2fac76f429adb738894499b8fb756d2f3/h5bp/tls/policy_strict.conf#L47) · nginx · `X25519`
* [certbot/certbot/certbot/src/certbot/_internal/plugins/apache/tls_configs/current-options-ssl-apache.conf:11](https://github.com/certbot/certbot/blob/138defe9c7c68ceb29a66cbd5f3a346567139211/certbot/src/certbot/_internal/plugins/apache/tls_configs/current-options-ssl-apache.conf#L11) · apache · `X25519 prime256v1 secp384r1`
* [terraform-aws-modules/terraform-aws-alb/examples/mutual-auth-alb/main.tf:83](https://github.com/terraform-aws-modules/terraform-aws-alb/blob/6c6e48c10d450d01cf6715346e926df0b858efc2/examples/mutual-auth-alb/main.tf#L83) · aws-elb · `ELBSecurityPolicy-TLS13-1-2-Res-2021-06`
* [kubernetes-sigs/aws-load-balancer-controller/pkg/config/controller_config.go:49](https://github.com/kubernetes-sigs/aws-load-balancer-controller/blob/46813afa652c390e6c3d8410b42f26e4fb371c55/pkg/config/controller_config.go#L49) · aws-elb · `ELBSecurityPolicy-2016-08`

## Copied from an older guideline

Mozilla's TLS guideline 6.0 recommends modern: `X25519MLKEM768:X25519:prime256v1:secp384r1`; intermediate: `X25519MLKEM768:X25519:prime256v1:secp384r1`. Pinned lists that are identical to an earlier Mozilla recommendation were most likely copied from it and never updated:

* [certbot/certbot/certbot/src/certbot/_internal/plugins/apache/tls_configs/current-options-ssl-apache.conf:11](https://github.com/certbot/certbot/blob/138defe9c7c68ceb29a66cbd5f3a346567139211/certbot/src/certbot/_internal/plugins/apache/tls_configs/current-options-ssl-apache.conf#L11) · `X25519 prime256v1 secp384r1` = Mozilla 5.7 intermediate / Mozilla 5.7 old

## Product defaults used

| Product | Without a setting | Source |
|---|---|---|
| envoy | off | https://github.com/envoyproxy/envoy/pull/44944 |
| envoy-gateway | off | https://github.com/envoyproxy/envoy/pull/44944 |
| istio | off | https://docs.redhat.com/en/documentation/red_hat_openshift_service_mesh/3.3/html/installing/ossm-pqc-install |
| go | on (Go 1.24+) | https://github.com/golang/go/issues/69985 |
| caddy | on (built with Go 1.24+) | https://github.com/golang/go/issues/69985 |
| traefik | on (built with Go 1.24+) | https://github.com/golang/go/issues/69985 |
| nginx | depends on OpenSSL (3.5+: on) | https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/ |
| ingress-nginx | depends on OpenSSL (3.5+: on) | https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/ |
| haproxy | depends on OpenSSL (3.5+: on) | https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/ |
| apache | depends on OpenSSL (3.5+: on) | https://gixy.getpagespeed.com/checks/ssl-ecdh-curve/ |
| aws-elb | off from API/IaC (on in the console) | https://docs.aws.amazon.com/elasticloadbalancing/latest/application/describe-ssl-policies.html |

## Limits

* The scanner reads text. It does not render Helm templates or resolve variables, so templated values are counted as unresolved and left out of the percentages.
* A setting in a repository is not a running server. The study measures what people are given to copy, and the companion live measurement (Discovery) measures what servers negotiate.
* Go and Go-based products switch ML-KEM on by default only when built with Go 1.24 or newer; the scan cannot see the toolchain a binary was built with.
* File categories are inferred from paths and can be wrong for unusual layouts.
