"""Self-check magazynu huba (M9-B1) — bez sieci xAI.

Magazyn `caelo_core/history_store.py` (SQLite + FTS5): artefakty + zdarzenia historii.
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
import caelo_core.history_store as HS  # noqa: E402
from caelo_core.history_store import HistoryStore, _fts_query  # noqa: E402

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
    check("path: filename is caelo_history.db", db.name == "caelo_history.db")
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


def test_all_modes_land_and_fts() -> None:
    """B2: zdarzenie z KAŻDEGO trybu ląduje i jest znajdowane przez FTS."""
    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            samples = {
                "chat":  "chat about quantum entanglement",
                "image": "image of a violet nebula",
                "video": "video of cascading waterfalls",
                "voice": "voice memo about migration patterns",
                "code":  "code refactor of the parser module",
            }
            uniq = {"chat": "entanglement", "image": "nebula", "video": "waterfalls",
                    "voice": "migration", "code": "refactor"}
            for mode, text in samples.items():
                store.record_event(mode=mode, text=text)
            for mode, word in uniq.items():
                hits = store.list_events(q=word)
                check(f"all-modes: {mode} event lands + FTS-found",
                      len(hits) == 1 and hits[0].mode == mode)
        finally:
            store.close()


class _FakeHistory:
    """Atrapa legacy HistoryManager — neutralizuje zapis do caelo_config.json w teście."""
    def __init__(self, save_dir: str) -> None:
        self._dir = save_dir

    def get_save_path(self) -> str:
        return self._dir

    def save_to_history(self, mode, path, prompt) -> None:
        pass


def test_backend_wiring() -> None:
    """B2: Backend.record_event + ścieżka media (save_media_urls/bytes) trafiają do
    wspólnej historii huba. Magazyn podmieniony na temp; legacy history zatrapowany,
    by NIE dotknąć realnego caelo_config.json. Sieć wyłączona (download=False)."""
    from caelo_core.state import Backend  # import tu — pociąga state.py (legacy managery)

    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev = HS._default_store
        HS._default_store = store  # get_store() (i Backend.history_store) -> temp
        try:
            b = Backend()
            b.history = _FakeHistory(d)  # neutralizuj legacy zapis

            ev = b.record_event(mode="chat", text="hello about dragons and castles")
            check("backend: record_event lands", ev is not None)
            check("backend: chat event FTS-found",
                  len(store.list_events(q="dragons", mode="chat")) == 1)

            # media obraz: save_media_urls(download=False) -> artefakt image + event
            b.save_media_urls(["https://x.test/a.png"], "neon cyberpunk skyline",
                              "generate", ".png", download=False)
            img = store.list_events(q="cyberpunk", mode="image")
            check("backend: media image event recorded", len(img) == 1)
            check("backend: media event linked to artifact",
                  bool(img) and img[0].artifact_id is not None)
            art = store.get_artifact(img[0].artifact_id) if img else None
            check("backend: image artifact type/mime",
                  art is not None and art.type == "image" and art.mime == "image/png")
            check("backend: image artifact meta has prompt + url",
                  art is not None and art.meta.get("prompt") == "neon cyberpunk skyline"
                  and bool(art.meta.get("url")))

            # voice TTS bajty: save_media_bytes -> artefakt audio (mode=voice) + event
            b.save_media_bytes(b"\x00\x01fake-audio-bytes", "spoken note about whales",
                              "tts", ".mp3")
            voice = store.list_events(q="whales", mode="voice")
            check("backend: voice tts event recorded", len(voice) == 1)
            vart = store.get_artifact(voice[0].artifact_id) if voice else None
            check("backend: audio artifact type/mode",
                  vart is not None and vart.type == "audio" and vart.mode == "voice")
        finally:
            HS._default_store = prev
            store.close()


def test_input_blocks() -> None:
    """B4: artefakt -> blok wejściowy zgodny z typem (image->vision, pdf->document,
    text/code->text) + przypadki negatywne (poza sandboxem / brak pliku / nieobsługiwany)."""
    from caelo_core.routes import history as hist_route

    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        bases = [Path(d).resolve()]
        try:
            # image -> blok vision (image_url, data:image/...)
            (Path(d) / "pic.png").write_bytes(b"\x89PNG\r\n\x1a\nfake")
            img = store.add_artifact(type="image", mode="image", mime="image/png",
                                     path=str(Path(d) / "pic.png"))
            p = hist_route.build_input_payload(img, bases)
            check("input: image -> image_url block",
                  p["block"]["type"] == "image_url"
                  and p["block"]["image_url"]["url"].startswith("data:image/png;base64,"))
            check("input: image payload carries data_uri", bool(p.get("data_uri")))

            # pdf (type=file) -> blok document
            (Path(d) / "doc.pdf").write_bytes(b"%PDF-1.4 fake")
            pdf = store.add_artifact(type="file", mode="chat", mime="application/pdf",
                                     path=str(Path(d) / "doc.pdf"))
            p = hist_route.build_input_payload(pdf, bases)
            check("input: pdf -> document block",
                  p["block"]["type"] == "document"
                  and p["block"]["document"]["data"].startswith("data:application/pdf;base64,"))

            # text / code -> blok text (treść inline)
            (Path(d) / "note.txt").write_text("hello world text", encoding="utf-8")
            txt = store.add_artifact(type="text", mode="chat", mime="text/plain",
                                     path=str(Path(d) / "note.txt"))
            p = hist_route.build_input_payload(txt, bases)
            check("input: text -> text block",
                  p["block"]["type"] == "text" and p["block"]["text"] == "hello world text")

            (Path(d) / "main.py").write_text("def f():\n    return 1\n", encoding="utf-8")
            code = store.add_artifact(type="code", mode="code", mime="",
                                      path=str(Path(d) / "main.py"))
            p = hist_route.build_input_payload(code, bases)
            check("input: code -> text block", p["block"]["type"] == "text" and "def f()" in p["block"]["text"])

            # video -> brak bloku wejściowego (415)
            vid = store.add_artifact(type="video", mode="video", mime="video/mp4",
                                     path=str(Path(d) / "pic.png"))
            check("input: video -> 415 (no input block)",
                  _raises_status(lambda: hist_route.build_input_payload(vid, bases), 415))

            # ścieżka poza sandboxem -> 403
            outside = store.add_artifact(type="image", mode="image", mime="image/png",
                                         path=str(Path(d).resolve().parent / "evil.png"))
            check("input: path outside allowed -> 403",
                  _raises_status(lambda: hist_route.build_input_payload(outside, bases), 403))

            # plik nieistniejący (w sandboxie) -> 404
            gone = store.add_artifact(type="image", mode="image", mime="image/png",
                                      path=str(Path(d) / "nope.png"))
            check("input: missing file -> 404",
                  _raises_status(lambda: hist_route.build_input_payload(gone, bases), 404))
        finally:
            store.close()


def test_project_scoping() -> None:
    """B5: mechanizm projektów (add/ensure idempotent/list/by-root) + stemplowanie
    aktywnym projektem przez Backend + izolacja filtra project_id (zdarzenia i artefakty)."""
    from caelo_core.state import Backend

    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev = HS._default_store
        HS._default_store = store  # Backend.history_store -> temp
        try:
            # --- store: rekord projektu + idempotencja po root ---
            p1 = store.add_project(name="Alpha", root="/ws/alpha")
            again = store.ensure_project_for_root("/ws/alpha")
            check("project: ensure_for_root idempotent (same root)", again.id == p1.id)
            p2 = store.ensure_project_for_root("/ws/beta", name="Beta")
            check("project: new root creates project", p2.id != p1.id and p2.name == "Beta")
            check("project: list returns all", {p.id for p in store.list_projects()} == {p1.id, p2.id})
            check("project: get_by_root resolves", store.get_project_by_root("/ws/alpha").id == p1.id)
            check("project: get_by_root empty -> None", store.get_project_by_root("") is None)

            # --- Backend stempluje AKTYWNYM projektem (bez zapisu ustawień: __new__) ---
            b = Backend.__new__(Backend)
            b.history = None  # nieużywane w tej ścieżce
            b.current_project_id = p1.id
            b.record_event(mode="chat", text="alpha note about gravity")
            b.current_project_id = p2.id
            b.record_event(mode="chat", text="beta note about gravity")

            a_ev = store.list_events(project_id=p1.id)
            check("project: event stamped with active project",
                  len(a_ev) == 1 and "alpha" in a_ev[0].text)
            check("project: filter isolates events by project",
                  len(store.list_events(project_id=p2.id)) == 1)

            b.current_project_id = p1.id
            art = b.add_artifact(type="text", mode="chat")
            check("project: artifact stamped with active project",
                  store.get_artifact(art.id).project_id == p1.id)
            check("project: filter isolates artifacts by project",
                  [x.id for x in store.list_artifacts(project_id=p1.id)] == [art.id]
                  and store.list_artifacts(project_id=p2.id) == [])

            # explicit project_id wins over active
            b.record_event(mode="chat", text="explicit override", project_id=p2.id)
            check("project: explicit project_id overrides active",
                  any(e.text == "explicit override" for e in store.list_events(project_id=p2.id)))
        finally:
            HS._default_store = prev
            store.close()


def test_memory_knn_hybrid() -> None:
    """M19-B8: magazyn embeddingów + brute-force cosine KNN + hybryda FTS, oraz
    `MemoryIndex` ze STUB-embedderem (indeksowanie / recall / wstrzyknięcie / opt-in).
    Zero sieci — wektory wstrzykiwane wprost (xAI endpoint = osobny spike, live)."""
    from caelo_core.memory import MemoryIndex

    vocab = {"cats": [1.0, 0.0, 0.0], "dogs": [0.0, 1.0, 0.0], "fish": [0.0, 0.0, 1.0]}

    def stub_embed(texts):
        out = []
        for t in texts:
            v = [0.0, 0.0, 0.0]
            tl = (t or "").lower()
            for w, wv in vocab.items():
                if w in tl:
                    v = [a + b for a, b in zip(v, wv)]
            out.append(v)
        return out

    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        try:
            e_cat = store.record_event(mode="chat", text="I really love cats and kittens")
            e_dog = store.record_event(mode="chat", text="dogs are loyal companions")
            e_fish = store.record_event(mode="chat", text="fish swim in the sea")
            for ev in (e_cat, e_dog, e_fish):
                store.set_event_embedding(ev.id, stub_embed([ev.text])[0])
            check("memory: embeddings stored (count)", store.count_event_embeddings() == 3)

            knn = store.knn_events(stub_embed(["cats"])[0], k=2, min_score=0.1)
            check("memory: KNN nearest is the cat event",
                  bool(knn) and knn[0][0].id == e_cat.id)
            check("memory: KNN scores sorted descending",
                  all(knn[i][1] >= knn[i + 1][1] for i in range(len(knn) - 1)))

            only_cat = store.knn_events(stub_embed(["cats"])[0], k=5, min_score=0.5)
            check("memory: min_score filters unrelated", [e.id for e, _ in only_cat] == [e_cat.id])

            # wektor o innym wymiarze (np. po zmianie modelu) jest pomijany, nie wywala
            e_bad = store.record_event(mode="chat", text="weird dimension event")
            store.set_event_embedding(e_bad.id, [0.5, 0.5])  # 2-dim
            mixed = store.knn_events([1.0, 0.0, 0.0], k=10, min_score=-1.0)
            check("memory: mismatched-dim vector skipped (no crash)",
                  all(e.id != e_bad.id for e, _ in mixed))

            # hybryda: KNN (query_vec→fish) + FTS ("loyal"→dog), dedup, KNN pierwszy
            hyb = store.hybrid_search(q_text="loyal", query_vec=stub_embed(["fish"])[0],
                                      k=5, min_score=0.5)
            ids = [e.id for e in hyb]
            check("memory: hybrid merges KNN + FTS (both, dedup)",
                  e_fish.id in ids and e_dog.id in ids and len(ids) == len(set(ids)))
            check("memory: hybrid puts KNN hit first", bool(ids) and ids[0] == e_fish.id)

            # MemoryIndex opt-in: OFF → no-op
            off = MemoryIndex(store, stub_embed, enabled=False)
            check("memory: disabled index/recall/inject are no-ops",
                  off.index_event("x", "cats") is False and off.recall("cats") == []
                  and off.injected_text("cats") == "")

            # MemoryIndex ON: index + recall + injected_text
            idx = MemoryIndex(store, stub_embed, enabled=True, max_results=3, min_score=0.5)
            e_new = store.record_event(mode="code", text="refactor the cats module")
            check("memory: index_event stores a vector", idx.index_event(e_new.id, e_new.text) is True)
            check("memory: recall returns cat-related events",
                  any(r.id == e_cat.id for r in idx.recall("cats")))
            inj = idx.injected_text("tell me about cats")
            check("memory: injected_text formats a memory block",
                  "Relevant memory" in inj and "cats" in inj.lower())
            check("memory: empty query -> no injection", idx.injected_text("   ") == "")
        finally:
            store.close()


def _raises_status(fn, status: int) -> bool:
    from fastapi import HTTPException
    try:
        fn()
        return False
    except HTTPException as e:
        return e.status_code == status
    except Exception:
        return False


def test_open_error_classification() -> None:
    """S31-d: błąd otwarcia bazy — lock/I-O = przejściowy (re-raise, NIE .corrupt);
    malformed/not-a-database/integrity = korupcja (backup). Bez tego zdrowa baza
    pod lockiem (druga instancja dev) wędrowała do .corrupt = „zniknęła historia"."""
    import sqlite3 as _s
    isc = HistoryStore._is_corruption
    check("history: 'database is locked' NOT corruption (S31-d)",
          isc(_s.OperationalError("database is locked")) is False)
    check("history: 'disk I/O error' NOT corruption (S31-d)",
          isc(_s.OperationalError("disk I/O error")) is False)
    check("history: 'malformed' IS corruption (S31-d)",
          isc(_s.OperationalError("database disk image is malformed")) is True)
    check("history: 'not a database' IS corruption (S31-d)",
          isc(_s.DatabaseError("file is not a database")) is True)
    check("history: integrity_check DatabaseError IS corruption (S31-d)",
          isc(_s.DatabaseError("integrity_check: bad")) is True)


def test_delete_project_files() -> None:
    """S31-k: delete_project kasuje PLIKI mediów artefaktów (sandbox media-base),
    a plik spoza dozwolonych baz zostaje (anty-traversal)."""
    from caelo_core.state import Backend

    with _tmp() as d:
        store = HistoryStore(Path(d) / "h.db")
        prev = HS._default_store
        HS._default_store = store
        try:
            save_dir = Path(d) / "media"
            save_dir.mkdir()
            in_base = save_dir / "art.png"
            in_base.write_bytes(b"x")
            outside = Path(d) / "outside.png"
            outside.write_bytes(b"y")

            proj = store.add_project(name="P")
            store.add_artifact(type="image", mode="image", mime="image/png",
                               path=str(in_base), project_id=proj.id, meta={})
            store.add_artifact(type="image", mode="image", mime="image/png",
                               path=str(outside), project_id=proj.id, meta={})

            b = Backend.__new__(Backend)

            class _H:
                def get_save_path(self_inner):
                    return str(save_dir)

            b.history = _H()
            b.current_project_id = None
            b._code_project_id = None

            b.delete_project(proj.id)
            check("delete_project: removes in-base media file (S31-k)", not in_base.exists())
            check("delete_project: leaves out-of-base file (anti-traversal, S31-k)", outside.exists())
        finally:
            HS._default_store = prev
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
    test_all_modes_land_and_fts()
    test_backend_wiring()
    test_input_blocks()
    test_project_scoping()
    test_memory_knn_hybrid()  # M19-B8: embeddingi + KNN + hybryda + MemoryIndex (stub)
    test_open_error_classification()  # S31-d
    test_delete_project_files()  # S31-k
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print("RESULT:", "OK" if ok else "FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
