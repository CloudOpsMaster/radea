# Contributing

Use Python 3.10 or newer and install the development dependencies:

```sh
python -m venv .venv
. .venv/bin/activate
python -m pip install --require-hashes -r requirements-ci.lock
python -m pip install --no-deps --no-build-isolation -e .
python -m pytest
ruff check src tests
```

Keep changes focused and include regression tests for behavioral changes. Tests
must not require credentials, external inference or a GPU. Mock provider calls
at the SDK/process boundary and verify routing, error behavior and sanitization.
Use synthetic credentials in fixtures and never submit private logs or real keys.

Describe the problem, resulting behavior and checks performed in pull requests.
CI must pass before release. Repository maintainers must configure required
status checks separately in GitHub branch protection.
