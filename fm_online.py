# -*- coding: utf-8 -*-
"""
FANTABANDA - collegamento online (Supabase)

Questo modulo NON ha grafica: è la libreria di sincronizzazione usata da fantamusica_kivy.py.
La vecchia sincronizzazione manuale da terminale è dismessa.

Come funziona
  * Il gioco vive ONLINE (Supabase): le regole per le richieste dei giocatori e per le operazioni
    dell'admin dalla pagina web girano dentro il database (supabase_fantabanda.sql). Nessun PC acceso.
  * L'app Kivy (e il gioco da terminale) lavorano su una copia locale (fantamusica_dati.json):
    l'app scarica le novita' online e pubblica le modifiche fatte da qui. Se nel frattempo qualcuno
    ha giocato, le due versioni vengono UNITE (unisci) invece di sovrascriversi.
  * Per unire serve l'ultima versione scaricata/pubblicata da questo computer: e' salvata in
    fantamusica_online_base.json accanto ai dati.
"""
import copy
import json
import secrets
import ssl
import os
import time
import urllib.error
import urllib.request
from datetime import datetime

import fantamusica_core as fm

ALFABETO_CODICI = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()


# --------------------------------------------------------------------------
# Codici di associazione dei giocatori
# --------------------------------------------------------------------------
def nuovo_codice(n=8):
    return "".join(secrets.choice(ALFABETO_CODICI) for _ in range(n))


def assicura_codici(db):
    """Dà un codice di associazione (campo codice_asta) a chi non ce l'ha; i codici sono tutti diversi.
    Ritorna True se ha modificato qualcosa."""
    cambiato = False
    usati = set()
    for u in db["utenti"]:
        c = (u.get("codice_asta") or "").upper().replace("-", "").replace(" ", "")
        valido = len(c) == 8 and all(ch in ALFABETO_CODICI for ch in c)
        if valido and c not in usati:
            usati.add(c)
            if c != u.get("codice_asta"):
                u["codice_asta"], cambiato = c, True
        else:
            if u.get("codice_asta") is not None:
                cambiato = True
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
    """Client Supabase per l'admin locale, autenticato con Supabase Auth.

    La password non viene mai salvata. Se l'utente sceglie "ricordami", viene
    salvato soltanto il refresh token in ``fantamusica_online_auth.json``.
    """

    AUTH_FILE = fm.DATA_FILE.with_name("fantamusica_online_auth.json")

    def __init__(self, cfg, timeout=15):
        self.url = cfg["url"].rstrip("/")
        self.chiave = cfg["anon_key"]
        self.timeout = timeout
        self.sessione = None
        self.ricorda = False
        self._carica_sessione()

    # ----- sessione Supabase Auth -----
    def _carica_sessione(self):
        try:
            with open(self.AUTH_FILE, encoding="utf-8") as f:
                d = json.load(f)
            if isinstance(d, dict) and d.get("refresh_token"):
                self.sessione = d
                self.ricorda = True
        except (OSError, ValueError, TypeError):
            self.sessione = None
            self.ricorda = False

    def _salva_sessione(self):
        if not self.ricorda or not self.sessione:
            return
        d = {
            "access_token": self.sessione.get("access_token"),
            "refresh_token": self.sessione.get("refresh_token"),
            "expires_at": self.sessione.get("expires_at"),
            "email": self.sessione.get("email"),
        }
        tmp = self.AUTH_FILE.with_suffix(self.AUTH_FILE.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(d, f, ensure_ascii=False, indent=2)
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, self.AUTH_FILE)
        try:
            os.chmod(self.AUTH_FILE, 0o600)
        except OSError:
            pass

    def _elimina_sessione_salvata(self):
        try:
            self.AUTH_FILE.unlink()
        except FileNotFoundError:
            pass
        except OSError:
            pass

    def ha_sessione(self):
        return bool(self.sessione and (self.sessione.get("access_token") or self.sessione.get("refresh_token")))

    def email(self):
        return (self.sessione or {}).get("email") or ""

    def _http_json(self, metodo, percorso, corpo=None, bearer=None):
        dati = None if corpo is None else json.dumps(corpo, ensure_ascii=False).encode("utf-8")
        headers = {"apikey": self.chiave, "Content-Type": "application/json"}
        if bearer:
            headers["Authorization"] = "Bearer " + bearer
        req = urllib.request.Request(self.url + percorso, data=dati, method=metodo, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                testo = r.read().decode("utf-8")
                return json.loads(testo) if testo else None
        except urllib.error.HTTPError as e:
            try:
                raw = e.read().decode("utf-8")
                dett = json.loads(raw) if raw else {}
                msg = dett.get("msg") or dett.get("message") or dett.get("error_description") or dett.get("error") or dett
            except Exception:
                msg = e.reason
            raise ErroreOnline(f"Supabase ha risposto {e.code}: {msg}")
        except (urllib.error.URLError, OSError) as e:
            raise ErroreOnline(f"Nessuna connessione a Supabase: {getattr(e, 'reason', e)}")

    def _imposta_sessione(self, r, ricorda=None):
        if not isinstance(r, dict) or not r.get("access_token"):
            raise ErroreOnline("Supabase non ha restituito una sessione valida")
        if ricorda is not None:
            self.ricorda = bool(ricorda)
        user = r.get("user") if isinstance(r.get("user"), dict) else {}
        expires_at = r.get("expires_at")
        if not expires_at:
            expires_at = int(time.time()) + int(r.get("expires_in") or 3600)
        self.sessione = {
            "access_token": r.get("access_token"),
            "refresh_token": r.get("refresh_token") or (self.sessione or {}).get("refresh_token"),
            "expires_at": int(expires_at),
            "email": user.get("email") or r.get("email") or (self.sessione or {}).get("email"),
        }
        if self.ricorda:
            self._salva_sessione()
        else:
            self._elimina_sessione_salvata()

    def login(self, email, password, ricorda=False):
        email = str(email or "").strip().lower()
        if not email or not password:
            raise ErroreOnline("Inserisci email e password dell'admin Supabase")
        r = self._http_json("POST", "/auth/v1/token?grant_type=password",
                            {"email": email, "password": password})
        self._imposta_sessione(r, ricorda=ricorda)
        st = self.rpc("fm_auth_stato")
        if not isinstance(st, dict) or not st.get("admin"):
            self.logout()
            raise ErroreOnline("L'account Supabase è valido ma non è autorizzato come admin FantaBanda")
        return {"ok": True, "email": self.email(), "admin": True}

    def refresh(self):
        rt = (self.sessione or {}).get("refresh_token")
        if not rt:
            raise ErroreOnline("Accesso Supabase admin richiesto")
        r = self._http_json("POST", "/auth/v1/token?grant_type=refresh_token", {"refresh_token": rt})
        self._imposta_sessione(r)
        return self.sessione

    def logout(self):
        token = (self.sessione or {}).get("access_token")
        if token:
            try:
                self._http_json("POST", "/auth/v1/logout", {}, bearer=token)
            except Exception:
                pass
        self.sessione = None
        self.ricorda = False
        self._elimina_sessione_salvata()

    def _token(self):
        if not self.sessione:
            raise ErroreOnline("Accesso Supabase admin richiesto")
        exp = int(self.sessione.get("expires_at") or 0)
        if not self.sessione.get("access_token") or exp <= int(time.time()) + 45:
            self.refresh()
        return self.sessione["access_token"]

    def rpc(self, nome, **par):
        r = self.grezzo(nome, **par)
        if isinstance(r, dict) and r.get("ok") is False and not r.get("conflitto"):
            msg = r.get("errore") or "Operazione rifiutata"
            problemi = r.get("problemi")
            if isinstance(problemi, list) and problemi:
                righe = [str(x) for x in problemi[:8]]
                if len(problemi) > 8:
                    righe.append(f"... e altri {len(problemi) - 8} problemi")
                msg += "\n\nDettagli:\n- " + "\n- ".join(righe)
            raise ErroreOnline(msg)
        return r

    def grezzo(self, nome, **par):
        """Come rpc ma senza sollevare errori quando la funzione risponde ok=false."""
        dati = json.dumps(par, ensure_ascii=False).encode("utf-8")
        for tentativo in range(2):
            token = self._token()
            req = urllib.request.Request(
                f"{self.url}/rest/v1/rpc/{nome}", data=dati, method="POST",
                headers={"apikey": self.chiave, "Authorization": "Bearer " + token,
                         "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout, context=_SSL) as r:
                    testo = r.read().decode("utf-8")
                return json.loads(testo) if testo else None
            except urllib.error.HTTPError as e:
                if e.code == 401 and tentativo == 0 and (self.sessione or {}).get("refresh_token"):
                    try:
                        self.refresh()
                        continue
                    except Exception:
                        pass
                try:
                    raw = e.read().decode("utf-8")
                    dett = json.loads(raw) if raw else {}
                    dett = dett.get("message") or dett.get("msg") or dett
                except Exception:
                    dett = e.reason
                raise ErroreOnline(f"Supabase ha risposto {e.code}: {dett}")
            except (urllib.error.URLError, OSError) as e:
                raise ErroreOnline(f"Nessuna connessione a Supabase: {getattr(e, 'reason', e)}")
        raise ErroreOnline("Sessione Supabase non valida")

    # ----- stato -----
    def stato(self):
        return self.rpc("fm_a_stato", p_admin=None)

    def push(self, dati, versione_base=None):
        """Pubblica il database dopo un pre-controllo locale; Supabase lo rivalida comunque sul server."""
        validatore = getattr(fm, "valida_integrita", None)
        if callable(validatore):
            try:
                problemi = validatore(dati)
            except Exception as e:
                raise ErroreOnline(f"Impossibile verificare l'integrità del database locale: {e}") from e
            if problemi:
                righe = [str(x) for x in problemi[:8]]
                if len(problemi) > 8:
                    righe.append(f"... e altri {len(problemi) - 8} problemi")
                raise ErroreOnline("Il database locale contiene incoerenze e non verrà pubblicato:\n- "
                                   + "\n- ".join(righe))
        return self.rpc("fm_a_push", p_admin=None, p_dati=dati, p_codici=codici(dati),
                        p_base=versione_base)

    def scarica(self):
        r = self.rpc("fm_a_scarica", p_admin=None)
        return r["versione"], r["dati"]

    def audit(self, prima_id=None, limite=100):
        par = {"p_admin": None, "p_limite": int(limite)}
        if prima_id is not None:
            par["p_prima_id"] = int(prima_id)
        return self.rpc("fm_audit_elenco", **par)

    def assicura_admin(self):
        st = self.rpc("fm_auth_stato")
        if not isinstance(st, dict) or not st.get("admin"):
            raise ErroreOnline("La sessione Supabase non appartiene a un admin FantaBanda")
        return True

    def verifica_snapshot(self, dati=None):
        """Valida uno snapshot sul server senza salvarlo. Se dati=None controlla quello già online."""
        return self.grezzo("fm_a_verifica_snapshot", p_dati=dati)


# --------------------------------------------------------------------------
# Applicazione delle richieste dei giocatori (regole originali del gioco)
# Online le richieste le applica Supabase da solo: queste funzioni restano come copia di riferimento
# delle stesse regole in Python (le prove automatiche confrontano riga per riga i due risultati).
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
            basi.append((None, "", voti, (s["min"], s["max"])))
        elif a["modalita"] == "tempo":
            if qta is None:
                qta = fm.parse_numero(str(p.get("quantita", "")))
                if qta is None or qta <= 0:
                    raise RichiestaNonValida("Serve una quantità maggiore di zero")
            basi.append((fm.arrotonda(qta * s["punti"]),
                         f"{fm.fmt_valore(qta)} {a['unita']} x {s['punti']:+d}", [], None))
        else:
            basi.append((s["punti"], "", [], None))
        coppie.append((m, s))
    for x in (p.get("altri") or [])[:20]:
        m = _musicista(db, x.get("musicista_id"))
        if m["id"] in presi:
            raise RichiestaNonValida(f"{m['nome']} è già coinvolto")
        presi.add(m["id"])
        esito = fm.parse_punteggio_libero(str(x.get("punti", "")))
        if esito is None:
            raise RichiestaNonValida(f"Punteggio di {m['nome']} non valido")
        coppie.append((m, None))
        if esito[0] == "fisso":
            if abs(esito[1]) > 1000:
                raise RichiestaNonValida("Punteggio troppo grande")
            basi.append((esito[1], "punteggio libero", [], None))
        else:
            basi.append((None, "", [], (esito[1], esito[2])))
    validi = set(a.get("bonus_ids", []))
    bonus = []
    visti_bonus = set()
    for i in p.get("bonus_ids") or []:
        bid = _intero(i, "bonus")
        if bid in visti_bonus:
            continue
        visti_bonus.add(bid)
        b = next((y for y in db["bonus"] if y["id"] == bid), None)
        if b and b["id"] in validi and b.get("bersaglio", "azione") == "azione":
            bonus.append({"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"],
                          "descrizione": b.get("descrizione", "")})
    nota = str(p.get("nota") or "").strip()[:200]
    # Probabile doppione: un'altra proposta già in pending ha lo stesso musicista e la stessa azione.
    # In tal caso l'evento viene comunque registrato, ma segnalato (duplicato) e mostrato solo all'admin.
    doppione = any(fm.evento_duplicato_pending(db, a["id"], mm["id"]) for mm, _ in coppie)
    gruppo = fm.prossimo_id(db, "gruppo") if len(coppie) > 1 else None
    creati = []
    for (m, s), (base, dett, voti, fascia) in zip(coppie, basi):
        e = g.aggiungi_evento(m, a, None, base, bonus, dett, True, nota, fascia=fascia, voti=voti,
                              gruppo=gruppo, ruolo=g.ruolo_evento(a, s))
        e["da_approvare"], e["proposto_da"] = True, me["nome"]
        e["proposta_base"] = None if (s and a["modalita"] == "sondaggio") else base
        e["duplicato"] = doppione
        if voti:
            e["votanti"] = [me["nome"]]
        creati.append(e)
    n = len(creati)
    if doppione:
        return (f"Esiste già una proposta in pending con lo stesso musicista e la stessa azione: "
                f"l'evento è stato comunque registrato, ma non viene mostrato per evitare doppioni. "
                f"Rivolgiti all'admin se pensi che sia corretto.")
    return f"Proposta inviata ({n} event{'o' if n == 1 else 'i'}): l'admin la confermerà."


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
    extra = (e.get("ruolo") or "") == "extra"
    if not e.get("fascia") and (extra or not (a and a["modalita"] == "sondaggio")):
        raise RichiestaNonValida("Questo evento non prevede un sondaggio")
    lo, hi = e.get("fascia") or (a["min"], a["max"])
    voti = fm.parse_voti(str(p.get("voto", "")), lo, hi)
    if not voti or len(voti) != 1:
        raise RichiestaNonValida(f"Il voto deve essere un intero da {lo} a {hi}")
    if me["nome"] in e.get("votanti", []):
        raise RichiestaNonValida("Hai già votato questo evento")
    gruppo = fm.gruppo_voto(db, e, [x for x in db["eventi"] if x.get("stato") == "pending"])
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


# --------------------------------------------------------------------------
# Unione di due versioni del database (questo computer + online)
# --------------------------------------------------------------------------
BASE_FILE = fm.DATA_FILE.with_name("fantamusica_online_base.json")

# liste di record: si uniscono record per record (chiave fra parentesi)
LISTE = {"utenti": "nome", "musicisti": "id", "azioni": "id", "bonus": "id", "scambi": "id", "eventi": "id",
         "campi": "id", "storico": "id"}
# contatori di ID usati anche online (giocatori, admin dal telefono): gli ID nuovi creati da questo computer
# vengono spostati dopo quelli creati online, cosi' non si scontrano
SPOSTABILI = {"evento": [("eventi", "id")], "gruppo": [("eventi", "gruppo")], "scambio": [("scambi", "id")]}
# contatore -> lista (e campo) da cui non deve mai restare indietro
CONTATORI = {"evento": ("eventi", "id"), "scambio": ("scambi", "id"), "musicista": ("musicisti", "id"),
             "azione": ("azioni", "id"), "bonus": ("bonus", "id"), "campo": ("campi", "id"),
             "stagione": ("storico", "id"), "gruppo": ("eventi", "gruppo")}
_MANCA = object()


def pulito(db):
    """Copia confrontabile del database (senza dati tecnici)."""
    d = copia_dati(db)
    d.pop("richieste_applicate", None)
    return d


def leggi_base():
    """(versione, dati) dell'ultima versione online nota a questo computer, oppure None."""
    try:
        with open(BASE_FILE, encoding="utf-8") as f:
            b = json.load(f)
        return b["versione"], b["dati"]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def scrivi_base(versione, dati):
    tmp = BASE_FILE.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"versione": versione, "dati": dati}, f, ensure_ascii=False)
    tmp.replace(BASE_FILE)


def _intero_vero(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _contatore(db, tipo):
    v = (db.get("contatori") or {}).get(tipo, 1)
    return v if _intero_vero(v) else 1


def _sposta_nuovi(base, locale, remoto):
    """Se sia questo computer sia online hanno creato nuovi eventi/gruppi/scambi partendo dalla stessa base,
    quelli di questo computer vengono rinumerati dopo quelli online."""
    loc = copy.deepcopy(locale)
    for tipo, campi in SPOSTABILI.items():
        cb, cl, cr = _contatore(base, tipo), _contatore(loc, tipo), _contatore(remoto, tipo)
        if cl > cb and cr > cb:
            delta = cr - cb
            for lista, campo in campi:
                for x in loc.get(lista) or []:
                    if isinstance(x, dict) and _intero_vero(x.get(campo)) and x[campo] >= cb:
                        x[campo] += delta
            loc.setdefault("contatori", {})[tipo] = cl + delta
    return loc


def _valore(b, l, r):
    if l == r:
        return copy.deepcopy(l)
    if b is not _MANCA and l == b:
        return copy.deepcopy(r)
    if b is not _MANCA and r == b:
        return copy.deepcopy(l)
    if isinstance(l, dict) and isinstance(r, dict):
        return _dizionario(b if isinstance(b, dict) else {}, l, r)
    return copy.deepcopy(l)          # cambiato in tutti e due i posti: vince questo computer (l'admin)


def _scegli(b, l, r):
    """Unione di un elemento (chiave di un dizionario o record di una lista). _MANCA = non c'e'."""
    if l is _MANCA and r is _MANCA:
        return _MANCA
    if l is _MANCA:          # non c'e' qui: aggiunto online (si tiene) oppure tolto qui (vince la rimozione)
        return copy.deepcopy(r) if b is _MANCA else _MANCA
    if r is _MANCA:          # non c'e' online: tolto online (se qui non e' cambiato) oppure aggiunto/cambiato qui
        return _MANCA if (b is not _MANCA and l == b) else copy.deepcopy(l)
    return _valore(b, l, r)


def _dizionario(b, l, r):
    out = {}
    for k in list(r) + [k for k in l if k not in r]:
        v = _scegli(b.get(k, _MANCA), l.get(k, _MANCA), r.get(k, _MANCA))
        if v is not _MANCA:
            out[k] = v
    return out


def _lista(b, l, r, chiave):
    tutti = (b or []) + (l or []) + (r or [])
    if not all(isinstance(x, dict) and chiave in x for x in tutti):
        return _valore(b, l, r)
    mappe = []
    for lst in (b or [], l or [], r or []):
        m = {}
        for x in lst:
            if x[chiave] in m:                     # chiavi doppie: non si puo' unire record per record
                return _valore(b, l, r)
            m[x[chiave]] = x
        mappe.append(m)
    mb, ml, mr = mappe
    ordine = [x[chiave] for x in r] + [x[chiave] for x in l if x[chiave] not in mr]
    out = []
    for k in ordine:
        v = _scegli(mb.get(k, _MANCA), ml.get(k, _MANCA), mr.get(k, _MANCA))
        if v is not _MANCA:
            out.append(v)
    return out


def unisci(base, locale, remoto):
    """Unione a tre vie: 'base' e' l'ultima versione online che questo computer conosceva, 'locale' quella
    modificata qui, 'remoto' quella online attuale. Le modifiche fatte da una parte sola passano tutte;
    se lo stesso dato e' cambiato in tutti e due i posti vince questo computer."""
    base, remoto = pulito(base), pulito(remoto)
    loc = _sposta_nuovi(base, pulito(locale), remoto)
    out = {}
    for k in list(remoto) + [k for k in loc if k not in remoto]:
        b, l, r = base.get(k, _MANCA), loc.get(k, _MANCA), remoto.get(k, _MANCA)
        if k in LISTE and isinstance(l, list) and isinstance(r, list):
            v = _lista(b if isinstance(b, list) else [], l, r, LISTE[k])
        elif k == "contatori" and isinstance(l, dict) and isinstance(r, dict):
            bb = b if isinstance(b, dict) else {}
            v = {}
            for t in list(r) + [t for t in l if t not in r]:
                lv, rv, bv = l.get(t), r.get(t), bb.get(t)
                if lv is None or rv is None:
                    v[t] = rv if lv is None else lv
                elif lv == bv:
                    v[t] = rv
                elif rv == bv:
                    v[t] = lv
                else:
                    v[t] = max(lv, rv)
        else:
            v = _scegli(b, l, r)
        if v is not _MANCA:
            out[k] = v
    cont = out.setdefault("contatori", {})
    for tipo, (lista, campo) in CONTATORI.items():
        ids = [x.get(campo) for x in out.get(lista) or [] if isinstance(x, dict) and _intero_vero(x.get(campo))]
        if ids and _contatore(out, tipo) <= max(ids):
            cont[tipo] = max(ids) + 1
    return out


# --------------------------------------------------------------------------
# Sincronizzazione da terminale (senza l'app): python3 fm_online.py sincronizza
# --------------------------------------------------------------------------
def sincronizza(cfg, db, scelta=None, on=None):
    """Porta online le modifiche fatte su questo computer e scarica le novita'. Ritorna (db, messaggio).
    scelta: None (automatico), 'locali' (sovrascrive online), 'online' (sostituisce i dati locali).

    ``on`` permette al chiamante (Kivy/CLI) di riusare il client Online gia' autenticato,
    evitando di perdere la sessione Supabase Auth appena creata.
    """
    if on is None:
        on = Online(cfg)
    st = on.stato()
    base = leggi_base()
    if st.get("vuoto") or scelta == "locali":
        assicura_codici(db)
        r = on.push(copia_dati(db), None if st.get("vuoto") else st["versione"])
        if r.get("conflitto"):
            raise ErroreOnline("Online e' cambiato proprio adesso: riprova")
        scrivi_base(r["versione"], copia_dati(db))
        return db, f"Dati di questo computer pubblicati (versione {r['versione']})."
    if scelta == "online" or base is None:
        if scelta is None:
            raise ErroreOnline("Questo computer non ha ancora una copia di riferimento dei dati online. Scegli:\n"
                               "  python3 fm_online.py sincronizza locali   (pubblica i dati di qui)\n"
                               "  python3 fm_online.py sincronizza online   (scarica quelli online, con backup)")
        ver, dati = on.scarica()
        if db is not None:
            fm.crea_backup(db, "prima-del-download-online")
        scrivi_base(ver, dati)
        return copy.deepcopy(dati), f"Scaricati i dati online (versione {ver})."
    for _ in range(5):
        ver_b, dati_b = base
        cambiato_qui = pulito(db) != pulito(dati_b)
        if st["versione"] == ver_b and not cambiato_qui:
            return db, "Già sincronizzato: nessuna modifica."
        if st["versione"] == ver_b:
            nuovo = pulito(db)
        else:
            ver, remoto = on.scarica()
            nuovo = unisci(dati_b, db, remoto) if cambiato_qui else pulito(remoto)
            base = (ver, remoto)
            scrivi_base(ver, remoto)
            if nuovo == pulito(remoto):
                return nuovo, f"Scaricate le novità online (versione {ver})."
        assicura_codici(nuovo)
        r = on.push(copia_dati(nuovo), base[0])
        if r.get("conflitto"):
            st = on.stato()
            db = nuovo
            continue
        scrivi_base(r["versione"], copia_dati(nuovo))
        return nuovo, f"Modifiche di questo computer unite e pubblicate (versione {r['versione']})."
    raise ErroreOnline("Online i dati cambiano troppo spesso in questo momento: riprova tra poco")


def main(argv=None):
    """Entry point legacy: la sincronizzazione si gestisce ora dall'app Kivy."""
    print("La sincronizzazione da terminale è stata dismessa.")
    print("Usa l'app: python3 fantamusica_kivy.py")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
