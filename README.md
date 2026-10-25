# FantaBanda 🎸

Un fantasy game dei musicisti da giocare con gli amici, in Python, direttamente dal terminale.
Nessuna dipendenza: basta Python 3.10 o superiore.

All'inizio della stagione ogni partecipante compra i suoi musicisti all'asta. Durante la stagione
l'admin registra le **azioni** dei musicisti (un nuovo singolo, un disco d'oro, uno scandalo...) e i
punti vanno a chi ha scelto quel musicista. Vince chi chiude la stagione in testa alla classifica.

## Avvio

```bash
python3 fantamusica.py
```

Al primo avvio si crea l'account admin. I dati vengono salvati in `fantamusica_dati.json`
accanto allo script (puoi cambiarne il percorso con la variabile d'ambiente `FANTAMUSICA_DATA`).
I salvataggi di versioni precedenti vengono aggiornati automaticamente all'apertura.

> **Attenzione:** `fantamusica_dati.json` contiene utenti e password (sotto forma di hash): è già
> escluso da Git tramite `.gitignore`, non pubblicarlo.

## Ruoli

| | Admin | Partecipante |
|---|---|---|
| Classifiche, statistiche, storico stagioni, profili | ✅ | ✅ |
| La mia squadra, mercato e scambi | se gioca | ✅ |
| Impostazioni della stagione | modifica | sola lettura |
| Preferenze personali (soprannomi, ordinamenti, password...) | ✅ | ✅ |
| Asta, musicisti, azioni, bonus, eventi, utenti, chiusura stagione | ✅ | ❌ |

## Come funziona il punteggio

Alla creazione di un'azione l'admin sceglie come si calcolano i punti:

- **Fisso**: sempre lo stesso punteggio (anche negativo).
- **Sondaggio**: il valore si decide dopo un sondaggio, in un range a scelta nel formato `1-10`.
  Si inserisce subito oppure l'evento resta in **pending** e si completa più tardi. Si possono
  raccogliere più voti anche in momenti diversi: vale la **media arrotondata per difetto**
  (una media tra 0 e 1 vale comunque 1 punto).
- **A quantità**: si chiede una quantità e si moltiplica per i punti di ogni unità. L'unità di
  misura è libera (minuti, ore, giorni, km, ascolti...).

**Più musicisti**: un'azione può prevedere dei ruoli (es. *Protagonista* e *Ospite*), ciascuno con il
proprio punteggio, definiti alla creazione. Quando si registra l'evento si possono aggiungere altri
musicisti coinvolti con un punteggio libero.

**Bonus e malus**: hanno un valore fissato alla creazione, scritto come `+5` / `-3` (punti interi) o
`20%` / `-10%` (percentuale), e si collegano a una o più azioni. Registrando l'evento il programma
chiede quali applicare. Ordine di calcolo: prima si sommano i punti interi alla base, poi si
applicano le percentuali (sommate tra loro) al totale ottenuto, arrotondando per difetto, cioè
verso il basso anche per i numeri negativi.

Esempio: base 10, bonus `+5` e `+20%` → 10 + 5 = 15, poi +20% di 15 = +3 → **18**.

**DITTATURA**: l'admin può inserire un evento con il punteggio deciso a mano, senza sondaggi né bonus.

## Mercato

I giocatori si propongono scambi o vendite di musicisti, con eventuale conguaglio in crediti. Ogni
musicista porta con sé il prezzo d'asta e i punti già maturati restano alla squadra che li ha
ottenuti. Il numero di scambi per giocatore a stagione è nelle impostazioni (default 3) e l'admin
può aprire e chiudere il mercato.

## Stagioni

*Chiudi stagione* archivia classifiche ed eventi nello storico e riparte da zero, tenendo utenti,
musicisti, azioni e bonus. Dallo storico si consultano le stagioni passate e la classifica cumulativa.

## Personalizzazione

- Caratteristiche dei profili (strumento, genere, anni di carriera, città...) definite dall'admin.
- Soprannome per ogni musicista (impostato dall'admin) e soprannomi personali che ogni giocatore
  vede solo sul proprio account.
- Elenchi ordinabili per colonna: l'ordinamento scelto viene ricordato per ogni giocatore.
- Recupero password con domanda segreta.

## Test

```bash
python3 -m unittest -v test_fantamusica
```

I test usano un file temporaneo e non toccano i dati reali.

## Pubblicare su GitHub

```bash
git init
git add .
git commit -m "FantaBanda: prima versione"
git branch -M main
git remote add origin https://github.com/<tuo-utente>/<nome-repo>.git
git push -u origin main
```

## Licenza

MIT, vedi [LICENSE](LICENSE).
