# FantaBanda online - guida rapida

## Auth v2 - giocatori e secondi admin

- I **codici giocatore sono ora codici di associazione monouso**: si inseriscono soltanto sul primo accesso di un dispositivo. Il browser crea una sessione Auth anonima e da quel momento riconosce il giocatore senza conservare il codice.
- I nuovi codici hanno **8 caratteri** dell'alfabeto senza caratteri ambigui e vengono mostrati come `ABCD-EFGH`. Supabase verifica l'hash del codice e marca l'invito come usato; la tabella legacy `asta_codici` non conserva più codici in chiaro.
- Un admin può generare un nuovo codice per un singolo giocatore dalla pagina **Impostazioni → Accessi giocatori** o dall'app Kivy **GIOCO ONLINE → CODICI DI ASSOCIAZIONE**. Le sessioni già associate restano valide finché l'admin non preme **Disconnetti**.
- Per aggiungere un secondo admin: **Impostazioni → Amministratori → Invita e invia link**. L'email viene autorizzata nel database e Supabase invia un **Magic Link** monouso. Dopo il clic l'account viene promosso automaticamente ad admin.
- Per questa fase devi attivare in Supabase **Authentication → Providers → Anonymous Sign-Ins**, perché i dispositivi dei giocatori usano utenti Auth anonimi. Supabase applica un rate limit agli accessi anonimi; per una distribuzione pubblica è consigliabile aggiungere anche CAPTCHA/Turnstile.
- In **Authentication → URL Configuration**, aggiungi l'indirizzo GitHub Pages di FantaBanda tra i Redirect URLs, altrimenti il Magic Link può tornare al Site URL predefinito.
- **Le tabelle dell'asta non sono più leggibili direttamente con la anon key**: `asta_squadre`, `asta_musicisti`, `asta_corrente`, `asta_offerte` e `asta_messaggi` hanno SELECT revocato. Il browser riceve lo stato dell'asta solo tramite RPC che accettano esclusivamente una sessione FantaBanda autorizzata.


## Come funziona
- **Il gioco vive online, su Supabase.** Anche le regole girano lì dentro. Le richieste dei giocatori (proporre un evento, votare un sondaggio, proporre o accettare uno scambio, cambiare un soprannome) vengono applicate **subito** dal database. Le regole sono le stesse di `fantamusica.py`. **Nessun computer deve restare acceso.**
- **I giocatori usano la pagina web** (`index.html`): classifiche, squadre, eventi, pending, mercato e scambi, statistiche, storico, asta live. Al primo accesso associano il dispositivo con il **codice di associazione**; poi entrano con la sessione del dispositivo.
- **L'admin gestisce dal telefono**, entrando nella stessa pagina con **email e password tramite Supabase Auth**. Durante la migrazione resta disponibile il vecchio codice admin. Può:
  - registrare eventi, anche con DITTATURA; nei sondaggi apre il pending ma non inserisce voti;
  - confermare o rifiutare le proposte non a sondaggio dei giocatori;
  - controllare l'avanzamento dei sondaggi segreti; ogni giocatore vota una sola volta e il pending si chiude automaticamente quando hanno votato tutti gli aventi diritto;
  - aprire o chiudere il mercato;
  - condurre l'asta live: aprire un'asta, aggiudicare, annullare, mandare messaggi e il conto alla rovescia;
  - vedere e copiare i codici dei giocatori.
- **L'app Kivy sul computer è l'app principale**: gestisce anche azioni, buff/debuff (bonus/malus), utenti, caratteristiche descrittive, foto, backup/ripristino e chiusura della stagione. Quando la apri scarica le novità; quando modifichi qualcosa lo pubblica. **Non serve tenerla aperta.**
- Dentro Kivy c'è anche **MODALITÀ TERMINALE**: mostra i vecchi menu numerici in una console integrata. Non serve avviare un secondo programma.
- **Se hai cambiato qualcosa nell'app mentre online qualcuno giocava, le due versioni si uniscono.** Gli eventi nuovi delle due parti vengono numerati senza doppioni. Se lo stesso dato è stato cambiato in tutti e due i posti, vince quello del computer.
- `fantamusica.py` resta solo come wrapper di compatibilità. Il motore condiviso è `fantamusica_core.py`; normalmente avvia soltanto `python3 fantamusica_kivy.py`. Se vuoi sincronizzare senza aprire la GUI puoi ancora usare `python3 fm_online.py sincronizza`.


### Accesso amministratore — Supabase Auth (nuovo)
L'amministratore della pagina web non deve più usare ogni giorno un codice segreto condiviso: usa un vero account **Supabase Auth con email e password**.

**Prima migrazione dall'installazione precedente:**
1. Esegui il nuovo `supabase_fantabanda.sql`.
2. Carica il nuovo `index.html` su GitHub Pages.
3. Nella pagina, sotto **Accesso amministratore**, inserisci email e una password di almeno 8 caratteri e premi **Crea account**.
4. Se il progetto richiede la conferma email, conferma il messaggio ricevuto e poi premi **Accedi admin**.
5. La prima volta l'account risulta autenticato ma non ancora amministratore: compare il campo **Vecchio codice admin**. Inseriscilo una sola volta e premi **Collega questo account**.
6. Da quel momento sul web entri con email/password. Il vecchio codice non serve più per l'accesso quotidiano.

La casella **Ricordami su questo dispositivo** decide dove viene conservata la sessione: se è disattivata vale solo per la sessione del browser; se è attivata resta anche dopo averlo chiuso. Non viene più salvata la password.

Per compatibilità, in questa fase `fantamusica_kivy.py` e `fm_online.py` continuano a usare `admin_code` nel file locale `fantamusica_online.json`. Le RPC accettano entrambe le forme: **account Auth** dal browser oppure **codice legacy** dall'app. Questo ponte verrà rimosso solo dopo aver migrato anche Kivy.

Il file SQL non contiene più un codice admin fisso: se il codice legacy manca, ne genera uno casuale una sola volta e non lo cambia rieseguendo lo script.


### Sondaggi e pending
- Quando un evento apre un **sondaggio**, i voti sono **segreti finché il pending è aperto**. La pagina pubblica non riceve i valori dei voti: mostra soltanto quanti aventi diritto hanno già votato e, al singolo giocatore, se lui ha già espresso il proprio voto.
- Ogni giocatore che partecipa alla stagione può votare **una sola volta** per quel sondaggio. L'elenco degli aventi diritto viene fotografato quando nasce il pending, così il quorum non cambia a metà votazione se successivamente viene aggiunto o disattivato un account.
- Al voto dell'ultimo avente diritto Supabase calcola subito la media, applica buff/debuff, chiude il pending e registra il risultato. Non serve alcun clic dell'admin.
- L'admin **non può aggiungere, azzerare o modificare voti**, né forzare la chiusura di un sondaggio. Può ancora rifiutare una proposta mentre è pending e può eliminare in seguito un evento se scopre un problema.
- In **Eventi → Auto-chiusi voti**, visibile soltanto all'admin, compaiono gli eventi chiusi automaticamente per quorum.

### Proposte doppione
Capita che due giocatori segnalino lo stesso fatto. Da ora il gioco lo riconosce da solo.

- Quando un giocatore propone un evento e **in pending c'è già una proposta con lo stesso musicista e la stessa azione**, la nuova proposta viene **registrata comunque** ma segnata come **probabile doppione**.
- Chi l'ha inviata riceve subito questo avviso: *l'evento è stato comunque registrato, ma non viene mostrato per evitare doppioni; rivolgiti all'admin se pensi che sia corretto.* Nessun dato va perso e nessuno deve riscrivere niente.
- La proposta segnata **compare soltanto nella lista pending dell'admin**: gli altri giocatori non la vedono né nel pending né negli elenchi degli eventi, così il pending non si riempie di copie.
- L'admin la riconosce subito: riga **gialla** con un **asterisco** e lo stato **DOPPIONE?** (nella pagina web l'etichetta è la stessa). Aprendola trova la spiegazione e decide:
  - **CONFERMA** se è davvero un evento a sé: il contrassegno cade e l'evento torna visibile a tutti come qualunque altro;
  - **RIFIUTA ED ELIMINA** se era una ripetizione.
- Il controllo scatta **solo sulle proposte dei giocatori**. L'admin registra sempre senza blocchi, anche se sta inserendo volutamente due eventi identici (per esempio due assoli nella stessa serata).
- Vale in tutte le facce del gioco: app Kivy, modalità terminale, pagina web e funzioni Supabase.

### Statistiche
Oltre a classifiche e riepiloghi, nella voce **STATISTICHE** (home dell'app Kivy, pannello admin, menu statistiche della versione a terminale e della pagina web) ci sono:

| Scheda | Cosa dice |
|---|---|
| Tipi di evento | quante volte si verifica ogni tipo di evento, i punti prodotti in tutto e la **media per evento** |
| Punti musicisti | punti totali generati da ciascun musicista e i **punti per credito d'asta** |
| Positivi/negativi | come si dividono gli eventi fra punteggi positivi, negativi e neutri, in numero e in punti |
| Buff/debuff | quanto gli effetti hanno spostato i punteggi: eventi coinvolti, punti aggiunti, punti sottratti, **effetto netto** |
| Top 5 | quanta **percentuale del punteggio** arriva dai 5 musicisti migliori |
| Peggiori 5 | i 5 musicisti con **meno punti** e quanto pesano sul totale negativo del campo |
| Mercato | i giocatori più efficienti: punti ottenuti per ogni credito speso in rosa |
| Valore/resa | **valore d'asta contro rendimento reale**: per ogni musicista comprato, quanto avrebbe dovuto rendere a quel prezzo e quanto ha reso davvero |

I nomi delle schede cambiano un poco fra app e pagina web (lì ci sono anche *Riepilogo*, *Squadre a confronto* e *Affari*, e i punti per credito di ogni musicista stanno nella classifica musicisti), ma i dati sono gli stessi: i conti stanno in `fantamusica_core.py` e sono rifatti in JavaScript nella pagina, e le due parti danno gli stessi numeri.

### Verifica integrità dei dati
*Pannello admin → **VERIFICA INTEGRITÀ DEI DATI*** (anche dai menu admin della modalità terminale).

È un controllo di **sola lettura: non modifica e non corregge nulla**, dice soltanto cosa non torna, riga per riga, così decidi tu. Passa in rassegna riferimenti, ID, proprietari, bonus, azioni, scambi, contatori, crediti e rose:

- musicisti con ID doppi, proprietari inesistenti o non in classifica, prezzi incoerenti con l'assegnazione;
- azioni con bonus collegati che non esistono o modalità non valide;
- buff/debuff puntati su musicisti o giocatori inesistenti;
- eventi con musicista, azione o proprietario inesistenti, o con stato non valido;
- scambi che citano giocatori o musicisti inesistenti;
- contatori degli ID che non superano un ID già in uso (gli ID non vengono mai riciclati);
- crediti negativi e rose oltre il limite di musicisti per squadra;
- utenti senza nessun admin o con codici d'asta duplicati.

I messaggi sono puntuali, per esempio:

```
Evento 147 → bonus_id 12 inesistente
Musicista 31 → proprietario "Marco" non presente tra i partecipanti
```

Se non c'è nulla da segnalare lo dice. È la prima cosa da aprire se un dato sembra sparito o un punteggio non quadra.

### Buff / debuff
- Nella schermata **Bonus e malus** non devi più conoscere o digitare ID: scegli **evento**, **musicista** o **giocatore** dagli elenchi. Per gli eventi spunti direttamente i tipi di evento nei quali l'effetto può essere usato.
- I vecchi bonus legati alle azioni sono mostrati come buff/debuff dell'**evento**: durante la registrazione dell'evento scegli quali applicare. Musicisti e giocatori ricevono invece automaticamente gli effetti attivi che li riguardano.
- La durata può essere **permanente**, per un certo numero di **eventi**, oppure **a tempo**. Le date compaiono solo scegliendo *a tempo*. I salvataggi vecchi che usavano il nome interno `date` vengono convertiti automaticamente.
- Ogni buff/debuff può avere una **descrizione**. Kivy e la pagina web mostrano gli effetti attivi nelle schede di giocatori e musicisti e, per gli eventi, nei dettagli del calcolo.
- Le **caratteristiche** restano per informazioni descrittive del profilo (per esempio strumento, genere, città). Kivy non ricrea più automaticamente caratteristiche che rappresentano stati di gioco: stati temporanei o effetti sul punteggio vanno creati come buff/debuff. Le vecchie caratteristiche già presenti non vengono cancellate automaticamente, per non perdere dati.


### Sicurezza delle letture dell'asta
La chiave `anon` presente in `index.html` **non è un segreto** e non va usata come barriera di sicurezza. Per questo le cinque tabelle live dell'asta non concedono più `SELECT` né ad `anon` né ad `authenticated`.

La pagina usa invece due RPC:
- `asta_leggi()` restituisce soltanto lo stato necessario alla schermata Asta (asta corrente, ultime offerte, ultimi messaggi, squadre e musicisti);
- `asta_messaggi_dopo(...)` restituisce soltanto i nuovi messaggi necessari ai banner live.

Entrambe verificano lato database che il JWT appartenga a un **admin FantaBanda** oppure a un **dispositivo giocatore già associato**. Un utente Supabase generico, anche se autenticato, non basta. Il vecchio canale Postgres Realtime sulle tabelle `asta_*` viene rimosso perché questa versione usa già il polling RPC.

### Rate limiting e protezione dagli abusi
FantaBanda usa due livelli distinti di protezione:

1. **Supabase Auth** limita già gli endpoint di autenticazione (password, refresh token, Magic Link e creazione di sessioni anonime).
2. **FantaBanda** applica limiti server-side alle RPC del gioco, quindi non sono aggirabili modificando JavaScript o ricaricando la pagina.

I limiti applicativi predefiniti sono volutamente conservativi:

| Operazione | Limite |
|---|---:|
| associazione di un dispositivo giocatore | 6 tentativi / 5 minuti per sessione Auth |
| collegamento iniziale dell'account admin | 5 tentativi / 10 minuti |
| inviti di nuovi admin | 5 / 10 minuti per admin |
| riscatto di un invito admin | 10 / 10 minuti per account |
| login legacy senza sessione Auth | 120 richieste / minuto complessive + 12 / 5 minuti per credenziale |
| rilanci d'asta | 30 / minuto per giocatore |
| ping presenza asta | 18 / minuto per giocatore |
| richieste di gioco (`fm_invia`) | 30 / minuto per giocatore, oltre al vecchio limite di 20 richieste applicate/minuto |
| lettura asta / nuovi messaggi | 90 / minuto per sessione |
| operazioni admin sull'asta | 60 / minuto per admin |

Quando un limite viene superato la RPC risponde con un errore leggibile e, quando disponibile, con `retry_after` in secondi. La tabella interna `fm_rate_limits` ha RLS attiva, non è leggibile dal browser e non contiene password o codici in chiaro: usa una chiave derivata dall'identità/sessione.

Per una futura distribuzione pubblica conviene inoltre abilitare CAPTCHA/Turnstile per gli accessi anonimi in Supabase Auth. Per un gruppo privato non è indispensabile, ma aggiunge protezione contro la creazione automatizzata di molte sessioni.

### Validazione server-side prima di un push admin
Prima di sostituire lo stato online con il database proveniente da Kivy/`fm_online.py`, Supabase esegue ora un controllo di integrità **sul server**. Essere autenticati come admin non basta: anche il contenuto del push deve essere coerente.

Il controllo blocca, fra le altre cose:
- struttura JSON incompleta o campi principali del tipo sbagliato;
- ID non validi o duplicati di musicisti, azioni, bonus, eventi, scambi, caratteristiche e stagioni archiviate;
- riferimenti a musicisti, azioni, bonus, proprietari o giocatori inesistenti;
- musicisti liberi con prezzo diverso da zero o assegnati con prezzo non valido;
- modalità di azione, tipo/bersaglio/durata dei bonus e stato di eventi/scambi non validi;
- codici giocatore malformati o duplicati;
- contatori ID che non superano gli ID già utilizzati;
- rose oltre `musicisti_per_squadra` e crediti negativi;
- assenza di almeno un admin.

`fm_online.py` esegue anche il validatore locale già presente nel core prima di inviare. Questo serve soltanto a dare un errore immediato e leggibile: **la decisione definitiva resta al server**, che rivalida sempre i dati. Se trova problemi, `fm_a_push` restituisce `ok=false` con l'elenco `problemi` e non chiama `fm__salva`, quindi la versione online non viene modificata.

Esempio di errore:

```text
Il database locale contiene incoerenze e non verrà pubblicato:
- Musicista 31 → proprietario "Marco" non presente tra i partecipanti
- Contatore musicista → è 31 ma esiste già un ID 31
```

Le funzioni interne di validazione non hanno permesso `EXECUTE` per `anon` o `authenticated`: possono essere usate solo dalle funzioni server che ne hanno bisogno.

## Dove va ogni file

| File | Dove | Pubblico? |
|---|---|---|
| `supabase_fantabanda.sql` | si incolla nel SQL Editor di Supabase. **Sostituisce i due script vecchi** | no |
| `index.html` | **unico file su GitHub**, nella radice del repository | sì: contiene solo l'indirizzo e la chiave "anon", che sono pubblici per natura; la anon key da sola non può leggere le tabelle dell'asta |
| `fantamusica_core.py` | cartella del gioco sul computer: motore condiviso, non si avvia direttamente | no |
| `fantamusica_kivy.py`, `fm_online.py` | stessa cartella; Kivy è l'app da avviare | no |
| `fantamusica.py` | wrapper di compatibilità per la vecchia CLI; opzionale nell'uso normale | no |
| `fantamusica_online.json` | stessa cartella. In questa fase contiene ancora `admin_code` per Kivy/fm_online | **MAI** su GitHub né a nessuno |
| `fantamusica_online_base.json` | stessa cartella: lo crea l'app da sola. È l'ultima versione online che il computer conosce e serve a unire le modifiche. Non toccarlo | no |
| `fantamusica_dati.json`, cartelle `foto` e `backup` | stessa cartella (le crea il gioco) | no |

`fantamusica_online.json` resta com'è:

```json
{"url": "https://dyzvtfprezdhfnxiwlez.supabase.co", "anon_key": "...", "admin_code": "IL-TUO-CODICE-ADMIN", "web_url": "https://TUOUTENTE.github.io/NOMEREPO/"}
```

## Aggiornamento: validazione push admin
Per questo passaggio specifico bastano:
1. eseguire tutto il nuovo `supabase_fantabanda.sql` nel SQL Editor con RLS attiva;
2. sostituire `fm_online.py` nella cartella del gioco;
3. riavviare Kivy.

`index.html`, `fantamusica_kivy.py` e `fantamusica_core.py` non cambiano in questo passaggio.

## Aggiornamento alla versione completamente online (una volta, circa 5 minuti)

1. **Supabase** → SQL Editor → New query → incolla **tutto** `supabase_fantabanda.sql` → Run. Non cancella nessun dato. **Da ora in poi usa solo questo file**: non rieseguire `supabase_asta.sql` o `supabase_gioco.sql`, perché rimetterebbero le funzioni vecchie, quelle che volevano il PC acceso. Se succede per sbaglio, riesegui `supabase_fantabanda.sql`.
2. **GitHub**: carica il nuovo `index.html` al posto del vecchio (*Add file → Upload files* → *Commit changes*). La pagina si aggiorna in 1-2 minuti. Sul telefono ricaricala; se vedi ancora la vecchia, chiudi e riapri la scheda.
3. **Computer**: sostituisci `fantamusica_kivy.py`, `fantamusica_core.py` e `fm_online.py`, poi apri l'app con `python3 fantamusica_kivy.py`. Al primo avvio potrebbe chiederti cosa fare con i dati. Se non sei sicuro, scegli **SCARICA I DATI ONLINE**: prima fa un backup di quelli del computer.

## Ogni volta che si gioca
1. Al primo accesso ogni giocatore inserisce il proprio **codice di associazione**. Dopo l’associazione il dispositivo usa la sessione Auth e non deve più riscrivere né conservare il codice.
2. Tu apri la stessa pagina e accedi nella sezione **Accesso amministratore** con email e password. In alto compare **ADMIN**:
   - **Eventi → Registra un evento**: gli eventi fissi valgono subito. Spunta DITTATURA per decidere tu il punteggio finale. Un'azione a sondaggio apre invece un pending segreto che verrà votato dai giocatori.
   - **Eventi → Pending**: per le proposte con punteggio fisso puoi CONFERMARE o RIFIUTARE; per i sondaggi vedi solo il progresso dei votanti, senza valori e senza comandi per aggiungere voti. Le righe segnate **DOPPIONE?** le vedi solo tu: sono proposte uguale a una già in attesa (stesso musicista, stessa azione).
   - **Eventi → Auto-chiusi voti** (solo admin): mostra i sondaggi che si sono chiusi automaticamente perché hanno votato tutti gli aventi diritto.
   - **Mercato**: APRI/CHIUDI IL MERCATO.
   - **Asta**: METTI IN ASTA accanto a un musicista disponibile, poi AGGIUDICA (il musicista va subito nella squadra del vincitore), ANNULLA ASTA, POCO TEMPO, ULTIMA CHIAMATA, CONTO 5/10, messaggi liberi.
   - **Impostazioni → Accessi giocatori**: controlla dispositivi associati, genera nuovi codici e disconnette un giocatore se serve.
3. I codici si possono rigenerare per singolo giocatore dalla pagina web (*Impostazioni → Accessi giocatori*) oppure dall'app (*GIOCO ONLINE → CODICI DI ASSOCIAZIONE*).

## Cose da sapere
- Se un giocatore sbaglia qualcosa (scambio non fattibile, voto fuori dal range, ecc.) la pagina glielo dice subito. Nel pulsante **Le mie richieste** c'è lo storico.
- Il canale dell'asta si svuota da solo quando nessuna squadra è collegata da 30 secondi.
- L'app, se è aperta mentre si gioca, scarica le novità da sola ogni 4 secondi (ogni secondo durante l'asta live con 2 o più squadre collegate). Se in quel momento hai una finestra aperta, aspetta che la chiudi. In alto compare "● NOVITÀ ONLINE".
- La pagina web non mostra le foto (solo le iniziali); le foto restano nell'app.
- `admin_code` resta temporaneamente una credenziale **legacy solo locale** usata da Kivy/fm_online e per collegare il primo account Auth. Non è più scritto nello SQL e non va pubblicato. Sul web, dopo la migrazione, usa email/password.
- Da terminale, senza app: `python3 fm_online.py sincronizza` unisce e pubblica. Se il computer non ha ancora la copia di riferimento, ti chiede di scegliere fra `sincronizza online` (scarica, con backup) e `sincronizza locali` (pubblica i dati del computer).

## Prova veloce (5 minuti)
1. Dal telefono di un giocatore: Eventi → *Proponi un evento* scegliendo un'azione a sondaggio → inserisci eventualmente il tuo voto segreto → *Proponi*.
2. Dagli altri account che partecipano alla stagione apri Eventi → *Pending* e vota. Nessuno deve vedere i valori già espressi, soltanto il conteggio dei votanti.
3. Con l'ultimo voto il pending deve sparire da solo e comparire, per l'admin, in **Eventi → Auto-chiusi voti**; la classifica si aggiorna senza conferma manuale.
4. Asta: METTI IN ASTA un musicista, il giocatore rilancia, tu AGGIUDICA. Nella scheda Squadra del giocatore compare il musicista con il prezzo.
5. **Doppioni**: da due telefoni diversi proponi lo stesso musicista con la stessa azione. Il secondo giocatore legge l'avviso e nel suo pending non vede nulla di nuovo; tu come admin trovi la riga **DOPPIONE?** e decidi se confermarla o rifiutarla.
6. **Statistiche e integrità**: apri STATISTICHE e scorri le schede, poi *Pannello admin → VERIFICA INTEGRITÀ DEI DATI*: su dati sani deve rispondere che non c'è nessun problema.
7. Apri l'app sul computer: trovi tutte queste novità. Spegnila pure: il gioco continua.

## Aggiornamento: audit log amministrativo + bonus/profili Kivy

Questa versione aggiunge uno **storico amministrativo centrale** in Supabase e corregge due problemi dell'interfaccia Kivy.

### Audit log amministrativo

La nuova tabella privata `fm_audit_log` conserva le modifiche amministrative rilevanti. Non è leggibile direttamente con la anon key e non salva password, hash, `admin_code` o codici di associazione dei giocatori.

Vengono registrati, fra gli altri:
- creazione/eliminazione eventi e correzioni di punteggio;
- uso di **DITTATURA**;
- creazione/modifica/eliminazione di bonus e malus;
- cambi di proprietario/prezzo dei musicisti e aggiudicazioni d'asta;
- creazione/modifica/eliminazione di azioni e caratteristiche descrittive;
- modifiche a giocatori, impostazioni e cambio stagione;
- rigenerazione dei codici giocatore (senza salvare il codice);
- inviti admin, revoche e disconnessione dei dispositivi dei giocatori;
- modifiche non riconosciute in modo specifico come `CORREZIONE_MANUALE`.

Sul web: **Impostazioni → Audit log**.  
In Kivy: **Pannello admin → AUDIT LOG AMMINISTRATIVO**.

Le prime 100 voci vengono caricate subito; con **CARICA 100 PRECEDENTI** si può scorrere l'intero storico. Le modifiche fatte da un admin web Auth mostrano la sua email. Finché Kivy usa ancora il vecchio ponte `admin_code`, le sue modifiche sono indicate come `KIVY / admin legacy`.

Il log parte dal momento in cui installi questo aggiornamento: non ricostruisce retroattivamente le modifiche precedenti.

### Bonus/malus Kivy

Il form di creazione/modifica è ora realmente scorribile. Il bersaglio può essere:
- **evento**: selezioni i tipi di evento/azioni in cui il bonus è disponibile;
- **musicista**: si apre un elenco scorribile dei musicisti;
- **giocatore**: si apre un elenco scorribile dei giocatori partecipanti.

Il destinatario non usa più un menu a tendina enorme: viene scelto da una finestra dedicata, adatta anche a elenchi molto lunghi.

### Caratteristiche nei profili

Nei profili di giocatori e musicisti vengono mostrate solo le caratteristiche che quell'elemento possiede davvero e che hanno un valore. Le caratteristiche definite nel gioco ma non assegnate non producono più righe vuote o `-`. La stessa regola viene applicata anche alla pagina web.

### File da aggiornare per questo passaggio

1. **Supabase**: esegui tutto il nuovo `supabase_fantabanda.sql` con RLS attiva.
2. **GitHub Pages**: sostituisci `index.html`.
3. **Computer**: sostituisci `fantamusica_kivy.py` e `fm_online.py`.
4. Riavvia Kivy.

`fantamusica_core.py` non cambia in questo passaggio.
