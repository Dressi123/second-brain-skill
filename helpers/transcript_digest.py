#!/usr/bin/env python3
"""Compress a Claude Code session transcript into a text digest small enough
to inline into a prompt.

The raw JSONL is mostly tool *results* -- file dumps, build logs, search
output. A 5-hour session measured 5.1 MB across 2529 lines, of which the
human-readable spine (user turns + assistant prose) was ~150 KB. The
SessionEnd finalize hook grants the model `Read` and no Bash, and Read caps
at 2000 lines with per-line truncation, so handing it the raw path meant it
could never actually read the session it was summarizing -- it fell back to
the Stop hook's 200-word rolling draft, and produced 200-word-shaped
summaries of five-hour sessions. This is the fix: the wrapper (which has
real bash) precomputes the digest, same as it already does for taxonomy.

Kept: user turns, assistant prose, and a one-line trace per tool call
(name + target). Tool traces are what let the summary name real file paths
instead of saying "the stats service was consolidated".

Dropped: tool results, thinking blocks, sidechain (subagent/skill) turns,
and system-reminder injections.

Usage: transcript_digest.py <transcript.jsonl> [--max-chars N]
"""
import json
import sys

# Inlined into an argv-passed prompt; darwin's ARG_MAX is 1 MB and the rest
# of the prompt is small, so this leaves a wide margin.
DEFAULT_MAX_CHARS = 250_000
# Per-block cap. Truncating inside long blocks preserves every turn; dropping
# whole turns would punch holes in the middle of the session, which is the
# part a summary most needs.
BLOCK_CAP = 4_000


def target_of(name, inp):
    """The one field that identifies what a tool call acted on."""
    if not isinstance(inp, dict):
        return ""
    for key in ("file_path", "path", "notebook_path", "command", "pattern", "url", "query", "prompt"):
        v = inp.get(key)
        if isinstance(v, str) and v.strip():
            return v.strip().replace("\n", " ")[:160]
    return ""


def clip(text, cap=BLOCK_CAP):
    text = text.strip()
    if len(text) <= cap:
        return text
    return text[:cap] + f"\n[... {len(text) - cap} chars truncated ...]"


def digest(path, max_chars=DEFAULT_MAX_CHARS):
    out = []
    for line in open(path, encoding="utf-8", errors="replace"):
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        # Subagent and skill turns land in the same file; they are a parallel
        # conversation, not this one, and muddy a long session's narrative.
        if entry.get("isSidechain"):
            continue
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        content = msg.get("content")
        blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content
        if not isinstance(blocks, list):
            continue
        for b in blocks:
            if not isinstance(b, dict):
                continue
            kind = b.get("type")
            if kind == "text":
                text = (b.get("text") or "").strip()
                if not text:
                    continue
                # Harness injections, not anything a human said.
                if role == "user" and text.startswith("<") and "system-reminder" in text[:200]:
                    continue
                out.append(f"\n### {'USER' if role == 'user' else 'CLAUDE'}\n{clip(text)}")
            elif kind == "tool_use" and role == "assistant":
                tgt = target_of(b.get("name"), b.get("input"))
                out.append(f"  -> {b.get('name')}{': ' + tgt if tgt else ''}")

    text = "\n".join(out)
    if len(text) > max_chars:
        # Keep the end: the close of a session holds its conclusions, and the
        # running draft already covers the opening.
        text = f"[... earlier {len(text) - max_chars} chars omitted ...]\n" + text[-max_chars:]
    return text


if __name__ == "__main__":
    args = [a for a in sys.argv[1:]]
    cap = DEFAULT_MAX_CHARS
    if "--max-chars" in args:
        i = args.index("--max-chars")
        cap = int(args[i + 1])
        del args[i:i + 2]
    if not args:
        sys.exit("usage: transcript_digest.py <transcript.jsonl> [--max-chars N]")
    sys.stdout.write(digest(args[0], cap))
