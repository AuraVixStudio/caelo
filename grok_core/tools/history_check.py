"""Self-check magazynu huba (M9-B1) — bez sieci xAI.

Magazyn `grok_core/history_store.py` (SQLite + FTS5): artefakty + zdarzenia historii.
Asercje wg DoD/selfcheck z `docs/PLAN_M9_SZKIELET.md`:

1) Roundtrip artefaktu: insert -> get po id (treść + meta zachowane).
2) FTS: zdarzenie historii jest znajdowane po treści (też UTF-8 / polskie znaki).
3) Filtry: `mode`/`project_id`/zakres czasu zawężają poprawnie.
4) Trwałość: dane przeżywają „restart sidecara" (close + ponowne otwarcie tej samej bazy).
5) Ścieżka bazy faktycznie pod `config.DATA_DIR` (brak ucieczki), IS_FROZEN-aware stała.
6) Korupcja: uszkodzony plik -> backup `.corrupt` (zachowany), świeża baza działa (nie wipe).
7) Sanitizer FTS: dowolny tekst użytkownika (samotny `"`, operatory) nie wywala MATCH.

Kod wyjścia 0 = wszystkie asercje OK.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import config  # noqa: E402
from grok_core.history_store import HistoryStore, _fts_query  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def _tmp() -> tempfile.TemporaryDirectory:
    # ignore_cleanup_errors: na Windows pliki -wal/-shm bywają jeszcze zablokowane
    return tempfile.TemporaryDirectory(ignore_cleanup_errors=True)


def test_artifact_roundtrip() -> None:
    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            art = store.add_artifact(
                type="image", mode="image", mime="image/png",
                path="generated_history/x.png",
                meta={"prompt": "neon cyberpunk city", "model": "grok-imagine-image"},
            )
            check("artifact: id assigned", bool(art.id))
            got = store.get_artifact(art.id)
            check("artifact: get by id", got is not None and got.id == art.id)
            check("artifact: fields preserved",
                  got.type == "image" and got.mime == "image/png"
                  and got.path == "generated_history/x.png")
            check("artifact: meta json roundtrip",
                  got.meta.get("prompt") == "neon cyberpunk city"
                  and got.meta.get("model") == "grok-imagine-image")
            check("artifact: missing id -> None", store.get_artifact("nope") is None)

            store.add_artifact(type="text", mode="chat", project_id="p1")
            check("artifact: list filter by mode",
                  [a.mode for a in store.list_artifacts(mode="image")] == ["image"])
        finally:
            store.close()


def test_event_fts() -> None:
    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            store.record_event(mode="image", text="neon cyberpunk city at night",
                               meta={"prompt": "neon cyberpunk city at night"})
            store.record_event(mode="chat", text="a quiet meadow with flowers")
            store.record_event(mode="voice", text="zażółć gęślą jaźń po polsku")

            hits = store.list_events(q="cyberpunk")
            check("fts: finds by content word",
                  len(hits) == 1 and hits[0].mode == "image")
            check("fts: ranking returns the match",
                  any("cyberpunk" in h.text for h in hits))

            none = store.list_events(q="dragon")
            check("fts: no false hit", none == [])

            # UTF-8 / polskie znaki przeszukiwalne (konwencja UTF-8 repo)
            pl = store.list_events(q="gęślą")
            check("fts: utf-8 (polish) searchable",
                  len(pl) == 1 and "jaźń" in pl[0].text)

            # filtr mode łączy się z FTS
            both = store.list_events(q="city", mode="chat")
            check("fts: mode filter narrows", all(h.mode == "chat" for h in both))
        finally:
            store.close()


def test_event_filters_and_artifact_link() -> None:
    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            art = store.add_artifact(type="image", mode="image")
            store.record_event(mode="image", text="render one", artifact_id=art.id,
                               project_id="proj-A", created_at=1000.0)
            store.record_event(mode="chat", text="hello there",
                               project_id="proj-B", created_at=2000.0)

            a_only = store.list_events(project_id="proj-A")
            check("filter: project_id isolates",
                  len(a_only) == 1 and a_only[0].artifact_id == art.id)

            window = store.list_events(since=1500.0, until=2500.0)
            check("filter: time window", len(window) == 1 and window[0].text == "hello there")

            recent_first = store.list_events()
            check("list: newest first (created_at desc)",
                  [e.created_at for e in recent_first] == [2000.0, 1000.0])
        finally:
            store.close()


def test_persistence_across_restart() -> None:
    with _tmp() as d:
        path = Path(d) / "h.db"
        store = HistoryStore(path)
        art = store.add_artifact(type="video", mode="video", meta={"prompt": "ocean waves"})
        store.record_event(mode="video", text="ocean waves clip", artifact_id=art.id)
        store.close()

        # symulacja restartu sidecara: nowy obiekt na tej samej ścieżce
        reopened = HistoryStore(path)
        try:
            check("persist: artifact survives restart",
                  reopened.get_artifact(art.id) is not None)
            check("persist: event survives restart + FTS still works",
                  len(reopened.list_events(q="ocean")) == 1)
        finally:
            reopened.close()


def test_db_path_under_data_dir() -> None:
    db = Path(config.HISTORY_DB_FILE)
    data = Path(config.DATA_DIR)
    check("path: HISTORY_DB_FILE under DATA_DIR", db.resolve().is_relative_to(data.resolve()))
    check("path: filename is grok_history.db", db.name == "grok_history.db")
    check("path: no traversal in db path", ".." not in db.parts)


def test_corrupt_backup_not_wipe() -> None:
    with _tmp() as d:
        path = Path(d) / "h.db"
        garbage = b"this is definitely not a sqlite database \x00\x01\x02 zzz" * 8
        path.write_bytes(garbage)

        store = HistoryStore(path)  # powinno wykryć korupcję i zrobić backup
        try:
            backup = path.with_suffix(path.suffix + ".corrupt")
            check("corrupt: backup created", backup.exists())
            check("corrupt: backup preserves original bytes (no wipe)",
                  backup.exists() and backup.read_bytes() == garbage)
            # świeża baza działa
            art = store.add_artifact(type="text", mode="chat")
            check("corrupt: fresh db usable after backup",
                  store.get_artifact(art.id) is not None)
        finally:
            store.close()


def test_empty_file_is_valid_db() -> None:
    # 0-bajtowy plik to dla SQLite poprawna PUSTA baza (NIE korupcja) — nie rób backupu.
    with _tmp() as d:
        path = Path(d) / "h.db"
        path.write_bytes(b"")
        store = HistoryStore(path)
        try:
            check("empty file: treated as fresh db (no .corrupt)",
                  not path.with_suffix(path.suffix + ".corrupt").exists())
            art = store.add_artifact(type="text", mode="chat")
            check("empty file: usable", store.get_artifact(art.id) is not None)
        finally:
            store.close()


def test_fts_query_sanitizer() -> None:
    # Sanitizer nie może rzucać i ma izolować operatory/cudzysłowy.
    check("sanitizer: empty -> no-match token", _fts_query("   ") == '""')
    check("sanitizer: doubles embedded quote", _fts_query('a"b') == '"a""b"')
    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            store.record_event(mode="chat", text='he said "world" AND stayed')
            # surowy `"` lub operator NIE może wywalić MATCH
            raised = False
            try:
                store.list_events(q='"')
                store.list_events(q="AND OR *")
                hit = store.list_events(q="world")
            except Exception:
                raised = True
                hit = []
            check("sanitizer: weird query does not raise", not raised)
            check("sanitizer: still matches real token", len(hit) == 1)
        finally:
            store.close()


def main() -> int:
    test_artifact_roundtrip()
    test_event_fts()
    test_event_filters_and_artifact_link()
    test_persistence_across_restart()
    test_db_path_under_data_dir()
    test_corrupt_backup_not_wipe()
    test_empty_file_is_valid_db()
    test_fts_query_sanitizer()
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
