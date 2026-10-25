#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FANTAMUSICA - gioco a squadre con asta iniziale

Come si gioca
  1. A inizio stagione i partecipanti comprano i musicisti all'asta (con i crediti).
  2. Durante la stagione l'admin registra le azioni dei musicisti (nuovo singolo,
     disco d'oro, scandalo...): i punti vanno a chi ha scelto quel musicista.
  3. Tutti possono consultare classifica, statistiche e profili.

Come si calcolano i punti di un'azione (scelto alla creazione dell'azione)
  - fisso:      punteggio sempre uguale.
  - sondaggio:  il valore (da 1 a 5 oppure da 6 a 10) si decide dopo un sondaggio. Si puo'
                inserire subito oppure lasciare l'evento in PENDING e completarlo piu' tardi.
  - tempo:      si chiede il tempo (minuti, ore o giorni) e si moltiplica per i punti
                dell'unita' di tempo (es. 3 punti per ora).
  Alle azioni si possono collegare dei bonus/malus (a punti o in percentuale): quando si
  registra l'evento il programma chiede quali applicare, poi calcola il punteggio finale:
      finale = base x (1 + somma % / 100) + somma dei bonus/malus a punti   (arrotondato)
  DITTATURA: l'admin puo' inserire un evento con il punteggio deciso a mano.

Ruoli
  - admin:        permessi globali (asta, musicisti, azioni, bonus, eventi, utenti, profili,
                  impostazioni)
  - partecipante: consulta classifica, statistiche, profili, la propria squadra, le
                  impostazioni della stagione (sola lettura) e gestisce le proprie
                  preferenze personali (soprannome, ordinamenti, riepilogo all'accesso...)

Avvio:  python3 fantamusica.py
I dati sono salvati in fantamusica_dati.json (accanto allo script).
I salvataggi delle versioni precedenti vengono aggiornati in automatico all'apertura.
"""
import functools
import getpass
import hashlib
import json
import math
import os
import secrets
from datetime import datetime
from pathlib import Path

DATA_FILE = Path(os.environ.get("FANTAMUSICA_DATA")
                 or Path(__file__).with_name("fantamusica_dati.json"))

# Azioni di partenza (l'admin può modificarle dal pannello)
AZIONI_BASE = [
    ("Nuovo singolo pubblicato", 10),
    ("Nuovo album pubblicato", 25),
    ("Concerto / data del tour", 5),
    ("Primo posto in classifica", 30),
    ("Disco d'oro", 20),
    ("Disco di platino", 35),
    ("Premio vinto", 40),
    ("Collaborazione (feat)", 8),
    ("Scandalo / polemica", -15),
    ("Concerto annullato", -10),
]

# Caratteristiche di partenza dei profili (l'admin può rinominarle, eliminarle o aggiungerne)
CAMPI_BASE = [
    ("musicisti", "Strumento", "testo"),
    ("musicisti", "Genere musicale", "testo"),
    ("musicisti", "Anni di carriera", "numero"),
    ("giocatori", "Città", "testo"),
]

UNITA_TEMPO = ("minuti", "ore", "giorni")
FASCE_SONDAGGIO = {"1": (1, 5), "2": (6, 10)}

# Preferenze personali di ogni giocatore (salvate nel suo profilo e caricate al login)
PREF_BASE = {
    "soprannome": "",          # mostrato nel saluto e nella classifica
    "riepilogo_login": True,   # riepilogo all'accesso (posizione, novità, pending)
    "righe_eventi": 15,        # quanti eventi mostrare negli elenchi (0 = tutti)
    "ordinamenti": {},         # ultimo ordinamento scelto per ogni elenco: {lista: [colonna, decrescente]}
    "ultimo_accesso": None,
}


# --------------------------------------------------------------------------
# Dati
# --------------------------------------------------------------------------
def nuova_azione(id_, nome, punti):
    return {"id": id_, "nome": nome, "modalita": "fisso", "punti": punti,
            "min": None, "max": None, "unita": None, "bonus_ids": []}


def nuovo_db():
    db = {
        "impostazioni": {
            "stagione": "Stagione 1",
            "musicisti_per_squadra": 5,
            "budget_iniziale": 500,
            "rilancio_minimo": 1,
        },
        "utenti": [],      # {nome, ruolo, salt, hash, gioca, profilo, preferenze}
        "musicisti": [],   # {id, nome, proprietario, prezzo, profilo}
        "azioni": [nuova_azione(i + 1, n, p) for i, (n, p) in enumerate(AZIONI_BASE)],
        # {id, nome, modalita: fisso|sondaggio|tempo, punti, min, max, unita, bonus_ids}
        "bonus": [],       # {id, nome, tipo: "punti"|"percentuale", valore}
        "eventi": [],      # {id, data, musicista_id, azione_id, azione, stato: ok|pending, punti, base,
                           #  bonus: [snapshot], dettaglio, dittatura, proprietario, nota}
        "contatori": {"musicista": 1, "azione": len(AZIONI_BASE) + 1, "evento": 1, "campo": 1, "bonus": 1},
    }
    # migra() crea "campi" ({id, per: "musicisti"|"giocatori", nome, tipo: "testo"|"numero"})
    # con le caratteristiche di partenza
    migra(db)
    return db


def prefs(u):
    """Preferenze personali dell'utente, con i valori predefiniti per quelle mancanti."""
    p = u.setdefault("preferenze", {})
    for k, v in PREF_BASE.items():
        if k not in p:
            p[k] = {} if isinstance(v, dict) else v
    return p


def migra(db):
    """Porta un salvataggio di una versione precedente al formato attuale.
    Restituisce True se ha cambiato qualcosa."""
    cambiato = False

    def imposta(d, k, v):
        nonlocal cambiato
        if k not in d:
            d[k] = v
            cambiato = True

    imposta(db, "bonus", [])
    imposta(db["contatori"], "bonus", 1)
    if "campi" not in db:
        db["campi"] = []
        db["contatori"].setdefault("campo", 1)
        for per, nome, tipo in CAMPI_BASE:
            db["campi"].append({"id": prossimo_id(db, "campo"), "per": per, "nome": nome, "tipo": tipo})
        cambiato = True
    for u in db["utenti"]:
        imposta(u, "profilo", {})
        if "preferenze" not in u:
            cambiato = True
        prefs(u)
    for m in db["musicisti"]:
        imposta(m, "profilo", {})
    for a in db["azioni"]:
        imposta(a, "modalita", "fisso")
        imposta(a, "min", None)
        imposta(a, "max", None)
        imposta(a, "unita", None)
        imposta(a, "bonus_ids", [])
    # Gli eventi puntano all'azione per ID (così rinominarla aggiorna anche lo storico)
    per_nome = {a["nome"].lower(): a["id"] for a in db["azioni"]}
    for e in db["eventi"]:
        if "azione_id" not in e:
            e["azione_id"] = per_nome.get(e["azione"].lower())
            cambiato = True
        imposta(e, "stato", "ok")
        imposta(e, "base", e["punti"])
        imposta(e, "bonus", [])
        imposta(e, "dettaglio", "")
        imposta(e, "dittatura", False)
    return cambiato


def carica():
    if DATA_FILE.exists():
        with open(DATA_FILE, encoding="utf-8") as f:
            return json.load(f)
    return None


def salva(db):
    tmp = DATA_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    os.replace(tmp, DATA_FILE)


def prossimo_id(db, tipo):
    n = db["contatori"][tipo]
    db["contatori"][tipo] += 1
    return n


def riempi_buco(db, chiave, contatore, vuoto):
    """Dopo una rimozione l'ID 'vuoto' resta libero: l'elemento con l'ID più alto lo prende
    al suo posto, così gli ID restano consecutivi. Restituisce (vecchio_id, nuovo_id)
    se un elemento è stato spostato, altrimenti None. Aggiorna anche il contatore."""
    lista = db[chiave]
    spostato = None
    if lista:
        ultimo = max(lista, key=lambda x: x["id"])
        if ultimo["id"] > vuoto:
            spostato = (ultimo["id"], vuoto)
            ultimo["id"] = vuoto
            lista.sort(key=lambda x: x["id"])
    db["contatori"][contatore] = max((x["id"] for x in lista), default=0) + 1
    return spostato


# --------------------------------------------------------------------------
# Password
# --------------------------------------------------------------------------
def hash_password(password, salt=None):
    salt = salt or secrets.token_hex(8)
    h = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode(), 100_000).hex()
    return salt, h


def verifica_password(u, password):
    _, h = hash_password(password, u["salt"])
    return secrets.compare_digest(h, u["hash"])


def leggi_password(prompt):
    try:
        return getpass.getpass(prompt)
    except (EOFError, KeyboardInterrupt):
        print()
        raise SystemExit(0)


def nuova_password():
    while True:
        p1 = leggi_password("Password (min. 4 caratteri): ")
        if len(p1) < 4:
            print("Troppo corta.")
            continue
        if p1 != leggi_password("Ripeti password: "):
            print("Le password non coincidono.")
            continue
        return p1


def crea_utente(db, nome, password, ruolo="partecipante"):
    salt, h = hash_password(password)
    u = {"nome": nome, "ruolo": ruolo, "salt": salt, "hash": h, "gioca": True, "profilo": {}}
    prefs(u)
    db["utenti"].append(u)
    return u


# --------------------------------------------------------------------------
# Query sui dati
# --------------------------------------------------------------------------
def utente(db, nome):
    for u in db["utenti"]:
        if u["nome"].lower() == nome.strip().lower():
            return u
    return None


def etichetta_utente(db, nome):
    """Nome con l'eventuale soprannome scelto dal giocatore."""
    u = utente(db, nome)
    sopr = prefs(u)["soprannome"] if u else ""
    return f"{nome} ({sopr})" if sopr else nome


def giocatori(db):
    return [u for u in db["utenti"] if u["gioca"]]


def rosa(db, nome):
    return [m for m in db["musicisti"] if m["proprietario"] == nome]


def speso(db, nome):
    return sum(m["prezzo"] for m in rosa(db, nome))


def crediti(db, nome):
    return db["impostazioni"]["budget_iniziale"] - speso(db, nome)


def nome_musicista(db, mid):
    for m in db["musicisti"]:
        if m["id"] == mid:
            return m["nome"]
    return "?"


def eventi_ok(db):
    """Eventi con punteggio definitivo (esclusi quelli in pending)."""
    return [e for e in db["eventi"] if e.get("stato", "ok") == "ok"]


def eventi_pending(db):
    return [e for e in db["eventi"] if e.get("stato", "ok") == "pending"]


def punti_musicista(db, mid, proprietario=None):
    """Punti totali del musicista; con 'proprietario' solo quelli andati a quella squadra."""
    return sum(e["punti"] for e in eventi_ok(db)
               if e["musicista_id"] == mid and (proprietario is None or e["proprietario"] == proprietario))


def punti_utente(db, nome):
    return sum(e["punti"] for e in eventi_ok(db) if e["proprietario"] == nome)


def posizioni(valori):
    """Posizioni in classifica con parimerito (valori già ordinati dal più alto)."""
    pos = []
    for i, v in enumerate(valori):
        pos.append(pos[-1] if i and v == valori[i - 1] else i + 1)
    return pos


def classifica_giocatori(db):
    dati = sorted(((u["nome"], punti_utente(db, u["nome"])) for u in giocatori(db)),
                  key=lambda x: (-x[1], x[0].lower()))
    pos = posizioni([p for _, p in dati])
    return [(ps, n, p) for ps, (n, p) in zip(pos, dati)]


def eventi_recenti(db, n, filtro=None):
    """Gli ultimi n eventi (n = 0: tutti), il più recente per primo, ordinati per data."""
    ev = [e for e in db["eventi"] if (filtro is None or filtro(e))]
    ev.sort(key=lambda e: (e.get("data_completamento") or e["data"], e["id"]), reverse=True)
    return ev[:n] if n else ev


def campi_per(db, per):
    """Caratteristiche definite per 'musicisti' o 'giocatori'."""
    return [c for c in db["campi"] if c["per"] == per]


def profili_di(db, per):
    """Gli elementi che hanno un profilo: i musicisti, oppure gli utenti."""
    return db["musicisti"] if per == "musicisti" else db["utenti"]


def parse_numero(testo):
    """Numero intero o decimale (accetta anche la virgola); None se non valido."""
    try:
        v = float(testo.replace(",", "."))
    except ValueError:
        return None
    if not math.isfinite(v):
        return None
    return int(v) if v.is_integer() else v


def fmt_valore(v):
    return "-" if v is None or v == "" else str(v)


def fmt_segno(v):
    return f"{v:+g}"


def valore_profilo(elemento, campo):
    return fmt_valore(elemento.get("profilo", {}).get(str(campo["id"])))


def parse_ids(testo, validi):
    """'1, 3 4' -> [1, 3, 4]; None se contiene ID non validi."""
    ids = []
    for p in testo.replace(";", ",").replace(" ", ",").split(","):
        if not p:
            continue
        if not (p.isascii() and p.isdigit()) or int(p) not in validi:
            return None
        if int(p) not in ids:
            ids.append(int(p))
    return sorted(ids)


# ----- calcolo dei punteggi -----
def arrotonda(x):
    return int(math.floor(x + 0.5))


def calcola_punti(base, bonus):
    """Punteggio finale: i bonus in % si applicano alla base, poi si sommano quelli a punti."""
    perc = sum(b["valore"] for b in bonus if b["tipo"] == "percentuale")
    fissi = sum(b["valore"] for b in bonus if b["tipo"] == "punti")
    return arrotonda(base * (1 + perc / 100) + fissi)


def descrivi_bonus(b):
    return f"{b['nome']} ({fmt_segno(b['valore'])}{'%' if b['tipo'] == 'percentuale' else ''})"


def descrivi_punteggio(a):
    if a["modalita"] == "sondaggio":
        return f"sondaggio {a['min']}-{a['max']}"
    if a["modalita"] == "tempo":
        singolare = {"minuti": "minuto", "ore": "ora", "giorni": "giorno"}[a["unita"]]
        return f"{a['punti']:+d} per {singolare}"
    return f"{a['punti']:+d}"


def descrivi_calcolo(e):
    parti = []
    if e.get("dittatura"):
        return "DITTATURA"
    if e.get("dettaglio"):
        parti.append(e["dettaglio"])
    if e.get("bonus"):
        if e.get("base") is not None:
            parti.append(f"base {e['base']}")
        parti.extend(descrivi_bonus(b) for b in e["bonus"])
    return "; ".join(parti)


# --------------------------------------------------------------------------
# Input / output
# --------------------------------------------------------------------------
def ask(prompt=""):
    try:
        return input(prompt).strip()
    except (EOFError, KeyboardInterrupt):
        print("\nArrivederci!")
        raise SystemExit(0)


def ask_int(prompt, minimo=None, massimo=None):
    while True:
        try:
            v = int(ask(prompt))
        except ValueError:
            print("Inserisci un numero intero.")
            continue
        if minimo is not None and v < minimo:
            print(f"Il valore minimo è {minimo}.")
            continue
        if massimo is not None and v > massimo:
            print(f"Il valore massimo è {massimo}.")
            continue
        return v


def ask_num(prompt):
    while True:
        v = parse_numero(ask(prompt))
        if v is None:
            print("Serve un numero (es. 12 oppure 3,5).")
            continue
        return v


def ask_si(prompt):
    return ask(prompt + " (s/N) ").lower() == "s"


def pct(parte, totale):
    return f"{100 * parte / totale:.1f}%" if totale > 0 else "n/d"


def tabella(intest, righe, allinea=None):
    allinea = allinea or "<" * len(intest)
    colonne = list(zip(intest, *righe))
    larg = [max(len(str(c)) for c in col) for col in colonne]

    def riga(r):
        return "  ".join(f"{str(v):{a}{w}}" for v, a, w in zip(r, allinea, larg))

    print(riga(intest))
    print("  ".join("-" * w for w in larg))
    for r in righe:
        print(riga(r))


def solo_admin(fn):
    """Permessi globali: solo l'admin può eseguire il metodo."""
    @functools.wraps(fn)
    def wrapper(self, *args, **kwargs):
        if self.me["ruolo"] != "admin":
            print("Permesso negato: serve il ruolo admin.")
            return None
        return fn(self, *args, **kwargs)
    return wrapper


# ----- tabelle ordinabili -----
class Col:
    """Colonna di una tabella ordinabile.
    val(riga) -> valore grezzo (usato anche per ordinare, salvo 'ordine');
    fmt(valore, riga) -> testo da mostrare (None -> '-')."""

    def __init__(self, chiave, titolo, val, allinea="<", fmt=None, ordine=None, ordinabile=True):
        self.chiave, self.titolo, self.val, self.allinea = chiave, titolo, val, allinea
        self.fmt, self.ordine, self.ordinabile = fmt, ordine, ordinabile

    def testo(self, riga):
        v = self.val(riga)
        if self.fmt:
            return self.fmt(v, riga)
        return fmt_valore(v)


def ordina_righe(righe, col, decrescente):
    """Ordina per la colonna scelta; i valori mancanti restano sempre in fondo."""
    pieni, vuoti = [], []
    for r in righe:
        k = (col.ordine or col.val)(r)
        if isinstance(k, str):
            k = k.lower()
        (vuoti if k is None else pieni).append((k, r))
    try:
        pieni.sort(key=lambda t: t[0], reverse=decrescente)
    except TypeError:  # valori misti (testo e numeri)
        pieni.sort(key=lambda t: str(t[0]), reverse=decrescente)
    return [r for _, r in pieni] + [r for _, r in vuoti]


# --------------------------------------------------------------------------
# Il gioco
# --------------------------------------------------------------------------
class Gioco:
    def __init__(self, db, me):
        self.db = db
        self.me = me

    def salva(self):
        salva(self.db)

    # ---------- menu ----------
    def menu(self, titolo, voci, indietro="Indietro"):
        while True:
            print(f"\n=== {titolo} ===")
            for i, (etichetta, _) in enumerate(voci, 1):
                print(f"  {i}. {etichetta}")
            print(f"  0. {indietro}")
            s = ask("> ")
            if s == "0":
                return
            if s.isascii() and s.isdigit() and 1 <= int(s) <= len(voci):
                voci[int(s) - 1][1]()
                self.salva()
            else:
                print("Scelta non valida.")

    def avvia(self):
        p = prefs(self.me)
        print(f"\nBenvenuto, {p['soprannome'] or self.me['nome']}! (ruolo: {self.me['ruolo']})")
        self.riepilogo_accesso()
        voci = [
            ("Classifica", self.menu_classifica),
            ("Statistiche", self.menu_statistiche),
            ("La mia squadra", lambda: self.dettaglio_squadra(self.me["nome"])),
            ("Profili (musicisti e giocatori)", self.menu_profili),
            ("Impostazioni", self.impostazioni),
            ("Cambia la mia password", self.cambia_password),
        ]
        if self.me["ruolo"] == "admin":
            voci.append(("PANNELLO ADMIN", self.menu_admin))
        self.menu(f"{self.db['impostazioni']['stagione']} - Menu principale", voci, "Esci")

    def riepilogo_accesso(self):
        db, me = self.db, self.me
        p = prefs(me)
        da = p["ultimo_accesso"]
        if p["riepilogo_login"]:
            righe = []
            if me["gioca"]:
                cl = classifica_giocatori(db)
                mia = next((x for x in cl if x[1] == me["nome"]), None)
                if mia:
                    righe.append(f"Sei {mia[0]}° in classifica con {mia[2]} punti.")
                if da:
                    nuovi = [e for e in eventi_ok(db) if e["proprietario"] == me["nome"]
                             and (e.get("data_completamento") or e["data"]) > da]
                    righe.append(f"Dall'ultimo accesso ({da}): {len(nuovi)} eventi per la tua squadra "
                                 f"({sum(e['punti'] for e in nuovi):+d} punti).")
            n_pend = len(eventi_pending(db))
            if n_pend:
                righe.append(f"Eventi in pending (sondaggi da completare): {n_pend}.")
            for r in righe:
                print("  " + r)
        p["ultimo_accesso"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.salva()

    def cambia_password(self):
        self.me["salt"], self.me["hash"] = hash_password(nuova_password())
        print("Password aggiornata.")

    # ---------- scelta per ID / nome (l'elenco viene sempre mostrato prima) ----------
    def scegli_per_id(self, lista, prompt, mostra):
        """Mostra l'elenco (anche dopo un ID errato) e chiede un ID; invio = annulla."""
        while True:
            mostra()
            s = ask(prompt)
            if not s:
                return None
            if s.isascii() and s.isdigit():
                for x in lista:
                    if x["id"] == int(s):
                        return x
            print("ID non valido.")

    def scegli_utente(self, prompt, invio_sono_io=False):
        while True:
            self.mostra_utenti()
            s = ask(prompt)
            if not s:
                return self.me if invio_sono_io else None
            u = utente(self.db, s)
            if u:
                return u
            print("Utente non trovato.")

    # ---------- ordinamenti ----------
    def ordine_salvato(self, lid, colonne, default):
        chiavi = {c.chiave: c for c in colonne if c.ordinabile}
        sal = prefs(self.me)["ordinamenti"].get(lid)
        if sal and sal[0] in chiavi:
            return chiavi[sal[0]], bool(sal[1])
        return chiavi[default[0]], default[1]

    def stampa(self, lid, colonne, righe, default):
        """Stampa la tabella con l'ordinamento salvato dall'utente per questa lista."""
        col, desc = self.ordine_salvato(lid, colonne, default)
        righe = ordina_righe(righe, col, desc)
        celle = [[c.testo(r) for c in colonne] for r in righe]
        tabella([c.titolo for c in colonne], celle, "".join(c.allinea for c in colonne))
        return col, desc

    def scegli_ordine(self, lid, colonne):
        opz = [c for c in colonne if c.ordinabile]
        print("Ordina per:")
        for i, c in enumerate(opz, 1):
            print(f"  {i}. {c.titolo}")
        n = ask_int("Numero: ", 1, len(opz))
        desc = ask("1 = crescente (A-Z, dal più piccolo), 2 = decrescente [1]: ") == "2"
        prefs(self.me)["ordinamenti"][lid] = [opz[n - 1].chiave, desc]
        self.salva()

    def vista(self, lid, colonne, righe, default, intestazione=None):
        """Tabella con possibilità di cambiare l'ordine (la scelta viene ricordata)."""
        while True:
            if intestazione:
                print(intestazione)
            col, desc = self.stampa(lid, colonne, righe, default)
            if len(righe) < 2:
                return
            if not ask_si(f"Ordinato per {col.titolo} ({'decrescente' if desc else 'crescente'}). "
                          f"Cambia ordine?"):
                return
            self.scegli_ordine(lid, colonne)

    def colonne_campi(self, per, elemento):
        """Una colonna per ogni caratteristica dei profili; elemento(riga) -> musicista/utente."""
        def val(c):
            return lambda r: elemento(r).get("profilo", {}).get(str(c["id"]))
        return [Col("c%d" % c["id"], c["nome"], val(c), ">" if c["tipo"] == "numero" else "<")
                for c in campi_per(self.db, per)]

    # ---------- colonne e tabelle dei vari elenchi ----------
    def colonne_musicisti(self, campi=False):
        db = self.db
        cols = [Col("id", "ID", lambda m: m["id"], ">"),
                Col("nome", "Musicista", lambda m: m["nome"]),
                Col("squadra", "Squadra", lambda m: m["proprietario"]),
                Col("prezzo", "Prezzo", lambda m: m["prezzo"] if m["proprietario"] else None, ">"),
                Col("punti", "Punti", lambda m: punti_musicista(db, m["id"]), ">")]
        if campi:
            cols += self.colonne_campi("musicisti", lambda m: m)
        return cols

    def mostra_musicisti(self, lista=None):
        self.stampa("musicisti", self.colonne_musicisti(), self.db["musicisti"] if lista is None else lista,
                    ("id", False))

    def colonne_utenti(self):
        db = self.db
        return [Col("nome", "Utente", lambda u: u["nome"], fmt=lambda v, u: etichetta_utente(db, v)),
                Col("ruolo", "Ruolo", lambda u: u["ruolo"]),
                Col("gioca", "In classifica", lambda u: u["gioca"], fmt=lambda v, u: "sì" if v else "no"),
                Col("musicisti", "Musicisti", lambda u: len(rosa(db, u["nome"])), ">"),
                Col("crediti", "Crediti", lambda u: crediti(db, u["nome"]), ">")]

    def mostra_utenti(self):
        self.stampa("utenti", self.colonne_utenti(), self.db["utenti"], ("nome", False))

    def colonne_eventi(self):
        db = self.db

        def punti_txt(v, e):
            if e.get("stato") == "pending":
                return "PENDING"
            return f"{v:+d}" + ("*" if e.get("dittatura") else "")
        return [Col("id", "ID", lambda e: e["id"], ">"),
                Col("data", "Data", lambda e: e.get("data_completamento") or e["data"]),
                Col("musicista", "Musicista", lambda e: nome_musicista(db, e["musicista_id"])),
                Col("azione", "Azione", lambda e: e["azione"]),
                Col("punti", "Punti", lambda e: e["punti"], ">", fmt=punti_txt,
                    ordine=lambda e: e["punti"] if e.get("stato") != "pending" else None),
                Col("squadra", "Squadra", lambda e: e["proprietario"]),
                Col("calcolo", "Calcolo", descrivi_calcolo, ordinabile=False)]

    def mostra_eventi(self, eventi, lid="eventi"):
        self.stampa(lid, self.colonne_eventi(), eventi, ("data", True))

    def mostra_ultimi_eventi(self):
        self.mostra_eventi(eventi_recenti(self.db, prefs(self.me)["righe_eventi"]))

    def mostra_pending(self):
        self.mostra_eventi(eventi_pending(self.db), "pending")

    def colonne_azioni(self):
        db = self.db
        return [Col("id", "ID", lambda a: a["id"], ">"),
                Col("nome", "Azione", lambda a: a["nome"]),
                Col("modalita", "Modalità", lambda a: a["modalita"]),
                Col("punti", "Punteggio", descrivi_punteggio, ">",
                    ordine=lambda a: a["min"] if a["modalita"] == "sondaggio" else a["punti"]),
                Col("bonus", "Bonus/malus", lambda a: ", ".join(b["nome"] for b in db["bonus"]
                                                               if b["id"] in a["bonus_ids"]) or None,
                    ordinabile=False)]

    def mostra_azioni(self):
        self.stampa("azioni", self.colonne_azioni(), self.db["azioni"], ("id", False))

    def colonne_bonus(self):
        db = self.db
        return [Col("id", "ID", lambda b: b["id"], ">"),
                Col("nome", "Nome", lambda b: b["nome"]),
                Col("tipo", "Tipo", lambda b: b["tipo"]),
                Col("valore", "Valore", lambda b: b["valore"], ">",
                    fmt=lambda v, b: fmt_segno(v) + ("%" if b["tipo"] == "percentuale" else "")),
                Col("azioni", "Collegato a", lambda b: ", ".join(a["nome"] for a in db["azioni"]
                                                                 if b["id"] in a["bonus_ids"]) or None,
                    ordinabile=False)]

    def mostra_bonus(self):
        self.stampa("bonus", self.colonne_bonus(), self.db["bonus"], ("id", False))

    def colonne_campi_def(self):
        db = self.db

        def compilati(c):
            profili = profili_di(db, c["per"])
            return sum(1 for p in profili if str(c["id"]) in p.get("profilo", {})), len(profili)
        return [Col("id", "ID", lambda c: c["id"], ">"),
                Col("per", "Per", lambda c: c["per"]),
                Col("nome", "Caratteristica", lambda c: c["nome"]),
                Col("tipo", "Tipo", lambda c: c["tipo"]),
                Col("compilata", "Compilata", compilati,
                    fmt=lambda v, c: f"{v[0]}/{v[1]} ({pct(v[0], v[1])})",
                    ordine=lambda c: compilati(c)[0])]

    def mostra_campi(self):
        self.stampa("campi", self.colonne_campi_def(), self.db["campi"], ("id", False))

    # ---------- classifica ----------
    def menu_classifica(self):
        self.menu("Classifica", [("Giocatori", self.classifica_giocatori),
                                 ("Musicisti", self.classifica_musicisti)])

    def classifica_giocatori(self):
        db = self.db
        cl = classifica_giocatori(db)
        if not cl:
            print("Nessun giocatore.")
            return
        n_max = db["impostazioni"]["musicisti_per_squadra"]
        totale = sum(p for _, _, p in cl)
        capo = cl[0][2]
        cols = [Col("pos", "Pos", lambda r: r[0], ">"),
                Col("nome", "Giocatore", lambda r: r[1], fmt=lambda v, r: etichetta_utente(db, v)),
                Col("punti", "Punti", lambda r: r[2], ">"),
                Col("distacco", "Distacco", lambda r: r[2] - capo, ">",
                    fmt=lambda v, r: "-" if v == 0 else str(v), ordinabile=False),
                Col("perc", "% punti", lambda r: r[2], ">", fmt=lambda v, r: pct(v, totale), ordinabile=False),
                Col("rosa", "Rosa", lambda r: len(rosa(db, r[1])), ">", fmt=lambda v, r: f"{v}/{n_max}")]
        cols += self.colonne_campi("giocatori", lambda r: utente(db, r[1]))
        self.vista("cl_giocatori", cols, cl, ("pos", False),
                   f"\nClassifica giocatori - {db['impostazioni']['stagione']}")

    def classifica_musicisti(self):
        db = self.db
        if not db["musicisti"]:
            print("Nessun musicista.")
            return
        tot = sum(e["punti"] for e in eventi_ok(db))
        dati = sorted(((m, punti_musicista(db, m["id"])) for m in db["musicisti"]),
                      key=lambda x: (-x[1], x[0]["nome"].lower()))
        pos = posizioni([p for _, p in dati])
        righe = [(ps, m, p) for ps, (m, p) in zip(pos, dati)]
        cols = [Col("pos", "Pos", lambda r: r[0], ">"),
                Col("nome", "Musicista", lambda r: r[1]["nome"]),
                Col("squadra", "Squadra", lambda r: r[1]["proprietario"]),
                Col("punti", "Punti", lambda r: r[2], ">"),
                Col("perc", "% punti", lambda r: r[2], ">", fmt=lambda v, r: pct(v, tot), ordinabile=False)]
        cols += self.colonne_campi("musicisti", lambda r: r[1])
        self.vista("cl_musicisti", cols, righe, ("pos", False), "\nClassifica musicisti")

    # ---------- statistiche ----------
    def menu_statistiche(self):
        self.menu("Statistiche", [
            ("Riepilogo generale", self.stat_riepilogo),
            ("Azioni più frequenti", self.stat_azioni),
            ("Squadre a confronto", self.stat_squadre),
            ("Dettaglio di una squadra", self.scegli_squadra),
            ("Migliori e peggiori affari (punti per credito)", self.stat_affari),
            ("Ultimi eventi", self.stat_ultimi_eventi),
            ("Eventi in pending", self.stat_pending),
        ])

    def stat_riepilogo(self):
        db = self.db
        s = db["impostazioni"]
        ev, mus, gio = eventi_ok(db), db["musicisti"], giocatori(db)
        venduti = [m for m in mus if m["proprietario"]]
        budget_tot = s["budget_iniziale"] * len(gio)
        speso_tot = sum(speso(db, u["nome"]) for u in gio)
        tot_punti = sum(e["punti"] for e in ev)
        pos = [e for e in ev if e["punti"] > 0]
        neg = [e for e in ev if e["punti"] < 0]
        senza = sum(e["punti"] for e in ev if not e["proprietario"])
        print(f"\nRiepilogo - {s['stagione']}")
        print(f"  Giocatori:              {len(gio)}")
        print(f"  Musicisti acquistati:   {len(venduti)}/{len(mus)} ({pct(len(venduti), len(mus))})")
        print(f"  Crediti spesi in asta:  {speso_tot}/{budget_tot} ({pct(speso_tot, budget_tot)})")
        print(f"  Eventi registrati:      {len(ev)}  (in pending: {len(eventi_pending(db))})")
        if ev:
            print(f"    positivi:             {len(pos)} ({pct(len(pos), len(ev))})")
            print(f"    negativi:             {len(neg)} ({pct(len(neg), len(ev))})")
            ditt = sum(1 for e in ev if e.get("dittatura"))
            print(f"    con bonus/malus:      {sum(1 for e in ev if e['bonus'])} "
                  f"({pct(sum(1 for e in ev if e['bonus']), len(ev))}) - DITTATURA: {ditt} ({pct(ditt, len(ev))})")
            print(f"  Punti totali assegnati: {tot_punti:+d} (media {tot_punti / len(ev):+.1f} a evento)")
            print(f"  Punti a musicisti senza squadra: {senza:+d} ({pct(senza, tot_punti)} del totale)")
            migliore = max(ev, key=lambda e: e["punti"])
            peggiore = min(ev, key=lambda e: e["punti"])
            print(f"  Evento migliore:  {migliore['punti']:+d}  {nome_musicista(db, migliore['musicista_id'])} - {migliore['azione']}")
            print(f"  Evento peggiore:  {peggiore['punti']:+d}  {nome_musicista(db, peggiore['musicista_id'])} - {peggiore['azione']}")

    def stat_azioni(self):
        ev = eventi_ok(self.db)
        if not ev:
            print("Nessun evento registrato.")
            return
        agg = {}
        for e in ev:
            c = agg.setdefault(e["azione"], [0, 0])
            c[0] += 1
            c[1] += e["punti"]
        righe = [(n, c[0], c[1]) for n, c in agg.items()]
        cols = [Col("nome", "Azione", lambda r: r[0]),
                Col("volte", "Volte", lambda r: r[1], ">"),
                Col("perc", "% eventi", lambda r: r[1], ">", fmt=lambda v, r: pct(v, len(ev)), ordinabile=False),
                Col("tot", "Punti tot.", lambda r: r[2], ">", fmt=lambda v, r: f"{v:+d}"),
                Col("media", "Media", lambda r: r[2] / r[1], ">", fmt=lambda v, r: f"{v:+.1f}")]
        self.vista("st_azioni", cols, righe, ("volte", True), "\nAzioni più frequenti")

    def stat_squadre(self):
        db = self.db
        s = db["impostazioni"]
        cl = classifica_giocatori(db)
        if not cl:
            print("Nessun giocatore.")
            return
        tot = sum(p for _, _, p in cl)
        cols = [Col("pos", "Pos", lambda r: r[0], ">"),
                Col("nome", "Giocatore", lambda r: r[1], fmt=lambda v, r: etichetta_utente(db, v)),
                Col("speso", "Speso", lambda r: speso(db, r[1]), ">",
                    fmt=lambda v, r: f"{v}/{s['budget_iniziale']}"),
                Col("budget", "% budget", lambda r: speso(db, r[1]), ">",
                    fmt=lambda v, r: pct(v, s["budget_iniziale"]), ordinabile=False),
                Col("punti", "Punti", lambda r: r[2], ">"),
                Col("perc", "% punti", lambda r: r[2], ">", fmt=lambda v, r: pct(v, tot), ordinabile=False),
                Col("resa", "Punti/credito", lambda r: r[2] / speso(db, r[1]) if speso(db, r[1]) else None,
                    ">", fmt=lambda v, r: f"{v:.2f}"),
                Col("media", "Media/musicista", lambda r: r[2] / len(rosa(db, r[1])) if rosa(db, r[1]) else None,
                    ">", fmt=lambda v, r: f"{v:.1f}")]
        self.vista("st_squadre", cols, cl, ("pos", False), "\nSquadre a confronto")

    def scegli_squadra(self):
        u = self.scegli_utente("Nome giocatore (invio = la tua squadra): ", invio_sono_io=True)
        if u:
            self.dettaglio_squadra(u["nome"])

    def dettaglio_squadra(self, nome, interattiva=True):
        db = self.db
        s = db["impostazioni"]
        r = rosa(db, nome)
        tot = punti_utente(db, nome)
        print(f"\nSquadra di {nome}: crediti residui {crediti(db, nome)}/{s['budget_iniziale']}, "
              f"musicisti {len(r)}/{s['musicisti_per_squadra']}")
        if not r:
            print("Nessun musicista in squadra.")
            return
        sp = speso(db, nome)
        righe = [(m, punti_musicista(db, m["id"], nome)) for m in r]
        cols = [Col("nome", "Musicista", lambda x: x[0]["nome"]),
                Col("prezzo", "Prezzo", lambda x: x[0]["prezzo"], ">"),
                Col("spesa", "% spesa", lambda x: x[0]["prezzo"], ">", fmt=lambda v, x: pct(v, sp),
                    ordinabile=False),
                Col("punti", "Punti", lambda x: x[1], ">"),
                Col("perc", "% punti squadra", lambda x: x[1], ">", fmt=lambda v, x: pct(v, tot),
                    ordinabile=False),
                Col("resa", "Punti/credito", lambda x: x[1] / x[0]["prezzo"] if x[0]["prezzo"] else None, ">",
                    fmt=lambda v, x: f"{v:.2f}")]
        if interattiva:
            self.vista("squadra", cols, righe, ("punti", True))
        else:
            self.stampa("squadra", cols, righe, ("punti", True))
        ex = tot - sum(p for _, p in righe)
        if ex:
            print(f"Punti maturati da musicisti non più in squadra: {ex:+d}")
        cl = classifica_giocatori(db)
        posizione = next((pos for pos, n, _ in cl if n == nome), None)
        print(f"Totale squadra: {tot:+d} punti" + (f" - posizione in classifica: {posizione}°" if posizione else ""))

    def stat_affari(self):
        db = self.db
        righe = []
        for m in db["musicisti"]:
            if m["proprietario"] and m["prezzo"] > 0:
                p = punti_musicista(db, m["id"], m["proprietario"])
                righe.append((m, p))
        if not righe:
            print("Nessun musicista acquistato.")
            return
        cols = [Col("nome", "Musicista", lambda r: r[0]["nome"]),
                Col("squadra", "Squadra", lambda r: r[0]["proprietario"]),
                Col("prezzo", "Prezzo", lambda r: r[0]["prezzo"], ">"),
                Col("punti", "Punti", lambda r: r[1], ">"),
                Col("resa", "Punti/credito", lambda r: r[1] / r[0]["prezzo"], ">", fmt=lambda v, r: f"{v:.2f}")]
        self.vista("st_affari", cols, righe, ("resa", True),
                   "\nResa dei musicisti (punti per credito speso)")

    def stat_ultimi_eventi(self):
        if not self.db["eventi"]:
            print("Nessun evento registrato.")
            return
        n = prefs(self.me)["righe_eventi"]
        self.vista("eventi", self.colonne_eventi(), eventi_recenti(self.db, n), ("data", True),
                   f"\nUltimi {n} eventi (puoi cambiare il numero da Impostazioni > Preferenze)"
                   if n else "\nTutti gli eventi")

    def stat_pending(self):
        pend = eventi_pending(self.db)
        if not pend:
            print("Nessun evento in pending.")
            return
        self.vista("pending", self.colonne_eventi(), pend, ("data", True),
                   "\nEventi in pending: il punteggio si decide dopo il sondaggio")

    # ---------- profili (consultazione, per tutti) ----------
    def menu_profili(self):
        self.menu("Profili", [("Profilo di un musicista", self.profilo_musicista),
                              ("Profilo di un giocatore", self.profilo_giocatore)])

    def stampa_caratteristiche(self, elemento, per):
        campi = campi_per(self.db, per)
        if not campi:
            print("(nessuna caratteristica definita)")
            return
        larg = max(len(c["nome"]) for c in campi) + 1
        for c in campi:
            print(f"  {c['nome'] + ':':<{larg}} {valore_profilo(elemento, c)}")

    def profilo_musicista(self):
        db = self.db
        if not db["musicisti"]:
            print("Nessun musicista.")
            return
        m = self.scegli_per_id(db["musicisti"], "ID musicista (invio per tornare indietro): ",
                               lambda: self.stampa("musicisti", self.colonne_musicisti(campi=True),
                                                   db["musicisti"], ("id", False)))
        if not m:
            return
        tot = sum(e["punti"] for e in eventi_ok(db))
        p = punti_musicista(db, m["id"])
        print(f"\n=== {m['nome']} ===")
        if m["proprietario"]:
            print(f"  Squadra: {m['proprietario']} (pagato {m['prezzo']} crediti)")
        else:
            print("  Squadra: nessuna (libero)")
        print(f"  Punti:   {p:+d} ({pct(p, tot)} dei punti totali)")
        self.stampa_caratteristiche(m, "musicisti")
        recenti = eventi_recenti(db, 5, lambda e: e["musicista_id"] == m["id"])
        if recenti:
            print("\nUltimi eventi")
            self.mostra_eventi(recenti)

    def profilo_giocatore(self):
        db = self.db
        u = self.scegli_utente("Nome giocatore (invio = il tuo profilo): ", invio_sono_io=True)
        if not u:
            return
        print(f"\n=== {etichetta_utente(db, u['nome'])} ===")
        self.stampa_caratteristiche(u, "giocatori")
        if u["gioca"]:
            self.dettaglio_squadra(u["nome"], interattiva=False)

    # ---------- impostazioni ----------
    def impostazioni(self):
        self.menu("Impostazioni", [("Preferenze personali", self.preferenze),
                                   ("Impostazioni della stagione", self.impostazioni_stagione)])

    def preferenze(self):
        p = prefs(self.me)
        while True:
            print("\n=== Preferenze personali (salvate nel tuo profilo, valgono a ogni accesso) ===")
            print(f"  1. Soprannome (nel saluto e in classifica): {p['soprannome'] or '-'}")
            print(f"  2. Riepilogo all'accesso:                   {'sì' if p['riepilogo_login'] else 'no'}")
            print(f"  3. Eventi mostrati negli elenchi:           {p['righe_eventi'] or 'tutti'}")
            print(f"  4. Ordinamenti ricordati:                   {len(p['ordinamenti'])} "
                  f"(sceglilo per ripristinare quelli predefiniti)")
            s = ask("Numero da modificare (0 = indietro): ")
            if s in ("", "0"):
                return
            if s == "1":
                nuovo = ask("Nuovo soprannome (max 20 caratteri, - per toglierlo): ")
                if nuovo == "-":
                    p["soprannome"] = ""
                elif nuovo:
                    p["soprannome"] = nuovo[:20]
            elif s == "2":
                p["riepilogo_login"] = not p["riepilogo_login"]
            elif s == "3":
                p["righe_eventi"] = ask_int("Quanti eventi mostrare (0 = tutti): ", 0)
            elif s == "4":
                if ask_si("Ripristinare gli ordinamenti predefiniti di tutti gli elenchi?"):
                    p["ordinamenti"].clear()
            else:
                print("Scelta non valida.")
                continue
            self.salva()

    def impostazioni_stagione(self):
        s = self.db["impostazioni"]
        while True:
            print("\n=== Impostazioni della stagione ===")
            print(f"  1. Nome stagione:             {s['stagione']}")
            print(f"  2. Musicisti per squadra:     {s['musicisti_per_squadra']}")
            print(f"  3. Budget iniziale (crediti): {s['budget_iniziale']}")
            print(f"  4. Rilancio minimo all'asta:  {s['rilancio_minimo']}")
            if self.me["ruolo"] != "admin":
                print("\n(Sola lettura: solo l'admin può modificare le impostazioni.)")
                return
            scelta = ask("Numero da modificare (0 = indietro): ")
            if scelta in ("", "0"):
                return
            self.modifica_impostazione(scelta)
            self.salva()

    @solo_admin
    def modifica_impostazione(self, scelta):
        db = self.db
        s = db["impostazioni"]
        if scelta == "1":
            nome = ask("Nuovo nome stagione: ")
            if nome:
                s["stagione"] = nome
        elif scelta == "2":
            n = ask_int("Nuovo numero di musicisti per squadra: ", 1)
            troppi = [f"{u['nome']} ({len(rosa(db, u['nome']))})" for u in db["utenti"]
                      if len(rosa(db, u["nome"])) > n]
            if troppi:
                print("Impossibile: queste squadre hanno già più musicisti: " + ", ".join(troppi))
                print("Svincola prima qualche musicista dal pannello admin.")
            elif n > s["budget_iniziale"]:
                print("Impossibile: serve almeno 1 credito di budget per ogni posto in squadra.")
            else:
                s["musicisti_per_squadra"] = n
                print(f"Ora ogni squadra ha {n} posti.")
        elif scelta == "3":
            b = ask_int("Nuovo budget iniziale: ", 1)
            oltre = [f"{u['nome']} ({speso(db, u['nome'])})" for u in db["utenti"] if speso(db, u["nome"]) > b]
            if oltre:
                print("Impossibile: hanno già speso di più: " + ", ".join(oltre))
            elif b < s["musicisti_per_squadra"]:
                print("Impossibile: serve almeno 1 credito per ogni posto in squadra.")
            else:
                s["budget_iniziale"] = b
                print("Budget aggiornato (i crediti residui si ricalcolano da soli).")
        elif scelta == "4":
            s["rilancio_minimo"] = ask_int("Nuovo rilancio minimo: ", 1)
        else:
            print("Scelta non valida.")

    # ---------- pannello admin ----------
    @solo_admin
    def menu_admin(self):
        self.menu("Pannello admin", [
            ("Registra evento / assegna punti", self.registra_evento),
            ("DITTATURA (evento con punteggio deciso a mano)", self.dittatura),
            ("Completa un evento in pending (valore del sondaggio)", self.completa_pending),
            ("Asta musicisti", self.asta),
            ("Gestione musicisti", self.menu_musicisti),
            ("Gestione azioni", self.menu_azioni),
            ("Bonus e malus", self.menu_bonus),
            ("Gestione utenti", self.menu_utenti),
            ("Caratteristiche dei profili", self.menu_campi),
            ("Elimina un evento", self.elimina_evento),
            ("Azzera stagione", self.azzera_stagione),
        ])

    # ----- registrazione eventi -----
    def scegli_musicista_azione(self):
        db = self.db
        if not db["musicisti"] or not db["azioni"]:
            print("Servono almeno un musicista e un'azione.")
            return None, None
        m = self.scegli_per_id(db["musicisti"], "ID musicista (invio per annullare): ", self.mostra_musicisti)
        if not m:
            return None, None
        a = self.scegli_per_id(db["azioni"], "ID azione (invio per annullare): ", self.mostra_azioni)
        return (m, a) if a else (None, None)

    def chiedi_base(self, a):
        """Punteggio base dell'azione: (base, dettaglio, pending) oppure None se annullato."""
        if a["modalita"] == "sondaggio":
            lo, hi = a["min"], a["max"]
            while True:
                s = ask(f"Valore del sondaggio da {lo} a {hi} (invio = lascia in PENDING): ")
                if not s:
                    return None, "", True
                if s.isascii() and s.isdigit() and lo <= int(s) <= hi:
                    return int(s), f"sondaggio {int(s)}", False
                print(f"Inserisci un intero da {lo} a {hi}.")
        if a["modalita"] == "tempo":
            while True:
                s = ask(f"Tempo in {a['unita']} (es. 90 o 1,5; invio per annullare): ")
                if not s:
                    return None
                v = parse_numero(s)
                if v is None or v <= 0:
                    print("Serve un numero maggiore di zero.")
                    continue
                return arrotonda(v * a["punti"]), f"{fmt_valore(v)} {a['unita']} x {a['punti']:+d}", False
        return a["punti"], "", False

    def chiedi_bonus_da_applicare(self, a):
        """Per ogni bonus/malus collegato all'azione chiede se applicarlo; ritorna gli snapshot."""
        scelti = []
        for b in self.db["bonus"]:
            if b["id"] in a["bonus_ids"] and ask_si(f"Applicare {descrivi_bonus(b)}?"):
                scelti.append({"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"]})
        return scelti

    def aggiungi_evento(self, m, a, punti, base, bonus, dettaglio, pending, nota, dittatura=False, fascia=None):
        db = self.db
        e = {
            "id": prossimo_id(db, "evento"),
            "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "musicista_id": m["id"],
            "azione_id": a["id"],
            "azione": a["nome"],
            "stato": "pending" if pending else "ok",
            "punti": 0 if pending else punti,
            "base": None if pending else base,
            "bonus": bonus,
            "dettaglio": dettaglio,
            "dittatura": dittatura,
            "proprietario": m["proprietario"],
            "nota": nota,
        }
        if fascia:
            e["fascia"] = list(fascia)
        db["eventi"].append(e)
        return e

    @solo_admin
    def registra_evento(self):
        m, a = self.scegli_musicista_azione()
        if not m:
            return
        risultato = self.chiedi_base(a)
        if risultato is None:
            print("Annullato.")
            return
        base, dettaglio, pending = risultato
        bonus = self.chiedi_bonus_da_applicare(a)
        punti = None if pending else calcola_punti(base, bonus)
        nota = ask("Nota (facoltativa): ")
        fascia = (a["min"], a["max"]) if a["modalita"] == "sondaggio" else None
        e = self.aggiungi_evento(m, a, punti, base, bonus, dettaglio, pending, nota, fascia=fascia)
        dove = f"alla squadra di {m['proprietario']}" if m["proprietario"] else "a nessuno (musicista senza squadra)"
        if pending:
            print(f"Evento {e['id']} registrato in PENDING per {m['nome']} ({a['nome']}): "
                  f"completalo quando il sondaggio è chiuso.")
        else:
            calcolo = descrivi_calcolo(e)
            print(f"Registrato: {punti:+d} a {m['nome']} -> {dove}." + (f" [{calcolo}]" if calcolo else ""))

    @solo_admin
    def dittatura(self):
        print("DITTATURA: l'evento viene inserito col punteggio che decidi tu, "
              "senza sondaggi, calcoli sul tempo né bonus/malus.")
        m, a = self.scegli_musicista_azione()
        if not m:
            return
        punti = ask_int("Punteggio finale (anche negativo): ")
        nota = ask("Nota (facoltativa): ")
        self.aggiungi_evento(m, a, punti, punti, [], "", False, nota, dittatura=True)
        dove = f"alla squadra di {m['proprietario']}" if m["proprietario"] else "a nessuno (musicista senza squadra)"
        print(f"DITTATURA: {punti:+d} a {m['nome']} ({a['nome']}) -> {dove}.")

    @solo_admin
    def completa_pending(self):
        db = self.db
        if not eventi_pending(db):
            print("Nessun evento in pending.")
            return
        e = self.scegli_per_id(eventi_pending(db), "ID evento da completare (invio per annullare): ",
                               self.mostra_pending)
        if not e:
            return
        az = next((a for a in db["azioni"] if a["id"] == e.get("azione_id")), None)
        lo, hi = (e.get("fascia") or ((az["min"], az["max"]) if az else (1, 10)))
        while True:
            s = ask(f"Valore del sondaggio da {lo} a {hi} (invio per annullare): ")
            if not s:
                return
            if s.isascii() and s.isdigit() and lo <= int(s) <= hi:
                break
            print(f"Inserisci un intero da {lo} a {hi}.")
        base = int(s)
        e["base"] = base
        e["punti"] = calcola_punti(base, e["bonus"])
        e["dettaglio"] = f"sondaggio {base}"
        e["stato"] = "ok"
        e["data_completamento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        print(f"Evento {e['id']} completato: {e['punti']:+d} punti "
              f"({nome_musicista(db, e['musicista_id'])} -> {e['proprietario'] or 'nessuna squadra'}).")

    @solo_admin
    def elimina_evento(self):
        db = self.db
        ev = db["eventi"]
        if not ev:
            print("Nessun evento registrato.")
            return
        e = self.scegli_per_id(ev, "ID evento da eliminare (invio per annullare): ",
                               lambda: self.mostra_eventi(eventi_recenti(db, prefs(self.me)["righe_eventi"])))
        if e and ask_si("Confermi?"):
            ev.remove(e)
            riempi_buco(db, "eventi", "evento", e["id"])
            print("Evento eliminato: i punti sono stati tolti alla squadra.")

    # ----- asta -----
    def stato_crediti(self):
        db = self.db
        n_max = db["impostazioni"]["musicisti_per_squadra"]
        tabella(["Giocatore", "Crediti", "Posti liberi"],
                [(u["nome"], crediti(db, u["nome"]), n_max - len(rosa(db, u["nome"]))) for u in giocatori(db)], "<>>")

    @solo_admin
    def asta(self):
        db = self.db
        s = db["impostazioni"]
        n_max = s["musicisti_per_squadra"]
        while True:
            liberi = [m for m in db["musicisti"] if not m["proprietario"]]
            if not liberi:
                print("Nessun musicista disponibile all'asta.")
                return

            def elenco():
                print("\nMusicisti ancora disponibili:")
                self.mostra_musicisti(liberi)
            m = self.scegli_per_id(liberi, "ID musicista da mettere all'asta (invio per uscire): ", elenco)
            if not m:
                return
            print(f"\nASTA: {m['nome']} - base 1 credito, rilancio minimo {s['rilancio_minimo']}")
            print("Comandi: 'nome importo' = offerta | ok = aggiudica | annulla | stato = crediti")
            vincitore, miglior = None, 0
            while True:
                cmd = ask("asta> ")
                low = cmd.lower()
                if low == "annulla":
                    print("Asta annullata.")
                    break
                if low == "stato":
                    self.stato_crediti()
                    continue
                if low == "ok":
                    if not vincitore:
                        print("Nessuna offerta registrata.")
                        continue
                    m["proprietario"], m["prezzo"] = vincitore, miglior
                    self.salva()
                    print(f"AGGIUDICATO: {m['nome']} a {vincitore} per {miglior} crediti.")
                    break
                parti = cmd.rsplit(" ", 1)
                if len(parti) != 2 or not (parti[1].isascii() and parti[1].isdigit()):
                    print("Formato: nome importo (es. Mario 25)")
                    continue
                u, importo = utente(db, parti[0]), int(parti[1])
                if not u or not u["gioca"]:
                    print("Giocatore non trovato.")
                    continue
                posti = n_max - len(rosa(db, u["nome"]))
                if posti <= 0:
                    print(f"{u['nome']} ha già la squadra completa.")
                    continue
                minimo = 1 if vincitore is None else miglior + s["rilancio_minimo"]
                massimo = crediti(db, u["nome"]) - (posti - 1)  # 1 credito per ogni altro posto da riempire
                if importo < minimo:
                    print(f"Offerta troppo bassa: minimo {minimo}.")
                elif importo > massimo:
                    print(f"{u['nome']} può offrire al massimo {massimo} "
                          f"(deve tenere 1 credito per ogni altro posto da riempire).")
                else:
                    vincitore, miglior = u["nome"], importo
                    print(f"Offerta migliore: {vincitore} con {miglior}.")

    # ----- musicisti -----
    @solo_admin
    def menu_musicisti(self):
        self.menu("Musicisti", [
            ("Elenco", self.elenco_musicisti),
            ("Aggiungi musicisti", self.aggiungi_musicisti),
            ("Modifica un musicista (nome, prezzo, caratteristiche)", self.modifica_musicista),
            ("Rimuovi un musicista", self.rimuovi_musicista),
            ("Svincola un musicista (torna libero, rimborso)", self.svincola_musicista),
        ])

    @solo_admin
    def elenco_musicisti(self):
        if self.db["musicisti"]:
            self.vista("musicisti", self.colonne_musicisti(campi=True), self.db["musicisti"], ("id", False))
        else:
            print("Nessun musicista.")

    @solo_admin
    def aggiungi_musicisti(self):
        db = self.db
        print("Scrivi un nome per riga, riga vuota per finire.")
        while True:
            nome = ask("Nome: ")
            if not nome:
                return
            if any(m["nome"].lower() == nome.lower() for m in db["musicisti"]):
                print("Già presente.")
                continue
            db["musicisti"].append({"id": prossimo_id(db, "musicista"), "nome": nome,
                                    "proprietario": None, "prezzo": 0, "profilo": {}})

    @solo_admin
    def chiedi_valori_profilo(self, elemento, per):
        """Compila le caratteristiche di un profilo: invio = invariato, '-' = cancella."""
        campi = campi_per(self.db, per)
        if not campi:
            print("Nessuna caratteristica definita: creale da Pannello admin > Caratteristiche dei profili.")
            return
        profilo = elemento.setdefault("profilo", {})
        print("Caratteristiche (invio = lascia com'è, - = cancella il valore):")
        for c in campi:
            chiave = str(c["id"])
            while True:
                s = ask(f"  {c['nome']} ({c['tipo']}) [{valore_profilo(elemento, c)}]: ")
                if not s:
                    break
                if s == "-":
                    profilo.pop(chiave, None)
                    break
                if c["tipo"] == "numero":
                    v = parse_numero(s)
                    if v is None:
                        print("  Serve un numero (es. 12 oppure 3,5).")
                        continue
                    profilo[chiave] = v
                else:
                    profilo[chiave] = s
                break

    @solo_admin
    def modifica_musicista(self):
        db = self.db
        if not db["musicisti"]:
            print("Nessun musicista.")
            return
        m = self.scegli_per_id(db["musicisti"], "ID musicista da modificare (invio per annullare): ",
                               self.mostra_musicisti)
        if not m:
            return
        print(f"\nModifica di {m['nome']} (invio = lascia com'è)")
        nome = ask(f"Nome [{m['nome']}]: ")
        if nome and nome != m["nome"]:
            if any(x is not m and x["nome"].lower() == nome.lower() for x in db["musicisti"]):
                print("Esiste già un musicista con questo nome: nome lasciato invariato.")
            else:
                m["nome"] = nome
        if m["proprietario"]:
            s = ask(f"Prezzo pagato da {m['proprietario']} [{m['prezzo']}]: ")
            if s:
                nuovo = int(s) if s.isascii() and s.isdigit() else 0
                if nuovo < 1:
                    print("Il prezzo deve essere un intero di almeno 1: prezzo lasciato invariato.")
                elif nuovo - m["prezzo"] > crediti(db, m["proprietario"]):
                    print(f"{m['proprietario']} non ha crediti sufficienti "
                          f"({crediti(db, m['proprietario'])} disponibili): prezzo lasciato invariato.")
                else:
                    m["prezzo"] = nuovo
        self.chiedi_valori_profilo(m, "musicisti")
        print(f"{m['nome']} aggiornato.")

    @solo_admin
    def rimuovi_musicista(self):
        db = self.db
        m = self.scegli_per_id(db["musicisti"], "ID da rimuovere (invio per annullare): ", self.mostra_musicisti)
        if not m:
            return
        if m["proprietario"]:
            print("Prima svincolalo dalla squadra.")
        elif any(e["musicista_id"] == m["id"] for e in db["eventi"]):
            print("Ha eventi registrati: eliminali prima oppure lascialo in elenco.")
        elif ask_si(f"Rimuovere {m['nome']}?"):
            db["musicisti"].remove(m)
            sp = riempi_buco(db, "musicisti", "musicista", m["id"])
            if sp:
                for e in db["eventi"]:
                    if e["musicista_id"] == sp[0]:
                        e["musicista_id"] = sp[1]
                print(f"Il musicista con ID {sp[0]} ora ha ID {sp[1]}.")

    @solo_admin
    def svincola_musicista(self):
        db = self.db
        venduti = [m for m in db["musicisti"] if m["proprietario"]]
        if not venduti:
            print("Nessun musicista acquistato.")
            return
        m = self.scegli_per_id(venduti, "ID da svincolare (invio per annullare): ",
                               lambda: self.mostra_musicisti(venduti))
        if not m:
            return
        print(f"{m['nome']} torna libero e {m['proprietario']} recupera {m['prezzo']} crediti. "
              f"I punti già maturati restano alla squadra.")
        if ask_si("Confermi?"):
            m["proprietario"], m["prezzo"] = None, 0

    # ----- azioni -----
    @solo_admin
    def menu_azioni(self):
        self.menu("Azioni e punteggi", [
            ("Elenco", self.elenco_azioni),
            ("Aggiungi azione", self.aggiungi_azione),
            ("Modifica azione", self.modifica_azione),
            ("Elimina azione", self.elimina_azione),
        ])

    @solo_admin
    def elenco_azioni(self):
        self.vista("azioni", self.colonne_azioni(), self.db["azioni"], ("id", False))

    def chiedi_bonus_collegati(self, attuali):
        """Chiede a quali bonus/malus collegare un'azione; ritorna la lista di ID."""
        db = self.db
        if not db["bonus"]:
            return attuali
        validi = {b["id"] for b in db["bonus"]}
        while True:
            self.mostra_bonus()
            s = ask(f"ID bonus/malus collegati [{', '.join(map(str, attuali)) or 'nessuno'}] "
                    f"(invio = invariati, - = nessuno): ")
            if not s:
                return attuali
            if s == "-":
                return []
            ids = parse_ids(s, validi)
            if ids is None:
                print("ID non validi.")
                continue
            return ids

    def chiedi_fascia(self, attuale=None):
        while True:
            s = ask("Fascia del sondaggio: 1 = da 1 a 5, 2 = da 6 a 10" +
                    (f" [{attuale[0]}-{attuale[1]}]" if attuale else "") + ": ")
            if not s and attuale:
                return attuale
            if s in FASCE_SONDAGGIO:
                return FASCE_SONDAGGIO[s]
            print("Scegli 1 o 2.")

    def chiedi_unita(self, attuale=None):
        while True:
            s = ask("Unità di tempo: 1 = minuti, 2 = ore, 3 = giorni" +
                    (f" [{attuale}]" if attuale else "") + ": ")
            if not s and attuale:
                return attuale
            if s in ("1", "2", "3"):
                return UNITA_TEMPO[int(s) - 1]
            print("Scegli 1, 2 o 3.")

    @solo_admin
    def aggiungi_azione(self):
        db = self.db
        nome = ask("Nome azione: ")
        if not nome:
            return
        if any(x["nome"].lower() == nome.lower() for x in db["azioni"]):
            print("Esiste già un'azione con questo nome.")
            return
        modo = ""
        while modo not in ("1", "2", "3"):
            modo = ask("Punteggio: 1 = fisso, 2 = da sondaggio (inserito poi o subito), "
                       "3 = calcolato sul tempo (minuti/ore/giorni): ")
        a = nuova_azione(prossimo_id(db, "azione"), nome, 0)
        if modo == "1":
            a["punti"] = ask_int("Punti (anche negativi): ")
        elif modo == "2":
            a["modalita"] = "sondaggio"
            a["min"], a["max"] = self.chiedi_fascia()
        else:
            a["modalita"] = "tempo"
            a["unita"] = self.chiedi_unita()
            a["punti"] = ask_int(f"Punti per ogni unità di tempo ({a['unita']}; anche negativi): ")
        a["bonus_ids"] = self.chiedi_bonus_collegati([])
        db["azioni"].append(a)
        print(f"Azione '{nome}' aggiunta ({descrivi_punteggio(a)}).")

    def aggiorna_punti_fisso(self, a, eventi):
        """Cambio del punteggio di un'azione fissa, con scelta sugli eventi già registrati."""
        p = ask(f"Punti [{a['punti']:+d}]: ")
        if not p:
            return
        try:
            nuovi = int(p)
        except ValueError:
            print("Punti non validi, lasciati invariati.")
            return
        vecchi = a["punti"]
        a["punti"] = nuovi
        if nuovi == vecchi:
            return
        da_aggiornare = [e for e in eventi if e["stato"] == "ok" and e["punti"] == vecchi
                         and not e["bonus"] and not e.get("dittatura")]
        if not da_aggiornare:
            print("Il nuovo punteggio vale dai prossimi eventi.")
            return
        print(f"{len(da_aggiornare)} eventi già registrati hanno il vecchio punteggio ({vecchi:+d}).")
        if len(eventi) > len(da_aggiornare):
            print(f"Gli altri {len(eventi) - len(da_aggiornare)} (bonus/malus, DITTATURA, punteggio diverso, "
                  f"pending) non verrebbero toccati.")
        if ask_si(f"Portarli a {nuovi:+d}? Le classifiche cambieranno."):
            for e in da_aggiornare:
                e["punti"] = e["base"] = nuovi
            print("Eventi aggiornati.")
        else:
            print("Eventi lasciati invariati: il nuovo punteggio vale dai prossimi.")

    @solo_admin
    def modifica_azione(self):
        db = self.db
        a = self.scegli_per_id(db["azioni"], "ID azione da modificare (invio per annullare): ", self.mostra_azioni)
        if not a:
            return
        eventi = [e for e in db["eventi"] if e.get("azione_id") == a["id"]]
        print(f"\nModifica di '{a['nome']}' ({a['modalita']}) - usata in {len(eventi)} eventi "
              f"(invio = lascia com'è). Per cambiare la modalità elimina e ricrea l'azione.")
        nome = ask(f"Nome [{a['nome']}]: ")
        if nome and nome != a["nome"]:
            if any(x is not a and x["nome"].lower() == nome.lower() for x in db["azioni"]):
                print("Esiste già un'azione con questo nome: nome lasciato invariato.")
            else:
                a["nome"] = nome
                for e in eventi:
                    e["azione"] = nome  # anche lo storico mostra il nome corretto
                if eventi:
                    print(f"Nome aggiornato anche nei {len(eventi)} eventi già registrati.")
        if a["modalita"] == "fisso":
            self.aggiorna_punti_fisso(a, eventi)
        elif a["modalita"] == "sondaggio":
            a["min"], a["max"] = self.chiedi_fascia((a["min"], a["max"]))
        else:
            a["unita"] = self.chiedi_unita(a["unita"])
            p = ask(f"Punti per {a['unita']} [{a['punti']:+d}]: ")
            if p:
                try:
                    a["punti"] = int(p)
                except ValueError:
                    print("Punti non validi, lasciati invariati.")
            print("Gli eventi già registrati non cambiano.")
        a["bonus_ids"] = self.chiedi_bonus_collegati(a["bonus_ids"])
        print("Azione aggiornata.")

    @solo_admin
    def elimina_azione(self):
        db = self.db
        a = self.scegli_per_id(db["azioni"], "ID azione da eliminare (invio per annullare): ", self.mostra_azioni)
        if a and ask_si(f"Eliminare '{a['nome']}'?"):
            for e in db["eventi"]:
                if e.get("azione_id") == a["id"]:
                    e["azione_id"] = None  # lo storico conserva il nome dell'azione
            db["azioni"].remove(a)
            sp = riempi_buco(db, "azioni", "azione", a["id"])
            if sp:
                for e in db["eventi"]:
                    if e.get("azione_id") == sp[0]:
                        e["azione_id"] = sp[1]
                print(f"L'azione con ID {sp[0]} ora ha ID {sp[1]}.")

    # ----- bonus e malus -----
    @solo_admin
    def menu_bonus(self):
        self.menu("Bonus e malus", [
            ("Elenco", self.elenco_bonus),
            ("Aggiungi bonus/malus", self.aggiungi_bonus),
            ("Modifica bonus/malus", self.modifica_bonus),
            ("Elimina bonus/malus", self.elimina_bonus),
            ("Collega a più azioni", self.collega_bonus),
        ])

    @solo_admin
    def elenco_bonus(self):
        if not self.db["bonus"]:
            print("Nessun bonus/malus definito.")
            return
        self.vista("bonus", self.colonne_bonus(), self.db["bonus"], ("id", False))

    def chiedi_tipo_bonus(self, attuale=None):
        while True:
            s = ask("Tipo: 1 = punti (somma/sottrae), 2 = percentuale (sul punteggio base)" +
                    (f" [{attuale}]" if attuale else "") + ": ")
            if not s and attuale:
                return attuale
            if s in ("1", "2"):
                return "punti" if s == "1" else "percentuale"
            print("Scegli 1 o 2.")

    def chiedi_valore_bonus(self, tipo, attuale=None):
        while True:
            s = ask(f"Valore (negativo = malus; {'es. 20 = +20%' if tipo == 'percentuale' else 'es. 5 o -3'})" +
                    (f" [{fmt_segno(attuale)}]" if attuale is not None else "") + ": ")
            if not s and attuale is not None:
                return attuale
            v = parse_numero(s)
            if v is None or v == 0:
                print("Serve un numero diverso da zero.")
                continue
            return v

    @solo_admin
    def aggiungi_bonus(self):
        db = self.db
        nome = ask("Nome del bonus/malus: ")
        if not nome:
            return
        if any(b["nome"].lower() == nome.lower() for b in db["bonus"]):
            print("Esiste già un bonus/malus con questo nome.")
            return
        tipo = self.chiedi_tipo_bonus()
        valore = self.chiedi_valore_bonus(tipo)
        db["bonus"].append({"id": prossimo_id(db, "bonus"), "nome": nome, "tipo": tipo, "valore": valore})
        print("Aggiunto: collegalo alle azioni da 'Collega a più azioni' o da Modifica azione.")

    @solo_admin
    def modifica_bonus(self):
        db = self.db
        if not db["bonus"]:
            print("Nessun bonus/malus definito.")
            return
        b = self.scegli_per_id(db["bonus"], "ID da modificare (invio per annullare): ", self.mostra_bonus)
        if not b:
            return
        nome = ask(f"Nome [{b['nome']}]: ")
        if nome and nome != b["nome"]:
            if any(x is not b and x["nome"].lower() == nome.lower() for x in db["bonus"]):
                print("Esiste già un bonus/malus con questo nome: nome lasciato invariato.")
            else:
                b["nome"] = nome
        b["tipo"] = self.chiedi_tipo_bonus(b["tipo"])
        b["valore"] = self.chiedi_valore_bonus(b["tipo"], b["valore"])
        print("Aggiornato (gli eventi già registrati non cambiano).")

    @solo_admin
    def elimina_bonus(self):
        db = self.db
        if not db["bonus"]:
            print("Nessun bonus/malus definito.")
            return
        b = self.scegli_per_id(db["bonus"], "ID da eliminare (invio per annullare): ", self.mostra_bonus)
        if not b or not ask_si(f"Eliminare '{b['nome']}'? Verrà scollegato da tutte le azioni."):
            return
        for a in db["azioni"]:
            if b["id"] in a["bonus_ids"]:
                a["bonus_ids"].remove(b["id"])
        db["bonus"].remove(b)
        sp = riempi_buco(db, "bonus", "bonus", b["id"])
        if sp:
            for a in db["azioni"]:
                if sp[0] in a["bonus_ids"]:
                    a["bonus_ids"] = sorted(sp[1] if i == sp[0] else i for i in a["bonus_ids"])
            print(f"Il bonus/malus con ID {sp[0]} ora ha ID {sp[1]}.")

    @solo_admin
    def collega_bonus(self):
        db = self.db
        if not db["bonus"] or not db["azioni"]:
            print("Servono almeno un bonus/malus e un'azione.")
            return
        b = self.scegli_per_id(db["bonus"], "ID bonus/malus da collegare (invio per annullare): ", self.mostra_bonus)
        if not b:
            return
        attuali = [a["id"] for a in db["azioni"] if b["id"] in a["bonus_ids"]]
        validi = {a["id"] for a in db["azioni"]}
        while True:
            self.mostra_azioni()
            s = ask(f"ID azioni a cui applicare '{b['nome']}' [{', '.join(map(str, attuali)) or 'nessuna'}] "
                    f"(invio = invariate, - = nessuna): ")
            if not s:
                return
            ids = [] if s == "-" else parse_ids(s, validi)
            if ids is None:
                print("ID non validi.")
                continue
            break
        for a in db["azioni"]:
            if a["id"] in ids and b["id"] not in a["bonus_ids"]:
                a["bonus_ids"] = sorted(a["bonus_ids"] + [b["id"]])
            elif a["id"] not in ids and b["id"] in a["bonus_ids"]:
                a["bonus_ids"].remove(b["id"])
        print("Collegamenti aggiornati.")

    # ----- utenti -----
    @solo_admin
    def menu_utenti(self):
        self.menu("Utenti", [
            ("Elenco", self.elenco_utenti),
            ("Aggiungi utente", self.aggiungi_utente),
            ("Modifica profilo giocatore (caratteristiche)", self.modifica_profilo_giocatore),
            ("Reimposta password", self.reset_password),
            ("Promuovi / retrocedi admin", self.cambia_ruolo),
            ("Partecipa / non partecipa alla classifica", self.cambia_gioca),
            ("Elimina utente", self.elimina_utente),
        ])

    def chiedi_utente(self, prompt="Nome utente (invio per annullare): "):
        return self.scegli_utente(prompt)

    def n_admin(self):
        return sum(1 for u in self.db["utenti"] if u["ruolo"] == "admin")

    @solo_admin
    def elenco_utenti(self):
        self.vista("utenti", self.colonne_utenti(), self.db["utenti"], ("nome", False))

    @solo_admin
    def aggiungi_utente(self):
        db = self.db
        nome = ask("Nome nuovo utente (invio per annullare): ")
        if not nome:
            return
        if utente(db, nome):
            print("Esiste già un utente con questo nome.")
            return
        pw = nuova_password()
        ruolo = "admin" if ask_si("Admin?") else "partecipante"
        crea_utente(db, nome, pw, ruolo)
        print(f"Utente {nome} creato ({ruolo}).")

    @solo_admin
    def modifica_profilo_giocatore(self):
        u = self.chiedi_utente()
        if u:
            print(f"\nProfilo di {u['nome']}")
            self.chiedi_valori_profilo(u, "giocatori")

    @solo_admin
    def reset_password(self):
        u = self.chiedi_utente()
        if u:
            u["salt"], u["hash"] = hash_password(nuova_password())
            print("Password reimpostata.")

    @solo_admin
    def cambia_ruolo(self):
        u = self.chiedi_utente()
        if not u:
            return
        if u["ruolo"] == "admin":
            if self.n_admin() <= 1:
                print("Deve restare almeno un admin.")
                return
            u["ruolo"] = "partecipante"
        else:
            u["ruolo"] = "admin"
        print(f"{u['nome']} ora è {u['ruolo']}.")

    @solo_admin
    def cambia_gioca(self):
        u = self.chiedi_utente()
        if not u:
            return
        if u["gioca"] and rosa(self.db, u["nome"]):
            print("Ha musicisti in squadra: svincolali prima.")
            return
        u["gioca"] = not u["gioca"]
        print(f"{u['nome']} ora {'partecipa' if u['gioca'] else 'non partecipa'} alla classifica.")

    @solo_admin
    def elimina_utente(self):
        db = self.db
        u = self.chiedi_utente()
        if not u:
            return
        if u is self.me:
            print("Non puoi eliminare te stesso.")
            return
        if u["ruolo"] == "admin" and self.n_admin() <= 1:
            print("Deve restare almeno un admin.")
            return
        if not ask_si(f"Eliminare {u['nome']}? I suoi musicisti torneranno liberi."):
            return
        for m in rosa(db, u["nome"]):
            m["proprietario"], m["prezzo"] = None, 0
        for e in db["eventi"]:
            if e["proprietario"] == u["nome"]:
                e["proprietario"] = None
        db["utenti"].remove(u)
        print("Utente eliminato.")

    # ----- caratteristiche dei profili -----
    @solo_admin
    def menu_campi(self):
        self.menu("Caratteristiche dei profili", [
            ("Elenco", self.elenco_campi),
            ("Aggiungi una caratteristica", self.aggiungi_campo),
            ("Rinomina una caratteristica", self.rinomina_campo),
            ("Elimina una caratteristica", self.elimina_campo),
        ])

    @solo_admin
    def elenco_campi(self):
        db = self.db
        if not db["campi"]:
            print("Nessuna caratteristica definita.")
            return
        self.vista("campi", self.colonne_campi_def(), db["campi"], ("id", False))
        print("I valori si inseriscono da Gestione musicisti > Modifica e da Gestione utenti > Modifica profilo.")

    @solo_admin
    def aggiungi_campo(self):
        db = self.db
        s = ask("Per chi? 1 = musicisti, 2 = giocatori (invio per annullare): ")
        if not s:
            return
        per = {"1": "musicisti", "2": "giocatori"}.get(s)
        if not per:
            print("Scelta non valida.")
            return
        nome = ask("Nome della caratteristica (es. Strumento): ")
        if not nome:
            return
        if any(c["per"] == per and c["nome"].lower() == nome.lower() for c in db["campi"]):
            print("Esiste già una caratteristica con questo nome.")
            return
        t = ask("Tipo: 1 = testo, 2 = numero [1]: ")
        if t not in ("", "1", "2"):
            print("Scelta non valida.")
            return
        db["campi"].append({"id": prossimo_id(db, "campo"), "per": per, "nome": nome,
                            "tipo": "numero" if t == "2" else "testo"})
        print(f"Aggiunta '{nome}' ai profili dei {per}: ora puoi compilarla.")

    @solo_admin
    def rinomina_campo(self):
        db = self.db
        if not db["campi"]:
            print("Nessuna caratteristica definita.")
            return
        c = self.scegli_per_id(db["campi"], "ID caratteristica da rinominare (invio per annullare): ",
                               self.mostra_campi)
        if not c:
            return
        nome = ask(f"Nuovo nome [{c['nome']}]: ")
        if not nome or nome == c["nome"]:
            return
        if any(x is not c and x["per"] == c["per"] and x["nome"].lower() == nome.lower() for x in db["campi"]):
            print("Esiste già una caratteristica con questo nome.")
            return
        c["nome"] = nome
        print("Rinominata: i valori già inseriti restano.")

    @solo_admin
    def elimina_campo(self):
        db = self.db
        if not db["campi"]:
            print("Nessuna caratteristica definita.")
            return
        c = self.scegli_per_id(db["campi"], "ID caratteristica da eliminare (invio per annullare): ",
                               self.mostra_campi)
        if not c:
            return
        profili = profili_di(db, c["per"])
        compilati = [p for p in profili if str(c["id"]) in p.get("profilo", {})]
        if not ask_si(f"Eliminare '{c['nome']}'? Verranno cancellati i valori inseriti in {len(compilati)} profili."):
            return
        for p in compilati:
            del p["profilo"][str(c["id"])]
        db["campi"].remove(c)
        sp = riempi_buco(db, "campi", "campo", c["id"])
        if sp:
            for pr in profili_di(db, next(x["per"] for x in db["campi"] if x["id"] == sp[1])):
                if str(sp[0]) in pr.get("profilo", {}):
                    pr["profilo"][str(sp[1])] = pr["profilo"].pop(str(sp[0]))
            print(f"La caratteristica con ID {sp[0]} ora ha ID {sp[1]}.")
        print("Caratteristica eliminata.")

    # ----- nuova stagione -----
    @solo_admin
    def azzera_stagione(self):
        db = self.db
        print("Verranno cancellati TUTTI gli eventi (anche quelli in pending) e le assegnazioni dei musicisti.")
        print("Restano utenti, preferenze, elenco musicisti, azioni, bonus/malus e impostazioni.")
        if ask("Scrivi AZZERA per confermare: ") != "AZZERA":
            print("Annullato.")
            return
        db["eventi"].clear()
        db["contatori"]["evento"] = 1
        for m in db["musicisti"]:
            m["proprietario"], m["prezzo"] = None, 0
        print("Stagione azzerata: puoi rifare l'asta.")


# --------------------------------------------------------------------------
# Avvio
# --------------------------------------------------------------------------
def setup_iniziale():
    print("Primo avvio: creazione dell'account amministratore.")
    nome = ""
    while not nome:
        nome = ask("Nome admin: ")
    db = nuovo_db()
    crea_utente(db, nome, nuova_password(), "admin")
    salva(db)
    print("Admin creato. Dal pannello admin puoi aggiungere utenti e musicisti e fare l'asta.")
    return db


def login(db):
    for _ in range(3):
        nome = ask("\nUtente (invio per uscire): ")
        if not nome:
            return None
        pw = leggi_password("Password: ")
        u = utente(db, nome)
        if u and verifica_password(u, pw):
            return u
        print("Credenziali errate.")
    print("Troppi tentativi.")
    return None


def main():
    db = carica()
    if db is None:
        db = setup_iniziale()
    elif migra(db):
        salva(db)  # salvataggio di una versione precedente: aggiornato al formato attuale
    print("=== FANTAMUSICA ===")
    u = login(db)
    if u:
        Gioco(db, u).avvia()
    print("Alla prossima!")


if __name__ == "__main__":
    main()
