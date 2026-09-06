"""Compare identical schema generations, sequentially and on eight threads."""

import json
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor

import drf_spectacular
from test_schema_race import generate, routes

patterns, _ = routes()
expected = generate(patterns)


def attempt(_):
    try:
        actual = generate(patterns)
        return "identical" if actual == expected else "different schema"
    except Exception as exc:
        return f"{type(exc).__name__}: {exc}"


sequential = Counter(map(attempt, range(100)))
# Increase opportunities for ordinary Python thread preemption. No monkeypatches,
# injected exceptions, artificial pauses, network, or database accesses.
sys.setswitchinterval(0.000001)
with ThreadPoolExecutor(max_workers=8) as pool:
    concurrent = Counter(pool.map(attempt, range(400)))
print(
    json.dumps(
        {
            "version": drf_spectacular.__version__,
            "module": drf_spectacular.__file__,
            "sequential": sequential,
            "concurrent": concurrent,
        },
        indent=2,
    )
)
if sequential != {"identical": 100} or concurrent != {"identical": 400}:
    sys.exit(1)
