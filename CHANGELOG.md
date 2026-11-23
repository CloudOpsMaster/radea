# Changelog

## 0.3.0rc1

### Added
- Deterministic reviews that use no model and no network: `k8s-review` (Kubernetes manifests
  and Helm chart sources), `dockerfile-review`, `ci-review` (GitHub Actions and GitLab CI),
  `tf-review`, `vuln-triage` (Grype/Trivy), `flaky` (JUnit runs), `rightsize`, `changelog`
  and `rules`. 67 rules, each traced to the article it implements; see `docs/static-review.md`
  and the generated `docs/rules.md`.
- 28 more offline failure signatures for `debug` and `triage` (image pull, scheduling, eviction,
  SIGKILL, RBAC, missing CRD, TLS, DNS, disk, Git and registry authentication, runner
  failures, Helm release failures and more). Symptoms no longer conflict with the category.
- `RADEA_INTERNAL_DOMAINS` to alias organisation-specific hostnames.
- PyYAML as a runtime dependency (`safe_load` semantics only); lock files regenerated.
- mypy runs in CI; `docs/feature-matrix.uk.md` now covers all 80 articles.

### Security
- Sanitizer: GitLab, Slack, Stripe, npm, PyPI, Google, SendGrid and Docker tokens, bare JWTs,
  `.netrc` passwords, Azure/SAS keys, kubeconfig key data, zero-width and full-width
  obfuscation, sensitive key names in JSON.
- Sanitizer: fixed quadratic regex backtracking. One hostile 64 KiB line previously took
  minutes (8 KiB took about 3 s); it now takes about a second at worst.
- Model output: unknown fields inside `hypotheses`, `findings`, `patterns` and `timeline`
  entries are now discarded, not only at the top level.
- The `internal_host` rule no longer mangles public hosts such as `corp-example.net`.

### Fixed
- mypy errors in provider diagnostics, packaged data access and PR comment validation.
- Own workflows now declare job timeouts and pass `ci-review`.

## 0.2.0rc1

Initial public release candidate of RADEA.
