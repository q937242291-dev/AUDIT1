# Executable schema fixture

trace_snapshot.json is a small fictional input for checking installation and
the nine-condition code contract. It is not experimental data, model output,
or a benchmark result. It deliberately has no fabricated usage or repair labels.

~~~sh
audit-framework ablate --snapshot examples/trace_snapshot.json --out outputs/example_grid.json
~~~

All nine results share the same snapshot digest and module-output digest.
Only the enabled module set or controller changes. Inspect those fields before
using real agent-visible snapshots.
