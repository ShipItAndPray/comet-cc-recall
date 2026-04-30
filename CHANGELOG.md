# Changelog

## 0.3.0

Three new top-level surfaces, built in parallel by isolated agents and
integrated together:

- **`mcp`** — runs an MCP server over stdio exposing six tools any
  agent can call: `recall_file`, `search`, `related`, `diff_recall`,
  `context_block`, `read_node`. Each tool catches `DaemonError` and
  returns a structured `{"error": ...}` payload instead of crashing the
  server. The MCP SDK is an optional extra: `pip install
  "comet-cc-recall[mcp]"`.
- **`hook`** — manage a non-blocking git hook that surfaces recalled
  memory before each push. Subcommands: `install`, `uninstall`,
  `status`. The hook script is idempotent (sentinel-delimited managed
  block) so it composes with any existing hook content. Defaults to
  `pre-push` but `--hook` accepts any standard git hook name. Never
  blocks the push — it's informational only.
- **`digest`** — periodic tag-grouped summary of recent memory nodes.
  `--since 7d`, `--importance HIGH`, `--top-per-tag 3`, `--max-groups`,
  `-o text|json|md`. Multi-tag nodes are placed in the highest-frequency
  tag's group deterministically. Untagged nodes get their own bucket.
  Children are filtered out so the digest stays parent-only.

Other changes:

- New library exports: `digest`, `Digest`, `DigestGroup`,
  `format_digest_text/md/json`, `hook.install/uninstall/status`,
  `mcp_server.build_server`, `mcp_server.serve_stdio`.
- Coverage: 95% across 1,203 statements, 200 tests passing on Python
  3.10/3.11/3.12, ruff clean.

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
