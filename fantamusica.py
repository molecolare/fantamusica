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
  - sondaggio:  il valore si decide dopo un sondaggio, in un range scelto alla creazione
                (formato "1-10", personalizzabile). Si puo' inserire subito oppure lasciare
                l'evento in PENDING e completarlo piu' tardi.
  - quantita':  si chiede una quantita' (minuti, ore, giorni, km... l'unita' di misura la
                scrive l'admin) e si moltiplica per i punti di ogni unita' (es. 3 punti per ora).
  Sondaggio: si possono inserire piu' voti nel range indicato (anche in momenti diversi
  sul pending): il valore usato e' la media dei voti, arrotondata per difetto (una media
  tra 0 e 1 vale comunque 1 punto).
  Bonus/malus: ognuno ha un valore fissato alla creazione, scritto come "+5"/"-3" (punti
  interi) oppure "20%"/"-10%" (percentuale). Si collegano a una o piu' azioni; registrando
  l'evento il programma chiede quali applicare. Ordine di calcolo: prima si sommano i punti
  interi alla base, poi si applicano le percentuali (sommate fra loro) al totale cosi' ottenuto,
  con arrotondamento per difetto (verso il basso, anche per i negativi).
  Un'azione puo' prevedere piu' musicisti, ciascuno con il proprio ruolo e punteggio
  (definiti alla creazione); alla registrazione si possono aggiungere altri musicisti
  coinvolti con un punteggio libero (come punteggio base: anche a loro si applicano i bonus/malus
  scelti).
  DITTATURA: l'admin puo' inserire un evento con il punteggio deciso a mano.

Mercato
  I giocatori possono proporsi scambi o vendite di musicisti (con eventuale conguaglio in
  crediti). Ogni musicista porta con se' il prezzo d'asta; i punti gia' maturati restano
  alla squadra che li ha ottenuti. L'admin puo' aprire/chiudere il mercato.

Stagioni
  "Chiudi stagione" archivia classifiche ed eventi: lo storico permette di consultare le
  stagioni passate e la classifica cumulativa.

Ruoli
  - admin:        permessi globali (asta, musicisti, azioni, bonus, eventi, utenti, profili,
                  impostazioni)
  - partecipante: consulta classifica, statistiche, storico, profili, la propria squadra,
                  fa scambi sul mercato, vede le impostazioni della stagione (sola lettura)
                  e gestisce le proprie preferenze personali (soprannome, riepilogo
                  all'accesso, recupero password...)

Avvio:  python3 fantamusica.py
I dati sono salvati in fantamusica_dati.json (accanto allo script). Il pannello admin ha
"Backup ed esportazione": backup datati (cartella backup/, anche in automatico a ogni chiusura
stagione), ripristino, esportazione/importazione dell'intero database e CSV di classifiche ed eventi.
I salvataggi delle versioni precedenti vengono aggiornati in automatico all'apertura.
"""
import copy
import functools
import getpass
import hashlib
import csv
import json
import math
import os
import secrets
from datetime import datetime
from fractions import Fraction
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

# Unita' di misura suggerite per le azioni a quantita' (l'admin puo' scriverne altre)
UNITA_SUGGERITE = ("minuti", "ore", "giorni")
SINGOLARI = {"minuti": "minuto", "ore": "ora", "giorni": "giorno", "secondi": "secondo",
             "settimane": "settimana", "mesi": "mese", "anni": "anno"}
RANGE_PREDEFINITO = "1-10"
SCAMBI_PREDEFINITI = 3

# Preferenze personali di ogni giocatore (salvate nel suo profilo e caricate al login)
PREF_BASE = {
    "soprannome": "",          # mostrato nel saluto e nella classifica
    "soprannomi_musicisti": {},  # soprannomi personali dei musicisti: {id musicista: soprannome}
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
            "min": None, "max": None, "unita": None, "bonus_ids": [],
            "ruolo": "", "extra": []}


def nuovo_db():
    db = {
        "impostazioni": {
            "stagione": "Stagione 1",
            "musicisti_per_squadra": 5,
            "budget_iniziale": 500,
            "rilancio_minimo": 1,
            "mercato_aperto": True,
            "scambi_max": SCAMBI_PREDEFINITI,
        },
        "utenti": [],      # {nome, ruolo, salt, hash, gioca, profilo, preferenze, saldo, recupero}
        "musicisti": [],   # {id, nome, proprietario, prezzo, profilo}
        "azioni": [nuova_azione(i + 1, n, p) for i, (n, p) in enumerate(AZIONI_BASE)],
        # {id, nome, modalita: fisso|sondaggio|tempo, punti, min, max, unita, bonus_ids,
        #  ruolo, extra: [{ruolo, punti, min, max}]}  (ruolo/punti/min/max = primo musicista,
        #  extra = gli altri musicisti coinvolti, ognuno col suo punteggio)
        "bonus": [],       # {id, nome, tipo: punti|percentuale, valore}
        "scambi": [],      # {id, data, da, a, offro, chiedo, nomi_offro, nomi_chiedo, crediti, stato}
        "storico": [],     # stagioni archiviate
        "eventi": [],      # {id, data, musicista_id, azione_id, azione, stato: ok|pending, punti, base,
                           #  bonus: [snapshot], voti, gruppo, dettaglio, dittatura, proprietario, nota}
        "contatori": {"musicista": 1, "azione": len(AZIONI_BASE) + 1, "evento": 1, "campo": 1, "bonus": 1,
                       "scambio": 1, "gruppo": 1, "stagione": 1},
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
    imposta(db, "scambi", [])
    imposta(db, "storico", [])
    for k in ("bonus", "scambio", "gruppo", "stagione"):
        imposta(db["contatori"], k, 1)
    imposta(db["impostazioni"], "mercato_aperto", True)
    imposta(db["impostazioni"], "scambi_max", SCAMBI_PREDEFINITI)
    if "campi" not in db:
        db["campi"] = []
        db["contatori"].setdefault("campo", 1)
        for per, nome, tipo in CAMPI_BASE:
            db["campi"].append({"id": prossimo_id(db, "campo"), "per": per, "nome": nome, "tipo": tipo})
        cambiato = True
    for u in db["utenti"]:
        imposta(u, "profilo", {})
        imposta(u, "saldo", 0)
        imposta(u, "recupero", None)
        if "preferenze" not in u:
            cambiato = True
        prefs(u)
    for m in db["musicisti"]:
        imposta(m, "profilo", {})
        imposta(m, "soprannome", "")
    # Bonus: ora hanno un tipo (punti|percentuale) e un valore fissi. Nelle versioni precedenti
    # la formula si sceglieva per ogni collegamento: si prende quella del primo collegamento.
    tipo_da_link = {}
    for a in db["azioni"]:
        for l in a.get("bonus_links", []):
            if isinstance(l, dict):
                tipo_da_link.setdefault(l["id"], l.get("formula"))
    for b in db["bonus"]:
        if b.get("tipo") not in ("punti", "percentuale"):
            vecchio = tipo_da_link.get(b["id"]) or b.get("tipo")
            if vecchio == "moltiplicatore":
                b["tipo"], b["valore"] = "percentuale", round((b["valore"] - 1) * 100, 2)
            elif vecchio == "percentuale":
                b["tipo"] = "percentuale"
            elif vecchio in ("somma", "punti") or float(b["valore"]).is_integer():
                b["tipo"] = "punti"
            else:
                b["tipo"] = "percentuale"
            cambiato = True
        if b["tipo"] == "punti" and not isinstance(b["valore"], int):
            b["valore"] = int(b["valore"])
            cambiato = True
        elif isinstance(b["valore"], float) and b["valore"].is_integer():
            b["valore"] = int(b["valore"])
    for a in db["azioni"]:
        imposta(a, "modalita", "fisso")
        imposta(a, "min", None)
        imposta(a, "max", None)
        imposta(a, "unita", None)
        imposta(a, "ruolo", "")
        imposta(a, "extra", [])
        if "bonus_ids" not in a:
            a["bonus_ids"] = []
            cambiato = True
        if "bonus_links" in a:
            for l in a.pop("bonus_links"):
                i = l["id"] if isinstance(l, dict) else l
                if i not in a["bonus_ids"]:
                    a["bonus_ids"].append(i)
            cambiato = True
    # Gli eventi puntano all'azione per ID (cosi' rinominarla aggiorna anche lo storico)
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
        imposta(e, "voti", [])
        imposta(e, "gruppo", None)
        imposta(e, "ruolo", "")
        for b in e["bonus"]:
            if "formula" in b or b.get("tipo") not in ("punti", "percentuale"):
                f = b.pop("formula", None) or b.get("tipo")
                if f == "moltiplicatore":
                    b["tipo"], b["valore"] = "percentuale", round((b["valore"] - 1) * 100, 2)
                elif f in ("somma", "punti"):
                    b["tipo"] = "punti"
                else:
                    b["tipo"] = "percentuale"
                cambiato = True
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
    u = utente(db, nome)
    saldo = u.get("saldo", 0) if u else 0
    return db["impostazioni"]["budget_iniziale"] - speso(db, nome) + saldo


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


def parse_ids(testo, validi, ordina=True):
    """'1, 3 4' -> [1, 3, 4]; None se contiene ID non validi."""
    ids = []
    for p in testo.replace(";", ",").replace(" ", ",").split(","):
        if not p:
            continue
        if not (p.isascii() and p.isdigit()) or int(p) not in validi:
            return None
        if int(p) not in ids:
            ids.append(int(p))
    return sorted(ids) if ordina else ids


# ----- calcolo dei punteggi -----
def arrotonda(x):
    return int(math.floor(x + 0.5))


def parse_bonus(testo):
    """'+5' / '-3' -> ('punti', 5/-3); '20%' / '-10%' -> ('percentuale', 20/-10); altrimenti None."""
    t = testo.strip().replace(" ", "")
    if t.endswith("%"):
        v = parse_numero(t[:-1])
        return ("percentuale", v) if v else None
    v = parse_numero(t)
    if v is None or v == 0 or not float(v).is_integer():
        return None
    return "punti", int(v)


def parse_range(testo):
    """'1-10' (anche '1 - 10', '1–10', '1 a 10') -> (1, 10); None se non valido."""
    t = testo.strip().lower().replace("–", "-").replace("—", "-").replace(" a ", "-").replace(" ", "")
    parti = t.split("-")
    if len(parti) != 2 or not all(p.isascii() and p.isdigit() for p in parti):
        return None
    lo, hi = int(parti[0]), int(parti[1])
    return (lo, hi) if lo < hi else None





def calcola_punti(base, bonus):
    """Punteggio finale: base + bonus/malus a punti interi; poi le percentuali (sommate) si applicano
    a questo totale, arrotondando per difetto (verso il basso, anche se negativo)."""
    totale = int(base) + sum(int(b["valore"]) for b in bonus if b["tipo"] == "punti")
    perc = sum(Fraction(str(b["valore"])) for b in bonus if b["tipo"] == "percentuale")
    return totale + math.floor(totale * perc / 100)


def parse_voti(testo, lo, hi):
    """'3 4,5' -> [3, 4, 5] se tutti nel range, altrimenti None."""
    voti = []
    for t in testo.replace(",", " ").replace(";", " ").split():
        if not (t.isascii() and t.isdigit()) or not lo <= int(t) <= hi:
            return None
        voti.append(int(t))
    return voti or None


def media_voti(voti):
    """Media per difetto; una media tra 0 e 1 vale comunque 1 punto."""
    m = sum(voti) // len(voti)
    return 1 if m == 0 and sum(voti) > 0 else m


def base_da_voti(voti):
    """(base, dettaglio) per un elenco di voti: un voto solo vale se stesso, altrimenti la media."""
    if len(voti) == 1:
        return voti[0], f"sondaggio {voti[0]}"
    m = media_voti(voti)
    return m, f"sondaggio: voti {', '.join(map(str, voti))} = media {m}"


def descrivi_bonus(b):
    t = fmt_segno(b["valore"]) + ("%" if b["tipo"] == "percentuale" else "")
    return f"{b['nome']} ({t})"


def slot_azione(a):
    """I musicisti coinvolti dall'azione: [{ruolo, punti, min, max}]; il primo e' quello 'principale'."""
    return [{"ruolo": a.get("ruolo", ""), "punti": a["punti"], "min": a["min"], "max": a["max"]}] \
        + [dict(x) for x in a.get("extra", [])]


def descrivi_slot(a, s):
    if a["modalita"] == "sondaggio":
        return f"sondaggio {s['min']}-{s['max']}"
    if a["modalita"] == "tempo":
        return f"{s['punti']:+d} per {SINGOLARI.get(a['unita'], a['unita'])}"
    return f"{s['punti']:+d}"


def descrivi_punteggio(a):
    slot = slot_azione(a)
    if len(slot) == 1:
        return descrivi_slot(a, slot[0])
    return " | ".join(f"{s['ruolo']}: {descrivi_slot(a, s)}" for s in slot)


def descrivi_calcolo(e):
    parti = []
    if e.get("dittatura"):
        parti.append("DITTATURA")
    elif e.get("dettaglio"):
        parti.append(e["dettaglio"])
    if e.get("bonus") and not e.get("dittatura"):
        if e.get("base") is not None:
            parti.append(f"base {e['base']}")
        parti.extend(descrivi_bonus(b) for b in e["bonus"])
    if e.get("ruolo"):
        parti.append(f"ruolo {e['ruolo']}")
    if e.get("gruppo"):
        parti.append(f"gruppo {e['gruppo']}")
    return "; ".join(parti)


# ----- mercato -----
def scambi_fatti(db, nome):
    """Scambi accettati in questa stagione in cui il giocatore compare (come proponente o destinatario)."""
    return sum(1 for x in db["scambi"] if x["stato"] == "accettato" and nome in (x["da"], x["a"]))


def simula_scambio(db, p):
    """Controlla se uno scambio e' fattibile ora. Ritorna (errore o None, {nome: (musicisti, crediti)})."""
    n_max = db["impostazioni"]["musicisti_per_squadra"]
    da, a = utente(db, p["da"]), utente(db, p["a"])
    if not da or not a or da is a or not da["gioca"] or not a["gioca"]:
        return "Giocatori non validi per lo scambio.", None
    if not p["offro"] and not p["chiedo"]:
        return "Lo scambio deve coinvolgere almeno un musicista.", None
    mus = {m["id"]: m for m in db["musicisti"]}
    for ids, chi in ((p["offro"], da), (p["chiedo"], a)):
        for i in ids:
            if i not in mus or mus[i]["proprietario"] != chi["nome"]:
                nome = mus[i]["nome"] if i in mus else f"ID {i}"
                return f"{nome} non appartiene (più) a {chi['nome']}.", None
    s_max = db["impostazioni"].get("scambi_max", SCAMBI_PREDEFINITI)
    for chi in (da, a):
        if scambi_fatti(db, chi["nome"]) >= s_max:
            return f"{chi['nome']} ha già fatto {scambi_fatti(db, chi['nome'])} scambi su {s_max} consentiti.", None
    val_off = sum(mus[i]["prezzo"] for i in p["offro"])
    val_chi = sum(mus[i]["prezzo"] for i in p["chiedo"])
    n_da = len(rosa(db, da["nome"])) - len(p["offro"]) + len(p["chiedo"])
    n_a = len(rosa(db, a["nome"])) - len(p["chiedo"]) + len(p["offro"])
    cr_da = crediti(db, da["nome"]) + val_off - val_chi - p["crediti"]
    cr_a = crediti(db, a["nome"]) + val_chi - val_off + p["crediti"]
    dopo = {da["nome"]: (n_da, cr_da), a["nome"]: (n_a, cr_a)}
    for nome, (n, cr) in dopo.items():
        if n > n_max:
            return f"{nome} avrebbe {n} musicisti (massimo {n_max}).", dopo
        if cr < 0:
            return f"{nome} non avrebbe crediti sufficienti ({cr}).", dopo
    return None, dopo


def esegui_scambio(db, p):
    for m in db["musicisti"]:
        if m["id"] in p["offro"]:
            m["proprietario"] = p["a"]
        elif m["id"] in p["chiedo"]:
            m["proprietario"] = p["da"]
    utente(db, p["da"])["saldo"] = utente(db, p["da"]).get("saldo", 0) - p["crediti"]
    utente(db, p["a"])["saldo"] = utente(db, p["a"]).get("saldo", 0) + p["crediti"]
    p["stato"] = "accettato"
    p["data_esito"] = datetime.now().strftime("%Y-%m-%d %H:%M")


# ----- storico stagioni -----
def classifica_cumulativa(db, includi_corrente=True):
    """[(pos, nome, {punti, stagioni, titoli})] sommando stagioni archiviate (e quella in corso)."""
    tot = {}

    def aggiungi(nome, punti, titolo):
        d = tot.setdefault(nome, {"punti": 0, "stagioni": 0, "titoli": 0})
        d["punti"] += punti
        d["stagioni"] += 1
        d["titoli"] += 1 if titolo else 0

    for st in db["storico"]:
        for r in st["classifica"]:
            aggiungi(r["nome"], r["punti"], r["pos"] == 1)
    if includi_corrente and eventi_ok(db):
        for _, nome, punti in classifica_giocatori(db):
            aggiungi(nome, punti, False)
    righe = sorted(tot.items(), key=lambda x: (-x[1]["punti"], x[0].lower()))
    pos = posizioni([d["punti"] for _, d in righe])
    return [(p, n, d) for p, (n, d) in zip(pos, righe)]


# ----- recupero password -----
# ----- backup ed esportazione -----
CHIAVI_OBBLIGATORIE = ("impostazioni", "utenti", "musicisti", "azioni", "eventi", "contatori")


def cartella_backup():
    return DATA_FILE.parent / "backup"


def cartella_esportazioni():
    return DATA_FILE.parent / "esportazioni"


def percorso_libero(cartella, nome):
    """cartella/nome, con un numero in coda se esiste gia' (due backup nello stesso secondo)."""
    p = cartella / nome
    n = 2
    while p.exists():
        p = cartella / f"{Path(nome).stem}-{n}{Path(nome).suffix}"
        n += 1
    return p


def scrivi_json(db, percorso):
    percorso.parent.mkdir(parents=True, exist_ok=True)
    with open(percorso, "w", encoding="utf-8") as f:
        json.dump(db, f, ensure_ascii=False, indent=2)
    return percorso


def crea_backup(db, motivo="manuale"):
    """Copia datata del database nella cartella 'backup' accanto ai dati. Ritorna il percorso."""
    nome = f"{DATA_FILE.stem}_{motivo}_{datetime.now():%Y%m%d-%H%M%S}.json"
    return scrivi_json(db, percorso_libero(cartella_backup(), nome))


def elenco_backup():
    """I backup esistenti, dal piu' recente."""
    cart = cartella_backup()
    if not cart.is_dir():
        return []
    return sorted(cart.glob(f"{DATA_FILE.stem}_*.json"), key=lambda p: (p.stat().st_mtime, p.name), reverse=True)


def leggi_database(percorso):
    """Legge e controlla un file di database. Ritorna (db migrato, errore o None)."""
    try:
        with open(percorso, encoding="utf-8") as f:
            dati = json.load(f)
    except OSError as e:
        return None, f"Impossibile leggere il file: {e.strerror or e}"
    except ValueError:
        return None, "Il file non è un JSON valido."
    if not isinstance(dati, dict) or any(not isinstance(dati.get(k), (dict, list)) for k in CHIAVI_OBBLIGATORIE):
        return None, "Il file non sembra un database di FantaBanda."
    try:
        migra(dati)
    except (KeyError, TypeError, ValueError, AttributeError):
        return None, "Il database nel file è incompleto o danneggiato."
    return dati, None


def righe_csv(db):
    """{nome file: (intestazioni, righe)} con classifiche ed eventi."""
    cmus, cgio = campi_per(db, "musicisti"), campi_per(db, "giocatori")

    def car(elemento, campi):
        return [elemento.get("profilo", {}).get(str(c["id"]), "") for c in campi]

    gio = []
    for pos, nome, punti in classifica_giocatori(db):
        u = utente(db, nome)
        gio.append([pos, nome, prefs(u)["soprannome"], punti, crediti(db, nome),
                    ", ".join(m["nome"] for m in rosa(db, nome))] + car(u, cgio))
    dati = sorted(((m, punti_musicista(db, m["id"])) for m in db["musicisti"]),
                  key=lambda x: (-x[1], x[0]["nome"].lower()))
    mus = [[ps, m["nome"], m.get("soprannome", ""), m["proprietario"] or "", m["prezzo"] if m["proprietario"] else "",
            p] + car(m, cmus)
           for ps, (m, p) in zip(posizioni([p for _, p in dati]), dati)]
    nomi = {m["id"]: m["nome"] for m in db["musicisti"]}
    ev = [[e["id"], e["data"], e["stato"], nomi.get(e["musicista_id"], "?"), e["azione"], e.get("ruolo", ""),
           e["punti"], "" if e.get("base") is None else e["base"],
           ", ".join(descrivi_bonus(b) for b in e.get("bonus", [])),
           " ".join(map(str, e.get("voti", []))), e.get("dettaglio", ""), e.get("proprietario") or "",
           "sì" if e.get("dittatura") else "", e.get("gruppo") or "", e.get("nota", "")]
          for e in db["eventi"]]
    return {
        "classifica_giocatori.csv": (["Posizione", "Giocatore", "Soprannome", "Punti", "Crediti", "Musicisti"]
                                     + [c["nome"] for c in cgio], gio),
        "classifica_musicisti.csv": (["Posizione", "Musicista", "Soprannome", "Squadra", "Prezzo", "Punti"]
                                     + [c["nome"] for c in cmus], mus),
        "eventi.csv": (["ID", "Data", "Stato", "Musicista", "Azione", "Ruolo", "Punti", "Base", "Bonus/malus",
                        "Voti", "Dettaglio", "Squadra", "DITTATURA", "Gruppo", "Nota"], ev),
    }


def esporta_csv(db, cartella):
    """Scrive i CSV (separatore ';', apribili con Excel); ritorna i percorsi."""
    cartella.mkdir(parents=True, exist_ok=True)
    scritti = []
    for nome, (intestazioni, righe) in righe_csv(db).items():
        p = cartella / nome
        with open(p, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f, delimiter=";")
            w.writerow(intestazioni)
            w.writerows(righe)
        scritti.append(p)
    return scritti


def normalizza_risposta(s):
    return " ".join(s.lower().split())


def recupero_password(db):
    nome = ask("Nome utente: ")
    u = utente(db, nome) if nome else None
    if not u or not u.get("recupero"):
        print("Recupero non disponibile: chiedi all'admin di reimpostare la password.")
        return
    r = u["recupero"]
    print(f"Domanda: {r['domanda']}")
    for _ in range(3):
        _, h = hash_password(normalizza_risposta(ask("Risposta: ")), r["salt"])
        if secrets.compare_digest(h, r["hash"]):
            u["salt"], u["hash"] = hash_password(nuova_password())
            salva(db)
            print("Password aggiornata: ora puoi accedere.")
            return
        print("Risposta errata.")
    print("Troppi tentativi.")


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
            ("La mia squadra", lambda: self.dettaglio_squadra(self.me["nome"])),
            ("Mercato e scambi", self.menu_mercato),
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
            nprop = sum(1 for x in db["scambi"] if x["stato"] == "proposto" and x["a"] == me["nome"])
            if nprop:
                righe.append(f"Hai {nprop} proposte di scambio da valutare (Mercato e scambi).")
            if not me.get("recupero"):
                righe.append("Suggerimento: imposta il recupero password da Impostazioni > Preferenze personali.")
            for r in righe:
                print("  " + r)
        p["ultimo_accesso"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.salva()

    def verifica_vecchia_password(self):
        for _ in range(3):
            if verifica_password(self.me, leggi_password("Password attuale: ")):
                return True
            print("Password errata.")
        print("Troppi tentativi.")
        return False

    def cambia_password(self):
        if not self.verifica_vecchia_password():
            return
        self.me["salt"], self.me["hash"] = hash_password(nuova_password())
        print("Password aggiornata.")

    def imposta_recupero(self):
        r = self.me.get("recupero")
        if r:
            print(f"Domanda attuale: {r['domanda']}")
        if not self.verifica_vecchia_password():
            return
        domanda = ask("Domanda segreta (es. il nome del mio primo gatto; invio per annullare): ")
        if not domanda:
            return
        risposta = ask("Risposta: ")
        if not risposta:
            return
        salt, h = hash_password(normalizza_risposta(risposta))
        self.me["recupero"] = {"domanda": domanda, "salt": salt, "hash": h}
        print("Recupero impostato: al login scrivi ? al posto del nome utente per usarlo.")

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
    def col_soprannome(self):
        return Col("soprannome", "Soprannome", lambda m: m.get("soprannome") or None)

    def col_mio_soprannome(self):
        return Col("mio_sopr", "Il tuo soprannome",
                   lambda m: prefs(self.me)["soprannomi_musicisti"].get(str(m["id"])) or None)

    def colonne_musicisti(self, campi=False):
        db = self.db
        cols = [Col("id", "ID", lambda m: m["id"], ">"),
                Col("nome", "Musicista", lambda m: m["nome"]),
                self.col_soprannome(), self.col_mio_soprannome(),
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
                Col("bonus", "Bonus/malus",
                    lambda a: ", ".join(descrivi_bonus(b) for i in a["bonus_ids"]
                                        for b in db["bonus"] if b["id"] == i) or None,
                    ordinabile=False)]

    def mostra_azioni(self):
        self.stampa("azioni", self.colonne_azioni(), self.db["azioni"], ("id", False))

    def colonne_bonus(self):
        db = self.db
        return [Col("id", "ID", lambda b: b["id"], ">"),
                Col("nome", "Nome", lambda b: b["nome"]),
                Col("valore", "Valore", lambda b: b["valore"], ">",
                    fmt=lambda v, b: fmt_segno(v) + ("%" if b["tipo"] == "percentuale" else "")),
                Col("azioni", "Collegato a",
                    lambda b: ", ".join(a["nome"] for a in db["azioni"] if b["id"] in a["bonus_ids"]) or None,
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
                                 ("Musicisti", self.classifica_musicisti),
                                 ("Statistiche", self.menu_statistiche),
                                 ("Storico stagioni", self.menu_storico)])

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
                Col("rosa", "Rosa", lambda r: len(rosa(db, r[1])), ">", fmt=lambda v, r: f"{v}/{n_max}"),
                Col("crediti", "Crediti", lambda r: crediti(db, r[1]), ">"),
                Col("musicisti", "Musicisti", lambda r: ", ".join(m["nome"] for m in rosa(db, r[1])) or None,
                    ordinabile=False)]
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
                Col("soprannome", "Soprannome", lambda r: r[1].get("soprannome") or None),
                Col("mio_sopr", "Il tuo soprannome",
                    lambda r: prefs(self.me)["soprannomi_musicisti"].get(str(r[1]["id"])) or None),
                Col("squadra", "Squadra", lambda r: r[1]["proprietario"]),
                Col("prezzo", "Prezzo", lambda r: r[1]["prezzo"] if r[1]["proprietario"] else None, ">"),
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
    # ---------- impostazioni ----------
    # ---------- storico stagioni ----------
    def menu_storico(self):
        self.menu("Storico stagioni", [
            ("Classifica di una stagione archiviata", self.classifica_stagione),
            ("Classifica cumulativa", self.classifica_cumulativa_vista),
        ])

    def mostra_stagioni(self):
        cols = [Col("id", "ID", lambda s: s["id"], ">"),
                Col("nome", "Stagione", lambda s: s["nome"]),
                Col("chiusa", "Chiusa il", lambda s: s["chiusa"]),
                Col("vincitore", "Vincitore", lambda s: s["classifica"][0]["nome"] if s["classifica"] else None),
                Col("punti", "Punti", lambda s: s["classifica"][0]["punti"] if s["classifica"] else None, ">")]
        self.stampa("stagioni", cols, self.db["storico"], ("id", False))

    def classifica_stagione(self):
        db = self.db
        if not db["storico"]:
            print("Nessuna stagione archiviata.")
            return
        st = self.scegli_per_id(db["storico"], "ID stagione (invio per tornare indietro): ", self.mostra_stagioni)
        if not st:
            return
        cols = [Col("pos", "Pos", lambda r: r["pos"], ">"),
                Col("nome", "Giocatore", lambda r: r["nome"]),
                Col("punti", "Punti", lambda r: r["punti"], ">"),
                Col("musicisti", "Musicisti", lambda r: ", ".join(r["musicisti"]) or None, ordinabile=False)]
        self.vista("st_stagione_g", cols, st["classifica"], ("pos", False),
                   f"\n{st['nome']} - classifica giocatori")
        cols = [Col("pos", "Pos", lambda r: r["pos"], ">"),
                Col("nome", "Musicista", lambda r: r["nome"]),
                Col("squadra", "Squadra", lambda r: r["squadra"]),
                Col("punti", "Punti", lambda r: r["punti"], ">")]
        self.vista("st_stagione_m", cols, st["musicisti"], ("pos", False), f"\n{st['nome']} - classifica musicisti")

    def classifica_cumulativa_vista(self):
        db = self.db
        dati = classifica_cumulativa(db)
        if not dati:
            print("Nessun dato: non ci sono stagioni archiviate né eventi nella stagione in corso.")
            return
        totale = sum(d["punti"] for _, _, d in dati)
        cols = [Col("pos", "Pos", lambda r: r[0], ">"),
                Col("nome", "Giocatore", lambda r: r[1], fmt=lambda v, r: etichetta_utente(db, v)),
                Col("punti", "Totale", lambda r: r[2]["punti"], ">"),
                Col("perc", "% sul totale", lambda r: r[2]["punti"], ">", fmt=lambda v, r: pct(v, totale),
                    ordinabile=False),
                Col("stagioni", "Stagioni", lambda r: r[2]["stagioni"], ">"),
                Col("titoli", "Titoli", lambda r: r[2]["titoli"], ">"),
                Col("media", "Media a stagione", lambda r: r[2]["punti"] / r[2]["stagioni"], ">",
                    fmt=lambda v, r: f"{v:.1f}")]
        corrente = " + stagione in corso" if eventi_ok(db) else ""
        self.vista("cumulativa", cols, dati, ("pos", False),
                   f"\nClassifica cumulativa ({len(db['storico'])} stagioni archiviate{corrente})")

    def impostazioni(self):
        self.menu("Impostazioni", [("Preferenze personali", self.preferenze),
                                   ("Impostazioni della stagione", self.impostazioni_stagione)])

    def soprannomi_musicisti(self):
        """Ogni giocatore puo' dare un soprannome ai musicisti, visibile solo a lui (accanto a quello ufficiale)."""
        db = self.db
        mio = prefs(self.me)["soprannomi_musicisti"]
        if not db["musicisti"]:
            print("Nessun musicista.")
            return
        while True:
            m = self.scegli_per_id(db["musicisti"], "ID musicista a cui dare un soprannome (invio per finire): ",
                                   self.mostra_musicisti)
            if not m:
                return
            s = ask(f"Il tuo soprannome per {m['nome']} [{mio.get(str(m['id'])) or '-'}] "
                    f"(max 30 caratteri, - per toglierlo, invio = invariato): ")
            if s == "-":
                mio.pop(str(m["id"]), None)
            elif s:
                mio[str(m["id"])] = s[:30]
            self.salva()

    def preferenze(self):
        p = prefs(self.me)
        while True:
            print("\n=== Preferenze personali (salvate nel tuo profilo, valgono a ogni accesso) ===")
            print(f"  1. Soprannome (nel saluto e in classifica): {p['soprannome'] or '-'}")
            print(f"  2. Riepilogo all'accesso:                   {'sì' if p['riepilogo_login'] else 'no'}")
            print(f"  3. Eventi mostrati negli elenchi:           {p['righe_eventi'] or 'tutti'}")
            print(f"  4. Recupero password:                       "
                  f"{'impostato' if self.me.get('recupero') else 'non impostato'}")
            print(f"  5. Soprannomi personali dei musicisti:      {len(p['soprannomi_musicisti'])} impostati")
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
                self.imposta_recupero()
            elif s == "5":
                self.soprannomi_musicisti()
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
            print(f"  5. Mercato (scambi):          {'aperto' if s.get('mercato_aperto', True) else 'chiuso'}")
            print(f"  6. Scambi consentiti:         {s.get('scambi_max', SCAMBI_PREDEFINITI)} a testa per stagione")
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
            oltre = [f"{u['nome']} ({speso(db, u['nome']) - u.get('saldo', 0)})" for u in db["utenti"]
                     if speso(db, u["nome"]) - u.get("saldo", 0) > b]
            if oltre:
                print("Impossibile: hanno già speso di più: " + ", ".join(oltre))
            elif b < s["musicisti_per_squadra"]:
                print("Impossibile: serve almeno 1 credito per ogni posto in squadra.")
            else:
                s["budget_iniziale"] = b
                print("Budget aggiornato (i crediti residui si ricalcolano da soli).")
        elif scelta == "4":
            s["rilancio_minimo"] = ask_int("Nuovo rilancio minimo: ", 1)
        elif scelta == "5":
            s["mercato_aperto"] = not s.get("mercato_aperto", True)
            print("Mercato " + ("aperto." if s["mercato_aperto"] else "chiuso."))
        elif scelta == "6":
            s["scambi_max"] = ask_int("Quanti scambi può fare ogni giocatore in una stagione (0 = nessuno): ", 0)
            print(f"Ogni giocatore potrà fare al massimo {s['scambi_max']} scambi.")
        else:
            print("Scelta non valida.")

    # ---------- pannello admin ----------
    @solo_admin
    def menu_admin(self):
        self.menu("Pannello admin", [
            ("Registra evento / assegna punti", self.registra_evento),
            ("DITTATURA (evento con punteggio deciso a mano)", self.dittatura),
            ("Pending: voti e completamento", self.gestisci_pending),
            ("Modifica un evento", self.modifica_evento),
            ("Asta musicisti", self.asta),
            ("Gestione musicisti", self.menu_musicisti),
            ("Gestione azioni", self.menu_azioni),
            ("Bonus e malus", self.menu_bonus),
            ("Gestione utenti", self.menu_utenti),
            ("Caratteristiche dei profili", self.menu_campi),
            ("Elimina un evento", self.elimina_evento),
            ("Backup ed esportazione", self.menu_backup),
            ("Chiudi la stagione (archivia e azzera)", self.chiudi_stagione),
        ])

    # ----- registrazione eventi -----
    def scegli_musicisti_azione(self):
        """Sceglie l'azione, un musicista per ogni ruolo previsto dall'azione (definiti alla sua
        creazione) ed eventuali altri coinvolti (ruolo None: punteggio libero).
        Ritorna ([(musicista, ruolo o None)], azione) oppure (None, None)."""
        db = self.db
        if not db["musicisti"] or not db["azioni"]:
            print("Servono almeno un musicista e un'azione.")
            return None, None
        a = self.scegli_per_id(db["azioni"], "ID azione (invio per annullare): ", self.mostra_azioni)
        if not a:
            return None, None
        ruoli = slot_azione(a)
        if len(ruoli) > len(db["musicisti"]):
            print(f"L'azione coinvolge {len(ruoli)} musicisti ma ce ne sono solo {len(db['musicisti'])}.")
            return None, None
        scelti = []
        for s in ruoli:
            presi = [m["id"] for m, _ in scelti]
            liberi = [m for m in db["musicisti"] if m["id"] not in presi]
            if len(ruoli) > 1:
                print(f"\nRuolo «{s['ruolo']}» ({descrivi_slot(a, s)})")
            m = self.scegli_per_id(liberi, "ID musicista (invio per annullare): ",
                                   lambda: self.mostra_musicisti(liberi))
            if not m:
                return None, None
            scelti.append((m, s))
        # eventuali altri coinvolti, con punteggio libero da vincoli
        liberi = [m for m in db["musicisti"] if m["id"] not in [x["id"] for x, _ in scelti]]
        if liberi and ask_si("C'è qualcun altro coinvolto?"):
            validi = {m["id"] for m in liberi}
            while True:
                self.mostra_musicisti(liberi)
                r = ask("ID degli altri musicisti coinvolti (separati da virgola; invio = nessuno): ")
                if not r:
                    break
                ids = parse_ids(r, validi, ordina=False)
                if not ids:
                    print("ID non validi.")
                    continue
                scelti += [(m, None) for i in ids for m in liberi if m["id"] == i]
                break
        return scelti, a

    def chiedi_base(self, a, s, ctx, chi):
        """Punteggio base di un musicista dell'azione: (base, dettaglio, pending, voti) oppure None se
        annullato. s = ruolo/punteggio del musicista, ctx = risposte da condividere fra i musicisti
        dello stesso evento (la quantita' si chiede una volta sola), chi = nome per i messaggi."""
        if a["modalita"] == "sondaggio":
            lo, hi = s["min"], s["max"]
            while True:
                r = ask(f"Voto del sondaggio per {chi} da {lo} a {hi} (più voti separati da spazio o virgola = "
                        f"media; invio = lascia in PENDING): ")
                if not r:
                    return None, "", True, []
                voti = parse_voti(r, lo, hi)
                if voti is None:
                    print(f"Inserisci uno o più interi da {lo} a {hi}.")
                    continue
                base, dettaglio = base_da_voti(voti)
                return base, dettaglio, False, voti
        if a["modalita"] == "tempo":
            if "quantita" not in ctx:
                while True:
                    r = ask(f"Quantità in {a['unita']} (es. 90 o 1,5; invio per annullare): ")
                    if not r:
                        return None
                    v = parse_numero(r)
                    if v is None or v <= 0:
                        print("Serve un numero maggiore di zero.")
                        continue
                    ctx["quantita"] = v
                    break
            v = ctx["quantita"]
            return arrotonda(v * s["punti"]), f"{fmt_valore(v)} {a['unita']} x {s['punti']:+d}", False, []
        return s["punti"], "", False, []

    def chiedi_bonus_da_applicare(self, a):
        """Per ogni bonus/malus collegato all'azione chiede se applicarlo (valore gia' fissato)."""
        scelti = []
        for i in a["bonus_ids"]:
            b = next((x for x in self.db["bonus"] if x["id"] == i), None)
            if b and ask_si(f"Applicare {descrivi_bonus(b)}?"):
                scelti.append({"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"]})
        return scelti

    def aggiungi_evento(self, m, a, punti, base, bonus, dettaglio, pending, nota, dittatura=False,
                        fascia=None, voti=None, gruppo=None, ruolo=""):
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
            "voti": list(voti or []),
            "gruppo": gruppo,
            "ruolo": ruolo,
            "dettaglio": dettaglio,
            "dittatura": dittatura,
            "proprietario": m["proprietario"],
            "nota": nota,
        }
        if fascia:
            e["fascia"] = list(fascia)
        db["eventi"].append(e)
        return e

    def ruolo_evento(self, a, s):
        """Ruolo da scrivere nell'evento: quello dell'azione se ne prevede piu' di uno, 'extra' per i
        musicisti aggiunti alla registrazione."""
        if s is None:
            return "extra"
        return s["ruolo"] if len(slot_azione(a)) > 1 else ""

    @solo_admin
    def registra_evento(self):
        db = self.db
        coppie, a = self.scegli_musicisti_azione()
        if not coppie:
            return
        ctx, basi = {}, []
        for m, s in coppie:
            if s is None:
                p = ask_int(f"Punteggio libero per {m['nome']} (anche negativo): ")
                basi.append((p, "punteggio libero", False, []))
                continue
            risultato = self.chiedi_base(a, s, ctx, m["nome"])
            if risultato is None:
                print("Annullato.")
                return
            basi.append(risultato)
        bonus = self.chiedi_bonus_da_applicare(a)
        nota = ask("Nota (facoltativa): ")
        gruppo = prossimo_id(db, "gruppo") if len(coppie) > 1 else None
        for (m, s), (base, dettaglio, pending, voti) in zip(coppie, basi):
            b = bonus
            punti = None if pending else calcola_punti(base, b)
            fascia = (s["min"], s["max"]) if s and a["modalita"] == "sondaggio" else None
            e = self.aggiungi_evento(m, a, punti, base, b, dettaglio, pending, nota, fascia=fascia,
                                     voti=voti, gruppo=gruppo, ruolo=self.ruolo_evento(a, s))
            dove = f"alla squadra di {m['proprietario']}" if m["proprietario"] else "a nessuno (musicista senza squadra)"
            if pending:
                print(f"Evento {e['id']} in PENDING per {m['nome']} ({a['nome']}).")
            else:
                calcolo = descrivi_calcolo(e)
                print(f"Registrato: {punti:+d} a {m['nome']} -> {dove}." + (f" [{calcolo}]" if calcolo else ""))
        if any(r[2] for r in basi):
            print("Aggiungi i voti e completa l'evento da 'Pending: voti e completamento' quando il sondaggio è chiuso.")

    @solo_admin
    def dittatura(self):
        db = self.db
        print("DITTATURA: l'evento viene inserito col punteggio che decidi tu, "
              "senza sondaggi, calcoli sul tempo né bonus/malus.")
        coppie, a = self.scegli_musicisti_azione()
        if not coppie:
            return
        punteggi = []
        for m, s in coppie:
            extra = f" ({s['ruolo']})" if s and len(slot_azione(a)) > 1 else ""
            punteggi.append(ask_int(f"Punteggio finale per {m['nome']}{extra} (anche negativo): "))
        nota = ask("Nota (facoltativa): ")
        gruppo = prossimo_id(db, "gruppo") if len(coppie) > 1 else None
        for (m, s), punti in zip(coppie, punteggi):
            self.aggiungi_evento(m, a, punti, punti, [], "", False, nota, dittatura=True, gruppo=gruppo,
                                 ruolo=self.ruolo_evento(a, s))
            dove = f"alla squadra di {m['proprietario']}" if m["proprietario"] else "a nessuno (musicista senza squadra)"
            print(f"DITTATURA: {punti:+d} a {m['nome']} ({a['nome']}) -> {dove}.")

    @solo_admin
    def gestisci_pending(self):
        db = self.db
        if not eventi_pending(db):
            print("Nessun evento in pending.")
            return
        e = self.scegli_per_id(eventi_pending(db), "ID evento da gestire (invio per annullare): ",
                               self.mostra_pending)
        if not e:
            return
        gruppo = [x for x in eventi_pending(db) if e.get("gruppo") and x.get("gruppo") == e["gruppo"]
                  and (x.get("ruolo") or "") == (e.get("ruolo") or "")] or [e]
        az = next((a for a in db["azioni"] if a["id"] == e.get("azione_id")), None)
        lo, hi = (e.get("fascia") or ((az["min"], az["max"]) if az else (1, 10)))
        voti = list(e.get("voti", []))
        if len(gruppo) > 1:
            print("L'evento vale per: " + ", ".join(nome_musicista(db, x["musicista_id"]) for x in gruppo))
        while True:
            print(f"\n{e['azione']} - voti finora: {', '.join(map(str, voti)) or 'nessuno'}"
                  + (f" (media {media_voti(voti)})" if voti else ""))
            s = ask(f"Voti da aggiungere da {lo} a {hi} (separati da spazio o virgola; "
                    f"invio = basta così, - = azzera i voti): ")
            if not s:
                break
            if s == "-":
                voti = []
                continue
            nuovi = parse_voti(s, lo, hi)
            if nuovi is None:
                print(f"Inserisci interi da {lo} a {hi}.")
                continue
            voti += nuovi
        if not voti:
            for x in gruppo:
                x["voti"], x["dettaglio"] = [], ""
            print("Nessun voto: l'evento resta in pending.")
            return
        if ask_si(f"Chiudere ora l'evento con la media di {len(voti)} voti ({media_voti(voti)})?"):
            base, dettaglio = base_da_voti(voti)
            for x in gruppo:
                x["voti"], x["base"], x["dettaglio"] = list(voti), base, dettaglio
                x["punti"] = calcola_punti(base, x["bonus"])
                x["stato"] = "ok"
                x["data_completamento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                print(f"Evento {x['id']} completato: {x['punti']:+d} punti "
                      f"({nome_musicista(db, x['musicista_id'])} -> {x['proprietario'] or 'nessuna squadra'}).")
        else:
            for x in gruppo:
                x["voti"] = list(voti)
                x["dettaglio"] = f"voti finora: {', '.join(map(str, voti))}"
            print("Voti salvati: l'evento resta in pending.")

    @solo_admin
    def modifica_evento(self):
        db = self.db
        if not db["eventi"]:
            print("Nessun evento registrato.")
            return
        e = self.scegli_per_id(db["eventi"], "ID evento da modificare (invio per annullare): ",
                               lambda: self.mostra_eventi(eventi_recenti(db, prefs(self.me)["righe_eventi"])))
        if not e:
            return
        while True:
            print("\nEvento selezionato:")
            self.mostra_eventi([e], "evento_singolo")
            if e.get("gruppo"):
                n = sum(1 for x in db["eventi"] if x.get("gruppo") == e["gruppo"]) - 1
                print(f"(fa parte di un gruppo con altri {n} eventi: la modifica riguarda solo questo)")
            print("  1. Cambia musicista")
            print("  2. Cambia azione e ricalcola il punteggio")
            print("  3. Imposta il punteggio a mano (come DITTATURA)")
            print("  4. Cambia la squadra a cui vanno i punti")
            print("  5. Cambia la nota")
            print("  6. Cambia la data")
            print("  0. Fine")
            s = ask("> ")
            if s in ("", "0"):
                return
            if s == "1":
                m = self.scegli_per_id(db["musicisti"], "ID nuovo musicista (invio per annullare): ",
                                       self.mostra_musicisti)
                if m:
                    e["musicista_id"], e["proprietario"] = m["id"], m["proprietario"]
                    print(f"Musicista cambiato: i punti vanno a {m['proprietario'] or 'nessuna squadra'} "
                          f"(la sua squadra attuale; usa 4 per cambiarla).")
            elif s == "2":
                a = self.scegli_per_id(db["azioni"], "ID nuova azione (invio per annullare): ", self.mostra_azioni)
                ruoli = slot_azione(a) if a else []
                sl = ruoli[0] if ruoli else None
                if len(ruoli) > 1:
                    for i, r in enumerate(ruoli, 1):
                        print(f"  {i}. {r['ruolo']} ({descrivi_slot(a, r)})")
                    sl = ruoli[ask_int("Quale ruolo ha questo musicista? ", 1, len(ruoli)) - 1]
                risultato = self.chiedi_base(a, sl, {}, nome_musicista(db, e["musicista_id"])) if a else None
                if risultato is not None:
                    base, dettaglio, pending, voti = risultato
                    bonus = self.chiedi_bonus_da_applicare(a)
                    e.update(azione_id=a["id"], azione=a["nome"], bonus=bonus, dettaglio=dettaglio, voti=voti,
                             ruolo=sl["ruolo"] if len(ruoli) > 1 else "",
                             dittatura=False, stato="pending" if pending else "ok",
                             base=None if pending else base,
                             punti=0 if pending else calcola_punti(base, bonus))
                    e.pop("data_completamento", None)
                    if a["modalita"] == "sondaggio":
                        e["fascia"] = [sl["min"], sl["max"]]
                    else:
                        e.pop("fascia", None)
                    print("Evento ricalcolato.")
            elif s == "3":
                p = ask_int("Nuovo punteggio finale: ")
                e.update(punti=p, base=p, bonus=[], dettaglio="", voti=[], dittatura=True, stato="ok")
                print("Punteggio impostato a mano.")
            elif s == "4":
                while True:
                    self.mostra_utenti()
                    n = ask(f"Nuova squadra [{e['proprietario'] or 'nessuna'}] (invio = annulla, - = nessuna): ")
                    if not n:
                        break
                    if n == "-":
                        e["proprietario"] = None
                        break
                    u = utente(db, n)
                    if u and u["gioca"]:
                        e["proprietario"] = u["nome"]
                        break
                    print("Giocatore non trovato.")
            elif s == "5":
                n = ask(f"Nota [{e.get('nota') or '-'}] (invio = invariata, - = cancella): ")
                if n:
                    e["nota"] = "" if n == "-" else n
            elif s == "6":
                n = ask(f"Data [{e['data']}] nel formato AAAA-MM-GG HH:MM (invio = invariata): ")
                if n:
                    try:
                        datetime.strptime(n, "%Y-%m-%d %H:%M")
                        e["data"] = n
                    except ValueError:
                        print("Formato non valido.")
            else:
                print("Scelta non valida.")
            self.salva()

    @solo_admin
    def elimina_evento(self):
        db = self.db
        ev = db["eventi"]
        if not ev:
            print("Nessun evento registrato.")
            return
        e = self.scegli_per_id(ev, "ID evento da eliminare (invio per annullare): ",
                               lambda: self.mostra_eventi(eventi_recenti(db, prefs(self.me)["righe_eventi"])))
        if not e:
            return
        da_togliere = [e]
        compagni = [x for x in ev if e.get("gruppo") and x.get("gruppo") == e["gruppo"] and x is not e]
        if compagni and ask_si(f"L'evento fa parte di un gruppo di {len(compagni) + 1}: eliminare anche gli altri?"):
            da_togliere += compagni
        if ask_si("Confermi?"):
            for x in da_togliere:
                ev.remove(x)
                riempi_buco(db, "eventi", "evento", x["id"])
            print("Evento eliminato: i punti sono stati tolti alla squadra." if len(da_togliere) == 1
                  else f"{len(da_togliere)} eventi eliminati.")

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
    # ----- mercato e scambi -----
    def mercato_aperto(self):
        return self.db["impostazioni"].get("mercato_aperto", True)

    def menu_mercato(self):
        fatti = scambi_fatti(self.db, self.me["nome"])
        massimo = self.db["impostazioni"].get("scambi_max", SCAMBI_PREDEFINITI)
        self.menu(f"Mercato e scambi (mercato {'APERTO' if self.mercato_aperto() else 'CHIUSO'}; "
                  f"i tuoi scambi: {fatti}/{massimo})", [
            ("Nuova proposta (scambio o vendita)", self.nuova_proposta),
            ("Proposte in sospeso (accetta, rifiuta, annulla)", self.proposte_in_sospeso),
            ("Storico scambi", self.storico_scambi),
        ])

    def colonne_scambi(self):
        return [Col("id", "ID", lambda p: p["id"], ">"),
                Col("data", "Data", lambda p: p.get("data_esito") or p["data"]),
                Col("da", "Proponente", lambda p: p["da"]),
                Col("a", "Destinatario", lambda p: p["a"]),
                Col("cede", "Proponente cede", lambda p: ", ".join(p["nomi_offro"]) or None, ordinabile=False),
                Col("riceve", "Destinatario cede", lambda p: ", ".join(p["nomi_chiedo"]) or None,
                    ordinabile=False),
                Col("crediti", "Conguaglio (paga il proponente)", lambda p: p["crediti"], ">",
                    fmt=lambda v, p: f"{v:+d}" if v else "-"),
                Col("stato", "Stato", lambda p: p["stato"])]

    def mostra_scambi(self, lista):
        self.stampa("scambi", self.colonne_scambi(), lista, ("id", False))

    def riepilogo_scambio(self, p, dopo):
        print(f"  {p['da']} cede: {', '.join(p['nomi_offro']) or 'nessun musicista'}")
        print(f"  {p['a']} cede: {', '.join(p['nomi_chiedo']) or 'nessun musicista'}")
        if p["crediti"] > 0:
            print(f"  Conguaglio: {p['da']} paga {p['crediti']} crediti a {p['a']}")
        elif p["crediti"] < 0:
            print(f"  Conguaglio: {p['a']} paga {-p['crediti']} crediti a {p['da']}")
        else:
            print("  Nessun conguaglio (ogni musicista porta con sé il suo prezzo d'asta)")
        for nome, (n, cr) in (dopo or {}).items():
            print(f"  Dopo lo scambio {nome}: {n} musicisti, {cr} crediti")

    def chiedi_musicisti_scambio(self, descrizione, lista):
        if not lista:
            return []
        validi = {m["id"] for m in lista}
        while True:
            self.mostra_musicisti(lista)
            s = ask(f"ID {descrizione} (separati da virgola; invio = nessuno): ")
            if not s:
                return []
            ids = parse_ids(s, validi)
            if not ids:
                print("ID non validi.")
                continue
            return ids

    def nuova_proposta(self):
        db, me = self.db, self.me
        if not self.mercato_aperto():
            print("Il mercato è chiuso.")
            return
        if not me["gioca"]:
            print("Solo chi partecipa alla classifica può fare scambi.")
            return
        altri = [u for u in giocatori(db) if u is not me]
        if not altri:
            print("Non ci sono altri giocatori.")
            return
        while True:
            self.mostra_utenti()
            s = ask("Con chi vuoi fare lo scambio? Nome giocatore (invio per annullare): ")
            if not s:
                return
            dest = utente(db, s)
            if dest in altri:
                break
            print("Giocatore non valido.")
        offro = self.chiedi_musicisti_scambio("dei TUOI musicisti che cedi", rosa(db, me["nome"]))
        chiedo = self.chiedi_musicisti_scambio(f"dei musicisti di {dest['nome']} che vuoi ricevere",
                                               rosa(db, dest["nome"]))
        if not offro and not chiedo:
            print("Nessun musicista coinvolto: annullato.")
            return
        c = ask_int(f"Conguaglio: crediti che TU paghi a {dest['nome']} oltre ai prezzi dei musicisti "
                    f"(negativo = li ricevi, 0 = nessuno): ")

        def nomi(ids):
            return [m["nome"] for i in ids for m in db["musicisti"] if m["id"] == i]
        p = {"data": datetime.now().strftime("%Y-%m-%d %H:%M"), "da": me["nome"], "a": dest["nome"],
             "offro": offro, "chiedo": chiedo, "nomi_offro": nomi(offro), "nomi_chiedo": nomi(chiedo),
             "crediti": c, "stato": "proposto"}
        errore, dopo = simula_scambio(db, p)
        print("\nRiepilogo della proposta:")
        self.riepilogo_scambio(p, dopo)
        if errore:
            print(f"Non fattibile ora: {errore}")
            return
        if ask_si("Inviare la proposta?"):
            p["id"] = prossimo_id(db, "scambio")
            db["scambi"].append(p)
            print(f"Proposta {p['id']} inviata a {dest['nome']}.")

    def proposte_in_sospeso(self):
        db, me = self.db, self.me
        admin = me["ruolo"] == "admin"
        aperte = [p for p in db["scambi"] if p["stato"] == "proposto" and (admin or me["nome"] in (p["da"], p["a"]))]
        if not aperte:
            print("Nessuna proposta in sospeso.")
            return
        p = self.scegli_per_id(aperte, "ID proposta (invio per tornare indietro): ",
                               lambda: self.mostra_scambi(aperte))
        if not p:
            return
        errore, dopo = simula_scambio(db, p)
        self.riepilogo_scambio(p, dopo)
        s = ask("1 = accetta, 2 = rifiuta, 3 = annulla la proposta (invio = niente): ")
        sono_dest = admin or me["nome"] == p["a"]
        sono_prop = admin or me["nome"] == p["da"]
        if s == "1" and sono_dest:
            if not self.mercato_aperto():
                print("Il mercato è chiuso.")
            elif errore:
                print(f"Non fattibile ora: {errore}")
            else:
                esegui_scambio(db, p)
                print("Scambio completato.")
        elif s == "2" and sono_dest:
            p["stato"], p["data_esito"] = "rifiutato", datetime.now().strftime("%Y-%m-%d %H:%M")
            print("Proposta rifiutata.")
        elif s == "3" and sono_prop:
            p["stato"], p["data_esito"] = "annullato", datetime.now().strftime("%Y-%m-%d %H:%M")
            print("Proposta annullata.")
        elif s in ("1", "2", "3"):
            print("Permesso negato: non puoi fare questa operazione su questa proposta.")

    def storico_scambi(self):
        chiusi = [p for p in self.db["scambi"] if p["stato"] != "proposto"]
        if not chiusi:
            print("Nessuno scambio concluso.")
            return
        self.vista("scambi", self.colonne_scambi(), chiusi, ("id", False), "\nStorico scambi")

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
            db["musicisti"].append({"id": prossimo_id(db, "musicista"), "nome": nome, "soprannome": "",
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
        s = ask(f"Soprannome [{m.get('soprannome') or '-'}] (- per toglierlo): ")
        if s:
            m["soprannome"] = "" if s == "-" else s[:30]
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
            for u in db["utenti"]:
                prefs(u)["soprannomi_musicisti"].pop(str(m["id"]), None)
            sp = riempi_buco(db, "musicisti", "musicista", m["id"])
            if sp:
                for u in db["utenti"]:
                    sopr = prefs(u)["soprannomi_musicisti"]
                    if str(sp[0]) in sopr:
                        sopr[str(sp[1])] = sopr.pop(str(sp[0]))
                for e in db["eventi"]:
                    if e["musicista_id"] == sp[0]:
                        e["musicista_id"] = sp[1]
                for x in db["scambi"]:
                    x["offro"] = [sp[1] if i == sp[0] else i for i in x["offro"]]
                    x["chiedo"] = [sp[1] if i == sp[0] else i for i in x["chiedo"]]
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
        """Chiede quali bonus/malus collegare a un'azione (anche piu' di uno); ritorna la lista di ID."""
        db = self.db
        if not db["bonus"]:
            return attuali
        validi = {b["id"] for b in db["bonus"]}
        while True:
            self.mostra_bonus()
            s = ask(f"ID bonus/malus da collegare, separati da virgola "
                    f"[{', '.join(map(str, attuali)) or 'nessuno'}] (invio = invariati, - = nessuno): ")
            if not s:
                return attuali
            if s == "-":
                return []
            ids = parse_ids(s, validi)
            if not ids:
                print("ID non validi.")
                continue
            return ids

    def chiedi_range(self, attuale=None, chi=""):
        """Range di un sondaggio nel formato min-max (es. 1-10)."""
        while True:
            r = ask(f"Range del sondaggio{chi} nel formato min-max, es. {RANGE_PREDEFINITO}" +
                    (f" [{attuale[0]}-{attuale[1]}]" if attuale else f" (invio = {RANGE_PREDEFINITO})") + ": ")
            if not r:
                return tuple(attuale) if attuale else parse_range(RANGE_PREDEFINITO)
            v = parse_range(r)
            if v:
                return v
            print("Formato non valido: due interi col trattino e il primo minore del secondo (es. 1-10).")

    def chiedi_unita(self, attuale=None):
        """Unita' di misura libera (minuti, ore, giorni, km, ascolti...)."""
        while True:
            s = ask(f"Unità di misura (es. {', '.join(UNITA_SUGGERITE)} o altra a piacere)" +
                    (f" [{attuale}]" if attuale else "") + ": ")
            if not s and attuale:
                return attuale
            if s:
                return s.lower()
            print("Scrivi un'unità di misura.")

    def chiedi_n_musicisti(self, attuale=1):
        while True:
            s = ask(f"Quanti musicisti coinvolge l'azione? [{attuale}]: ")
            if not s:
                return attuale
            if s.isascii() and s.isdigit() and 1 <= int(s) <= 20:
                return int(s)
            print("Inserisci un numero da 1 a 20.")

    def chiedi_slot(self, a, i, n, attuale=None, altri=()):
        """Ruolo e punteggio del musicista numero i (da 0) di un'azione; attuale = valori correnti."""
        att = attuale or {}
        ruolo = ""
        if n > 1:
            while True:
                r = ask(f"Ruolo del musicista {i + 1} (es. Protagonista, Ospite)" +
                        (f" [{att['ruolo']}]" if att.get("ruolo") else "") + ": ")
                if not r and att.get("ruolo"):
                    r = att["ruolo"]
                if not r:
                    print("Il ruolo serve per distinguere i musicisti.")
                elif r.lower() in [x.lower() for x in altri]:
                    print("Esiste già un ruolo con questo nome in questa azione.")
                else:
                    ruolo = r
                    break
        chi = f" per «{ruolo}»" if n > 1 else ""
        s = {"ruolo": ruolo, "punti": att.get("punti", 0), "min": att.get("min"), "max": att.get("max")}
        if a["modalita"] == "sondaggio":
            s["min"], s["max"] = self.chiedi_range(
                (att["min"], att["max"]) if att.get("min") is not None else None, chi)
        else:
            testo = "Punti" if a["modalita"] == "fisso" else f"Punti per ogni {SINGOLARI.get(a['unita'], a['unita'])}"
            while True:
                r = ask(f"{testo}{chi} (anche negativi)" + (f" [{att['punti']:+d}]" if "punti" in att else "") + ": ")
                if not r and "punti" in att:
                    break
                try:
                    s["punti"] = int(r)
                    break
                except ValueError:
                    print("Inserisci un numero intero.")
        return s

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
                       "3 = calcolato su una quantità (minuti, ore, giorni... a scelta): ")
        a = nuova_azione(prossimo_id(db, "azione"), nome, 0)
        a["modalita"] = {"1": "fisso", "2": "sondaggio", "3": "tempo"}[modo]
        if modo == "3":
            a["unita"] = self.chiedi_unita()
        n = self.chiedi_n_musicisti()
        slot = []
        for i in range(n):
            slot.append(self.chiedi_slot(a, i, n, altri=[x["ruolo"] for x in slot]))
        a.update(slot[0])
        a["extra"] = slot[1:]
        a["bonus_ids"] = self.chiedi_bonus_collegati([])
        db["azioni"].append(a)
        print(f"Azione '{nome}' aggiunta ({descrivi_punteggio(a)}).")

    def aggiorna_eventi_fisso(self, eventi, vecchi, nuovi):
        """Cambio del punteggio di un'azione fissa, con scelta sugli eventi già registrati
        (eventi = quelli dello stesso musicista/ruolo dell'azione)."""
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
        if a["modalita"] == "tempo":
            a["unita"] = self.chiedi_unita(a["unita"])
        vecchi = slot_azione(a)
        n = self.chiedi_n_musicisti(len(vecchi))
        nuovi = []
        for i in range(n):
            att = vecchi[i] if i < len(vecchi) else None
            nuovi.append(self.chiedi_slot(a, i, n, att, altri=[x["ruolo"] for x in nuovi]))
        for i, s in enumerate(nuovi):
            if i >= len(vecchi):
                continue
            v = vecchi[i]
            propri = [e for e in eventi if (e.get("ruolo") or "") == v["ruolo"]]
            if s["ruolo"] != v["ruolo"]:
                for e in propri:
                    e["ruolo"] = s["ruolo"]
            if a["modalita"] == "fisso":
                self.aggiorna_eventi_fisso(propri, v["punti"], s["punti"])
        if len(nuovi) < len(vecchi):
            print("I musicisti in meno non ricevono più punti dai prossimi eventi (quelli già registrati restano).")
        if a["modalita"] == "tempo":
            print("Gli eventi già registrati non cambiano.")
        a.update(nuovi[0])
        a["extra"] = nuovi[1:]
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

    def chiedi_valore_bonus(self, attuale=None):
        """Valore di un bonus/malus: punti interi ('+5', '-3') o percentuale ('20%', '-10%').
        Ritorna (tipo, valore)."""
        while True:
            corrente = (f" [{fmt_segno(attuale['valore'])}" + ("%" if attuale["tipo"] == "percentuale" else "")
                        + "]") if attuale else ""
            s = ask("Valore: punti interi (es. 5 o -3) oppure percentuale (es. 20% o -10%, arrotondata "
                    "per difetto all'intero; negativo = malus)" + corrente + ": ")
            if not s and attuale:
                return attuale["tipo"], attuale["valore"]
            r = parse_bonus(s)
            if r is None:
                print("Valore non valido: usa un intero (5, -3) o una percentuale (20%, -10%).")
                continue
            return r

    @solo_admin
    def aggiungi_bonus(self):
        db = self.db
        nome = ask("Nome del bonus/malus: ")
        if not nome:
            return
        if any(b["nome"].lower() == nome.lower() for b in db["bonus"]):
            print("Esiste già un bonus/malus con questo nome.")
            return
        tipo, valore = self.chiedi_valore_bonus()
        b = {"id": prossimo_id(db, "bonus"), "nome": nome, "tipo": tipo, "valore": valore}
        db["bonus"].append(b)
        print(f"Aggiunto: {descrivi_bonus(b)}.")
        if db["azioni"]:
            self.scegli_azioni_per_bonus(b)

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
        b["tipo"], b["valore"] = self.chiedi_valore_bonus(b)
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
            a["bonus_ids"] = [i for i in a["bonus_ids"] if i != b["id"]]
        db["bonus"].remove(b)
        sp = riempi_buco(db, "bonus", "bonus", b["id"])
        if sp:
            for a in db["azioni"]:
                a["bonus_ids"] = [sp[1] if i == sp[0] else i for i in a["bonus_ids"]]
            print(f"Il bonus/malus con ID {sp[0]} ora ha ID {sp[1]}.")

    def scegli_azioni_per_bonus(self, b):
        """Collega (o scollega) il bonus/malus a una o piu' azioni, mostrandone il valore gia' salvato."""
        db = self.db
        attuali = [a["id"] for a in db["azioni"] if b["id"] in a["bonus_ids"]]
        validi = {a["id"] for a in db["azioni"]}
        while True:
            self.mostra_azioni()
            s = ask(f"ID azioni a cui collegare {descrivi_bonus(b)}, separati da virgola "
                    f"[{', '.join(map(str, attuali)) or 'nessuna'}] (invio = invariate, - = nessuna): ")
            if not s:
                return
            ids = [] if s == "-" else parse_ids(s, validi)
            if ids is None:
                print("ID non validi.")
                continue
            break
        for a in db["azioni"]:
            if a["id"] in ids and b["id"] not in a["bonus_ids"]:
                a["bonus_ids"].append(b["id"])
            elif a["id"] not in ids and b["id"] in a["bonus_ids"]:
                a["bonus_ids"].remove(b["id"])
        print("Collegamenti aggiornati.")

    @solo_admin
    def collega_bonus(self):
        db = self.db
        if not db["bonus"] or not db["azioni"]:
            print("Servono almeno un bonus/malus e un'azione.")
            return
        b = self.scegli_per_id(db["bonus"], "ID bonus/malus da collegare (invio per annullare): ", self.mostra_bonus)
        if b:
            self.scegli_azioni_per_bonus(b)

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
        for x in db["scambi"]:
            if x["stato"] == "proposto" and u["nome"] in (x["da"], x["a"]):
                x["stato"] = "annullato"
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
    def menu_backup(self):
        self.menu("Backup ed esportazione", [
            ("Crea un backup ora", self.backup_manuale),
            ("Ripristina da un backup", self.ripristina_backup),
            ("Esporta tutto il database in un file", self.esporta_database),
            ("Importa il database da un file", self.importa_database),
            ("Esporta classifiche ed eventi in CSV", self.esporta_csv_menu),
        ])

    @solo_admin
    def backup_manuale(self):
        p = crea_backup(self.db, "manuale")
        print(f"Backup creato: {p}")

    def sostituisci_database(self, nuovo, etichetta):
        """Sostituisce tutti i dati con 'nuovo' (dopo un backup di sicurezza dei dati attuali)."""
        db = self.db
        admin = utente(nuovo, self.me["nome"])
        if not admin or admin["ruolo"] != "admin":
            print(f"Operazione annullata: nel database scelto '{self.me['nome']}' non è un admin, "
                  f"quindi perderesti l'accesso.")
            return False
        print(f"Il database scelto ({etichetta}) contiene {len(nuovo['utenti'])} utenti, "
              f"{len(nuovo['musicisti'])} musicisti, {len(nuovo['eventi'])} eventi in "
              f"'{nuovo['impostazioni'].get('stagione', '?')}'.")
        print("TUTTI i dati attuali verranno sostituiti (ne viene fatto prima un backup).")
        if ask("Scrivi SOSTITUISCI per confermare: ") != "SOSTITUISCI":
            print("Annullato.")
            return False
        print(f"Backup dei dati attuali: {crea_backup(db, 'prima-del-ripristino')}")
        db.clear()
        db.update(nuovo)
        self.me = utente(db, self.me["nome"])
        self.salva()
        print("Database sostituito.")
        return True

    @solo_admin
    def ripristina_backup(self):
        lista = elenco_backup()
        if not lista:
            print("Nessun backup trovato.")
            return
        for i, p in enumerate(lista, 1):
            quando = datetime.fromtimestamp(p.stat().st_mtime).strftime("%Y-%m-%d %H:%M")
            print(f"  {i}. {p.name}  ({quando})")
        while True:
            s = ask("Numero del backup da ripristinare (invio per annullare): ")
            if not s:
                return
            if s.isascii() and s.isdigit() and 1 <= int(s) <= len(lista):
                break
            print("Scelta non valida.")
        nuovo, errore = leggi_database(lista[int(s) - 1])
        if errore:
            print(errore)
            return
        self.sostituisci_database(nuovo, lista[int(s) - 1].name)

    @solo_admin
    def esporta_database(self):
        print("Attenzione: il file contiene anche gli hash delle password: conservalo con cura.")
        predefinito = percorso_libero(cartella_esportazioni(), f"fantamusica_export_{datetime.now():%Y%m%d-%H%M%S}.json")
        s = ask(f"File di destinazione [{predefinito}] (invio = quello indicato): ")
        percorso = Path(s).expanduser() if s else predefinito
        if percorso.exists() and not ask_si(f"{percorso} esiste già: sovrascrivere?"):
            print("Annullato.")
            return
        try:
            scrivi_json(self.db, percorso)
        except OSError as e:
            print(f"Impossibile scrivere il file: {e.strerror or e}")
            return
        print(f"Database esportato in {percorso}")

    @solo_admin
    def importa_database(self):
        s = ask("File da importare (invio per annullare): ")
        if not s:
            return
        percorso = Path(s).expanduser()
        nuovo, errore = leggi_database(percorso)
        if errore:
            print(errore)
            return
        self.sostituisci_database(nuovo, percorso.name)

    @solo_admin
    def esporta_csv_menu(self):
        predefinita = cartella_esportazioni()
        s = ask(f"Cartella di destinazione [{predefinita}] (invio = quella indicata): ")
        cartella = Path(s).expanduser() if s else predefinita
        try:
            scritti = esporta_csv(self.db, cartella)
        except OSError as e:
            print(f"Impossibile scrivere i file: {e.strerror or e}")
            return
        print("Creati (separatore ';', si aprono con Excel):")
        for p in scritti:
            print(f"  {p}")

    @solo_admin
    def chiudi_stagione(self):
        db = self.db
        s = db["impostazioni"]
        pend = eventi_pending(db)
        print(f"Chiudere '{s['stagione']}': classifiche ed eventi vengono archiviati nello storico e")
        print("la stagione riparte da zero (squadre, crediti ed eventi). Restano utenti, preferenze,")
        print("elenco musicisti, azioni, bonus/malus e impostazioni.")
        if pend:
            print(f"Attenzione: {len(pend)} eventi sono ancora in pending e andranno persi.")
        if ask("Scrivi CHIUDI per confermare: ") != "CHIUDI":
            print("Annullato.")
            return
        print(f"Backup prima della chiusura: {crea_backup(db, 'chiusura-stagione')}")
        cl = classifica_giocatori(db)
        dati_m = sorted(((m, punti_musicista(db, m["id"])) for m in db["musicisti"]),
                        key=lambda x: (-x[1], x[0]["nome"].lower()))
        pos_m = posizioni([p for _, p in dati_m])
        db["storico"].append({
            "id": prossimo_id(db, "stagione"),
            "nome": s["stagione"],
            "chiusa": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "classifica": [{"pos": pos, "nome": n, "punti": p, "musicisti": [m["nome"] for m in rosa(db, n)]}
                           for pos, n, p in cl],
            "musicisti": [{"pos": ps, "nome": m["nome"], "squadra": m["proprietario"], "punti": p}
                          for ps, (m, p) in zip(pos_m, dati_m)],
            "eventi": copy.deepcopy(eventi_ok(db)),
            "scambi": copy.deepcopy([x for x in db["scambi"] if x["stato"] == "accettato"]),
        })
        db["eventi"].clear()
        db["scambi"].clear()
        db["contatori"]["evento"] = db["contatori"]["scambio"] = 1
        for m in db["musicisti"]:
            m["proprietario"], m["prezzo"] = None, 0
        for u in db["utenti"]:
            u["saldo"] = 0
        nuovo = ask(f"Nome della nuova stagione [Stagione {len(db['storico']) + 1}]: ")
        s["stagione"] = nuovo or f"Stagione {len(db['storico']) + 1}"
        print(f"Stagione archiviata. Ora si parte con '{s['stagione']}': puoi rifare l'asta.")

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
    tentativi = 0
    while tentativi < 3:
        nome = ask("\nUtente (invio per uscire, ? = password dimenticata): ")
        if not nome:
            return None
        if nome == "?":
            recupero_password(db)
            continue
        pw = leggi_password("Password: ")
        u = utente(db, nome)
        if u and verifica_password(u, pw):
            return u
        print("Credenziali errate.")
        tentativi += 1
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
