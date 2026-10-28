# FantaBanda online - guida rapida

## Come funziona
- **Il gioco vive online, su Supabase.** Anche le regole girano lì dentro. Le richieste dei giocatori (proporre un evento, votare un sondaggio, proporre o accettare uno scambio, cambiare un soprannome) vengono applicate **subito** dal database. Le regole sono le stesse di `fantamusica.py`. **Nessun computer deve restare acceso.**
- **I giocatori usano la pagina web** (`index.html`): classifiche, squadre, eventi, pending, mercato e scambi, statistiche, storico, asta live. Entrano con il **loro codice personale**.
- **L'admin gestisce dal telefono**, entrando nella stessa pagina con il **codice admin**. Può:
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

## Dove va ogni file

| File | Dove | Pubblico? |
|---|---|---|
| `supabase_fantabanda.sql` | si incolla nel SQL Editor di Supabase. **Sostituisce i due script vecchi** | no |
| `index.html` | **unico file su GitHub**, nella radice del repository | sì: contiene solo l'indirizzo e la chiave "anon", che sono pubblici per natura |
| `fantamusica_core.py` | cartella del gioco sul computer: motore condiviso, non si avvia direttamente | no |
| `fantamusica_kivy.py`, `fm_online.py` | stessa cartella; Kivy è l'app da avviare | no |
| `fantamusica.py` | wrapper di compatibilità per la vecchia CLI; opzionale nell'uso normale | no |
| `fantamusica_online.json` | stessa cartella. Contiene `admin_code` = la chiave privata | **MAI** su GitHub né a nessuno |
| `fantamusica_online_base.json` | stessa cartella: lo crea l'app da sola. È l'ultima versione online che il computer conosce e serve a unire le modifiche. Non toccarlo | no |
| `fantamusica_dati.json`, cartelle `foto` e `backup` | stessa cartella (le crea il gioco) | no |

`fantamusica_online.json` resta com'è:

```json
{"url": "https://dyzvtfprezdhfnxiwlez.supabase.co", "anon_key": "...", "admin_code": "IL-TUO-CODICE-ADMIN", "web_url": "https://TUOUTENTE.github.io/NOMEREPO/"}
```

## Aggiornamento alla versione completamente online (una volta, circa 5 minuti)

1. **Supabase** → SQL Editor → New query → incolla **tutto** `supabase_fantabanda.sql` → Run. Non cancella nessun dato. **Da ora in poi usa solo questo file**: non rieseguire `supabase_asta.sql` o `supabase_gioco.sql`, perché rimetterebbero le funzioni vecchie, quelle che volevano il PC acceso. Se succede per sbaglio, riesegui `supabase_fantabanda.sql`.
2. **GitHub**: carica il nuovo `index.html` al posto del vecchio (*Add file → Upload files* → *Commit changes*). La pagina si aggiorna in 1-2 minuti. Sul telefono ricaricala; se vedi ancora la vecchia, chiudi e riapri la scheda.
3. **Computer**: sostituisci `fantamusica_kivy.py`, `fantamusica_core.py` e `fm_online.py`, poi apri l'app con `python3 fantamusica_kivy.py`. Al primo avvio potrebbe chiederti cosa fare con i dati. Se non sei sicuro, scegli **SCARICA I DATI ONLINE**: prima fa un backup di quelli del computer.

## Ogni volta che si gioca
1. I giocatori aprono la pagina e scrivono il loro codice, che resta salvato sul telefono.
2. Tu apri la stessa pagina e scrivi il **codice admin** (solo sul tuo telefono). In alto compare **ADMIN**:
   - **Eventi → Registra un evento**: gli eventi fissi valgono subito. Spunta DITTATURA per decidere tu il punteggio finale. Un'azione a sondaggio apre invece un pending segreto che verrà votato dai giocatori.
   - **Eventi → Pending**: per le proposte con punteggio fisso puoi CONFERMARE o RIFIUTARE; per i sondaggi vedi solo il progresso dei votanti, senza valori e senza comandi per aggiungere voti. Le righe segnate **DOPPIONE?** le vedi solo tu: sono proposte uguale a una già in attesa (stesso musicista, stessa azione).
   - **Eventi → Auto-chiusi voti** (solo admin): mostra i sondaggi che si sono chiusi automaticamente perché hanno votato tutti gli aventi diritto.
   - **Mercato**: APRI/CHIUDI IL MERCATO.
   - **Asta**: METTI IN ASTA accanto a un musicista disponibile, poi AGGIUDICA (il musicista va subito nella squadra del vincitore), ANNULLA ASTA, POCO TEMPO, ULTIMA CHIAMATA, CONTO 5/10, messaggi liberi.
   - **Impostazioni → Codici giocatori**: COPIA TUTTO per mandare a ognuno il suo codice e l'indirizzo della pagina.
3. I codici si generano o rigenerano solo dall'app: *Pannello admin → GIOCO ONLINE → CODICI DEI GIOCATORI*. Rigenerarli blocca subito quelli vecchi.

## Cose da sapere
- Se un giocatore sbaglia qualcosa (scambio non fattibile, voto fuori dal range, ecc.) la pagina glielo dice subito. Nel pulsante **Le mie richieste** c'è lo storico.
- Il canale dell'asta si svuota da solo quando nessuna squadra è collegata da 30 secondi.
- L'app, se è aperta mentre si gioca, scarica le novità da sola ogni 4 secondi (ogni secondo durante l'asta live con 2 o più squadre collegate). Se in quel momento hai una finestra aperta, aspetta che la chiudi. In alto compare "● NOVITÀ ONLINE".
- La pagina web non mostra le foto (solo le iniziali); le foto restano nell'app.
- La chiave privata è `admin_code`, e sul tuo telefono è anche il codice con cui entri come admin. Se pensi che sia trapelata, cambiala nella riga `insert into asta_config ... 'admin_codice'` di `supabase_fantabanda.sql`, riesegui lo script e aggiorna `fantamusica_online.json`.
- Da terminale, senza app: `python3 fm_online.py sincronizza` unisce e pubblica. Se il computer non ha ancora la copia di riferimento, ti chiede di scegliere fra `sincronizza online` (scarica, con backup) e `sincronizza locali` (pubblica i dati del computer).

## Prova veloce (5 minuti)
1. Dal telefono di un giocatore: Eventi → *Proponi un evento* scegliendo un'azione a sondaggio → inserisci eventualmente il tuo voto segreto → *Proponi*.
2. Dagli altri account che partecipano alla stagione apri Eventi → *Pending* e vota. Nessuno deve vedere i valori già espressi, soltanto il conteggio dei votanti.
3. Con l'ultimo voto il pending deve sparire da solo e comparire, per l'admin, in **Eventi → Auto-chiusi voti**; la classifica si aggiorna senza conferma manuale.
4. Asta: METTI IN ASTA un musicista, il giocatore rilancia, tu AGGIUDICA. Nella scheda Squadra del giocatore compare il musicista con il prezzo.
5. **Doppioni**: da due telefoni diversi proponi lo stesso musicista con la stessa azione. Il secondo giocatore legge l'avviso e nel suo pending non vede nulla di nuovo; tu come admin trovi la riga **DOPPIONE?** e decidi se confermarla o rifiutarla.
6. **Statistiche e integrità**: apri STATISTICHE e scorri le schede, poi *Pannello admin → VERIFICA INTEGRITÀ DEI DATI*: su dati sani deve rispondere che non c'è nessun problema.
7. Apri l'app sul computer: trovi tutte queste novità. Spegnila pure: il gioco continua.
