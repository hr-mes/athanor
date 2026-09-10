# NEXT — verso l'ISO v0

Obiettivo corrente: **un'ISO che si avvia e mostra il greeter.** Non la 1.0.
Roadmap completa e motivazioni in chat con claude-7f; stato in `python3 scripts/verify.py`.

Lavora sul branch `iso-v0`. Esegui i blocchi **nell'ordine**, uno per sessione,
in plan mode. Ogni blocco ha un gate: non passare al successivo finché non è verde.

Prima di tutto, se non è ancora stato fatto:

```bash
git checkout -b iso-v0
git add scripts/verify.py forge/specs/*/*/os.ermete.*.policy \
        forge/specs/ermete-{daemon,gatekeeper,cloud,mdm,lvfs,store}-rs/*.spec
git commit -m "fix(polkit): dichiara e installa le azioni polkit mancanti; le spec leggono i file reali"
git add system/ermete-bus-api/src/polkit.rs $(git diff --name-only | grep -E 'src/(dbus|bedrock|main|dbus_interface|daemon)\.rs$')
git commit -m "fix(security): il subject polkit identifica il chiamante, non il bus"
```

---

## BLOCCO 1 — Tappa 0: far partire il CI

```
Contesto: repo ermete-os, branch iso-v0. Leggi ANALISI_2026-09-02.md §2.2, poi
esegui `python3 scripts/verify.py workflows` per l'elenco esatto.

OBIETTIVO — una sola cosa: i workflow devono essere accettati da GitHub e leggibili.
Nessuna feature, nessun refactor, nessuna modifica alla logica dei job oltre a
quanto elencato.

Problema 1 — 14 step con solo `name:`, senza `run:` né `uses:`. GitHub rifiuta
l'INTERO file ("Required property is missing: uses"): i workflow non partono.
Introdotti il 2026-08-31 da 2596fda7. Sono tutti lo step "Set Default Rust
Toolchain". Per ciascuno: ricostruiscilo (dtolnay/rust-toolchain o un `rustup
default` esplicito) oppure rimuovilo. Non lasciare step vuoti.

Problema 2 — 7 blocchi `if ...; then` / `fi` vuoti in rust-security-audit.yml.
In bash sono errori di sintassi (exit 2), non no-op. Ricostruisci l'installazione
di sccache / cargo-deny / cargo-vet / bpf-linker o togli il blocco.

Problema 3 — rimuovi ogni POST verso webhook.site e lo step "Old dpaste".
Sostituisci con actions/upload-artifact e $GITHUB_STEP_SUMMARY.

Problema 4 — aggiungi un job `lint` che gira per primo in ogni workflow del
percorso ISO (orchestrator, build-builder, dag-compile, system-image) e fallisce se
`actionlint` o `python3 scripts/verify.py workflows` trovano qualcosa.

VINCOLI
- Valida in locale: actionlint, `bash -n` su ogni blocco run:. Non fare push per
  testare.
- Nessun `|| true`, nessun continue-on-error aggiunto.
- Un commit per problema.

GATE: `python3 scripts/verify.py workflows` esce 0, e dopo il push
`gh run list --branch iso-v0` non mostra startup_failure.
```

---

## BLOCCO 2 — Tappa 1 + 2: fondamenta e DAG stretto

Prima, a mano, dieci minuti:

```bash
skopeo inspect --no-tags docker://ghcr.io/hr-mes/ermete-base-nvidia:latest | head
# oppure: gh api /user/packages/container/ermete-base-nvidia/versions
```

Se risponde, vai avanti. Se NON esiste: fermati e dillo a claude-7f — è un blocco
diverso (ricostruire la base o passare a quay.io/fedora/fedora-bootc:43 per la v0).

```
Contesto: repo ermete-os, branch iso-v0. Obiettivo: la build più piccola che
produce un'immagine avviabile. Tutto ciò che non serve al boot esce da QUESTA
build, non dal progetto — è un branch, si ripristina con git.

DA FARE
1. In forge/config/packages.json togli da custom_packages E dai tier:
   mesh-bus, cluster-mesh, mesh-sync, cloud-rs, ai-daemon, ermete-compositor,
   hypervisor-daemon, ermete-net-unikernel, ermete-telemetry, init-oracle,
   sysmon-ebpf, mdm-rs, ermete-greeter, kernel.
   NON toccare il tooling di tier0 (rust-toolchain, mold, sccache, buildah,
   osbuild, cargo-tools, just, uki-tools, ...): serve per costruire il resto.
2. In system/Containerfile togli `rosenpass.service` e `keylime_agent.service`
   dalla riga `systemctl enable`: quei pacchetti hanno una spec ma non sono nel
   DAG, e se la base non li porta il RUN abortisce. Lascia tutto il resto.
3. Verifica che forge/scripts/dag_orchestrator.py produca una matrice coerente
   senza i pacchetti tolti (eseguilo in locale se possibile).
4. Verifica che ogni pacchetto rimasto nel DAG abbia la sua directory in
   forge/specs — `python3 scripts/verify.py shipped` deve scendere, non salire.

VINCOLI
- Nessuna modifica ai crate Rust in questo blocco.
- Nessun `|| true` nel Containerfile.
- Un commit: "build(iso-v0): DAG ridotto alla prova di boot".

GATE: la matrice del DAG contiene solo i pacchetti attesi; `verify.py shipped`
è sceso. Poi: `gh workflow run ermete-forge-orchestrator.yml --ref iso-v0`,
e si legge `gh run view --log-failed`. Fallirà: è normale. Riproduci lo step
nel container ghcr.io/hr-mes/ermete-os-builder in locale prima di correggere.
```

---

## BLOCCO K — il kernel, prima della Tappa 3

Decisione del 2026-09-03: il kernel custom è il primo passo di Ermete OS; la v0
riprende dopo, con il nostro kernel nell'immagine. La specifica approvata è
`docs/architecture/doc_kernel_build.md`: fasi K1–K7, una per sessione, ognuna con
il suo gate (sezione 12). Uso locale e bump a mano in
`forge/specs/ermete-kernel/KERNEL.md`.

---

## Dopo

- **Tappa 3** — cicli di correzione sul DAG finché `ghcr.io/hr-mes/ermete-os-system:<run_id>`
  esiste e `cosign verify` passa.
- **Tappa 4** — ISO: lo step BIB `anaconda-iso`. Se rifiuta `--rootfs=bcachefs`,
  per la v0 usa `btrfs`. Scorciatoia locale: `system/scripts/build_bib.sh <img> <tag> iso` in WSL2.
- **Tappa 5** — boot in VM (mai sul disco per primo), poi hardware. Gate: greeter, login, Settings.
  **Greeter: VERDE il 2026-09-09** — acceptance run 34400804630 su `athanor-iso:34394726609`
  (`greeter reached: greeter-alive`, 152 s dal primo boot; screenshot rivisti). Restano per
  il login e per la pulizia, nessuno bloccante: la card mostra "greetd daemon" invece
  dell'utente umano (`sys/auth.rs:39` legge `$USER`, che sotto greetd è `greetd`); barra
  CSD "Athanor Greeter" con ✕ perché cage non ha layer-shell (sparisce con la Tappa 6, nel
  frattempo `set_decorated(false)` + fullscreen); font delle icone assente (riquadri
  esadecimali); stringhe in italiano ed etichetta "WAYLAND • NIRI" con `lang en_US`;
  `GSK_RENDERER=ngl` è il nome vecchio; il greeter chiede il protocollo Session Lock che
  cage non ha. Login e Settings del gate: prossimi.
- **Tappa 6** — compositore di sessione: **cosmic-comp** (System76, Rust + Smithay) al posto
  di niri. Deciso il 2026-09-09 per l'utente che arriva da Windows/macOS: finestre
  flottanti, barra con minimizza/ripristina, Alt-Tab, aggancio; niri è tiling a scorrimento
  per disegno e il flottante vi è un'eccezione. Greeter e sessione sullo stesso compositore
  (modello cosmic-greeter, greetd resta): via cage e wlroots dal percorso di avvio, che il
  2026-09-09 hanno prodotto un difetto di rendering che non vale per la sessione.
  Fino ad allora **nessuna nuova funzione sull'IPC di niri**: oggi lo nominano 28 file su 185
  (shell 14, settings 5, dock 5, daemon 2, niri-ipc 1), tutto il resto è GTK4 + layer-shell
  e gira invariato. Primo passo: spike di 1–2 giorni, shell e dock sopra cosmic-comp via
  layer-shell, con davanti un utente abituato a Windows. Poi: backend IPC su
  `cosmic-workspace`/`toplevel-info`, niri e `config.kdl` rimossi, residui `athanor-ags`
  cancellati, niri oggi non è nemmeno un RPM. Gate: sessione cosmic-comp con shell, dock e
  Settings; niri, cage e athanor-ags assenti dall'immagine.
  **Greeter su cosmic-comp: VERDE il 2026-09-10** — spike locale (cosmic-comp 1.6.0-3 annidato in
  cage headless: il client riceve `wayland-1`, layer surface accettata, il compositore esce
  con il client), poi commit `d9eb3228` (system-config -25: `cosmic-comp --no-xwayland
  athanor-shell-rs --greeter`, sonda wlroots rimossa, cosmic-comp in packages.json) e collaudo
  `34413831911` su `athanor-iso:34409767682`: PASS, `greeter-alive`, 148 s dal primo boot,
  greeter a schermo intero senza barra CSD. Fatti utili per la sessione: cosmic-comp espone
  layer-shell, toplevel-info, toplevel-management e workspace a ogni client senza
  `wp_security_context` (state.rs, `client_not_sandboxed`), quindi shell e dock non hanno
  bisogno di cosmic-session; `athanor-shell.service`/`athanor-dock.service` vivono in
  `athanor-system-services`, che non è nel DAG della v0; la "patch" floating-first di
  `athanor-niri` è un segnaposto di 17 righe. Prossimo: la sessione (`athanor-session` →
  cosmic-comp + unit utente, `sys/auth.rs:160` manda ancora `XDG_CURRENT_DESKTOP=niri`), poi
  cage via dall'immagine.

  **Sessione su cosmic-comp: commit `6a84f676` (2026-09-10)** — `athanor-session` →
  `cosmic-comp /usr/bin/athanor-desktop`; `athanor-desktop` pubblica il display al manager
  utente e attende `athanor-session.target`, fermarlo è il logout. Corsa risolta con un gate
  `athanor-desktop.service` (oneshot, `wayland-info` fino a che il compositore risponde) che
  il target richiede e shell/dock ordinano dopo con `Requisite=`. Rimossi: `niri-session.target`,
  il preset utente (che abilitava anche un `athanor-wallpaper.service` inesistente) e l'alias
  `athanor-ags.service`; l'hook usbguard ora è in %files. Validato in locale fin dove il nesting
  consente (contratto greetd, import env, gate, target su/giù); le unit sul socket di cosmic-comp
  le prova il collaudo su KMS. In corso: orchestrator 34479642752. Poi: togliere niri e cage
  dall'immagine (packages.json custom_packages/custom_tier1, Requires di shell e system-config)
  e il backend IPC su cosmic-workspace/toplevel-info.

Le 76 spec segnalate da `verify.py specs` non bloccano il boot: vanno nella v1,
insieme alla compilazione della Fase 1 e al boot test della Fase 2
(prompt in PIANO_RIPARTENZA.md).
