"""comet-cc-recall — file-anchored memory recall for CoMeT-CC.

Open a source file, get the memory nodes you've already reasoned through
about it, ranked by semantic + repo proximity.
"""

from comet_cc_recall.recall import RecallHit, recall

__version__ = "0.1.0"
__all__ = ["recall", "RecallHit", "__version__"]
