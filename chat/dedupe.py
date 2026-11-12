"""Near-duplicate detection for memories (Phase 4).

Pure functions over plain text — no Django imports, so the rules
are testable in isolation and reusable from both the harvest path
(skip a fact KAI already knows in slightly different words) and
the duplicates endpoint (show the user groups worth merging).

Similarity is Jaccard over word tokens: two facts are near
duplicates when they share most of their words, or when one
fact's words are entirely contained in the other (a shorter
restatement of the same fact). The threshold is deliberately
high — merging two DISTINCT facts would lose knowledge, while
missing a borderline duplicate only costs one extra row.
"""

import re

THRESHOLD = 0.8
_MIN_CONTAINMENT_TOKENS = 3

_WORD = re.compile(r"[a-z0-9]+")


def tokens(fact):
    """Lowercased word tokens, punctuation stripped."""
    return set(_WORD.findall(fact.lower()))


def similarity(a, b):
    """Jaccard similarity of two facts' token sets, 0.0–1.0."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def is_near_duplicate(a, b, threshold=THRESHOLD):
    """True when two facts say the same thing in different words."""
    ta, tb = tokens(a), tokens(b)
    if not ta or not tb:
        return False
    if ta == tb:
        return True
    if len(ta & tb) / len(ta | tb) >= threshold:
        return True
    # Containment: one fact restates the other plus extra words.
    smaller, larger = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    return len(smaller) >= _MIN_CONTAINMENT_TOKENS and smaller <= larger


def group_duplicates(memories):
    """Group Memory objects into near-duplicate clusters.

    Returns a list of groups (each a list of Memory objects, size
    >= 2). Clustering is transitive: A~B and B~C put all three in
    one group even when A and C are not directly similar.
    """
    items = list(memories)
    token_sets = [tokens(m.fact) for m in items]
    parent = list(range(len(items)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        parent[find(i)] = find(j)

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            ta, tb = token_sets[i], token_sets[j]
            if not ta or not tb:
                continue
            shared = len(ta & tb)
            if shared / len(ta | tb) >= THRESHOLD:
                union(i, j)
                continue
            smaller, larger = (
                (ta, tb) if len(ta) <= len(tb) else (tb, ta)
            )
            if len(smaller) >= _MIN_CONTAINMENT_TOKENS and smaller <= larger:
                union(i, j)

    groups = {}
    for i, memory in enumerate(items):
        groups.setdefault(find(i), []).append(memory)
    return [g for g in groups.values() if len(g) >= 2]


def pick_keeper(group):
    """The memory to keep when a group merges: a confirmed fact
    wins over a suggestion (it already passed the user's gate);
    among equals, the oldest (first learned) wins."""
    return sorted(
        group,
        key=lambda m: (
            0 if m.status == "confirmed" else 1,
            m.created_at,
            m.pk,
        ),
    )[0]
