# -*- coding: utf-8 -*-
"""
FANTABANDA - collegamento online (Supabase)

Questo modulo NON ha grafica: lo usano l'app Kivy (fantamusica_kivy.py) e, se vuoi, il programma
da terminale fantamusica_server.py. Sta accanto a fantamusica.py.

Come funziona
  * Il database del gioco resta sul computer dell'admin (fantamusica_dati.json) e viene
    PUBBLICATO su Supabase a ogni modifica (push). Online ne finisce anche una copia completa,
    leggibile solo con il codice admin, utile come backup.
  * I giocatori, dalla pagina web, mandano RICHIESTE (proponi evento, scambi, soprannomi, voti).
  * Il computer dell'admin le legge, le applica con le regole di fantamusica.py (elabora_richiesta)
    e ripubblica lo stato: per questo l'app dell'admin deve restare aperta durante il gioco.
"""
import json
import secrets
import ssl
import urllib.error
import urllib.request
from datetime import datetime

import fantamusica as fm

ALFABETO_CODICI = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()


# --------------------------------------------------------------------------
# Codici personali dei giocatori
# --------------------------------------------------------------------------
def nuovo_codice(n=6):
    return "".join(secrets.choice(ALFABETO_CODICI) for _ in range(n))


def assicura_codici(db):
    """Dà un codice personale (campo codice_asta) a chi non ce l'ha; i codici sono tutti diversi.
    Ritorna True se ha modificato qualcosa."""
    cambiato = False
    usati = set()
    for u in db["utenti"]:
        c = (u.get("codice_asta") or "").upper()
        if c and c not in usati:
            usati.add(c)
            if c != u.get("codice_asta"):
                u["codice_asta"], cambiato = c, True
        else:
            u["codice_asta"] = None
    for u in db["utenti"]:
        if not u.get("codice_asta"):
            c = nuovo_codice()
            while c in usati:
                c = nuovo_codice()
            usati.add(c)
            u["codice_asta"] = c
            cambiato = True
    return cambiato


def codici(db):
    return {u["nome"]: u["codice_asta"] for u in db["utenti"] if u.get("codice_asta")}


def copia_dati(db):
    """Copia indipendente del database (da fare nel thread dell'interfaccia prima di inviarlo)."""
    return json.loads(json.dumps(db, ensure_ascii=False))


# --------------------------------------------------------------------------
# Comunicazione con Supabase
# --------------------------------------------------------------------------
class ErroreOnline(RuntimeError):
    pass


class Online:
    """Client minimale per le funzioni SQL di supabase_gioco.sql (nessuna libreria esterna)."""

    def __init__(self, cfg, timeout=15):
        self.url = cfg["url"].rstrip("/")
        self.chiave = cfg["anon_key"]
        self.admin = cfg["admin_code"]
        self.timeout = timeout

    def rpc(self, nome, **par):
        r = self.grezzo(nome, **par)
        if isinstance(r, dict) and r.get("ok") is False and not r.get("conflitto"):
            raise ErroreOnline(r.get("errore") or "Operazione rifiutata")
        return r

    def grezzo(self, nome, **par):
        """Come rpc ma senza sollevare errori quando la funzione risponde ok=false."""
        dati = json.dumps(par, ensure_ascii=False).encode("utf-8")
        req = urllib.request.Request(
            f"{self.url}/rest/v1/rpc/{nome}", data=dati, method="POST",
            headers={"apikey": self.chiave, "Authorization": "Bearer " + self.chiave,
                     "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                testo = r.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            try:
                dett = json.loads(e.read().decode("utf-8"))
                dett = dett.get("message") or dett
            except Exception:
                dett = e.reason
            raise ErroreOnline(f"Supabase ha risposto {e.code}: {dett}")
        except (urllib.error.URLError, OSError) as e:
            raise ErroreOnline(f"Nessuna connessione a Supabase: {getattr(e, 'reason', e)}")
        return json.loads(testo) if testo else None

    # ----- stato -----
    def stato(self):
        return self.rpc("fm_a_stato", p_admin=self.admin)

    def push(self, dati, versione_base=None):
        """Pubblica il database (dati = copia_dati(db)). Ritorna la risposta: ok/conflitto/versione."""
        return self.rpc("fm_a_push", p_admin=self.admin, p_dati=dati, p_codici=codici(dati),
                        p_base=versione_base)

    def scarica(self):
        r = self.rpc("fm_a_scarica", p_admin=self.admin)
        return r["versione"], r["dati"]

    # ----- richieste dei giocatori -----
    def richieste(self):
        return self.rpc("fm_a_prendi", p_admin=self.admin)["richieste"]

    def esiti(self, lista):
        if lista:
            self.rpc("fm_a_esito", p_admin=self.admin, p_esiti=lista)


# --------------------------------------------------------------------------
# Applicazione delle richieste dei giocatori (regole originali del gioco)
# --------------------------------------------------------------------------
class RichiestaNonValida(Exception):
    pass


def _intero(v, nome="valore"):
    if isinstance(v, bool):
        raise RichiestaNonValida(f"{nome} non valido")
    if isinstance(v, (int, float)) and float(v).is_integer():
        return int(v)
    if isinstance(v, str) and v.strip().lstrip("+-").isdigit():
        return int(v)
    raise RichiestaNonValida(f"{nome} non valido")


def _musicista(db, mid):
    m = next((x for x in db["musicisti"] if x["id"] == _intero(mid, "musicista")), None)
    if not m:
        raise RichiestaNonValida("Musicista inesistente")
    return m


def _ora():
    return datetime.now().strftime("%Y-%m-%d %H:%M")


def _evento(db, me, p):
    """Proposta di un evento: resta in pending finché l'admin non la conferma."""
    a = next((x for x in db["azioni"] if x["id"] == _intero(p.get("azione_id"), "azione")), None)
    if not a:
        raise RichiestaNonValida("Azione inesistente")
    slot = fm.slot_azione(a)
    scelti = p.get("musicisti") or []
    if len(scelti) != len(slot):
        raise RichiestaNonValida(f"L'azione coinvolge {len(slot)} musicisti")
    g = fm.Gioco(db, me)
    coppie, basi, presi = [], [], set()
    qta = None
    for s, x in zip(slot, scelti):
        m = _musicista(db, x.get("musicista_id"))
        if m["id"] in presi:
            raise RichiestaNonValida("Un musicista è stato scelto due volte")
        presi.add(m["id"])
        if a["modalita"] == "sondaggio":
            testo = str(x.get("voto") or "").strip()
            voti = []
            if testo:
                voti = fm.parse_voti(testo, s["min"], s["max"])
                if not voti or len(voti) != 1:
                    raise RichiestaNonValida(f"Il voto per {m['nome']} deve essere un intero da {s['min']} a {s['max']}")
            basi.append((None, "", voti))
        elif a["modalita"] == "tempo":
            if qta is None:
                qta = fm.parse_numero(str(p.get("quantita", "")))
                if qta is None or qta <= 0:
                    raise RichiestaNonValida("Serve una quantità maggiore di zero")
            basi.append((fm.arrotonda(qta * s["punti"]),
                         f"{fm.fmt_valore(qta)} {a['unita']} x {s['punti']:+d}", []))
        else:
            basi.append((s["punti"], "", []))
        coppie.append((m, s))
    for x in (p.get("altri") or [])[:20]:
        m = _musicista(db, x.get("musicista_id"))
        if m["id"] in presi:
            raise RichiestaNonValida(f"{m['nome']} è già coinvolto")
        presi.add(m["id"])
        punti = _intero(x.get("punti"), f"punteggio di {m['nome']}")
        if abs(punti) > 1000:
            raise RichiestaNonValida("Punteggio troppo grande")
        coppie.append((m, None))
        basi.append((punti, "punteggio libero", []))
    validi = set(a.get("bonus_ids", []))
    bonus = []
    for i in p.get("bonus_ids") or []:
        b = next((y for y in db["bonus"] if y["id"] == _intero(i, "bonus")), None)
        if b and b["id"] in validi:
            bonus.append({"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"]})
    nota = str(p.get("nota") or "").strip()[:200]
    gruppo = fm.prossimo_id(db, "gruppo") if len(coppie) > 1 else None
    creati = []
    for (m, s), (base, dett, voti) in zip(coppie, basi):
        fascia = (s["min"], s["max"]) if s and a["modalita"] == "sondaggio" else None
        e = g.aggiungi_evento(m, a, None, base, bonus, dett, True, nota, fascia=fascia, voti=voti,
                              gruppo=gruppo, ruolo=g.ruolo_evento(a, s))
        e["da_approvare"], e["proposto_da"] = True, me["nome"]
        e["proposta_base"] = None if (s and a["modalita"] == "sondaggio") else base
        if voti:
            e["votanti"] = [me["nome"]]
        creati.append(e)
    return f"Proposta inviata ({len(creati)} event{'o' if len(creati) == 1 else 'i'}): l'admin la confermerà."


def _scambio_proponi(db, me, p):
    if not db["impostazioni"].get("mercato_aperto", True):
        raise RichiestaNonValida("Il mercato è chiuso")
    if not me["gioca"]:
        raise RichiestaNonValida("Solo chi partecipa alla classifica può fare scambi")
    dest = fm.utente(db, str(p.get("a") or ""))
    if not dest or dest is me or not dest["gioca"]:
        raise RichiestaNonValida("Giocatore destinatario non valido")
    offro = sorted({_intero(i, "musicista") for i in p.get("offro") or []})
    chiedo = sorted({_intero(i, "musicista") for i in p.get("chiedo") or []})
    crediti = _intero(p.get("crediti", 0), "conguaglio")
    prop = {"data": _ora(), "da": me["nome"], "a": dest["nome"], "offro": offro, "chiedo": chiedo,
            "nomi_offro": [fm.nome_musicista(db, i) for i in offro],
            "nomi_chiedo": [fm.nome_musicista(db, i) for i in chiedo],
            "crediti": crediti, "stato": "proposto"}
    errore, _ = fm.simula_scambio(db, prop)
    if errore:
        raise RichiestaNonValida(f"Non fattibile ora: {errore}")
    prop["id"] = fm.prossimo_id(db, "scambio")
    db["scambi"].append(prop)
    return f"Proposta di scambio {prop['id']} inviata a {dest['nome']}."


def _scambio_rispondi(db, me, p):
    pr = next((x for x in db["scambi"] if x["id"] == _intero(p.get("id"), "proposta")), None)
    if not pr or pr["stato"] != "proposto":
        raise RichiestaNonValida("La proposta non è più in sospeso")
    azione = p.get("azione")
    if azione in ("accetta", "rifiuta") and me["nome"] != pr["a"]:
        raise RichiestaNonValida("Solo il destinatario può accettare o rifiutare")
    if azione == "annulla" and me["nome"] != pr["da"]:
        raise RichiestaNonValida("Solo chi ha proposto può annullare")
    if azione == "accetta":
        if not db["impostazioni"].get("mercato_aperto", True):
            raise RichiestaNonValida("Il mercato è chiuso")
        errore, _ = fm.simula_scambio(db, pr)
        if errore:
            raise RichiestaNonValida(f"Non fattibile ora: {errore}")
        fm.esegui_scambio(db, pr)
        return "Scambio completato."
    if azione == "rifiuta":
        pr["stato"], pr["data_esito"] = "rifiutato", _ora()
        return "Proposta rifiutata."
    if azione == "annulla":
        pr["stato"], pr["data_esito"] = "annullato", _ora()
        return "Proposta annullata."
    raise RichiestaNonValida("Azione non valida")


def _pref_soprannome(db, me, p):
    testo = " ".join(str(p.get("testo") or "").split())[:20]
    fm.prefs(me)["soprannome"] = testo
    return "Soprannome aggiornato." if testo else "Soprannome tolto."


def _pref_sopr_musicista(db, me, p):
    m = _musicista(db, p.get("musicista_id"))
    testo = " ".join(str(p.get("testo") or "").split())[:30]
    mio = fm.prefs(me)["soprannomi_musicisti"]
    if testo:
        mio[str(m["id"])] = testo
    else:
        mio.pop(str(m["id"]), None)
    return f"Soprannome per {m['nome']} aggiornato."


def _voto(db, me, p):
    e = next((x for x in db["eventi"] if x["id"] == _intero(p.get("evento_id"), "evento")), None)
    if not e or e.get("stato") != "pending":
        raise RichiestaNonValida("L'evento non è più in pending")
    a = next((x for x in db["azioni"] if x["id"] == e.get("azione_id")), None)
    if not a or a["modalita"] != "sondaggio":
        raise RichiestaNonValida("Questo evento non prevede un sondaggio")
    lo, hi = e.get("fascia") or (a["min"], a["max"])
    voti = fm.parse_voti(str(p.get("voto", "")), lo, hi)
    if not voti or len(voti) != 1:
        raise RichiestaNonValida(f"Il voto deve essere un intero da {lo} a {hi}")
    if me["nome"] in e.get("votanti", []):
        raise RichiestaNonValida("Hai già votato questo evento")
    gruppo = [x for x in db["eventi"] if x.get("stato") == "pending" and e.get("gruppo")
              and x.get("gruppo") == e["gruppo"] and (x.get("ruolo") or "") == (e.get("ruolo") or "")] or [e]
    for x in gruppo:
        x.setdefault("voti", []).append(voti[0])
        x.setdefault("votanti", []).append(me["nome"])
        x["dettaglio"] = f"voti finora: {', '.join(map(str, x['voti']))}"
    return "Voto registrato."


GESTORI = {
    "evento": _evento,
    "scambio_proponi": _scambio_proponi,
    "scambio_rispondi": _scambio_rispondi,
    "pref_soprannome": _pref_soprannome,
    "pref_sopr_musicista": _pref_sopr_musicista,
    "voto": _voto,
}


def elabora_richiesta(db, r):
    """Applica UNA richiesta {id, nome, tipo, payload} al database.
    Ritorna (stato, messaggio) con stato 'ok' oppure 'errore' (in questo caso il database non è stato toccato)."""
    me = fm.utente(db, r.get("nome", ""))
    gestore = GESTORI.get(r.get("tipo"))
    if not me or not gestore:
        return "errore", "Richiesta sconosciuta"
    try:
        return "ok", gestore(db, me, r.get("payload") or {})   # ogni gestore controlla TUTTO prima di modificare
    except RichiestaNonValida as e:
        return "errore", str(e)
    except Exception as e:      # una richiesta malformata non deve mai bloccare le altre
        return "errore", f"Richiesta non valida ({e.__class__.__name__})"


def elabora_richieste(db, richieste):
    """Applica le richieste in ordine. Ritorna ([esiti per fm_a_esito], True se il database è cambiato).
    Ogni richiesta viene applicata UNA sola volta: l'esito resta annotato nel database
    (richieste_applicate), così anche se la risposta al server si perde non si duplica nulla."""
    reg = db.setdefault("richieste_applicate", {})
    esiti, cambiato = [], False
    for r in richieste:
        k = str(r["id"])
        if k in reg:
            stato, msg = reg[k]
        else:
            stato, msg = elabora_richiesta(db, r)
            reg[k] = [stato, msg]
            cambiato = True
        esiti.append({"id": r["id"], "stato": stato, "msg": msg})
    if len(reg) > 400:
        for k in sorted(reg, key=int)[:-300]:
            del reg[k]
    return esiti, cambiato
