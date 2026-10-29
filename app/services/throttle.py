"""Limite de tentativas de login por conexão (IP), em memória.

O bloqueio é da conexão que errou, não da conta: assim ninguém tranca o dono do painel ou um
cliente errando a senha dele de propósito. Duas regras:
- mesma conexão + mesma conta: PER_ACCOUNT erros em WINDOW bloqueiam essa combinação;
- mesma conexão em qualquer conta: PER_IP erros em WINDOW bloqueiam a conexão (testar senhas
  fáceis em muitos telefones).
Cada processo do servidor guarda o seu (com 2 processos o limite real fica no máximo o dobro).
"""

import time
from collections import defaultdict, deque

PER_ACCOUNT = 5
PER_IP = 20
WINDOW = 15 * 60


class Throttle:
    def __init__(self):
        self._fails = defaultdict(deque)

    def _recent(self, key, now):
        q = self._fails[key]
        while q and now - q[0] > WINDOW:
            q.popleft()
        if not q:
            self._fails.pop(key, None)
        return len(q)

    def blocked(self, ip, account):
        now = time.monotonic()
        return (self._recent(("conta", ip, account), now) >= PER_ACCOUNT
                or self._recent(("ip", ip), now) >= PER_IP)

    def fail(self, ip, account):
        now = time.monotonic()
        self._fails[("conta", ip, account)].append(now)
        self._fails[("ip", ip)].append(now)

    def success(self, ip, account):
        self._fails.pop(("conta", ip, account), None)

    def clear(self):
        self._fails.clear()


customer_logins = Throttle()
admin_logins = Throttle()
