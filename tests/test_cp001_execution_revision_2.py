import hashlib
import json
from pathlib import Path


def test_cp001_execution_revision_2_is_self_verifying():
    artifact = json.loads(Path(
        "experiments/CP-001-execution-revision-2.json"
    ).read_text())
    payload = json.dumps(
        artifact["specification"], sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode()
    assert hashlib.sha256(payload).hexdigest() == artifact["revision_fingerprint"]
    specification = artifact["specification"]
    implementation = specification["optimized_implementation"]
    items = []
    for filename, expected in sorted(implementation["implementation_files"].items()):
        actual = hashlib.sha256(Path(filename).read_bytes()).hexdigest()
        assert actual == expected, filename
        items.append({"path": filename, "sha256": actual})
    encoded = json.dumps(items, sort_keys=True, separators=(",", ":")).encode()
    assert hashlib.sha256(encoded).hexdigest() == \
        implementation["implementation_content_sha256"]
    equivalence = specification["behavioral_equivalence"]
    assert hashlib.sha256(Path(equivalence["test_file"]).read_bytes()).hexdigest() == \
        equivalence["test_file_sha256"]
    for key in ("original_baseline", "previous_execution_revision"):
        identity = specification[key]
        assert hashlib.sha256(Path(identity["artifact"]).read_bytes()).hexdigest() == \
            identity["artifact_file_sha256"]
