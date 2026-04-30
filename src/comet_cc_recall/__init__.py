"""comet-cc-recall — file-anchored memory recall for CoMeT-CC.

Open a source file, get the memory nodes you've already reasoned through
about it, ranked by semantic + repo proximity. Companion query surfaces:
diff-aware recall, raw semantic search, graph-walk by node, context-block
emitter for fresh agent sessions.
"""

from comet_cc_recall.context import context_block
from comet_cc_recall.diff import diff_recall
from comet_cc_recall.recall import RecallHit, recall
from comet_cc_recall.related import related
from comet_cc_recall.search import search

__version__ = "0.3.0"
__all__ = [
    "RecallHit",
    "__version__",
    "context_block",
    "diff_recall",
    "recall",
    "related",
    "search",
]
