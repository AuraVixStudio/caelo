"""Self-check + SPIKE klienta embeddings xAI (M19-B8).

Dwa tryby:

1) **Bez sieci (domyślny, w pytest/CI):** sprawdza parser odpowiedzi
   (`_parse_embeddings`) i obsługę błędów `embed_texts`/`probe` (brak klucza,
   pusta lista, błąd sieci → `EmbeddingError`/`probe.ok=False`). Mockuje warstwę
   `requests` — zero ruchu do `api.x.ai`.

2) **Live SPIKE (`--live`, na maszynie użytkownika):** woła REALNY
   `POST https://api.x.ai/v1/embeddings` przez `Backend.get_api_key` i wypisuje
   raport `{ok, model, dim}`. To rozstrzyga gate B8 z PLAN_M19_TIER2 §9 (czy xAI
   ma endpoint embeddings, jaki model/wymiary). Sandbox blokuje `api.x.ai`, więc
   live uruchamia użytkownik:  `python caelo_core/tools/embeddings_check.py --live`

Kod wyjścia 0 = OK.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from caelo_core import embeddings as E  # noqa: E402
from caelo_core.embeddings import EmbeddingError, _parse_embeddings  # noqa: E402

checks: list[tuple[str, bool]] = []


def check(name: str, passed: bool) -> None:
    checks.append((name, bool(passed)))


def test_parse() -> None:
    # poprawny kształt (OpenAI), porządkowanie wg index
    data = {"data": [{"embedding": [0.0, 1.0], "index": 1},
                     {"embedding": [1.0, 0.0], "index": 0}]}
    vecs = _parse_embeddings(data, expected=2)
    check("parse: orders by index", vecs == [[1.0, 0.0], [0.0, 1.0]])

    raised = False
    try:
        _parse_embeddings({"data": []}, expected=1)
    except EmbeddingError:
        raised = True
    check("parse: empty data -> EmbeddingError", raised)

    raised = False
    try:
        _parse_embeddings({"data": [{"embedding": [1.0]}]}, expected=2)
    except EmbeddingError:
        raised = True
    check("parse: count mismatch -> EmbeddingError", raised)

    raised = False
    try:
        _parse_embeddings({"data": [{"index": 0}]}, expected=1)  # brak 'embedding'
    except EmbeddingError:
        raised = True
    check("parse: missing 'embedding' -> EmbeddingError", raised)


def test_embed_errors() -> None:
    check("embed: empty input -> []",
          E.embed_texts([], api_key_provider=lambda: "k") == [])

    raised = False
    try:
        E.embed_texts(["hi"], api_key_provider=lambda: "")  # brak klucza
    except EmbeddingError:
        raised = True
    check("embed: no api key -> EmbeddingError", raised)

    # probe NIE rzuca — łapie błąd i raportuje ok=False
    rep = E.probe(lambda: "")
    check("probe: no key -> ok=False (no raise)", rep["ok"] is False and bool(rep["error"]))


def test_embed_with_mock_transport() -> None:
    """Mock warstwy `requests.post` — sprawdza pełną ścieżkę embed_texts bez sieci."""
    import types

    captured: dict = {}

    class _Resp:
        encoding = "iso-8859-1"

        def raise_for_status(self):  # noqa: D401
            return None

        def json(self):
            return {"data": [{"embedding": [0.1, 0.2, 0.3], "index": 0}]}

    def fake_post(url, headers=None, json=None, timeout=None):
        captured["url"] = url
        captured["payload"] = json
        captured["auth"] = (headers or {}).get("Authorization")
        return _Resp()

    orig = E.requests.post
    E.requests.post = fake_post  # type: ignore[assignment]
    try:
        vecs = E.embed_texts(["hello"], api_key_provider=lambda: "SECRET",
                             model="embedding-test", base="https://api.x.ai/v1")
        check("embed(mock): returns the vector", vecs == [[0.1, 0.2, 0.3]])
        check("embed(mock): hits /embeddings endpoint",
              captured["url"] == "https://api.x.ai/v1/embeddings")
        check("embed(mock): bearer auth from provider",
              captured["auth"] == "Bearer SECRET")
        check("embed(mock): payload carries model + input list",
              captured["payload"]["model"] == "embedding-test"
              and captured["payload"]["input"] == ["hello"])
    finally:
        E.requests.post = orig  # type: ignore[assignment]


def run_live_probe() -> int:
    """SPIKE na maszynie usera: realny POST /v1/embeddings przez Backend.get_api_key."""
    from caelo_core.state import Backend  # pociąga legacy managery — tylko w trybie live

    b = Backend()
    print("=== xAI embeddings SPIKE (live) ===")
    print(f"model: {getattr(__import__('config'), 'EMBED_MODEL', '?')}")
    rep = E.probe(b.get_api_key)
    if rep["ok"]:
        print(f"OK — model={rep['model']} dim={rep['dim']}")
        print("→ B8 może używać xAI embeddings (potwierdź wymiar/koszt w dokumentacji konta).")
        return 0
    print(f"FAILED — {rep['error']}")
    print("→ Jeśli to 404/400: xAI może nie mieć /v1/embeddings — B8 zostaje na stubie/odłożone.")
    return 1


def main() -> int:
    if "--live" in sys.argv or os.environ.get("CAELO_EMBED_LIVE", "") == "1":
        return run_live_probe()
    test_parse()
    test_embed_errors()
    test_embed_with_mock_transport()
    print("\n=== embeddings client self-check (M19-B8, no network) ===")
    ok = True
    for name, passed in checks:
        print(f"  [{'OK' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'ALL PASSED' if ok else 'SOME FAILED'} ({sum(p for _, p in checks)}/{len(checks)})")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
