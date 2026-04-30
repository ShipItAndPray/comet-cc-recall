# comet-cc-recall

> File-anchored memory recall for [CoMeT-CC](https://github.com/Dirac-Robot/CoMeT-CC).
> Open a source file → see the memory nodes you've already reasoned through about it.

```bash
$ comet-cc-recall services/payments.py
n_a8f2  1.31  HIGH  2026-03-03
  fixed redis SETNX race in services/payments.py — myrepo deploy
  trigger: idempotency key TTL shorter than retry interval
  tags: payments, redis, idempotency

n_4c11  1.05  MED   2026-02-19
  myrepo deploy notes — Postgres migration prep
  tags: deploys
```

CoMeT-CC stores summaries of every conversation you have with Claude
Code. This tool lets you query that store **outside the chat**, anchored
to whatever file you have open — so the next time you stare at
`services/payments.py` thinking *"didn't I figure this out three weeks
ago?"* you don't have to scroll through transcripts.

## How it works

1. Read the source file.
2. Extract top-level symbols (regex by language: Python, TS/JS, Go, Rust).
3. Resolve the repo root (walks up looking for `.git`).
4. Build an anchor query: `repo:myrepo | file:services/payments.py | lang:python | symbols: IdempotencyKey, reserve_key, release_key`.
5. Send the anchor to the running CoMeT-CC daemon's `get_context_window`
   RPC over its existing Unix socket. The daemon embeds with BGE-M3 and
   cosine-searches the store.
6. Apply a repo-name / file-path bonus on top of the daemon's ranking
   so nodes that mention the file climb above generic matches.
7. Print the top-K hits at tier-1 (summary + trigger + tags). Drill into
   tier-2 (`comet-cc-recall read <id> --depth 1`) or tier-3 raw
   (`--depth 2`) on demand.

No fork of CoMeT-CC, no schema changes — this is a sidecar that talks to
the daemon already on your machine.

## Install

```bash
pip install comet-cc-recall
```

Prereqs:

- [CoMeT-CC](https://github.com/Dirac-Robot/CoMeT-CC) installed and the
  daemon running (`comet-cc daemon start`).
- For cross-session recall (recommended), start the upstream daemon with:
  ```bash
  COMET_CC_CROSS_SESSION=1 comet-cc daemon start
  ```
  Otherwise recall returns only nodes from the probe session, which is
  almost certainly not what you want.

## Usage

### Subcommands

```bash
# File-anchored recall (default — the `recall` is implied)
comet-cc-recall services/payments.py
comet-cc-recall recall services/payments.py --top-k 8

# Raw semantic search by free-text query
comet-cc-recall search "redis idempotency race"

# Graph walk from a node id (similarity-linked peers)
comet-cc-recall related n_a8f2 --depth 2

# Recall against the union of `git diff` files (great pre-PR reflex)
comet-cc-recall diff
comet-cc-recall diff main

# Emit a <recalled-memory> block to paste into a fresh agent prompt
comet-cc-recall context services/payments.py -k 5

# Periodic digest, grouped by tag (perfect for daily / weekly review)
comet-cc-recall digest --since 7d --importance HIGH --top-per-tag 3

# Install a non-blocking pre-push git hook that surfaces recalled memory
comet-cc-recall hook install
comet-cc-recall hook status
comet-cc-recall hook uninstall

# Run as an MCP server (stdio) — any agent can call recall as a tool
pip install "comet-cc-recall[mcp]"
comet-cc-recall mcp

# Drill into a hit
comet-cc-recall read n_a8f2              # depth 0: summary + trigger
comet-cc-recall read n_a8f2 --depth 1    # haiku-cached detailed summary
comet-cc-recall read n_a8f2 --depth 2    # tier-3 raw turns

# Sanity check
comet-cc-recall doctor
```

### Shared filter flags

Apply to `recall`, `search`, `related`, `diff`:

| flag | meaning |
|---|---|
| `--tag <name>` | only nodes with this topic tag (repeatable, OR-match) |
| `--importance HIGH\|MED\|LOW` | restrict by importance (repeatable) |
| `--since 30d` | only nodes newer than the duration / ISO date (`90m`, `2w`, `2026-04-01`) |

### Shared output formats

| flag | format | use for |
|---|---|---|
| `-o text` *(default)* | ANSI-colored terminal | humans |
| `-o json` (or `--json`) | JSON array | editor integrations / piping |
| `-o md` | markdown cards | pasting into docs / PRs |
| `-o llm` | `<recalled-memory>` block | priming a fresh agent prompt |

Other:

| flag | default | meaning |
|---|---|---|
| `-k`, `--top-k` | `5` | max hits returned |
| `--min-score` | `0.20` | cosine floor passed to the daemon (recall/search/context) |
| `--no-repo-filter` | off | disable the repo / file-path rerank bonus (recall) |
| `--depth` | `1` | graph walk depth (related: 1\|2; read: 0\|1\|2) |
| `--color` | `auto` | `auto`, `always`, `never` |

## Supported languages

Symbol extraction: Python, TypeScript, JavaScript, Go, Rust. Files of
other types are silently skipped (no daemon call). Adding a language is
one regex pair in `src/comet_cc_recall/symbols.py`.

## Library use

```python
from comet_cc_recall import recall, search, related, diff_recall, context_block

hits = recall("src/auth/middleware.ts", top_k=5)
for h in hits:
    print(h.node_id, h.score, h.summary)

hits = search("postgres migration rollback strategy")
hits = related("n_a8f2", depth=2)
hits = diff_recall(base="main")        # uses git on the cwd
print(context_block("src/payments.py")) # paste into a fresh agent prompt
```

`hits` is a list of `RecallHit` (frozen dataclass): `node_id`, `score`,
`summary`, `trigger`, `importance`, `tags`, `session_id`, `created_at`.

Filtering composes:

```python
from comet_cc_recall.filters import filter_hits, parse_since

hits = recall("src/payments.py", top_k=20)
hits = filter_hits(hits, tags=["payments"], importance=["HIGH"],
                   since=parse_since("14d"))
```

## Editor integration

JSON output is the integration surface. A VSCode extension can shell out
on file open / focus and render hits in a margin or sidebar:

```bash
comet-cc-recall recall "$ZED_FILE" --json --top-k 3
```

A reference VSCode extension is on the roadmap.

## Architecture

```
┌──────────────────┐     anchor query      ┌────────────────────┐
│ comet-cc-recall  │ ────────────────────▶ │  CoMeT-CC daemon   │
│  (this package)  │                       │   (upstream)       │
│                  │ ◀──── ranked nodes ── │  - BGE-M3 embedder │
└──────────────────┘                       │  - SQLite NodeStore│
                                           │  - 3-tier read API │
                                           └────────────────────┘
```

The daemon does the heavy lifting. This package just composes a good
query, calls the existing RPC, and reranks with a tiny additive bonus.

## Development

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/pytest                       # 55 tests, no daemon needed
.venv/bin/ruff check src tests
```

The test suite spins up an in-process fake of CoMeT-CC's Unix-socket
JSON-RPC server, so you can run the full suite without installing the
upstream daemon.

## MCP integration

After `pip install "comet-cc-recall[mcp]"`, register the server with any
MCP-aware client. Example for Claude Code (`~/.config/claude/mcp.json`):

```json
{
  "mcpServers": {
    "comet-cc-recall": {
      "command": "comet-cc-recall",
      "args": ["mcp"]
    }
  }
}
```

Tools exposed: `recall_file`, `search`, `related`, `diff_recall`,
`context_block`, `read_node`. Each returns JSON-serializable dicts; on
daemon errors the tool returns `{"error": ...}` instead of crashing the
server.

## Roadmap

- VSCode extension: gutter icon + hover popup
- `--feedback` flag to mark hits irrelevant; persistent per-`(repo,file)` rerank bias
- Tree-sitter symbol extractor (drop the regex fallback)
- `comet-cc-recall index <repo>` for one-shot precomputation against
  long-lived repos
- Long-running JSON-RPC server for editor integrations (no spawn overhead)
- `compare <a> <b>` — nodes mentioning two files (cross-cutting concerns)

## Status

Alpha. The wire format mirrors upstream's existing public RPC; if
CoMeT-CC's daemon protocol changes this package will need a bump. CI
runs against the v0 RPC surface as of CoMeT-CC's main branch.

## License

MIT.
