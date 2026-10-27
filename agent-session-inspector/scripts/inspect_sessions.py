#!/usr/bin/env python3
"""Unified CLI to list, show, and search local sessions across DSH, Codex, Antigravity, and Kiro."""

import argparse
import datetime
import glob
import json
import os
import sqlite3
import subprocess
import sys
from typing import Any, Dict, List


def _fmt_ts(ms_or_iso: Any) -> str:
    if not ms_or_iso:
        return "-"
    if isinstance(ms_or_iso, (int, float)):
        ts = ms_or_iso / 1000.0 if ms_or_iso > 1e11 else float(ms_or_iso)
        return datetime.datetime.fromtimestamp(ts).strftime("%Y-%m-%d %H:%M:%S")
    return str(ms_or_iso)[:19].replace("T", " ")


# ---------------------------------------------------------------------------
# 1. DeepSeek Harness (DSH)
# ---------------------------------------------------------------------------
def iter_dsh_sessions(include_subagents: bool = False) -> List[Dict[str, Any]]:
    base = os.path.expanduser("~/.dsh/sessions")
    if not os.path.isdir(base):
        return []
    results: List[Dict[str, Any]] = []
    session_dirs = [
        os.path.join(dp, d)
        for dp, dn, _ in os.walk(base)
        for d in dn
        if not d.startswith("--")
    ]
    for sdir in sorted(session_dirs):
        f_v3 = os.path.join(sdir, "session.v3.jsonl.zstd")
        f_v1 = os.path.join(sdir, "session.jsonl.zstd")
        fpath = f_v3 if os.path.exists(f_v3) else (f_v1 if os.path.exists(f_v1) else None)
        if not fpath:
            continue
        try:
            p = subprocess.Popen(
                ["zstd", "-dc", fpath],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                text=True,
            )
            first_line = p.stdout.readline() if p.stdout else ""
            p.terminate()
            if not first_line.strip():
                continue
            meta = json.loads(first_line)
        except Exception:
            continue

        is_sub = meta.get("origin") == "subagent" or meta.get("delegationDepth", 0) > 0
        if is_sub and not include_subagents:
            continue

        results.append(
            {
                "tool": "dsh",
                "id": meta.get("id") or os.path.basename(sdir),
                "cwd": meta.get("cwd") or "-",
                "created_at": _fmt_ts(meta.get("createdAt")),
                "sort_key": meta.get("createdAt") or int(os.path.getmtime(fpath) * 1000),
                "path": fpath,
                "is_seeded": bool(meta.get("isSeeded", False)),
            }
        )
    return results


def parse_dsh_dialogue(session_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    fpath = session_info["path"]
    out = subprocess.check_output(["zstd", "-dc", fpath], text=True)
    events = []
    for line in out.split("\n"):
        if not line.strip():
            continue
        if (
            '"assistant/chunk"' in line
            or '"reasoning-chunks"' in line
            or '"tool-call-chunks"' in line
            or '"text-chunks"' in line
        ):
            continue
        try:
            events.append(json.loads(line))
        except Exception:
            pass

    end_seed_seq = -1
    for ev in events:
        if ev.get("type") == "session/end-seed":
            end_seed_seq = ev.get("seq", -1)

    cur_turn = 0
    cur_model = "unknown"
    turn_model: Dict[int, str] = {}
    for ev in events:
        t = ev.get("type")
        if t == "turn/start":
            cur_turn = ev.get("data", {}).get("turn", cur_turn + 1)
        elif t == "model/selection":
            d = ev.get("data", {})
            if d.get("model"):
                cur_model = f"{d.get('provider')}/{d.get('model')}"
        elif t in ("request/header", "request/context"):
            d = ev.get("data", {})
            cfg = d.get("header", {}).get("config", d)
            if cfg.get("model"):
                cur_model = f"{cfg.get('provider')}/{cfg.get('model')}"
                turn_model[cur_turn] = cur_model
        elif t == "assistant/message":
            msg = ev.get("data", {}).get("message", ev.get("data", {}))
            src = msg.get("source", {})
            if src.get("model"):
                cur_model = f"{src.get('provider')}/{src.get('model')}"
                turn_model[cur_turn] = cur_model
        if cur_turn > 0 and cur_turn not in turn_model and cur_model != "unknown":
            turn_model[cur_turn] = cur_model

    turns: List[Dict[str, Any]] = []
    cur_turn = 0
    last_model = "unknown"
    for ev in events:
        t = ev.get("type")
        seq = ev.get("seq", 0)
        if session_info.get("is_seeded") and seq <= end_seed_seq:
            continue
        if t == "turn/start":
            cur_turn = ev.get("data", {}).get("turn", cur_turn + 1)
            last_model = turn_model.get(cur_turn, last_model)
        elif t == "user/message":
            d = ev.get("data", {})
            src = d.get("source", {})
            if src.get("kind") == "user" and "rpcId" in src:
                txts = [
                    c.get("text", "")
                    for c in d.get("content", [])
                    if isinstance(c, dict) and c.get("type") == "text"
                ]
                turns.append(
                    {
                        "role": "user",
                        "model": turn_model.get(cur_turn, last_model),
                        "time": _fmt_ts(ev.get("time")),
                        "text": "\n".join(txts).strip(),
                    }
                )
        elif t == "assistant/message":
            msg = ev.get("data", {}).get("message", ev.get("data", {}))
            txts = [
                c.get("text", "")
                for c in msg.get("content", [])
                if isinstance(c, dict) and c.get("type") == "text" and c.get("text", "").strip()
            ]
            if txts:
                turns.append(
                    {
                        "role": "assistant",
                        "model": turn_model.get(cur_turn, last_model),
                        "time": _fmt_ts(ev.get("time")),
                        "text": "\n".join(txts).strip(),
                    }
                )
    return turns


# ---------------------------------------------------------------------------
# 2. Cursor / VSCode Codex Extension
# ---------------------------------------------------------------------------
def iter_codex_sessions() -> List[Dict[str, Any]]:
    patterns = [
        os.path.expanduser("~/.codex/sessions/**/*.jsonl"),
        os.path.expanduser("~/.codex/archived_sessions/**/*.jsonl"),
    ]
    files = sorted(f for p in patterns for f in glob.glob(p, recursive=True))
    results: List[Dict[str, Any]] = []
    for fpath in files:
        sid = os.path.basename(fpath)
        cwd = "-"
        ts_str = "-"
        try:
            with open(fpath, "r", encoding="utf-8") as fp:
                first_line = fp.readline()
            if first_line.strip():
                obj = json.loads(first_line)
                p = obj.get("payload", {})
                sid = p.get("session_id") or p.get("id") or sid
                cwd = p.get("cwd") or cwd
                ts_str = _fmt_ts(p.get("timestamp") or obj.get("timestamp"))
        except Exception:
            pass
        results.append(
            {
                "tool": "codex",
                "id": sid,
                "cwd": cwd,
                "created_at": ts_str,
                "sort_key": int(os.path.getmtime(fpath) * 1000),
                "path": fpath,
            }
        )
    return results


def parse_codex_dialogue(session_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    fpath = session_info["path"]
    turns: List[Dict[str, Any]] = []
    cur_model = "unknown"
    with open(fpath, "r", encoding="utf-8") as fp:
        for line in fp.read().split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            t = obj.get("type")
            p = obj.get("payload", {})
            ts = _fmt_ts(obj.get("timestamp"))
            if t == "session_meta":
                m = p.get("base_instructions", {}).get("provenance", {}).get("model")
                if m:
                    cur_model = m
            elif t == "turn_context":
                cur_model = p.get("model", cur_model)
            elif t == "event_msg":
                pt = p.get("type")
                if pt == "thread_settings_applied":
                    cur_model = p.get("thread_settings", {}).get("model", cur_model)
                elif pt == "user_message":
                    turns.append(
                        {
                            "role": "user",
                            "model": cur_model,
                            "time": ts,
                            "text": (p.get("message") or "").strip(),
                        }
                    )
                elif pt == "task_complete":
                    txt = (p.get("last_agent_message") or "").strip()
                    err = p.get("error")
                    if err and not txt:
                        txt = f"[ERROR] {json.dumps(err, ensure_ascii=False)}"
                    if txt:
                        turns.append(
                            {
                                "role": "assistant",
                                "model": cur_model,
                                "time": ts,
                                "text": txt,
                            }
                        )
    return turns


# ---------------------------------------------------------------------------
# 3. VSCode / Cursor Antigravity Extension
# ---------------------------------------------------------------------------
def iter_antigravity_sessions() -> List[Dict[str, Any]]:
    roots = [
        os.path.expanduser("~/.gemini/antigravity"),
        os.path.expanduser("~/.gemini/antigravity-cli"),
    ]
    seen = set()
    results: List[Dict[str, Any]] = []
    for r in roots:
        sum_db = os.path.join(r, "conversation_summaries.db")
        meta_map: Dict[str, Dict[str, Any]] = {}
        if os.path.exists(sum_db):
            try:
                conn = sqlite3.connect(sum_db)
                cur = conn.cursor()
                for row in cur.execute(
                    "SELECT conversation_id, title, workspace_uris, last_modified_time FROM conversation_summaries"
                ):
                    meta_map[row[0]] = {
                        "title": row[1] or "",
                        "cwd": row[2] or "-",
                        "mtime": row[3] or 0,
                    }
                conn.close()
            except Exception:
                pass

        for tpath in glob.glob(os.path.join(r, "brain/*/.system_generated/logs/transcript.jsonl")):
            cid = tpath.split("/brain/")[1].split("/")[0]
            if cid in seen:
                continue
            seen.add(cid)
            info = meta_map.get(cid, {})
            mtime_ms = int(os.path.getmtime(tpath) * 1000)
            results.append(
                {
                    "tool": "antigravity",
                    "id": cid,
                    "cwd": info.get("cwd") or "-",
                    "title": info.get("title") or "",
                    "created_at": _fmt_ts(mtime_ms),
                    "sort_key": mtime_ms,
                    "path": tpath,
                    "summary_db": sum_db if os.path.exists(sum_db) else None,
                }
            )
    return results


def parse_antigravity_dialogue(session_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    tpath = session_info["path"]
    turns: List[Dict[str, Any]] = []
    if os.path.exists(tpath):
        with open(tpath, "r", encoding="utf-8") as fp:
            for line in fp.read().split("\n"):
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                t = obj.get("type")
                ts = _fmt_ts(obj.get("created_at"))
                content = (obj.get("content") or "").strip()
                if t == "USER_INPUT" and content:
                    turns.append(
                        {
                            "role": "user",
                            "model": "antigravity/gemini",
                            "time": ts,
                            "text": content,
                        }
                    )
                elif t == "PLANNER_RESPONSE" and content:
                    turns.append(
                        {
                            "role": "assistant",
                            "model": "antigravity/gemini",
                            "time": ts,
                            "text": content,
                        }
                    )
    return turns


# ---------------------------------------------------------------------------
# 4. Kiro (IDE / CLI)
# ---------------------------------------------------------------------------
def iter_kiro_sessions(include_subagents: bool = False) -> List[Dict[str, Any]]:
    base = os.path.expanduser("~/.kiro/sessions")
    if not os.path.isdir(base):
        return []
    results: List[Dict[str, Any]] = []
    for mpath in sorted(glob.glob(os.path.join(base, "*", "sess_*", "messages.jsonl"))):
        sdir = os.path.dirname(mpath)
        meta_path = os.path.join(sdir, "session.json")
        meta: Dict[str, Any] = {}
        if os.path.exists(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as fp:
                    meta = json.load(fp)
            except Exception:
                pass
        sid = meta.get("id") or os.path.basename(sdir)
        ws_paths = meta.get("workspacePaths") or meta.get("rootPaths") or []
        cwd = ws_paths[0] if ws_paths else "-"
        model_id = (
            meta.get("modelId")
            or (meta.get("contextSnapshotModelDisplay") or {}).get("modelId")
            or "unknown"
        )
        mtime_ms = int(os.path.getmtime(mpath) * 1000)
        created_at = _fmt_ts(meta.get("createdAt") or mtime_ms)
        results.append(
            {
                "tool": "kiro",
                "id": sid,
                "cwd": cwd,
                "title": meta.get("title") or "",
                "model": model_id,
                "created_at": created_at,
                "sort_key": mtime_ms,
                "path": mpath,
                "is_subagent": False,
            }
        )
        if include_subagents:
            for spath in sorted(glob.glob(os.path.join(sdir, "sub-executions", "*.jsonl"))):
                sub_id = os.path.splitext(os.path.basename(spath))[0]
                sub_mtime_ms = int(os.path.getmtime(spath) * 1000)
                results.append(
                    {
                        "tool": "kiro",
                        "id": sub_id,
                        "cwd": cwd,
                        "title": f"[subagent of {sid}]",
                        "model": model_id,
                        "created_at": _fmt_ts(sub_mtime_ms),
                        "sort_key": sub_mtime_ms,
                        "path": spath,
                        "parent_path": mpath,
                        "is_subagent": True,
                    }
                )
    return results


def parse_kiro_dialogue(session_info: Dict[str, Any]) -> List[Dict[str, Any]]:
    fpath = session_info["path"]
    cur_model = session_info.get("model") or "unknown"
    turns: List[Dict[str, Any]] = []

    if session_info.get("is_subagent") and session_info.get("parent_path"):
        parent_path = session_info["parent_path"]
        sub_id = session_info["id"]
        if os.path.exists(parent_path):
            try:
                with open(parent_path, "r", encoding="utf-8") as pfp:
                    for line in pfp.read().split("\n"):
                        if not line.strip():
                            continue
                        obj = json.loads(line)
                        p = obj.get("payload", {})
                        if p.get("type") == "sub_agent_start" and p.get("subSessionId") == sub_id:
                            prompt = (p.get("prompt") or "").strip()
                            if prompt:
                                turns.append(
                                    {
                                        "role": "user",
                                        "model": cur_model,
                                        "time": _fmt_ts(obj.get("timestamp")),
                                        "text": prompt,
                                    }
                                )
                            break
            except Exception:
                pass

    if not os.path.exists(fpath):
        return turns

    with open(fpath, "r", encoding="utf-8") as fp:
        for line in fp.read().split("\n"):
            if not line.strip():
                continue
            try:
                obj = json.loads(line)
            except Exception:
                continue
            p = obj.get("payload", {})
            pt = p.get("type")
            ts = _fmt_ts(obj.get("timestamp"))

            rm = p.get("reasoningModelId")
            if rm:
                cur_model = rm.split("::", 1)[-1]
            elif pt == "usage_summary":
                m_disp = (p.get("modelDisplay") or {}).get("modelId")
                if m_disp:
                    cur_model = m_disp

            if pt == "user":
                content = (p.get("content") or "").strip()
                if content:
                    turns.append(
                        {
                            "role": "user",
                            "model": cur_model,
                            "time": ts,
                            "text": content,
                        }
                    )
            elif pt == "assistant" and p.get("operationType") != "Reasoning":
                content = (p.get("content") or "").strip()
                if content:
                    turns.append(
                        {
                            "role": "assistant",
                            "model": cur_model,
                            "time": ts,
                            "text": content,
                        }
                    )
            elif pt == "tool_call" and p.get("toolName") == "subagent_response":
                resp = ((p.get("args") or {}).get("response") or "").strip()
                if resp:
                    turns.append(
                        {
                            "role": "assistant",
                            "model": cur_model,
                            "time": ts,
                            "text": resp,
                        }
                    )
    return turns


# ---------------------------------------------------------------------------
# Unified Commands
# ---------------------------------------------------------------------------
def collect_all(tool: str, include_subagents: bool = False) -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []
    if tool in ("dsh", "all"):
        items.extend(iter_dsh_sessions(include_subagents=include_subagents))
    if tool in ("codex", "all"):
        items.extend(iter_codex_sessions())
    if tool in ("antigravity", "all"):
        items.extend(iter_antigravity_sessions())
    if tool in ("kiro", "all"):
        items.extend(iter_kiro_sessions(include_subagents=include_subagents))
    items.sort(key=lambda x: x.get("sort_key", 0), reverse=True)
    return items


def parse_dialogue(item: Dict[str, Any]) -> List[Dict[str, Any]]:
    t = item["tool"]
    if t == "dsh":
        return parse_dsh_dialogue(item)
    if t == "codex":
        return parse_codex_dialogue(item)
    if t == "antigravity":
        return parse_antigravity_dialogue(item)
    if t == "kiro":
        return parse_kiro_dialogue(item)
    return []


def cmd_list(args: argparse.Namespace) -> None:
    items = collect_all(args.tool, include_subagents=args.include_subagents)
    for s in items[: args.limit]:
        print(f"[{s['tool']:11s}] {s['created_at']} | {s['id']} | {s['cwd']}")


def cmd_show(args: argparse.Namespace) -> None:
    items = collect_all("all", include_subagents=True)
    matches = [s for s in items if args.session_id in s["id"]]
    if not matches:
        print(f"No session matching '{args.session_id}'", file=sys.stderr)
        sys.exit(1)
    target = matches[0]
    print(f"=== [{target['tool']}] {target['id']} | cwd: {target['cwd']} | file: {target['path']} ===")
    turns = parse_dialogue(target)
    for turn in turns:
        if args.user_only and turn["role"] != "user":
            continue
        role_tag = "USER" if turn["role"] == "user" else "ASST"
        print(f"\n--- [{role_tag}] ({turn['model']}) {turn['time']} ---")
        print(turn["text"])


def cmd_search(args: argparse.Namespace) -> None:
    items = collect_all(args.tool, include_subagents=args.include_subagents)
    kw = args.keyword.lower()
    hits = 0
    for s in items:
        try:
            turns = parse_dialogue(s)
        except Exception:
            continue
        for turn in turns:
            if args.user_only and turn["role"] != "user":
                continue
            if kw in turn["text"].lower():
                snippet = turn["text"].replace("\n", " ⏎ ")
                if len(snippet) > 220:
                    snippet = snippet[:220] + "..."
                print(
                    f"[{s['tool']}] {s['id'][:18]} | {turn['role']:9s} | {turn['model']} | {snippet}"
                )
                hits += 1
                if hits >= args.limit:
                    return


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Inspect local sessions across DSH, Codex, Antigravity, and Kiro."
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="List recent sessions")
    p_list.add_argument(
        "--tool", choices=["dsh", "codex", "antigravity", "kiro", "all"], default="all"
    )
    p_list.add_argument("--limit", type=int, default=20)
    p_list.add_argument("--include-subagents", action="store_true")
    p_list.set_defaults(func=cmd_list)

    p_show = sub.add_parser("show", help="Show conversation turns of a session")
    p_show.add_argument("session_id", help="Session ID or substring")
    p_show.add_argument("--user-only", action="store_true", help="Print only user messages")
    p_show.set_defaults(func=cmd_show)

    p_search = sub.add_parser("search", help="Search keyword across sessions")
    p_search.add_argument("keyword", help="Keyword to search")
    p_search.add_argument(
        "--tool", choices=["dsh", "codex", "antigravity", "kiro", "all"], default="all"
    )
    p_search.add_argument("--user-only", action="store_true", help="Search only user messages")
    p_search.add_argument("--include-subagents", action="store_true")
    p_search.add_argument("--limit", type=int, default=50)
    p_search.set_defaults(func=cmd_search)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
