# Security — Personal Portfolio

## Principio
I secret (Service Account key Google, API key AI) **non entrano mai nel repository**.
Vengono forniti al container **a runtime**, tramite volume montato o variabili ambiente.

## Cosa non committare mai
- Service Account JSON (`*service_account*.json`, contenuti in `secrets/`)
- File `.env` (solo `.env.example` è versionato)
- Chiavi private (`*.key`, `*.pem`), DB (`*.db`), backup (`backups/`)

Tutti coperti da `.gitignore`.

## Enforcement automatico (ADR-0011)
Hook `pre-commit` in `.githooks/pre-commit`: fa **grep del contenuto** dei file staged cercando
marcatori di secret e **blocca il commit** se li trova:
```
private_key | client_email | auth_uri | token_uri | -----BEGIN ... PRIVATE KEY-----
```
Criterio sul **contenuto**, non sulla dimensione: non blocca `package.json`/`tsconfig.json` legittimi.

### Attivazione (una tantum, dopo il clone)
```bash
git config core.hooksPath .githooks
# su Windows Git Bash il file è già eseguibile; su Linux/Mac:
chmod +x .githooks/pre-commit
```

### Test del hook
```bash
# crea una fake key e prova a committarla: il commit deve essere BLOCCATO
printf '{"private_key":"-----BEGIN PRIVATE KEY-----\\nX\\n-----END PRIVATE KEY-----","client_email":"x@y"}' > /tmp/fake_sa.json
git add -f /tmp/fake_sa.json && git commit -m "test" ; echo "exit=$?"
# atteso: "BLOCKED ..." + exit diverso da 0. Poi: git reset /tmp/fake_sa.json
```

## Come fornire le credenziali a runtime
1. **Service Account Google** (backup, Fase 4): salva il JSON in `./secrets/service_account.json`
   sull'host. `docker-compose.yml` lo monta **read-only** su `/secrets`. Path in `.env`:
   `GOOGLE_SA_KEY_PATH=/secrets/service_account.json`.
2. **API key AI** (Fase 6): imposta `AI_API_KEY` in `.env` (non committato).

La cartella `secrets/` esiste nel repo solo con un `.gitkeep`; il contenuto reale è ignorato.
