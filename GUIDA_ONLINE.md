# FantaBanda online - guida rapida

## Come funziona
- **Il database resta sul computer dell'admin** (`fantamusica_dati.json`, lo stesso file del gioco da terminale). L'app Kivy lo **pubblica su Supabase** a ogni modifica (entro 4 secondi) e ne tiene una copia di sicurezza online.
- **I giocatori usano una pagina web** (`index.html`): classifiche, squadre, eventi, pending, mercato e scambi, statistiche, storico, asta live. Entrano con il **loro codice personale**.
- Quando un giocatore **propone un evento, vota un sondaggio, propone/accetta uno scambio o cambia un soprannome**, la richiesta va su Supabase. **L'app dell'admin la applica con le regole di `fantamusica.py`** e ripubblica. Per questo **l'app dell'admin deve restare aperta mentre si gioca**: se è chiusa i giocatori vedono i dati ma le loro richieste restano "in attesa".
- L'admin continua a fare tutto dall'app (registrare eventi, confermare le proposte, asta, utenti...). Gli eventi proposti dai giocatori finiscono sempre in PENDING finché l'admin non li conferma.

## Dove va ogni file

| File | Dove | Pubblico? |
|---|---|---|
| `fantamusica.py` (originale) | cartella del gioco sul computer dell'admin | no |
| `fantamusica_kivy.py` (nuovo) | stessa cartella | no |
| `fm_online.py` (nuovo) | stessa cartella | no |
| `fantamusica_online.json` | stessa cartella. Contiene `admin_code` = la chiave privata | **MAI** su GitHub, a nessuno |
| `fantamusica_dati.json`, cartelle `foto`, `backup` | stessa cartella (le crea il gioco) | no |
| `supabase_gioco.sql` | si incolla nel SQL Editor di Supabase e basta | no |
| `index.html` | **unico file su GitHub**, nella radice del repository | sì (contiene solo l'indirizzo e la chiave "anon", pubbliche per natura) |

`fantamusica_online.json` ha questa forma (cambia solo `web_url`):

```json
{"url": "https://dyzvtfprezdhfnxiwlez.supabase.co", "anon_key": "...", "admin_code": "IL-TUO-CODICE-ADMIN", "web_url": "https://TUOUTENTE.github.io/NOMEREPO/"}
```

## Una tantum (circa 10 minuti)

1. **Supabase** → SQL Editor → New query → incolla tutto `supabase_gioco.sql` → Run. (Lo script dell'asta lo hai già eseguito: serve prima quello. Si può rieseguire senza danni.)
2. **GitHub**: nel repository → *Add file → Upload files* → trascina **`index.html`** (deve chiamarsi esattamente così, nella radice, non dentro una cartella) → *Commit changes*. Se c'è ancora `asta.html` puoi cancellarlo: l'asta ora è una scheda di `index.html`.
   *Settings → Pages* → Source: *Deploy from a branch* → Branch `main`, cartella `/ (root)` → Save. Dopo 1-2 minuti in alto compare "Your site is live at ..." : quello è l'indirizzo da dare ai giocatori. Se vedi 404: controlla il nome del file, che sia nella radice, che il repository sia pubblico, e guarda la scheda *Actions* (deve esserci una pubblicazione con la spunta verde).
3. **Computer dell'admin**: copia nella cartella del gioco `fantamusica_kivy.py` (sostituisce il vecchio) e `fm_online.py`. Scrivi l'indirizzo della pagina in `web_url` dentro `fantamusica_online.json`.

## Ogni volta che si gioca
1. Avvia l'app (`python3 fantamusica_kivy.py`) e accedi come admin. In alto a destra compare **● ONLINE** (dopo pochi secondi). Se compare "● OFFLINE" apri *Pannello admin → GIOCO ONLINE*: c'è l'ultimo errore.
2. *Pannello admin → GIOCO ONLINE → CODICI DEI GIOCATORI* → **COPIA TUTTO** e manda a ognuno il suo codice (e l'indirizzo della pagina). I codici valgono per tutto: gioco e asta. Il codice admin, usato sulla pagina, dà solo una vista da osservatore.
3. I giocatori aprono la pagina, scrivono il codice (resta salvato sul telefono).
4. Asta live: *Pannello admin → Asta musicisti → ASTA LIVE ONLINE*, come prima. I giocatori la vedono nella scheda **Asta**.

## Primo collegamento e due computer
- Se online non c'è ancora nulla, i dati di questo computer vengono pubblicati.
- Se online c'è un salvataggio che questo computer non ha pubblicato (per esempio hai giocato da un altro PC), l'app chiede se **usare i dati di questo computer** (sovrascrive online) o **scaricare quelli online** (prima fa un backup locale).
- Su un computer nuovo, nella schermata del primo avvio c'è **OPPURE SCARICA I DATI ONLINE**.

## Cose da sapere
- Non usare nello stesso momento il gioco da terminale e l'app: lavorano sullo stesso file. Se fai modifiche dal terminale (azioni, bonus, chiusura stagione...), chiudi il terminale, poi apri l'app: pubblica tutto all'avvio.
- La pagina web non mostra le foto (solo iniziali); le foto restano nell'app.
- Ogni giocatore può avere al massimo 8 richieste in attesa; vede lo stato nel pulsante **Richieste** in alto.
- Rigenerare i codici (CODICI DEI GIOCATORI → RIGENERA) blocca subito i vecchi.
- La chiave privata è `admin_code`. Se pensi sia trapelata: cambiala nello script dell'asta (riga `insert into asta_config ... 'admin_codice'`), riesegui lo script in Supabase e aggiorna `fantamusica_online.json`.

## Prova veloce prima di giocare (5 minuti)
1. App aperta, **● ONLINE**.
2. Dal telefono apri la pagina, entra con il codice di un giocatore.
3. Eventi → *Proponi un evento*, scegli un'azione e un musicista → *Proponi*.
4. Entro 4-5 secondi sul telefono compare "Proposta inviata..."; nell'app, *Pending*, l'evento è **DA CONFERMARE**. Confermalo: sul telefono la classifica si aggiorna da sola.
