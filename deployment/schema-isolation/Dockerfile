# Exact production 2.20.10 base. Do not substitute a newer image without retesting.
FROM ghcr.io/paperless-ngx/paperless-ngx@sha256:07a0b4ba01ce377c82a0636e16c0c3d931fde5b7e9304de6601986cc42d9b6e6

LABEL local.paperless.schema-fix="per-view-inspector-isolation-028-v1"
COPY patch.py /tmp/paperless-schema-patch.py
RUN python /tmp/paperless-schema-patch.py && rm /tmp/paperless-schema-patch.py
