# Paperless schema concurrency fix

Deployment-specific fix for Paperless-ngx **2.20.10**, using
drf-spectacular **0.28.0**. It changes the server, not pcli. No request
serialization, retries, schema cache, or reduction in worker/thread count.

## What Changes

drf-spectacular reuses class-level schema inspectors for views without a
method-level schema override. Concurrent schema generation mutates the same
inspector's view and component registry, causing both the missing-view assertion
and the `component.schema is None` error.

The patch shallow-copies the inspector onto each generated view. It also backports
drf-spectacular 0.30's generator-owned inspector storage and weak proxies, so
DRF's class-level descriptor does not accumulate views from completed requests.
Method-specific inspectors use that lifecycle too.

This fixes the two reproduced races, not a blanket thread-safety guarantee for
every drf-spectacular extension or configuration.

## Build And Use

Copy this directory alongside the deployment's Compose file, then set the
existing webserver service's image/build settings:

```yaml
services:
  webserver:
    image: paperless-ngx-local:2.20.10-schema-isolation-v1
    build: ./schema-isolation
    # Keep all existing environment, volume, network, and other service settings.
```

Build before restarting, using your existing Compose project name:

```sh
sudo docker compose --compatibility -p paperless build webserver
sudo docker compose --compatibility -p paperless up -d \
  --no-deps --no-build --pull never --timeout 60 \
  --wait --wait-timeout 180 webserver
```

The Dockerfile pins the exact original image digest. The patcher checks the
original source SHA-256 and fails the build if the source differs. It installs no
packages and changes only `drf_spectacular/generators.py`.

**Upgrades are deliberate:** pulling `latest` will not update this deployment.
Before upgrading Paperless, retest the fix against the new dependency version,
update the pinned image and patch guard, and build a new versioned local tag.
Do not just disable the hash check.

## Regression Tests

Run from the pcli repository in a separate test environment, never against the
server's installed packages:

```sh
uv venv --python 3.12 /tmp/pcli-schema-tests
uv pip install --python /tmp/pcli-schema-tests/bin/python \
  'Django==5.2.7' 'djangorestframework==3.16.1' \
  'drf-spectacular==0.28.0' 'pytest>=8,<9'
/tmp/pcli-schema-tests/bin/python deployment/schema-isolation/patch.py
/tmp/pcli-schema-tests/bin/python -m pytest \
  deployment/schema-isolation/test_schema_race.py -q
/tmp/pcli-schema-tests/bin/python deployment/schema-isolation/stress_schema.py
```

The patcher is intentionally one-shot: use a fresh environment to repeat it.
Tests require no database, credentials, documents, or running Paperless server.

- Nine tests cover both event-scheduled races and view retention, each with
  class-decorated, explicitly assigned, and default schema inspectors.
- The stress test checks complete schema equality for 100 sequential and 400
  concurrent generations on eight threads; failures exit nonzero.
- Deployment validation: before patching, 4/16 identical concurrent live schema
  requests returned HTTP 500. After patching, 64/64 succeeded with schemas exactly
  matching the sequential baseline.
- Eight concurrent pcli invocations (four at a time) successfully initialized and
  listed tags. The selected upstream 0.28.0 regression suites passed 209 tests.

## Rollback

The deployed installation has an original configuration backup under `backups/`
and a valid, pinned-base rollback file at `schema-isolation/rollback.compose.yml`.
Those deployment-specific files contain configuration and are **not** in this
repository. From the deployment directory:

```sh
cp docker-compose.yml schema-isolation/patched.compose.yml
cp schema-isolation/rollback.compose.yml docker-compose.yml
sudo docker compose --compatibility -p paperless up -d \
  --no-deps --no-build --pull never --timeout 60 \
  --wait --wait-timeout 180 webserver
```

This restores the original application image without changing volumes or
restarting PostgreSQL/Redis. Do not use `compose down` or delete volumes.
