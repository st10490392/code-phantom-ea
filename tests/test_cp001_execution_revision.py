import hashlib
import json
from pathlib import Path


def test_cp001_execution_revision_is_self_verifying_and_preserves_baseline():
    path = Path("experiments/CP-001-execution-revision-1.json")
    artifact = json.loads(path.read_text())
    payload = json.dumps(
        artifact["specification"], sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert hashlib.sha256(payload).hexdigest() == artifact["revision_fingerprint"]

    specification = artifact["specification"]
    optimized = specification["optimized_implementation"]
    items = []
    for filename, expected in sorted(optimized["implementation_files"].items()):
        actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        assert actual == expected, filename
        items.append({"path": filename, "sha256": actual})
    encoded = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == \
        optimized["implementation_content_sha256"]

    equivalence = specification["behavioral_equivalence"]
    assert hashlib.sha256(Path(equivalence["test_file"]).read_bytes()).hexdigest() == \
        equivalence["test_file_sha256"]

    baseline = specification["original_baseline"]
    baseline_bytes = Path(baseline["artifact"]).read_bytes()
    assert hashlib.sha256(baseline_bytes).hexdigest() == \
        baseline["artifact_file_sha256"]
    frozen = json.loads(baseline_bytes)
    assert frozen["freeze_fingerprint"] == baseline["freeze_fingerprint"]
