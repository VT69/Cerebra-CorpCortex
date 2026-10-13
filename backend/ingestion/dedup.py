"""
Near-duplicate detection for chunks (MinHash, standard library only).

SHA-256 on the whole file only catches byte-identical uploads. An attacker
(or a careless re-export) can upload many slightly edited copies so one
document floods the top-k. MinHash estimates the Jaccard similarity of two
chunks' word-3-shingle sets; a near-copy keeps most shingles, so its
estimated Jaccard stays high while unrelated chunks score near zero.

(SimHash was tried first and rejected: on ~800-char chunks a 3-word edit
moved fingerprints 3-15 bits, and repetitive table chunks collided at 0.)
"""
import hashlib
import re

NUM_PERM = 64
_P = (1 << 61) - 1  # Mersenne prime for universal hashing
_TOKEN = re.compile(r"[a-z0-9]+")


def _coeffs():
    out = []
    for i in range(NUM_PERM):
        d = hashlib.blake2b(f"minhash-{i}".encode(), digest_size=16).digest()
        out.append((int.from_bytes(d[:8], "big") % (_P - 1) + 1, int.from_bytes(d[8:], "big") % _P))
    return out


_COEFFS = _coeffs()


def shingles(text: str, k: int = 3) -> set[str]:
    tokens = _TOKEN.findall(text.lower())
    if len(tokens) < k:
        return {" ".join(tokens)} if tokens else set()
    return {" ".join(tokens[i:i + k]) for i in range(len(tokens) - k + 1)}


def minhash(text: str) -> list[int]:
    """64-value MinHash signature of the chunk's word-3-shingle set."""
    base = [int.from_bytes(hashlib.blake2b(s.encode(), digest_size=8).digest(), "big") for s in shingles(text)]
    if not base:
        return [_P] * NUM_PERM
    return [min((a * h + b) % _P for h in base) for a, b in _COEFFS]


def similarity(sig_a: list[int], sig_b: list[int]) -> float:
    """Estimated Jaccard similarity: fraction of matching signature slots."""
    return sum(x == y for x, y in zip(sig_a, sig_b)) / NUM_PERM


def encode(sig: list[int]) -> str:
    return ",".join(format(v, "x") for v in sig)


def decode(s: str) -> list[int]:
    return [int(v, 16) for v in s.split(",")] if s else []


def is_near_duplicate(sig: list[int], existing: list[list[int]], threshold: float) -> bool:
    """Linear scan — fine for thousands of chunks. At scale, index signatures
    with LSH banding (e.g. 16 bands x 4 rows) to find candidates in O(1)."""
    return any(similarity(sig, e) >= threshold for e in existing)
