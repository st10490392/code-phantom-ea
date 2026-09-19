"""Deterministic streaming CSV with canonical provenance manifests."""
import csv
from dataclasses import asdict, fields, is_dataclass
import hashlib
import io
import json
from pathlib import Path


def canonical(value):
    if is_dataclass(value):
        value = asdict(value)
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=True, allow_nan=False)


def fingerprint(value):
    return hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def implementation_identity():
    root = Path(__file__).resolve().parents[1]
    paths = ("research/__init__.py", "research/observer.py", "research/labels.py",
             "research/storage.py")
    return {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in paths}


def export_dataset(records, directory, *, record_type, source_fingerprint,
                   engine_identity, configuration_identity, population,
                   observation_dataset_fingerprint=None):
    """Rows must be ordered by (instrument, execution_index), without duplicates.

    CSV cells are canonical JSON values, preserving null/bool/tuple/reference
    types. Features and labels must be exported as separate typed datasets.
    No wall-clock timestamps or absolute paths enter the fingerprint.
    """
    from research.observer import ObservationRecord, SCHEMA_VERSION
    from research.labels import FutureLabel, LABEL_SCHEMA_VERSION
    if record_type not in (ObservationRecord, FutureLabel):
        raise TypeError("unsupported record schema")
    for value in (source_fingerprint, engine_identity, configuration_identity):
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("canonical sha256 identities required")
    if record_type is FutureLabel and not observation_dataset_fingerprint:
        raise ValueError("labels require parent observation dataset fingerprint")
    if record_type is ObservationRecord and observation_dataset_fingerprint is not None:
        raise ValueError("features cannot depend on a label/parent dataset")
    if population not in ("eligible", "all_completed", "offline_labels"):
        raise ValueError("explicit population required")
    if (record_type is FutureLabel) != (population == "offline_labels"):
        raise ValueError("population/schema mismatch")
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    table = directory / "rows.csv"
    manifest_path = directory / "manifest.json"
    if table.exists() or manifest_path.exists():
        raise FileExistsError("export destinations must be new; frozen datasets are not overwritten")
    names = [f.name for f in fields(record_type)]
    digest = hashlib.sha256()
    count = 0
    previous = None
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    with table.open("xb") as stream:
        def emit(values):
            writer.writerow(values)
            encoded = buffer.getvalue().encode("utf-8")
            stream.write(encoded)
            digest.update(encoded)
            buffer.seek(0)
            buffer.truncate(0)
        emit(names)
        for record in records:
            if type(record) is not record_type:
                raise TypeError("feature/label schema mixing forbidden")
            key = (record.instrument, record.execution_index)
            if previous is not None and key <= previous:
                raise ValueError("rows must be strictly ordered and unique")
            previous = key
            payload = asdict(record)
            emit([canonical(payload[name]) for name in names])
            count += 1
    payload = {
        "schema_version": SCHEMA_VERSION if record_type is ObservationRecord else LABEL_SCHEMA_VERSION,
        "source_dataset_fingerprint": source_fingerprint,
        "engine_execution_identity": engine_identity,
        "observer_implementation_files": implementation_identity(),
        "observer_implementation_identity": fingerprint(implementation_identity()),
        "configuration_identity": configuration_identity,
        "population": population,
        "row_count": count,
        "fields": names,
        "csv_sha256": digest.hexdigest(),
        "cell_encoding": "canonical JSON; CSV UTF-8, LF, schema field order",
        "observation_dataset_fingerprint": observation_dataset_fingerprint,
    }
    manifest = {"dataset": payload, "dataset_fingerprint": fingerprint(payload)}
    manifest_path.write_text(canonical(manifest) + "\n", encoding="utf-8")
    return manifest


def verify_export(directory):
    directory = Path(directory)
    manifest = json.loads((directory / "manifest.json").read_text())
    if fingerprint(manifest["dataset"]) != manifest["dataset_fingerprint"]:
        raise ValueError("manifest fingerprint mismatch")
    digest = hashlib.sha256()
    with (directory / "rows.csv").open("rb") as stream:
        for chunk in iter(lambda: stream.read(65536), b""):
            digest.update(chunk)
    if digest.hexdigest() != manifest["dataset"]["csv_sha256"]:
        raise ValueError("table fingerprint mismatch")
    with (directory / "rows.csv").open(newline="", encoding="utf-8") as stream:
        reader = csv.reader(stream)
        if next(reader) != manifest["dataset"]["fields"]:
            raise ValueError("schema header mismatch")
        if sum(1 for _ in reader) != manifest["dataset"]["row_count"]:
            raise ValueError("row count mismatch")
    return manifest


def read_dataset(directory, *, record_type):
    """Verify a frozen export, then reconstruct immutable typed rows offline."""
    from research.observer import (EventRef, LiquidityRef, ObservationRecord, PDRef, SCHEMA_VERSION,
                                   SwingRef)
    from research.labels import FutureLabel, LABEL_SCHEMA_VERSION
    manifest = verify_export(directory)
    expected = {ObservationRecord: SCHEMA_VERSION, FutureLabel: LABEL_SCHEMA_VERSION}
    if record_type not in expected or manifest['dataset']['schema_version'] != expected[record_type]:
        raise TypeError("dataset/schema mismatch")
    if manifest['dataset']['fields'] != [f.name for f in fields(record_type)]:
        raise ValueError("unsupported schema fields")
    with (Path(directory)/'rows.csv').open(newline='',encoding='utf-8') as stream:
        for raw in csv.DictReader(stream):
            row = {key: json.loads(value) for key,value in raw.items()}
            if record_type is ObservationRecord:
                for name in ('h4_event','latest_bullish_mss','latest_bearish_mss'):
                    row[name] = EventRef(**row[name]) if row[name] else None
                for name in ('protected_high','protected_low'):
                    row[name] = SwingRef(**row[name]) if row[name] else None
                for name in ('latest_bullish_pd','latest_bearish_pd'):
                    row[name] = PDRef(**row[name]) if row[name] else None
                for name in ('latest_bullish_liquidity','latest_bearish_liquidity'):
                    row[name] = LiquidityRef(**row[name]) if row[name] else None
                for name in ('current_bos','current_mss'):
                    row[name] = tuple(EventRef(**e) for e in row[name])
                for name in ('gate_passes','missing_gates'):
                    row[name] = tuple(row[name])
            yield record_type(**row)
