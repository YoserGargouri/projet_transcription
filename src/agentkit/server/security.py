"""
Mots de passe et jetons (bibliothèque standard uniquement).

- Mots de passe : scrypt (hashlib), sel aléatoire, comparaison à temps constant.
- Sessions et réinitialisations : jeton aléatoire remis au navigateur (cookie HttpOnly) ; seule
  son empreinte SHA-256 est stockée, une fuite de la base ne donne donc aucune session valide.
- Limitation simple des tentatives de connexion, en mémoire (suffisante pour un seul processus).
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import threading
import time

_N, _R, _P = 2**14, 8, 1


def hash_password(password: str) -> str:
    sel = secrets.token_bytes(16)
    h = hashlib.scrypt(password.encode("utf-8"), salt=sel, n=_N, r=_R, p=_P, dklen=32)
    return f"scrypt${_N}${_R}${_P}${base64.b64encode(sel).decode()}${base64.b64encode(h).decode()}"


def verify_password(password: str, stocke: str) -> bool:
    try:
        algo, n, r, p, sel, h = stocke.split("$")
        if algo != "scrypt":
            return False
        calcule = hashlib.scrypt(password.encode("utf-8"), salt=base64.b64decode(sel), n=int(n), r=int(r),
                                 p=int(p), dklen=32)
        return hmac.compare_digest(calcule, base64.b64decode(h))
    except (ValueError, TypeError):
        return False


def new_token() -> str:
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class RateLimiter:
    """Au plus `limite` essais par clé sur une fenêtre glissante de `fenetre_s` secondes."""

    def __init__(self, limite: int = 8, fenetre_s: float = 300):
        self.limite, self.fenetre = limite, fenetre_s
        self._essais: dict[str, list[float]] = {}
        self._lock = threading.Lock()

    def allow(self, cle: str) -> bool:
        maintenant = time.monotonic()
        with self._lock:
            essais = [t for t in self._essais.get(cle, []) if maintenant - t < self.fenetre]
            if len(essais) >= self.limite:
                self._essais[cle] = essais
                return False
            essais.append(maintenant)
            self._essais[cle] = essais
            return True
