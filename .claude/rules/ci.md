---
paths:
  - ".github/workflows/**"
  - "Justfile"
  - "**/Justfile"
  - "scripts/verify.py"
---

# CI e build

## Valida in locale, non con un push

I workflow del percorso ISO si validano prima di committare:

```
actionlint
python3 scripts/verify.py workflows
bash -n   # su ogni blocco run: non banale
```

Non usare il push come test. Un `startup_failure` su GitHub costa più di trenta
secondi di verifica locale.

## Errori già visti su questo repository

- **Step con solo `name:`**, senza `run:` né `uses:`. GitHub rifiuta l'**intero
  file**, non solo lo step: i workflow non partono affatto. Se ricostruisci uno
  step, dagli un corpo o rimuovilo. Mai lasciarlo vuoto.
- **Blocchi `if ...; then` / `fi` vuoti**. In bash sono errori di sintassi con
  uscita 2, non no-op silenziosi.
- **POST verso servizi esterni** per i log. Usa `actions/upload-artifact` e
  `$GITHUB_STEP_SUMMARY`.

## Vincoli

- Mai aggiungere `|| true` o `continue-on-error` per far passare un job. Un job
  che fallisce sta dicendo qualcosa.
- Un commit per problema, non un commit che sistema tutto.
- Ogni workflow del percorso ISO ha un job `lint` che gira per primo.

## Justfile

`just lint`, `just format`, `just check-syntax` sono le porte d'ingresso.
Il Justfile stesso è formattato da `just --unstable --fmt`: se lo modifichi,
`just check-syntax` deve restare verde.
