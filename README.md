# My Brain Is Full — Sanitized Runtime Pack

Ez a repo most egy letisztított, publikus export.

Nem egy teljes privát vault vagy teljes upstream tükör, hanem a szanitizált, újrahasznosítható runtime-hardening réteg:

- `references/runtime-hardening/scripts/` — determinisztikus guardok, auditok és orchestrator példák
- `references/runtime-hardening/tests/` — a csomag regressziós tesztjei
- `references/runtime-hardening/README.md` — rövid használati és scope leírás

Mi nincs benne:

- személyes note-ok, daily-k, operational state fájlok
- kontaktok, email helper-ek, lokális launch/config zaj
- egyedi, privát tartalomra kötött workflow-darabok

Gyors ellenőrzés:

```bash
python3 -m unittest discover -s references/runtime-hardening/tests -v
```

Megjegyzés:

- a csomag vault-szerű struktúrát feltételez, például `07-Daily/`, `Meta/Operational/`, `Meta/Temporal/Events/`
- referenciaanyagként van publikálva, nem kész termékként
