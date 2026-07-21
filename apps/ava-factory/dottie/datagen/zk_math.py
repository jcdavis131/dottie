"""ZkMathGenerator — zero-knowledge proofs and the number theory under them.

Solo personal project, no connection to employer, built with public/free-tier only
HOME-only, zero network, private RNG only, byte-identical determinism.

Nothing in the curriculum taught the cryptographic math that ZK rests on. This
generator does, and -- like logic.py and db_trace.py -- every answer is
*computed*, never templated: each doc's protocol transcript is produced by
actually running the group arithmetic, and the verification equation printed in
the doc genuinely holds. Builder functions return ``(text, task_type, concept,
meta)`` so the tests can re-derive every result independently from ``meta``
(re-check g^s == t*y^c, recompute the Merkle root, re-run Lagrange at 0, ...).

Families (all over a prime field / safe-prime group, all verified):
  * modexp    (automatic, p1): y = g^x mod p by square-and-multiply.
  * modinv    (automatic, p1): a^-1 mod p by Fermat and extended Euclid; a*a^-1==1.
  * schnorr   (deliberate, p3): the canonical Sigma protocol for knowledge of a
                discrete log. Commit t=g^r, challenge c, response s=r+cx mod q;
                verifier checks g^s == t*y^c mod p. Honest-verifier zero-knowledge.
  * pedersen  (deliberate, p3): commitment C = g^m * h^r mod p; opening verifies.
  * fiat_shamir(deliberate, p3/p5): the interactive Schnorr made non-interactive
                by deriving the challenge c = H(g|y|t) mod q -- a real SHA-256.
  * merkle    (deliberate, p3/p5): commit to leaves; an inclusion proof (sibling
                path) re-hashes to the committed root. Backbone of STARK/commit.
  * shamir    (deliberate, p3): (t,n) secret sharing over GF(p); any t shares
                reconstruct the secret via Lagrange interpolation at x=0.

Curriculum placement: phases (1, 3, 5).
  p1 math    : the field/number-theory drills (modexp, modinv).
  p3 reason  : the protocols and proofs (schnorr, pedersen, fiat_shamir, merkle, shamir).
  p5 anneal  : verified non-interactive proofs and commitment openings.

Determinism: private random.Random only; SHA-256 via hashlib is pure; no
wall-clock, no network, no global random; sorted structures throughout.
"""
from __future__ import annotations

import hashlib
import random
from typing import Dict, Iterator, List, Tuple

from dottie.datagen.base import Generator, run_cli

# Safe primes p = 2q+1 (q prime). The order-q subgroup of (Z/pZ)* is where the
# discrete-log problems live; a generator of it is any quadratic residue != 1.
_SAFE_PRIMES = [
    23, 47, 59, 83, 107, 167, 179, 227, 263, 347, 359, 383, 467, 479, 503,
    563, 587, 719, 839, 863, 887, 983, 1019, 1187, 1283, 1307, 1319, 1367,
    1439, 1487, 1523, 1619, 1823, 1907, 2039, 2063, 2099, 2207, 2447, 2459,
]


def _subgroup(p: int) -> Tuple[int, int]:
    """Return (q, g): q = (p-1)/2 and the smallest generator g of the order-q
    subgroup (smallest quadratic residue != 1). q is prime for a safe prime, so
    any such g has order exactly q."""
    q = (p - 1) // 2
    g = 2
    while pow(g, q, p) != 1:
        g += 1
    return q, g


def _egcd(a: int, b: int) -> Tuple[int, int, int]:
    """Extended Euclid: return (gcd, s, t) with a*s + b*t = gcd."""
    old_r, r = a, b
    old_s, s = 1, 0
    old_t, t = 0, 1
    while r:
        quot = old_r // r
        old_r, r = r, old_r - quot * r
        old_s, s = s, old_s - quot * s
        old_t, t = t, old_t - quot * t
    return old_r, old_s, old_t


def _inv(a: int, p: int) -> int:
    """Modular inverse of a mod prime p (Fermat)."""
    return pow(a, p - 2, p)


def _h16(s: str) -> str:
    """First 16 hex chars of SHA-256 of s (deterministic, offline)."""
    return hashlib.sha256(s.encode("utf-8")).hexdigest()[:16]


def _challenge(preimage: str, q: int) -> int:
    """Fiat-Shamir: hash the transcript prefix to a challenge in [0, q)."""
    return int(hashlib.sha256(preimage.encode("utf-8")).hexdigest(), 16) % q


# ---------------------------------------------------------------------------
# p1 drills
# ---------------------------------------------------------------------------

def _modexp_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice(_SAFE_PRIMES)
    g = rng.randint(2, p - 2)
    x = rng.randint(2, p - 2)
    y = pow(g, x, p)
    # square-and-multiply trace (verified: product of selected squares == y)
    bits = bin(x)[2:]
    acc = 1
    steps = []
    for b in bits:
        acc = (acc * acc) % p
        op = "square"
        if b == "1":
            acc = (acc * g) % p
            op = "square, mul by g"
        steps.append((b, op, acc))
    assert acc == y
    trace = "\n".join(f"  bit {b}: {op:>16} -> acc = {a}" for b, op, a in steps)
    meta = {"p": p, "g": g, "x": x, "y": y}
    text = f"""### Task: compute {g}^{x} mod {p} by square-and-multiply.

Modular exponentiation is the one-way street discrete-log crypto walks down:
computing y = g^x mod p is cheap, inverting it (finding x) is hard. That gap is
what a zero-knowledge proof of knowledge of x exploits.

Read the exponent x = {x} = binary {bits}. Start acc = 1; for each bit left to
right, square, and multiply by g when the bit is 1:
{trace}

Answer: {g}^{x} mod {p} = {y}. (Verified: pow({g},{x},{p}) = {y}.)

Source: zk_math/modexp -- p1 automatic, the primitive under Schnorr/ElGamal.
"""
    return text, "automatic", "modexp", meta


def _modinv_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice(_SAFE_PRIMES)
    a = rng.randint(2, p - 2)
    inv = _inv(a, p)
    g_, s_, _ = _egcd(a, p)
    s_mod = s_ % p
    assert (a * inv) % p == 1 and g_ == 1 and s_mod == inv
    meta = {"p": p, "a": a, "inv": inv}
    text = f"""### Task: find the modular inverse of {a} mod {p}.

In a prime field GF({p}) every nonzero element is invertible -- this is what
lets us divide, and it is the workhorse of Lagrange interpolation, elliptic
curve slopes, and commitment openings.

Two ways, same answer:
  1. Fermat: since {p} is prime, a^(p-1) = 1, so a^-1 = a^(p-2) mod p =
     {a}^{p - 2} mod {p} = {inv}.
  2. Extended Euclid on ({a}, {p}) gives gcd 1 = {a}*s + {p}*t with s = {s_ % p}
     (mod {p}), matching {inv}.

Check: {a} * {inv} mod {p} = {(a * inv) % p}. Answer: {a}^-1 = {inv} (mod {p}).

Source: zk_math/modinv -- p1 automatic, field arithmetic for ZK.
"""
    return text, "automatic", "modinv", meta


# ---------------------------------------------------------------------------
# p3 protocols
# ---------------------------------------------------------------------------

def _schnorr_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice([pp for pp in _SAFE_PRIMES if pp >= 47])
    q, g = _subgroup(p)
    x = rng.randint(2, q - 1)          # the secret (a discrete log)
    y = pow(g, x, p)                    # public key y = g^x
    r = rng.randint(2, q - 1)          # nonce
    t = pow(g, r, p)                    # commitment
    c = rng.randint(1, q - 1)          # verifier's challenge
    s = (r + c * x) % q                # response
    lhs = pow(g, s, p)
    rhs = (t * pow(y, c, p)) % p
    assert lhs == rhs
    meta = {"p": p, "q": q, "g": g, "x": x, "y": y, "r": r, "t": t, "c": c, "s": s}
    text = f"""### Task: run a Schnorr zero-knowledge proof of knowledge of a discrete log.

Setup: prime p = {p}, order-q subgroup q = {q}, generator g = {g}. The prover
knows a secret x with public key y = g^x mod p = {y}. She will convince a
verifier she knows x WITHOUT revealing it.

The Sigma protocol (commit -> challenge -> respond):
  1. Commit : prover picks nonce r = {r}, sends t = g^r mod p = {t}.
  2. Challenge: verifier picks c = {c} and sends it.
  3. Respond : prover sends s = r + c*x mod q = {r} + {c}*{x} mod {q} = {s}.

Verification: g^s ?= t * y^c (mod p).
  LHS: g^s = {g}^{s} mod {p} = {lhs}
  RHS: t*y^c = {t} * {y}^{c} mod {p} = {rhs}
  {lhs} == {rhs}  -> ACCEPT.

Why it is zero-knowledge: a simulator with no secret can pick s and c first and
set t = g^s * y^-c, producing an identically-distributed transcript. The
verifier learns nothing about x beyond "she knows it". Soundness: a prover who
could answer two different challenges c1,c2 on the same t would let you solve
x = (s1-s2)/(c1-c2) mod q -- so she must actually know x.

Source: zk_math/schnorr -- p3 deliberate, the canonical Sigma protocol.
"""
    return text, "deliberate", "schnorr", meta


def _pedersen_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice([pp for pp in _SAFE_PRIMES if pp >= 47])
    q, g = _subgroup(p)
    a = rng.randint(2, q - 1)
    h = pow(g, a, p)                    # second generator h = g^a (dlog unknown to prover)
    m = rng.randint(1, q - 1)          # committed message
    r = rng.randint(1, q - 1)          # blinding factor
    C = (pow(g, m, p) * pow(h, r, p)) % p
    assert C == (pow(g, m, p) * pow(h, r, p)) % p
    meta = {"p": p, "q": q, "g": g, "h": h, "m": m, "r": r, "C": C}
    text = f"""### Task: build and open a Pedersen commitment.

Setup: p = {p}, subgroup order q = {q}, generators g = {g} and h = {h}. A
Pedersen commitment to message m hides m while binding the committer to it:

  Commit : C = g^m * h^r mod p, with a fresh blinding r.
    m = {m}, r = {r}  ->  C = {g}^{m} * {h}^{r} mod {p} = {C}.

  Open   : reveal (m, r); the verifier recomputes g^m*h^r and checks it equals C.
    g^{m}*h^{r} mod {p} = {C} == C  -> valid opening.

Hiding: for any m, a uniform r makes C uniform, so C leaks nothing about m.
Binding: opening C to a different (m', r') would require knowing log_g(h) = {a}
(kept secret), which is the discrete log we assume is hard. Additively
homomorphic: C(m1,r1)*C(m2,r2) = C(m1+m2, r1+r2), which is why Pedersen is the
commitment inside range proofs and Bulletproofs.

Source: zk_math/pedersen -- p3 deliberate, hiding+binding commitment.
"""
    return text, "deliberate", "pedersen", meta


def _fiat_shamir_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice([pp for pp in _SAFE_PRIMES if pp >= 47])
    q, g = _subgroup(p)
    x = rng.randint(2, q - 1)
    y = pow(g, x, p)
    r = rng.randint(2, q - 1)
    t = pow(g, r, p)
    preimage = f"{g}|{y}|{t}"
    c = _challenge(preimage, q)        # non-interactive challenge from the transcript
    s = (r + c * x) % q
    lhs = pow(g, s, p)
    rhs = (t * pow(y, c, p)) % p
    assert lhs == rhs
    meta = {"p": p, "q": q, "g": g, "x": x, "y": y, "r": r, "t": t,
            "c": c, "s": s, "preimage": preimage}
    text = f"""### Task: make the Schnorr proof non-interactive with Fiat-Shamir.

The interactive proof needs a live verifier to supply a random challenge. The
Fiat-Shamir transform removes that: derive the challenge by HASHING the
transcript so far. A random oracle stands in for the verifier's coin.

Setup: p = {p}, q = {q}, g = {g}, public key y = g^x mod p = {y}.
Proof (a single message (t, s)):
  1. t = g^r mod p, r = {r}  ->  t = {t}.
  2. c = SHA-256("{preimage}") mod q = {c}.   # the verifier is replaced by H
  3. s = r + c*x mod q = {s}.

Verify (anyone, no interaction): recompute c = SHA-256("g|y|t") mod q from the
public (g, y, t), then check g^s ?= t * y^c mod p.
  LHS g^s = {lhs}; RHS t*y^c = {rhs}; {lhs} == {rhs} -> ACCEPT.

This is exactly how a Schnorr SIGNATURE works (bind the message into the hash:
c = H(g|y|t|msg)). The security caveat is real: the challenge must hash the
commitment t, or the proof is forgeable -- the classic "weak Fiat-Shamir" bug.

Source: zk_math/fiat_shamir -- deliberate, interactive -> non-interactive (NIZK).
"""
    return text, "deliberate", "fiat_shamir", meta


def _merkle_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    depth = rng.choice([2, 3])
    n = 2 ** depth
    leaves = [f"tx{rng.randint(0, 999):03d}" for _ in range(n)]
    leaf_h = [_h16("leaf:" + v) for v in leaves]
    # build the tree bottom-up; record levels for the proof path
    levels = [leaf_h]
    while len(levels[-1]) > 1:
        cur = levels[-1]
        nxt = [_h16(cur[i] + cur[i + 1]) for i in range(0, len(cur), 2)]
        levels.append(nxt)
    root = levels[-1][0]
    # inclusion proof for a random leaf: the sibling at each level
    idx = rng.randrange(n)
    proof = []
    j = idx
    for lvl in levels[:-1]:
        sib = j ^ 1
        proof.append((("R" if j % 2 == 0 else "L"), lvl[sib]))
        j //= 2
    # verify by recomputing (also done independently in the test)
    acc = leaf_h[idx]
    for side, sib in proof:
        acc = _h16(acc + sib) if side == "R" else _h16(sib + acc)
    assert acc == root
    meta = {"leaves": leaves, "leaf_hashes": leaf_h, "root": root,
            "index": idx, "proof": proof}
    proof_str = "\n".join(f"  level {i}: sibling on the {('right' if s=='R' else 'left')} = {h}"
                          for i, (s, h) in enumerate(proof))
    text = f"""### Task: verify a Merkle inclusion proof.

A Merkle tree commits to a whole list with one hash (the root); an inclusion
proof shows a leaf is in the list using only log2(n) sibling hashes. This is the
commitment backbone of STARKs, Certificate Transparency, and every rollup.

Leaves (n = {n}): {leaves}
Leaf hashes h(leaf) = SHA-256("leaf:"+value)[:16]:
{chr(10).join(f'  {i}: {h}' for i, h in enumerate(leaf_h))}
Parent = SHA-256(left_child + right_child)[:16], up to the root = {root}.

Prove leaf #{idx} ("{leaves[idx]}", hash {leaf_h[idx]}) is included. Path:
{proof_str}

Fold the leaf hash with each sibling (order matters: our leaf on the named side):
  start {leaf_h[idx]} -> ... -> {root}
Recomputed root == committed root {root} -> ACCEPT. The verifier never sees the
other {n - 1} leaves; the {len(proof)} siblings suffice.

Source: zk_math/merkle -- deliberate, log-size commitment/opening.
"""
    return text, "deliberate", "merkle", meta


def _shamir_doc(rng: random.Random) -> Tuple[str, str, str, dict]:
    p = rng.choice([pp for pp in _SAFE_PRIMES if pp >= 227])
    t = rng.choice([2, 3])             # threshold
    n = t + rng.choice([1, 2])         # number of shares
    secret = rng.randint(1, p - 1)
    coeffs = [secret] + [rng.randint(0, p - 1) for _ in range(t - 1)]

    def f(xv: int) -> int:
        return sum(co * pow(xv, k, p) for k, co in enumerate(coeffs)) % p

    shares = [(i, f(i)) for i in range(1, n + 1)]
    used = shares[:t]                  # any t shares reconstruct
    # Lagrange interpolation at x = 0 over GF(p)
    rec = 0
    for j, (xj, yj) in enumerate(used):
        num, den = 1, 1
        for m, (xm, _ym) in enumerate(used):
            if m == j:
                continue
            num = (num * (-xm)) % p
            den = (den * (xj - xm)) % p
        rec = (rec + yj * num * _inv(den % p, p)) % p
    assert rec == secret
    meta = {"p": p, "t": t, "n": n, "secret": secret, "coeffs": coeffs,
            "shares": shares, "used": used, "recovered": rec}
    share_str = ", ".join(f"({i}, {v})" for i, v in shares)
    used_str = ", ".join(f"({i}, {v})" for i, v in used)
    text = f"""### Task: reconstruct a Shamir-shared secret over GF({p}).

Shamir ({t}-of-{n}) secret sharing hides a secret as the constant term of a
degree-{t - 1} polynomial over GF({p}); any {t} of the {n} shares recover it,
any {t - 1} learn nothing. This polynomial-over-a-field idea is the seed of MPC
and of polynomial-commitment SNARKs (PLONK/KZG).

Secret s = f(0) = {secret}. Polynomial f(x) = {' + '.join(f'{c}*x^{k}' for k, c in enumerate(coeffs))} mod {p}.
Shares (x, f(x)): {share_str}

Reconstruct from the first {t} shares [{used_str}] by Lagrange interpolation at
x = 0:  s = sum_j y_j * prod_{{m!=j}} (0 - x_m)/(x_j - x_m) mod p.
Each division uses the modular inverse in GF({p}).

Recovered secret = {rec} == f(0) = {secret} -> correct. Fewer than {t} shares
leave the constant term uniformly undetermined, so they reveal nothing.

Source: zk_math/shamir -- deliberate, polynomials over a finite field.
"""
    return text, "deliberate", "shamir", meta


class ZkMathGenerator(Generator):
    name = "zk_math"
    phases = (1, 3, 5)

    _P1 = [_modexp_doc, _modinv_doc]
    _P3 = [_schnorr_doc, _pedersen_doc, _fiat_shamir_doc, _merkle_doc, _shamir_doc]
    _P5 = [_fiat_shamir_doc, _merkle_doc, _schnorr_doc]  # verified proofs at anneal

    def generate(self, target_bytes: int) -> Iterator[dict]:
        bytes_so_far = 0
        idx = 0
        while bytes_so_far < target_bytes:
            phase = self.rng.choice([1, 3, 5])
            if phase == 1:
                builder = self.rng.choice(self._P1)
            elif phase == 3:
                builder = self.rng.choice(self._P3)
            else:
                builder = self.rng.choice(self._P5)
            text, task_type, concept, _meta = builder(self.rng)
            idx += 1
            bytes_so_far += len(text.encode("utf-8")) + 200
            yield self.doc(text=text, task_type=task_type, concept=concept,
                           phase=phase, source=f"zk_math/{concept}")


if __name__ == "__main__":
    run_cli(ZkMathGenerator)
