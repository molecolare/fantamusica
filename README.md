# FantaMusica online

Il gioco di sempre, ma raggiungibile da qualsiasi browser (PC, telefono, tablet).
Si apre una pagina con un **terminale** identico a quello che usavi sul computer: stessi menu, stessi comandi.
I dati sono in un database condiviso (Supabase), così tutti i giocatori vedono le stesse cose.

```
Browser  ──►  Render (server.py + fantamusica.py)  ──►  Supabase (database Postgres)
```

- **GitHub**: contiene il codice. Render lo scarica da lì a ogni aggiornamento.
- **Render**: esegue il programma e gli dà un indirizzo web (`https://fantamusica-xxxx.onrender.com`).
- **Supabase**: conserva i dati in modo permanente. Il disco di Render si cancella a ogni riavvio, quindi senza Supabase perderesti tutto.

Costo: 0 €. Con 6 giocatori sei largamente dentro i limiti gratuiti.

---

## 1. Supabase (il database) — circa 5 minuti

1. Vai su <https://supabase.com>, crea un account e poi **New project**.
   - Nome a piacere (es. `fantamusica`), scegli una **password del database** e **segnatela** (usa solo lettere e numeri, evita simboli come `@ : / # ?`: complicano la stringa di connessione).
   - Regione: una europea (es. Frankfurt o Paris).
2. Quando il progetto è pronto clicca **Connect** (in alto) e scegli **Session pooler**.
   Copia la stringa, che assomiglia a:
   `postgresql://postgres.abcdefgh:[YOUR-PASSWORD]@aws-0-eu-central-1.pooler.supabase.com:5432/postgres`
3. Sostituisci `[YOUR-PASSWORD]` con la tua password del database. Questa è la tua **DATABASE_URL**: tienila a portata di mano e non pubblicarla mai.

> Usa proprio il *Session pooler*: la "Direct connection" funziona solo su IPv6 e da Render non si collega.

Non devi creare tabelle: il programma le crea da solo al primo avvio (in uno schema privato, con la sicurezza a livello di riga attiva, perché dentro ci sono gli hash delle password).

## 2. GitHub (il codice) — circa 5 minuti

1. Crea un account su <https://github.com> e poi **New repository**. Nome `fantamusica`, imposta **Private** (consigliato), non aggiungere README/gitignore.
2. Carica i file di questa cartella. Il modo più semplice senza usare il terminale: nella pagina del repository clicca **uploading an existing file** e trascina dentro **tutti** i file e la cartella `static` (devono restare `static/index.html`, `server.py`, `fantamusica.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `migra_su_database.py`, `README.md`). Poi **Commit changes**.

   Oppure da terminale, dentro la cartella:
   ```bash
   git init
   git add .
   git commit -m "FantaMusica online"
   git branch -M main
   git remote add origin https://github.com/TUO-UTENTE/fantamusica.git
   git push -u origin main
   ```
3. Controlla che **non** sia stato caricato `fantamusica_dati.json` (i dati e le password): il file `.gitignore` serve proprio a evitarlo.

## 3. Render (il sito) — circa 10 minuti

1. Su <https://render.com> crea un account e accedi con GitHub.
2. **New → Web Service**, scegli il repository `fantamusica` (la prima volta Render ti chiede di autorizzare l'accesso).
3. Compila:
   | Campo | Valore |
   |---|---|
   | Language / Runtime | `Python 3` |
   | Branch | `main` |
   | Build Command | `pip install -r requirements.txt` |
   | Start Command | `gunicorn -k gthread -w 1 --threads 32 --timeout 120 -b 0.0.0.0:$PORT server:app` |
   | Instance Type | **Free** |
4. In **Environment Variables** aggiungi:
   | Nome | Valore |
   |---|---|
   | `DATABASE_URL` | la stringa di Supabase del punto 1 |
   | `FANTAMUSICA_SETUP_CODE` | un codice a tua scelta (serve solo al primo avvio, vedi sotto) |
   | `PYTHON_VERSION` | `3.12.7` |
   | `TZ` | `Europe/Rome` (così gli orari degli eventi sono quelli italiani) |
5. **Create Web Service**. Dopo qualche minuto in alto compare l'indirizzo `https://….onrender.com`.

(In alternativa a 3 e 4 c'è `render.yaml`: **New → Blueprint** e Render compila tutto da solo, ti chiede solo i due valori segreti.)

## 4. Primo avvio

**Apri tu l'indirizzo per primo.** La prima persona che entra crea l'account admin: per questo il programma chiede il *codice di installazione* (`FANTAMUSICA_SETUP_CODE`), così uno sconosciuto che trovasse il link non può prendersi il gioco.

1. Scrivi il codice, poi nome e password dell'admin.
2. Accedi → **PANNELLO ADMIN → Gestione utenti → Aggiungi utente** per ogni giocatore (max 6).
3. Manda a ciascuno l'indirizzo, il suo nome utente e la password iniziale. Dopo l'accesso possono cambiarla e impostare il recupero password da *Impostazioni*.
4. Da qui in poi è come sempre: musicisti, asta, eventi…

### Se hai già dati sul computer
Prima di aprire il sito, dal tuo computer (serve Python):
```bash
pip install "psycopg[binary]"
export DATABASE_URL="postgresql://...la stringa di Supabase..."     # Windows (cmd): set DATABASE_URL=...
python3 migra_su_database.py fantamusica_dati.json
```
Poi apri il sito e accedi con i tuoi utenti di sempre (in quel caso il codice di installazione non serve).

---

## Come si usa dal browser

- Sul **computer** scrivi direttamente nel terminale. Le password non compaiono mentre le scrivi (come sempre).
- Da **telefono** tocca il terminale per la tastiera, oppure usa la barra in basso ("Invia"): è più comoda per i testi lunghi. Quando il programma chiede una password la barra nasconde i caratteri.
- Dopo 30 minuti senza digitare la sessione si chiude: ricarica la pagina (o premi *Riconnetti*) e rientra.

## Cosa cambia rispetto alla versione da terminale

- **Più persone insieme**: prima di ogni scelta di menu i dati vengono riletti dal database, quindi vedi subito le mosse degli altri (nuove proposte di scambio, eventi, ecc.).
- **Modifiche nello stesso istante**: se due persone salvano nello stesso momento, la seconda vede "ATTENZIONE… NON è stata salvata" e deve ripetere l'operazione. Nulla viene sovrascritto di nascosto. All'asta l'aggiudicazione si ricontrolla e si riprova da sola.
- **Backup**: "Backup ed esportazione → Crea un backup" li salva nel database (ne restano 50). Il ripristino funziona come prima. L'esportazione su file e il CSV non sono disponibili online (il disco del server non è permanente): per scaricare i dati puoi usare il *Table editor* di Supabase (schema `fantamusica`).
- Prima di **chiudere la stagione** viene creato un backup automatico, come prima.

## Limiti dei piani gratuiti (verificati il 25/10/2026)

- **Render free**: il servizio si "addormenta" dopo 15 minuti senza traffico e la prima apertura successiva richiede circa un minuto. Ha 750 ore al mese (un servizio sempre acceso ne usa al massimo 744). Il disco è effimero (per questo i dati stanno su Supabase). Quando Render si riavvia o addormenta, le sessioni aperte si chiudono: basta ricaricare la pagina, i dati non si perdono.
- **Supabase free**: 500 MB di database (questo gioco ne usa pochi KB) e il progetto viene **messo in pausa dopo 1 settimana di inattività**. Se non lo usate per più di una settimana, dal pannello Supabase premi *Restore project* e riparte con i dati intatti.

Fonti: [Render – Deploy for Free](https://render.com/docs/free), [Supabase – Pricing](https://supabase.com/pricing.md), [Supabase – IPv4 e IPv6](https://supabase.com/docs/guides/troubleshooting/supabase--your-network-ipv4-and-ipv6-compatibility-cHe3BP).

## Sicurezza (consigli)

- Tieni il repository **privato** e non scrivere mai la `DATABASE_URL` nei file: va solo nelle variabili d'ambiente di Render.
- Il programma accetta password da 4 caratteri: fate password più lunghe, visto che il sito è raggiungibile da chiunque conosca l'indirizzo. Dopo 3 password errate la sessione si chiude e dallo stesso indirizzo internet si possono aprire al massimo 20 sessioni ogni 10 minuti.
- Se perdi il controllo dell'admin, dal *Table editor* di Supabase puoi comunque intervenire sui dati.

## Aggiornare il gioco

Modifica i file su GitHub (o `git push`): Render si riavvia da solo con la nuova versione. I dati restano su Supabase.

## Provarlo sul proprio computer

```bash
pip install -r requirements.txt
python3 server.py            # poi apri http://localhost:8000
```
Senza `DATABASE_URL` i dati vanno nel file `fantamusica_dati.json` come sempre; con `DATABASE_URL` impostata usi il database online.
`server.py` funziona su Linux e macOS (su Windows serve WSL); non serve per giocare online, perché lì ci pensa Render.
`python3 fantamusica.py` continua a funzionare direttamente da terminale.

## Se qualcosa non va

- Pagina bianca / "Riconnetti" subito: guarda i **Logs** del servizio su Render.
- Errore di connessione al database: ricontrolla `DATABASE_URL` (password giusta, stringa del *Session pooler*, nessuna parentesi quadra rimasta).
- Dopo una settimana ferma: il progetto Supabase è in pausa, riattivalo dal pannello.
