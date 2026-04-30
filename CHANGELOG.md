# Changelog

## 0.2.0

New query surfaces:

- **`search "<query>"`** — raw semantic search by free-text, no file
  anchor required. Wraps the daemon's `get_context_window`.
- **`related <node_id>`** — graph walk from a seed node via the
  daemon's `list_linked_nodes` RPC. `--depth 1` or `--depth 2`.
- **`diff [base]`** — recall against the union of files reported by
  `git diff` (or working tree). Skips unsupported languages, dedupes
  hits across files keeping the max score.
- **`context <file>`** — emit a `<recalled-memory>` block ready to paste
  into a fresh Claude / agent prompt. Includes anchor + instruction.

Shared across `recall`, `search`, `related`, `diff`:

- **Filter flags** — `--tag` (repeatable, OR-match), `--importance`
  (repeatable), `--since` (`30d`, `12h`, `2026-04-01`).
- **Output formats** — `-o text|json|md|llm` (`--json` retained as
  shorthand). Markdown cards for docs/PRs; `llm` for prompt priming.

New library exports:

- `from comet_cc_recall import search, related, diff_recall, context_block`
- `from comet_cc_recall.filters import filter_hits, parse_since`

Client additions:

- `DaemonClient.get_node(node_id)`
- `DaemonClient.list_linked_nodes(parent_id)`

## 0.1.0

- Initial release.
- `recall <path>` — file-anchored memory recall.
- `read <node_id> [--depth 0|1|2]` — tiered read.
- `doctor` — daemon reachability + diagnostics.
