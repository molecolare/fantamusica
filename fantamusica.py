#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FANTAMUSICA - gioco a squadre con asta iniziale

Come si gioca
  1. A inizio stagione i partecipanti comprano i musicisti all'asta (con i crediti).
  2. Durante la stagione l'admin registra le azioni dei musicisti (nuovo singolo,
     disco d'oro, scandalo...): i punti vanno a chi ha scelto quel musicista.
  3. Tutti possono consultare classifica, statistiche e profili.

Profili
  L'admin definisce delle "caratteristiche" (es. Strumento, Anni di carriera) per i
  musicisti e per i giocatori e le compila: tutti possono poi consultare i profili.

Ruoli
  - admin:        permessi globali (asta, musicisti, azioni, eventi, utenti, profili,
                  impostazioni)
  - partecipante: consulta classifica, statistiche, profili, la propria squadra, le
                  impostazioni (sola lettura) e cambia la propria password

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
    ("giocatori", "Soprannome", "testo"),
]


# --------------------------------------------------------------------------
# Dati
# --------------------------------------------------------------------------
def nuovo_db():
    db = {
        "impostazioni": {
            "stagione": "Stagione 1",
            "musicisti_per_squadra": 5,
            "budget_iniziale": 500,
            "rilancio_minimo": 1,
        },
        "utenti": [],      # {nome, ruolo, salt, hash, gioca, profilo}
        "musicisti": [],   # {id, nome, proprietario, prezzo, profilo}
        "azioni": [{"id": i + 1, "nome": n, "punti": p} for i, (n, p) in enumerate(AZIONI_BASE)],
        "eventi": [],      # {id, data, musicista_id, azione_id, azione, punti, proprietario, nota}
        "contatori": {"musicista": 1, "azione": len(AZIONI_BASE) + 1, "evento": 1, "campo": 1},
    }
    # migra() crea "campi" ({id, per: "musicisti"|"giocatori", nome, tipo: "testo"|"numero"})
    # con le caratteristiche di partenza
    migra(db)
    return db


def migra(db):
    """Porta un salvataggio di una versione precedente al formato attuale.
    Restituisce True se ha cambiato qualcosa."""
    cambiato = False
    if "campi" not in db:
        db["campi"] = []
        db["contatori"].setdefault("campo", 1)
        for per, nome, tipo in CAMPI_BASE:
            db["campi"].append({"id": prossimo_id(db, "campo"), "per": per, "nome": nome, "tipo": tipo})
        cambiato = True
    for elemento in db["utenti"] + db["musicisti"]:
        if "profilo" not in elemento:
            elemento["profilo"] = {}
            cambiato = True
    # Gli eventi ora puntano all'azione per ID (così rinominarla aggiorna anche lo storico)
    per_nome = {a["nome"].lower(): a["id"] for a in db["azioni"]}
    for e in db["eventi"]:
        if "azione_id" not in e:
            e["azione_id"] = per_nome.get(e["azione"].lower())
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


def punti_musicista(db, mid, proprietario=None):
    """Punti totali del musicista; con 'proprietario' solo quelli andati a quella squadra."""
    return sum(e["punti"] for e in db["eventi"]
               if e["musicista_id"] == mid and (proprietario is None or e["proprietario"] == proprietario))


def punti_utente(db, nome):
    return sum(e["punti"] for e in db["eventi"] if e["proprietario"] == nome)


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


def valore_profilo(elemento, campo):
    return fmt_valore(elemento.get("profilo", {}).get(str(campo["id"])))


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
        print(f"\nBenvenuto, {self.me['nome']}! (ruolo: {self.me['ruolo']})")
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

    def scegli_per_id(self, lista, prompt):
        while True:
            s = ask(prompt)
            if not s:
                return None
            if s.isascii() and s.isdigit():
                for x in lista:
                    if x["id"] == int(s):
                        return x
            print("ID non valido.")

    def cambia_password(self):
        self.me["salt"], self.me["hash"] = hash_password(nuova_password())
        print("Password aggiornata.")

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
        righe = [(pos, nome, p, "-" if p == capo else p - capo, pct(p, totale),
                  f"{len(rosa(db, nome))}/{n_max}") for pos, nome, p in cl]
        print(f"\nClassifica giocatori - {db['impostazioni']['stagione']}")
        tabella(["Pos", "Giocatore", "Punti", "Distacco", "% punti", "Rosa"], righe, "><>>>>")

    def classifica_musicisti(self):
        db = self.db
        if not db["musicisti"]:
            print("Nessun musicista.")
            return
        tot = sum(e["punti"] for e in db["eventi"])
        dati = sorted(((m, punti_musicista(db, m["id"])) for m in db["musicisti"]),
                      key=lambda x: (-x[1], x[0]["nome"].lower()))
        pos = posizioni([p for _, p in dati])
        righe = [(ps, m["nome"], m["proprietario"] or "-", p, pct(p, tot))
                 for ps, (m, p) in zip(pos, dati)]
        print("\nClassifica musicisti")
        tabella(["Pos", "Musicista", "Squadra", "Punti", "% punti"], righe, "><<>>")

    # ---------- statistiche ----------
    def menu_statistiche(self):
        self.menu("Statistiche", [
            ("Riepilogo generale", self.stat_riepilogo),
            ("Azioni più frequenti", self.stat_azioni),
            ("Squadre a confronto", self.stat_squadre),
            ("Dettaglio di una squadra", self.scegli_squadra),
            ("Migliori e peggiori affari (punti per credito)", self.stat_affari),
            ("Ultimi eventi", self.stat_ultimi_eventi),
        ])

    def stat_riepilogo(self):
        db = self.db
        s = db["impostazioni"]
        ev, mus, gio = db["eventi"], db["musicisti"], giocatori(db)
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
        print(f"  Eventi registrati:      {len(ev)}")
        if ev:
            print(f"    positivi:             {len(pos)} ({pct(len(pos), len(ev))})")
            print(f"    negativi:             {len(neg)} ({pct(len(neg), len(ev))})")
            print(f"  Punti totali assegnati: {tot_punti:+d} (media {tot_punti / len(ev):+.1f} a evento)")
            print(f"  Punti a musicisti senza squadra: {senza:+d} ({pct(senza, tot_punti)} del totale)")
            migliore = max(ev, key=lambda e: e["punti"])
            peggiore = min(ev, key=lambda e: e["punti"])
            print(f"  Evento migliore:  {migliore['punti']:+d}  {nome_musicista(db, migliore['musicista_id'])} - {migliore['azione']}")
            print(f"  Evento peggiore:  {peggiore['punti']:+d}  {nome_musicista(db, peggiore['musicista_id'])} - {peggiore['azione']}")

    def stat_azioni(self):
        ev = self.db["eventi"]
        if not ev:
            print("Nessun evento registrato.")
            return
        agg = {}
        for e in ev:
            c = agg.setdefault(e["azione"], [0, 0])
            c[0] += 1
            c[1] += e["punti"]
        righe = [(nome, c[0], pct(c[0], len(ev)), f"{c[1]:+d}", f"{c[1] / c[0]:+.1f}")
                 for nome, c in sorted(agg.items(), key=lambda x: (-x[1][0], x[0]))]
        print("\nAzioni più frequenti")
        tabella(["Azione", "Volte", "% eventi", "Punti tot.", "Media"], righe, "<>>>>")

    def stat_squadre(self):
        db = self.db
        s = db["impostazioni"]
        cl = classifica_giocatori(db)
        if not cl:
            print("Nessun giocatore.")
            return
        tot = sum(p for _, _, p in cl)
        righe = []
        for pos, nome, p in cl:
            sp, n = speso(db, nome), len(rosa(db, nome))
            righe.append((pos, nome, f"{sp}/{s['budget_iniziale']}", pct(sp, s["budget_iniziale"]),
                          p, pct(p, tot), f"{p / sp:.2f}" if sp else "-", f"{p / n:.1f}" if n else "-"))
        print("\nSquadre a confronto")
        tabella(["Pos", "Giocatore", "Speso", "% budget", "Punti", "% punti", "Punti/credito", "Media/musicista"],
                righe, "><>>>>>>")

    def scegli_squadra(self):
        s = ask("Nome giocatore (invio = la tua squadra): ")
        u = utente(self.db, s) if s else self.me
        if not u:
            print("Giocatore non trovato.")
            return
        self.dettaglio_squadra(u["nome"])

    def dettaglio_squadra(self, nome):
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
        dati = sorted(((m, punti_musicista(db, m["id"], nome)) for m in r), key=lambda x: -x[1])
        righe = [(m["nome"], m["prezzo"], pct(m["prezzo"], sp), p, pct(p, tot),
                  f"{p / m['prezzo']:.2f}" if m["prezzo"] else "-") for m, p in dati]
        tabella(["Musicista", "Prezzo", "% spesa", "Punti", "% punti squadra", "Punti/credito"], righe, "<>>>>>")
        ex = tot - sum(p for _, p in dati)
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
                righe.append((m["nome"], m["proprietario"], m["prezzo"], p, p / m["prezzo"]))
        if not righe:
            print("Nessun musicista acquistato.")
            return
        righe.sort(key=lambda x: -x[4])
        print("\nResa dei musicisti (punti per credito speso), dal migliore al peggiore")
        tabella(["Musicista", "Squadra", "Prezzo", "Punti", "Punti/credito"],
                [(a, b, c, d, f"{e:.2f}") for a, b, c, d, e in righe], "<<>>>")

    def tabella_eventi(self, eventi):
        db = self.db
        righe = [(e["id"], e["data"], nome_musicista(db, e["musicista_id"]), e["azione"],
                  f"{e['punti']:+d}", e["proprietario"] or "-") for e in eventi]
        tabella(["ID", "Data", "Musicista", "Azione", "Punti", "Squadra"], righe, "><<<><")

    def stat_ultimi_eventi(self):
        ev = self.db["eventi"]
        if not ev:
            print("Nessun evento registrato.")
            return
        print("\nUltimi 15 eventi")
        self.tabella_eventi(list(reversed(ev[-15:])))

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
        self.tabella_musicisti()
        m = self.scegli_per_id(db["musicisti"], "ID musicista (invio per tornare indietro): ")
        if not m:
            return
        tot = sum(e["punti"] for e in db["eventi"])
        p = punti_musicista(db, m["id"])
        print(f"\n=== {m['nome']} ===")
        if m["proprietario"]:
            print(f"  Squadra: {m['proprietario']} (pagato {m['prezzo']} crediti)")
        else:
            print("  Squadra: nessuna (libero)")
        print(f"  Punti:   {p:+d} ({pct(p, tot)} dei punti totali)")
        self.stampa_caratteristiche(m, "musicisti")
        recenti = [e for e in db["eventi"] if e["musicista_id"] == m["id"]][-5:]
        if recenti:
            print("\nUltimi eventi")
            self.tabella_eventi(list(reversed(recenti)))

    def profilo_giocatore(self):
        db = self.db
        s = ask("Nome giocatore (invio = il tuo profilo): ")
        u = utente(db, s) if s else self.me
        if not u:
            print("Giocatore non trovato.")
            return
        print(f"\n=== {u['nome']} ===")
        self.stampa_caratteristiche(u, "giocatori")
        if u["gioca"]:
            self.dettaglio_squadra(u["nome"])

    # ---------- impostazioni ----------
    def impostazioni(self):
        s = self.db["impostazioni"]
        while True:
            print("\n=== Impostazioni ===")
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
            ("Asta musicisti", self.asta),
            ("Gestione musicisti", self.menu_musicisti),
            ("Gestione azioni", self.menu_azioni),
            ("Gestione utenti", self.menu_utenti),
            ("Caratteristiche dei profili", self.menu_campi),
            ("Elimina un evento", self.elimina_evento),
            ("Azzera stagione", self.azzera_stagione),
        ])

    def tabella_musicisti(self):
        db = self.db
        righe = [(m["id"], m["nome"], m["proprietario"] or "-", m["prezzo"] if m["proprietario"] else "-",
                  punti_musicista(db, m["id"])) for m in db["musicisti"]]
        tabella(["ID", "Musicista", "Squadra", "Prezzo", "Punti"], righe, "><<>>")

    @solo_admin
    def registra_evento(self):
        db = self.db
        if not db["musicisti"] or not db["azioni"]:
            print("Servono almeno un musicista e un'azione.")
            return
        self.tabella_musicisti()
        m = self.scegli_per_id(db["musicisti"], "ID musicista (invio per annullare): ")
        if not m:
            return
        tabella(["ID", "Azione", "Punti"], [(a["id"], a["nome"], f"{a['punti']:+d}") for a in db["azioni"]], "><>")
        a = self.scegli_per_id(db["azioni"], "ID azione (invio per annullare): ")
        if not a:
            return
        punti = a["punti"]
        s = ask(f"Punti [{punti:+d}] (invio = conferma, oppure scrivi un valore diverso): ")
        if s:
            try:
                punti = int(s)
            except ValueError:
                print("Valore non valido, evento annullato.")
                return
        nota = ask("Nota (facoltativa): ")
        db["eventi"].append({
            "id": prossimo_id(db, "evento"),
            "data": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "musicista_id": m["id"],
            "azione_id": a["id"],
            "azione": a["nome"],
            "punti": punti,
            "proprietario": m["proprietario"],
            "nota": nota,
        })
        dove = f"alla squadra di {m['proprietario']}" if m["proprietario"] else "a nessuno (musicista senza squadra)"
        print(f"Registrato: {punti:+d} a {m['nome']} -> {dove}.")

    @solo_admin
    def elimina_evento(self):
        ev = self.db["eventi"]
        if not ev:
            print("Nessun evento registrato.")
            return
        self.tabella_eventi(list(reversed(ev[-15:])))
        e = self.scegli_per_id(ev, "ID evento da eliminare (invio per annullare): ")
        if e and ask("Confermi? (s/N) ").lower() == "s":
            ev.remove(e)
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
            print("\nMusicisti ancora disponibili:")
            tabella(["ID", "Musicista"], [(m["id"], m["nome"]) for m in liberi], "><")
            m = self.scegli_per_id(liberi, "ID musicista da mettere all'asta (invio per uscire): ")
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
                if len(parti) != 2 or not parti[1].isdigit():
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
            self.tabella_musicisti()
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
        self.tabella_musicisti()
        m = self.scegli_per_id(db["musicisti"], "ID musicista da modificare (invio per annullare): ")
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
        self.tabella_musicisti()
        m = self.scegli_per_id(db["musicisti"], "ID da rimuovere (invio per annullare): ")
        if not m:
            return
        if m["proprietario"]:
            print("Prima svincolalo dalla squadra.")
        elif any(e["musicista_id"] == m["id"] for e in db["eventi"]):
            print("Ha eventi registrati: eliminali prima oppure lascialo in elenco.")
        elif ask(f"Rimuovere {m['nome']}? (s/N) ").lower() == "s":
            db["musicisti"].remove(m)

    @solo_admin
    def svincola_musicista(self):
        db = self.db
        venduti = [m for m in db["musicisti"] if m["proprietario"]]
        if not venduti:
            print("Nessun musicista acquistato.")
            return
        tabella(["ID", "Musicista", "Squadra", "Prezzo"],
                [(m["id"], m["nome"], m["proprietario"], m["prezzo"]) for m in venduti], "><<>")
        m = self.scegli_per_id(venduti, "ID da svincolare (invio per annullare): ")
        if not m:
            return
        print(f"{m['nome']} torna libero e {m['proprietario']} recupera {m['prezzo']} crediti. "
              f"I punti già maturati restano alla squadra.")
        if ask("Confermi? (s/N) ").lower() == "s":
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
        tabella(["ID", "Azione", "Punti"], [(a["id"], a["nome"], f"{a['punti']:+d}") for a in self.db["azioni"]], "><>")

    @solo_admin
    def aggiungi_azione(self):
        db = self.db
        nome = ask("Nome azione: ")
        if not nome:
            return
        if any(x["nome"].lower() == nome.lower() for x in db["azioni"]):
            print("Esiste già un'azione con questo nome.")
            return
        db["azioni"].append({"id": prossimo_id(db, "azione"), "nome": nome,
                             "punti": ask_int("Punti (anche negativi): ")})

    @solo_admin
    def modifica_azione(self):
        db = self.db
        self.elenco_azioni()
        a = self.scegli_per_id(db["azioni"], "ID azione da modificare (invio per annullare): ")
        if not a:
            return
        eventi = [e for e in db["eventi"] if e.get("azione_id") == a["id"]]
        print(f"\nModifica di '{a['nome']}' - usata in {len(eventi)} eventi (invio = lascia com'è)")

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

        p = ask(f"Punti [{a['punti']:+d}]: ")
        if p:
            try:
                nuovi = int(p)
            except ValueError:
                print("Punti non validi, lasciati invariati.")
                return
            vecchi = a["punti"]
            a["punti"] = nuovi
            if nuovi == vecchi:
                return
            da_aggiornare = [e for e in eventi if e["punti"] == vecchi]
            if da_aggiornare:
                print(f"{len(da_aggiornare)} eventi già registrati hanno il vecchio punteggio ({vecchi:+d}).")
                if len(eventi) > len(da_aggiornare):
                    print(f"Altri {len(eventi) - len(da_aggiornare)} hanno un punteggio personalizzato "
                          f"e non verrebbero toccati.")
                if ask(f"Portarli a {nuovi:+d}? Le classifiche cambieranno. (s/N) ").lower() == "s":
                    for e in da_aggiornare:
                        e["punti"] = nuovi
                    print("Eventi aggiornati.")
                else:
                    print("Eventi lasciati invariati: il nuovo punteggio vale dai prossimi.")
            else:
                print("Il nuovo punteggio vale dai prossimi eventi.")

    @solo_admin
    def elimina_azione(self):
        self.elenco_azioni()
        a = self.scegli_per_id(self.db["azioni"], "ID azione da eliminare (invio per annullare): ")
        if a and ask(f"Eliminare '{a['nome']}'? (s/N) ").lower() == "s":
            self.db["azioni"].remove(a)

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
        s = ask(prompt)
        if not s:
            return None
        u = utente(self.db, s)
        if not u:
            print("Utente non trovato.")
        return u

    def n_admin(self):
        return sum(1 for u in self.db["utenti"] if u["ruolo"] == "admin")

    @solo_admin
    def elenco_utenti(self):
        db = self.db
        tabella(["Utente", "Ruolo", "In classifica", "Musicisti", "Crediti"],
                [(u["nome"], u["ruolo"], "sì" if u["gioca"] else "no", len(rosa(db, u["nome"])),
                  crediti(db, u["nome"])) for u in db["utenti"]], "<<<>>")

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
        ruolo = "admin" if ask("Admin? (s/N) ").lower() == "s" else "partecipante"
        crea_utente(db, nome, pw, ruolo)
        print(f"Utente {nome} creato ({ruolo}).")

    @solo_admin
    def modifica_profilo_giocatore(self):
        u = self.chiedi_utente()
        if u:
            print(f"\nProfilo di {u['nome']}")
            self.chiedi_valori_profilo(u, "giocatori")

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
        righe = []
        for c in db["campi"]:
            profili = profili_di(db, c["per"])
            compilati = sum(1 for p in profili if str(c["id"]) in p.get("profilo", {}))
            righe.append((c["id"], c["per"], c["nome"], c["tipo"],
                          f"{compilati}/{len(profili)} ({pct(compilati, len(profili))})"))
        tabella(["ID", "Per", "Caratteristica", "Tipo", "Compilata"], righe, "><<<<")
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
        self.elenco_campi()
        c = self.scegli_per_id(db["campi"], "ID caratteristica da rinominare (invio per annullare): ")
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
        self.elenco_campi()
        c = self.scegli_per_id(db["campi"], "ID caratteristica da eliminare (invio per annullare): ")
        if not c:
            return
        profili = profili_di(db, c["per"])
        compilati = [p for p in profili if str(c["id"]) in p.get("profilo", {})]
        if ask(f"Eliminare '{c['nome']}'? Verranno cancellati i valori inseriti in {len(compilati)} profili. (s/N) ").lower() != "s":
            return
        for p in compilati:
            del p["profilo"][str(c["id"])]
        db["campi"].remove(c)
        print("Caratteristica eliminata.")

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
        if ask(f"Eliminare {u['nome']}? I suoi musicisti torneranno liberi. (s/N) ").lower() != "s":
            return
        for m in rosa(db, u["nome"]):
            m["proprietario"], m["prezzo"] = None, 0
        for e in db["eventi"]:
            if e["proprietario"] == u["nome"]:
                e["proprietario"] = None
        db["utenti"].remove(u)
        print("Utente eliminato.")

    # ----- nuova stagione -----
    @solo_admin
    def azzera_stagione(self):
        db = self.db
        print("Verranno cancellati TUTTI gli eventi e le assegnazioni dei musicisti.")
        print("Restano utenti, elenco musicisti, azioni e impostazioni.")
        if ask("Scrivi AZZERA per confermare: ") != "AZZERA":
            print("Annullato.")
            return
        db["eventi"].clear()
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
