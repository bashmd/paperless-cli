## pcli

Paperless CLI focused on predictable, LLM-friendly retrieval and management.

## Install (uv)

Install globally (puts `pcli` in `~/.local/bin` on typical uv setups):

```bash
uv tool install --from <repo-path-or-git-url> pcli
```

Examples:

```bash
uv tool install --from . pcli
uv tool install --from git+https://github.com/<org>/<repo>.git pcli
```

If you want an install command via `uvx`:

```bash
uvx --from <repo-path-or-git-url> pcli install
```

This command infers its source when possible and runs `uv tool install --from ... pcli`.
For local development checkouts, prefer `uv tool install --from . pcli` (or use a committed/tagged git ref) so version-cached `uvx` runs do not execute stale builds.

Rust acceleration:

```bash
pcli install from=<repo-path-or-git-url> rust=auto
```

`rust=auto` (default) tries to build/install the optional `pcli_rust_norm` extension when `cargo`/`rustc` are available, and falls back to Python otherwise.

## Upgrade

```bash
uv tool install --from <repo-path-or-git-url> pcli --reinstall
```

## Verify

```bash
pcli --version
pcli --help
```
