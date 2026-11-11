"""Load frozen, piece-disjoint collections of direct PianoVAM tasks."""

from dataclasses import dataclass
from functools import cached_property
import hashlib
import json
from pathlib import Path

from .pianovam_tasks import PianoVamTaskSet, load_task_set

MANIFEST_FORMAT = "piano_rl_tasks_manifest/2"
SPLIT_PHASE = {"train": "train", "ext-train": "train", "valid": "valid", "test": "test"}


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def metadata_recordings(path):
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(document, dict) or not document:
        raise ValueError("metadata must be a non-empty mapping")
    recordings = {}
    for entry in document.values():
        if (not isinstance(entry, dict) or not isinstance(entry.get("record_time"), str)
                or not entry["record_time"]):
            raise ValueError("each metadata entry must identify its recording")
        name = entry["record_time"]
        if name in recordings:
            raise ValueError(f"duplicate metadata recording {name}")
        recordings[name] = entry
    return recordings


def piece_identity(entry):
    composer = entry.get("composer")
    piece = entry.get("piece")
    if not all(isinstance(value, str) and value.strip() for value in (composer, piece)):
        raise ValueError("composer and piece are required for piece-disjoint splits")
    return composer.strip(), piece.strip()


def verify_split_isolation(entries):
    """Require each recording, source digest and piece to identify one phase."""
    recordings = set()
    digests = set()
    pieces = {}
    for split, recording, digest, composer, piece in entries:
        if recording in recordings or digest in digests:
            raise ValueError(f"duplicate recording or source content: {recording}")
        recordings.add(recording)
        digests.add(digest)
        key = tuple(" ".join(value.casefold().split()) for value in (composer, piece))
        phase = SPLIT_PHASE[split]
        if pieces.setdefault(key, phase) != phase:
            raise ValueError(f"piece crosses training/validation/test splits: {composer} / {piece}")


@dataclass(frozen=True)
class RecordingTasks:
    recording: str
    composer: str
    piece: str
    task_set: PianoVamTaskSet


@dataclass(frozen=True)
class PianoVamCorpus:
    recordings: tuple[RecordingTasks, ...]

    @cached_property
    def tasks(self):
        return tuple(task for source in self.recordings for task in source.task_set.tasks)

    @property
    def task_count(self):
        return len(self.tasks)

    @cached_property
    def recording_indices(self):
        groups = []
        start = 0
        for source in self.recordings:
            end = start + source.task_set.task_count
            groups.append(range(start, end))
            start = end
        return tuple(groups)

    @cached_property
    def task_recordings(self):
        return tuple(source for source in self.recordings for _ in source.task_set.tasks)


def _inside(base, value):
    path = (base / value).resolve()
    if not path.is_relative_to(base):
        raise ValueError(f"manifest file is outside {base}: {value}")
    return path


def load_corpus_manifest(path):
    """Verify input hashes and split identities before building any environment."""
    path = Path(path).resolve()
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("format") != MANIFEST_FORMAT:
        raise ValueError(f"expected {MANIFEST_FORMAT}, regenerate the task manifest")
    if not isinstance(document.get("splits"), dict):
        raise ValueError("manifest splits must be a mapping")
    dataset = (path.parent / document["dataset"]).resolve()
    metadata = (path.parent / document["metadata"]).resolve()
    if sha256(metadata) != document["metadata_sha256"]:
        raise ValueError("dataset metadata checksum changed")
    recordings = metadata_recordings(metadata)
    by_phase = {phase: [] for phase in SPLIT_PHASE.values()}
    identities = []
    for split, entries in document["splits"].items():
        if split not in SPLIT_PHASE or not isinstance(entries, list):
            raise ValueError(f"invalid manifest split: {split}")
        for entry in entries:
            if not isinstance(entry, dict):
                raise ValueError("manifest recording entry must be a mapping")
            source = _inside(dataset, entry["source"])
            task_path = _inside(path.parent, entry["tasks"])
            recording = source.stem
            record = recordings.get(recording)
            if not record or record.get("split") != split or entry["recording"] != recording:
                raise ValueError(f"recording metadata does not match split: {recording}")
            composer, piece = piece_identity(record)
            if (entry["composer"], entry["piece"]) != (composer, piece):
                raise ValueError(f"piece metadata changed: {recording}")
            digest = entry["source_sha256"]
            if sha256(source) != digest or sha256(task_path) != entry["tasks_sha256"]:
                raise ValueError(f"source or task checksum changed: {recording}")
            task_set = load_task_set(task_path)
            if (task_set.split != split or task_set.source_sha256 != digest
                    or Path(task_set.source).name != source.name
                    or not task_set.task_count or task_set.task_count != entry["task_count"]):
                raise ValueError(f"task provenance does not match manifest: {recording}")
            if any(event.start_sec < task.origin_sec
                   for task in task_set.tasks for event in task.events):
                raise ValueError(f"corpus tasks must start without held notes: {recording}")
            identities.append((split, recording, digest, composer, piece))
            by_phase[SPLIT_PHASE[split]].append(
                RecordingTasks(recording, composer, piece, task_set))
    verify_split_isolation(identities)
    return {phase: PianoVamCorpus(tuple(sources)) for phase, sources in by_phase.items()}
