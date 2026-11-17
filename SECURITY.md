# Security policy

RADEA is an early 0.1 project. Security fixes target the latest source and release.

Do not include credentials, private logs or exploitable vulnerability details in
public issues. Use [private vulnerability reporting](https://github.com/CloudOpsMaster/radea/security/advisories/new)
or contact a maintainer privately. No dedicated security
email address is currently published by this project.

Redaction is best effort. Review sensitive inputs before using a remote provider.
Logs, Terraform, model output and incident data are untrusted. Never execute
model suggestions without reviewing them. RADEA does not provide an OS sandbox
for external CLI providers; its Kiro profile disables tools and runs outside the
project working directory. Authentication and global CLI configuration remain
under the runner administrator's control.

CI includes regression tests, pip-audit and Bandit. These checks do not establish
that all secrets or vulnerabilities have been detected.
