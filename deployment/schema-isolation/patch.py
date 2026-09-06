"""Apply the narrowly versioned drf-spectacular 0.28.0 inspector isolation fix."""

import hashlib
import importlib.util
from pathlib import Path

EXPECTED_SHA256 = "e2c0f615c2c651276e48c4be9f4c910310080c5fb106cf9eaaf97a0cbaab1a8e"


def main():
    spec = importlib.util.find_spec("drf_spectacular")
    if spec is None or spec.origin is None:
        raise SystemExit("drf-spectacular is not installed")
    path = Path(spec.origin).with_name("generators.py")
    original = path.read_bytes()
    if hashlib.sha256(original).hexdigest() != EXPECTED_SHA256:
        raise SystemExit("Unexpected generators.py; refusing to patch a different source version")

    replacements = [
        ("import re\n", "import re\nimport weakref\nfrom copy import copy\n"),
        (
            "        self.inspector = None\n",
            "        self.inspector = None\n        self.schemas_storage = []\n",
        ),
        (
            "            # there is no method/action customized schema so we are done here.\n",
            "            # Class-level inspectors hold mutable per-generation state.\n"
            "            self._set_schema_to_view(view, copy(view.schema))\n",
        ),
        (
            "        view.schema = action_schema_class()\n",
            "        self._set_schema_to_view(view, action_schema_class())\n",
        ),
        (
            "    def _initialise_endpoints(self):\n",
            "    def _set_schema_to_view(self, view, schema):\n"
            "        # Backport the 0.30 lifecycle: descriptor values must not retain views.\n"
            "        view.schema = weakref.proxy(schema)\n"
            "        self.schemas_storage.append(schema)\n\n"
            "    def _initialise_endpoints(self):\n",
        ),
    ]
    patched = original.decode("utf-8")
    for before, after in replacements:
        if patched.count(before) != 1:
            raise SystemExit(f"Patch context is not unique: {before!r}")
        patched = patched.replace(before, after, 1)
    compile(patched, str(path), "exec")
    path.write_text(patched, encoding="utf-8")
    print(f"Patched {path}: sha256={hashlib.sha256(path.read_bytes()).hexdigest()}")


if __name__ == "__main__":
    main()
