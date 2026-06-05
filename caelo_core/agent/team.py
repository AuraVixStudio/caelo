"""Zespół subagentów — orkiestracja, izolacja, limity (M17-B1/B2/B3/B5/B6).

`TeamManager.run(tasks)` jest wołane przez narzędzie `delegate` orkiestratora
(`session.py`). Spawnuje wyspecjalizowanych subagentów (role z `roles.py`), każdy
jako **izolowaną pod-sesję** `AgentSession` z własną historią, zawężonymi
narzędziami i (dla ról mutujących) **worktree** (kopia workspace). Wyniki wracają
do orkiestratora jako **streszczenia** — nie transkrypty (czysty kontekst rodzica).

Twarde limity (B5): równoległość (semafor), timeout per subagent (monitor), budżet
łącznych tur LLM (wspólny licznik + stop), cap liczby subagentów, głębia = 1
(subagent nie dostaje `delegate`). Stop kaskadowy: stop orkiestratora widoczny w
domknięciu `stop` każdego subagenta → pętle się przerywają, a `run_command`
drzewo-ubija (P0-4). Brak eskalacji: zakres narzędzi roli przecięty z rodzicem.

Strumień (PLAN_M17 §5): jeden `WsStream`, zdarzenia subagentów tagowane `agent_id`
(ramka `subagent`); cykl życia w `subagent_status`; podsumowanie w `team_done`.
"""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Callable, Optional

import config  # type: ignore

from caelo_core.agent.permissions import MUTATING, READONLY
from caelo_core.agent.roles import RoleRegistry, effective_tools, role_is_mutating
from caelo_core.agent.session import AgentSession
from caelo_core.agent.workspace import Workspace
from caelo_core.agent.worktree import (
    apply_changes,
    compute_changes,
    copy_worktree,
    discard_worktree,
)

log = logging.getLogger(__name__)

# Pełny zbiór narzędzi plikowych rodzica (orkiestratora) — granica „bez eskalacji".
PARENT_FILE_TOOLS = READONLY | MUTATING

# B6: szacunek kosztu z tokenów (BYO-key — stawki orientacyjne, strojalne; rzeczywiste
# zależą od planu/modelu, jak estymata TTS w M12). 0 → nie pokazuj kwoty.
EST_USD_PER_MTOK_INPUT = 0.0
EST_USD_PER_MTOK_OUTPUT = 0.0


def _est_usd(inp: int, out: int) -> float:
    return round(inp / 1_000_000 * EST_USD_PER_MTOK_INPUT
                 + out / 1_000_000 * EST_USD_PER_MTOK_OUTPUT, 4)


# --- scoping MCP per rola (zawężenie do readonly / brak / pełne) -----------------
class ScopedMcp:
    """Fasada menedżera MCP zawężona do zakresu roli (`readonly`/`all`). Dla
    `readonly` advertuje i przepuszcza TYLKO narzędzia READONLY (mutujące stają się
    niewidoczne → odrzucane przez filtr roli w session.py). Brak eskalacji."""

    def __init__(self, mgr, scope: str) -> None:
        self._mgr = mgr
        self._scope = scope  # 'readonly' | 'all'

    def _readonly_names(self) -> set[str]:
        try:
            return {t["qualified_name"] for t in self._mgr.list_tools() if t.get("readonly")}
        except Exception:  # noqa: BLE001
            return set()

    def tool_defs_for_responses(self) -> list:
        defs = self._mgr.tool_defs_for_responses()
        if self._scope == "all":
            return defs
        allowed = self._readonly_names()
        return [d for d in defs if d.get("function", {}).get("name") in allowed]

    def is_mcp_tool(self, name: str) -> bool:
        if not self._mgr.is_mcp_tool(name):
            return False
        if self._scope == "all":
            return True
        return not self._mgr.is_mutating(name)  # readonly: tylko readonly „widoczne"

    def is_mutating(self, name: str) -> bool:
        return self._mgr.is_mutating(name)

    def describe_tool(self, name: str) -> dict:
        return self._mgr.describe_tool(name)

    def call_tool(self, name: str, args: dict) -> str:
        if self._scope != "all" and self._mgr.is_mutating(name):
            return "Error: this read-only subagent role may not call mutating MCP tools."
        return self._mgr.call_tool(name, args)


# --- pojedynczy subagent --------------------------------------------------------
class SubAgent:
    """Izolowana pod-sesja: rola → system prompt + zawężone narzędzia (+ worktree).
    `run()` wykonuje jedno zadanie i wypełnia `result`/`status`/telemetrię."""

    def __init__(self, *, agent_id: str, role: dict, task: str, team: "TeamManager",
                 model: str, mode: str) -> None:
        self.agent_id = agent_id
        self.role = role
        self.role_id = role.get("id", "")
        self.task = task
        self.team = team
        self.model = role.get("model") or model
        self.mode = mode
        self.status = "queued"
        self.error = ""
        self.summary = ""
        self.merge_id: Optional[str] = None
        self.files_changed = 0
        self.turns = 0
        self.tool_calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.started_at = 0.0
        self.duration = 0.0
        self.stop = False                  # indywidualny stop (timeout per subagent)
        self.timed_out = False
        self.done = threading.Event()
        self.thread: Optional[threading.Thread] = None
        self._worktree: Optional[Path] = None

    # --- domknięcia kontekstu pod-sesji ---
    def _scoped_emit(self, ev: dict) -> None:
        self.team.emit({"type": "subagent", "agent_id": self.agent_id,
                        "role": self.role_id, "task": self.task, "event": ev})

    def _scoped_approval(self, call_id: str, name: str, detail: Optional[dict]) -> str:
        # F3: zatwierdzenie otagowane subagentem; call_id znamespace'owany (brak kolizji
        # przy równoległych subagentach dzielących pulę `pending` w trasie).
        d = dict(detail or {})
        d.update({"agent_id": self.agent_id, "role": self.role_id, "task": self.task})
        return self.team.request_approval(f"{self.agent_id}:{call_id}", name, d)

    def _stop_flag(self) -> bool:
        return (self.stop or self.team.should_stop())

    def _on_turn(self) -> None:
        self.team.count_turn()

    def run(self) -> None:
        self.started_at = time.monotonic()
        try:
            ws = self._workspace_for_role()
            mcp = self._scoped_mcp()
            tools = set(effective_tools(self.role, PARENT_FILE_TOOLS))  # B5: ∩ rodzic
            session = AgentSession(
                ws, self.team.gate, self.team.llm_fn, self.team.api_key_provider,
                self.team.base_url, emit=self._scoped_emit,
                request_approval=self._scoped_approval,
                max_iters=self.team.limits.get("max_iters", 16),
                checkpoints_provider=None,        # worktree+merge to punkt cofania (B4)
                mcp=mcp, hooks=self.team.hooks, skills=None,
                tool_names=tools,                 # B1: zawężony zbiór narzędzi
                delegate_fn=None,                 # B5: głębia = 1 (brak wnuków)
                extra_system=self.role.get("prompt") or None,
                on_turn=self._on_turn,            # B5: budżet tur
            )
            # Mutująca rola pracuje w worktree → auto-akceptuj edycje (przegląd przy
            # scalaniu, B4 — nie pytaj per-edit). run_command nadal pyta (routowane do
            # UI, F3). READONLY rola: tryb bez znaczenia (brak mutacji).
            sub_mode = "accept-edits" if role_is_mutating(self.role) else "ask"
            session.run_turn(self.task, self.model, mode=sub_mode,
                             stop_flag=self._stop_flag)
            self.turns = session.turns
            self.tool_calls = session.tool_calls
            self.input_tokens = session.usage.get("input_tokens", 0)
            self.output_tokens = session.usage.get("output_tokens", 0)
            # streszczenie = ostatnia odpowiedź asystenta (czysty kontekst rodzica)
            self.summary = _last_assistant_text(session) or "(no summary returned)"
            if self.timed_out:
                self.status = "timeout"
            elif self._stop_flag():
                self.status = "cancelled"
            else:
                self.status = "done"
            self._finalize_worktree()
        except Exception as exc:  # noqa: BLE001
            log.warning("subagent %s failed", self.agent_id, exc_info=True)
            self.status = "failed"
            self.error = str(exc)
            self.summary = f"Error: {exc}"
            self._cleanup_worktree()
        finally:
            self.duration = time.monotonic() - self.started_at

    def _workspace_for_role(self) -> Workspace:
        """READONLY rola → realny workspace (bez kopii). Mutująca → izolowany worktree."""
        if not role_is_mutating(self.role):
            return self.team.workspace
        wt = self.team.new_worktree_path(self.agent_id)
        copy_worktree(self.team.workspace.root, wt)
        self._worktree = wt
        return Workspace(str(wt))

    def _scoped_mcp(self):
        scope = self.role.get("mcp", "readonly")
        if scope == "none" or self.team.mcp is None:
            return None
        return ScopedMcp(self.team.mcp, "all" if scope == "all" else "readonly")

    def _finalize_worktree(self) -> None:
        """Po pracy mutującego subagenta: policz zmiany; są → zarejestruj scalenie do
        przeglądu (B4), brak → wyrzuć kopię."""
        if self._worktree is None:
            return
        try:
            changes = compute_changes(self.team.workspace.root, self._worktree)
        except Exception:  # noqa: BLE001
            log.warning("compute_changes failed for %s", self.agent_id, exc_info=True)
            self._cleanup_worktree()
            return
        if not changes["files"]:
            self._cleanup_worktree()
            return
        self.files_changed = len(changes["files"])
        merge = self.team.register_merge(
            agent_id=self.agent_id, role=self.role_id, task=self.task,
            worktree_dir=str(self._worktree), files=changes["files"], diff=changes["diff"])
        self.merge_id = merge.id if merge else None

    def _cleanup_worktree(self) -> None:
        if self._worktree is not None:
            discard_worktree(self._worktree)
            self._worktree = None

    def report(self) -> dict:
        return {
            "agent_id": self.agent_id, "role": self.role_id, "task": self.task,
            "status": self.status, "summary": self.summary[:2000], "error": self.error,
            "turns": self.turns, "tool_calls": self.tool_calls,
            "input_tokens": self.input_tokens, "output_tokens": self.output_tokens,
            "est_usd": _est_usd(self.input_tokens, self.output_tokens),
            "duration": round(self.duration, 2),
            "merge_id": self.merge_id, "files_changed": self.files_changed,
        }


def _last_assistant_text(session: AgentSession) -> str:
    for m in reversed(session.history):
        if m.get("role") == "assistant" and (m.get("content") or "").strip():
            return str(m["content"]).strip()
    return ""


# --- magazyn oczekujących scaleń (współdzielony WS↔REST) ------------------------
class PendingMerge:
    def __init__(self, *, id: str, agent_id: str, role: str, task: str,
                 worktree_dir: str, files: list[dict], diff: str, created_at: int) -> None:
        self.id = id
        self.agent_id = agent_id
        self.role = role
        self.task = task
        self.worktree_dir = worktree_dir
        self.files = files
        self.diff = diff
        self.created_at = created_at
        self.conflicts: list[str] = []

    def summary(self) -> dict:
        return {"id": self.id, "agent_id": self.agent_id, "role": self.role,
                "task": self.task, "files": self.files, "conflicts": self.conflicts,
                "created_at": self.created_at, "file_count": len(self.files)}


class MergeStore:
    """Oczekujące scalenia worktree dla JEDNEGO workspace (jak CheckpointManager).
    Wykrywa konflikty (ta sama ścieżka w >1 worktree). Apply/reject sprzątają kopię."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root).resolve()
        self._merges: dict[str, PendingMerge] = {}
        self._lock = threading.RLock()
        self._seq = 0

    def add(self, *, agent_id: str, role: str, task: str, worktree_dir: str,
            files: list[dict], diff: str, created_at: int) -> PendingMerge:
        with self._lock:
            self._seq += 1
            mid = f"m{self._seq}"
            pm = PendingMerge(id=mid, agent_id=agent_id, role=role, task=task,
                              worktree_dir=worktree_dir, files=files, diff=diff,
                              created_at=created_at)
            self._merges[mid] = pm
            self._recompute_conflicts_locked()
            return pm

    def _recompute_conflicts_locked(self) -> None:
        # konflikt = ścieżka występująca w >1 oczekującym scaleniu
        seen: dict[str, int] = {}
        for pm in self._merges.values():
            for f in pm.files:
                seen[f["path"]] = seen.get(f["path"], 0) + 1
        for pm in self._merges.values():
            pm.conflicts = sorted({f["path"] for f in pm.files if seen.get(f["path"], 0) > 1})

    def list(self) -> list[dict]:
        with self._lock:
            return [pm.summary() for pm in self._merges.values()]

    def get(self, mid: str) -> Optional[PendingMerge]:
        return self._merges.get(mid)

    def diff(self, mid: str) -> Optional[str]:
        pm = self._merges.get(mid)
        return pm.diff if pm else None

    def apply(self, mid: str, workspace: Workspace, checkpoints=None) -> dict:
        with self._lock:
            pm = self._merges.get(mid)
            if pm is None:
                raise ValueError("unknown merge")
            res = apply_changes(workspace, Path(pm.worktree_dir), pm.files,
                                checkpoints=checkpoints,
                                label=f"Merge {pm.role} subagent")
            discard_worktree(Path(pm.worktree_dir))
            del self._merges[mid]
            self._recompute_conflicts_locked()
            res["ok"] = True
            res["merge_id"] = mid
            return res

    def reject(self, mid: str) -> dict:
        with self._lock:
            pm = self._merges.pop(mid, None)
            if pm is None:
                raise ValueError("unknown merge")
            discard_worktree(Path(pm.worktree_dir))
            self._recompute_conflicts_locked()
            return {"ok": True, "merge_id": mid}

    def clear(self) -> dict:
        with self._lock:
            for pm in self._merges.values():
                discard_worktree(Path(pm.worktree_dir))
            n = len(self._merges)
            self._merges.clear()
            return {"ok": True, "cleared": n}


# --- menedżer zespołu (orkiestracja jednego delegate) ---------------------------
class TeamManager:
    """Trwa per sesję orkiestratora (jak połączenie WS). `run(tasks, …)` obsługuje
    pojedyncze wywołanie `delegate`. Liczniki/raporty kumulują się w sesji."""

    def __init__(self, *, registry: RoleRegistry, gate, llm_fn: Callable,
                 api_key_provider: Callable[[], str], base_url: str, mcp, hooks,
                 emit: Callable[[dict], None], request_approval: Callable[..., str],
                 orchestrator_stop: Callable[[], bool],
                 merges_provider: Callable[[], MergeStore],
                 on_report: Optional[Callable[[dict], None]] = None) -> None:
        self.registry = registry
        self.gate = gate
        self.llm_fn = llm_fn
        self.api_key_provider = api_key_provider
        self.base_url = base_url
        self.mcp = mcp
        self.hooks = hooks
        self.emit = emit
        self.request_approval = request_approval
        self.orchestrator_stop = orchestrator_stop
        self.merges_provider = merges_provider
        self.on_report = on_report

        self.limits = registry.limits()
        self.workspace: Optional[Workspace] = None
        # baza worktree (nadpisywalna w testach, by nie pisać do repo).
        self.worktrees_base = Path(config.WORKTREES_DIR)
        self._lock = threading.RLock()
        self._turns_used = 0
        self._stopped = False
        self._seq = 0
        self._run_seq = 0

    # --- budżet / stop (B5) ---
    def count_turn(self) -> None:
        with self._lock:
            self._turns_used += 1

    def _budget_exceeded(self) -> bool:
        return self._turns_used >= int(self.limits.get("max_total_turns", 32))

    def should_stop(self) -> bool:
        if self._stopped or self._budget_exceeded():
            return True
        try:
            return bool(self.orchestrator_stop())
        except Exception:  # noqa: BLE001
            return False

    # --- worktree / merge ---
    def new_worktree_path(self, agent_id: str) -> Path:
        return Path(self.worktrees_base) / f"run{self._run_seq}" / agent_id

    def register_merge(self, **kw) -> Optional[PendingMerge]:
        try:
            store = self.merges_provider()
        except Exception:  # noqa: BLE001
            return None
        if store is None:
            return None
        return store.add(created_at=int(time.time()), **kw)

    # --- przebieg delegacji ---
    def run(self, tasks: list, *, model: str, workspace: Workspace, mode: str = "ask") -> str:
        self.workspace = workspace
        self.limits = self.registry.limits()  # świeże (UI mógł zmienić)
        self._turns_used = 0
        self._stopped = False
        self._run_seq += 1

        max_subs = int(self.limits.get("max_subagents", 8))
        subs: list[SubAgent] = []
        errors: list[str] = []
        for raw in tasks[:max_subs]:
            role_id = str((raw or {}).get("role") or "").strip()
            task = str((raw or {}).get("task") or "").strip()
            role = self.registry.get(role_id)
            if role is None:
                errors.append(f"[{role_id or '?'}] unknown role — skipped")
                continue
            if not task:
                errors.append(f"[{role_id}] empty task — skipped")
                continue
            # Tryb planowania: mutujące role wyłączone (jak write/edit/run w plan mode).
            if mode == "plan" and role_is_mutating(role):
                errors.append(f"[{role_id}] mutating role disabled in plan mode — skipped")
                continue
            self._seq += 1
            aid = f"sa{self._seq}"
            sub = SubAgent(agent_id=aid, role=role, task=task, team=self,
                           model=model, mode=mode)
            subs.append(sub)
            self._emit_status(sub)  # queued

        dropped = len(tasks) - len(tasks[:max_subs])
        if dropped > 0:
            errors.append(f"{dropped} task(s) dropped — exceeds max_subagents "
                          f"({max_subs})")

        if subs:
            self._run_concurrent(subs)

        report = self._build_report(subs, errors)
        if self.on_report is not None:
            try:
                self.on_report(report)
            except Exception:  # noqa: BLE001
                pass
        self.emit({"type": "team_done", "report": report})
        return self._summary_text(subs, errors)

    def _run_concurrent(self, subs: list[SubAgent]) -> None:
        sem = threading.Semaphore(max(1, int(self.limits.get("max_parallel", 3))))
        timeout_s = float(self.limits.get("timeout_s", 300))

        def _worker(sub: SubAgent) -> None:
            sem.acquire()
            try:
                if self.should_stop():
                    sub.status = "cancelled"
                    sub.summary = "(cancelled before start)"
                    return
                sub.status = "running"
                self._emit_status(sub)
                sub.run()
            finally:
                sem.release()
                sub.done.set()
                self._emit_status(sub)

        for sub in subs:
            t = threading.Thread(target=_worker, args=(sub,), daemon=True)
            sub.thread = t
            t.start()

        # Monitor: egzekwuj timeout per subagent + stop kaskadowy. Backstop deadline.
        hard_deadline = time.monotonic() + timeout_s * len(subs) + 30
        while not all(s.done.is_set() for s in subs):
            if self.should_stop():
                self._stopped = True
            now = time.monotonic()
            for sub in subs:
                if sub.done.is_set() or not sub.started_at:
                    continue
                if now - sub.started_at > timeout_s:
                    sub.timed_out = True
                    sub.stop = True  # domknięcie stop subagenta → pętla/komenda padają
            if now > hard_deadline:
                for sub in subs:
                    sub.stop = True
                break
            time.sleep(0.05)
        for sub in subs:
            if sub.thread is not None:
                sub.thread.join(timeout=2)

    # --- raport / streszczenie ---
    def _build_report(self, subs: list[SubAgent], errors: list[str]) -> dict:
        rows = [s.report() for s in subs]
        totals = {
            "subagents": len(rows),
            "turns": sum(r["turns"] for r in rows),
            "tool_calls": sum(r["tool_calls"] for r in rows),
            "input_tokens": sum(r["input_tokens"] for r in rows),
            "output_tokens": sum(r["output_tokens"] for r in rows),
            "merges": sum(1 for r in rows if r["merge_id"]),
        }
        totals["est_usd"] = _est_usd(totals["input_tokens"], totals["output_tokens"])
        return {"run": self._run_seq, "subagents": rows, "totals": totals,
                "errors": errors, "created_at": int(time.time())}

    def _summary_text(self, subs: list[SubAgent], errors: list[str]) -> str:
        if not subs and errors:
            return "Error: no subagents ran — " + "; ".join(errors)
        lines = [f"Delegated {len(subs)} subagent(s):", ""]
        for s in subs:
            head = f"[{s.role_id}] {s.status}"
            if s.merge_id:
                head += (f" — {s.files_changed} file(s) changed, pending your merge "
                         f"review (merge id: {s.merge_id})")
            lines.append(head)
            body = (s.summary or "").strip()
            if body:
                lines.append(body[:1500])
            lines.append("")
        if errors:
            lines.append("Notes: " + "; ".join(errors))
        return "\n".join(lines).strip()

    # --- zdarzenia cyklu życia (F1) ---
    def _emit_status(self, sub: SubAgent) -> None:
        self.emit({"type": "subagent_status", "agent_id": sub.agent_id,
                   "role": sub.role_id, "task": sub.task, "status": sub.status,
                   "summary": sub.summary[:600], "merge_id": sub.merge_id,
                   "files_changed": sub.files_changed,
                   "turns": sub.turns, "tool_calls": sub.tool_calls})
