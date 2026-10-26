#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FANTAMUSICA - versione grafica (Kivy) con stile retro-neon.

Usa la stessa logica e lo stesso file dati di fantamusica.py (che deve stare nella stessa
cartella): puoi alternare versione testuale e grafica senza perdere nulla.

Novita' rispetto alla versione testuale
  - Foto per giocatori e musicisti (cartella "foto" accanto ai dati). Nelle liste compaiono come
    piccole miniature quadrate (max ~46 dp), nei profili al massimo 120 dp. Le foto importate
    vengono ritagliate quadrate e ridotte (se e' installato Pillow: pip install pillow).
  - Aspetto personalizzabile (menu "Aspetto e preferenze", salvato nel profilo di ogni giocatore):
    tema verde / blu / arancio fluo con sfondo sfumato, effetto CRT a scanline, dimensione del testo.
  - Interfaccia a pulsanti: classifiche, squadre, profili, mercato e scambi, eventi, pending,
    asta, gestione musicisti e utenti, backup/CSV.

Non ancora portato nella grafica (resta disponibile da fantamusica.py, stesso file dati):
  gestione azioni, bonus/malus, caratteristiche dei profili, chiusura stagione, ripristino backup.

Gioco online (facoltativo): con il file fantamusica_online.json accanto ai dati, questa app pubblica
lo stato del gioco su Supabase e applica le richieste dei giocatori che usano la pagina web
(index.html). L'app dell'admin deve restare aperta durante il gioco. Vedi fm_online.py.

Avvio:  pip install kivy pillow   ->   python3 fantamusica_kivy.py
"""
import copy
import json
import os
import re
import secrets
import shutil
import ssl
import threading
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("KIVY_NO_ARGS", "1")

from kivy.config import Config
# il tasto destro non deve creare i cerchi rossi del multitouch simulato (va impostato prima di aprire la finestra)
Config.set("input", "mouse", "mouse,disable_multitouch")

from kivy import kivy_data_dir
from kivy.app import App
from kivy.clock import Clock
from kivy.core.image import Image as CoreImage
from kivy.core.text import Label as CoreLabel
from kivy.core.window import Window
from kivy.graphics import Color, Line, Rectangle
from kivy.graphics.texture import Texture
from kivy.metrics import dp, sp
from kivy.uix.anchorlayout import AnchorLayout
from kivy.uix.behaviors import ButtonBehavior
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.floatlayout import FloatLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.image import Image
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget
from kivy.utils import platform

try:
    from PIL import Image as PILImage
except ImportError:  # senza Pillow le foto vengono copiate cosi' come sono
    PILImage = None

import fantamusica as fm
import fm_online as fo

# --------------------------------------------------------------------------
# Temi e percorsi
# --------------------------------------------------------------------------
TEMI = {
    "verde": {"nome": "VERDE FLUO", "bg1": (0.01, 0.05, 0.03), "bg2": (0.02, 0.22, 0.11),
              "accent": (0.25, 1.0, 0.50), "accent2": (0.70, 1.0, 0.35),
              "testo": (0.72, 1.0, 0.80), "panel": (0.02, 0.11, 0.06)},
    "blu": {"nome": "BLU ELETTRICO", "bg1": (0.01, 0.03, 0.08), "bg2": (0.03, 0.12, 0.30),
            "accent": (0.20, 0.75, 1.0), "accent2": (0.45, 0.95, 1.0),
            "testo": (0.75, 0.90, 1.0), "panel": (0.02, 0.07, 0.17)},
    "arancio": {"nome": "ARANCIO FLUO", "bg1": (0.07, 0.03, 0.01), "bg2": (0.28, 0.10, 0.02),
                "accent": (1.0, 0.55, 0.12), "accent2": (1.0, 0.80, 0.25),
                "testo": (1.0, 0.87, 0.72), "panel": (0.14, 0.06, 0.02)},
}
CAMPI_GUI = [("Strumento", "testo"), ("Solista", "sino"), ("Carica/Scarica", "sino"),
             ("Archivista", "sino"), ("Presentatore", "sino")]
SCALE = {"PICCOLO": 0.85, "MEDIO": 1.0, "GRANDE": 1.2, "MOLTO GRANDE": 1.4}
ASPETTO_BASE = {"tema": "verde", "scanlines": False, "scala": 1.2}

TEMA = dict(TEMI["verde"], chiave="verde", scanlines=False, scala=1.2)

_font = os.path.join(kivy_data_dir, "fonts", "RobotoMono-Regular.ttf")
FONT = _font if os.path.exists(_font) else "Roboto"

CFG_FILE = fm.DATA_FILE.with_name("fantamusica_gui.json")   # ultimo tema usato (prima del login)
FOTO_DIR = fm.DATA_FILE.parent / "foto"


def col(k):
    return TEMA[k]


def fs(n):
    return sp(n * TEMA["scala"])


def attenua(c, f=0.55):
    return tuple(x * f for x in c)


def assicura_campi(db):
    """Aggiunge ai musicisti le caratteristiche Strumento, Solista, Carica/Scarica, Archivista, Presentatore
    (si/no = tipo 'sino') se mancano. Ritorna True se ha modificato qualcosa."""
    cambiato = False
    for nome, tipo in CAMPI_GUI:
        if not any(c["per"] == "musicisti" and c["nome"].lower() == nome.lower() for c in db["campi"]):
            db["campi"].append({"id": fm.prossimo_id(db, "campo"), "per": "musicisti", "nome": nome, "tipo": tipo})
            cambiato = True
    return cambiato


# --------------------------------------------------------------------------
# Asta live online (Supabase)
# --------------------------------------------------------------------------
ONLINE_FILE = fm.DATA_FILE.with_name("fantamusica_online.json")   # url, anon_key, admin_code, web_url
ALFABETO_CODICI = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

try:
    import certifi
    _SSL = ssl.create_default_context(cafile=certifi.where())
except Exception:
    _SSL = ssl.create_default_context()


def leggi_online():
    try:
        with open(ONLINE_FILE, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    return c if c.get("url") and c.get("anon_key") and c.get("admin_code") else None


def nuovo_codice():
    return "".join(secrets.choice(ALFABETO_CODICI) for _ in range(6))


def sb_chiama(c, metodo, percorso, corpo=None, timeout=12):
    dati = None if corpo is None else json.dumps(corpo).encode("utf-8")
    req = urllib.request.Request(c["url"].rstrip("/") + percorso, data=dati, method=metodo,
                                 headers={"apikey": c["anon_key"], "Authorization": "Bearer " + c["anon_key"],
                                          "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_SSL) as r:
            testo = r.read().decode("utf-8")
    except urllib.error.HTTPError as e:
        try:
            dett = json.loads(e.read().decode("utf-8"))
            dett = dett.get("message") or dett
        except Exception:
            dett = e.reason
        raise RuntimeError(f"Supabase ha risposto {e.code}: {dett}")
    return json.loads(testo) if testo else None


def sb_rpc(c, nome, **par):
    return sb_chiama(c, "POST", "/rest/v1/rpc/" + nome, par)


def sb_leggi(c, tabella, query):
    return sb_chiama(c, "GET", f"/rest/v1/{tabella}?{query}")


def in_thread(lavoro, ok, err=None):
    """Esegue 'lavoro' in un thread e richiama ok(risultato) / err(eccezione) nel thread dell'interfaccia."""
    def run():
        try:
            r = lavoro()
        except Exception as e:
            if err:
                Clock.schedule_once(lambda dt, e=e: err(e), 0)
            return
        Clock.schedule_once(lambda dt, r=r: ok(r), 0)
    threading.Thread(target=run, daemon=True).start()


def e_collegato(visto):
    """True se l'ultimo segnale di vita (ISO 8601) e' di meno di 30 secondi fa."""
    if not visto:
        return False
    try:
        t = re.sub(r"\.(\d+)", lambda m: "." + (m.group(1) + "000000")[:6], visto.replace("Z", "+00:00"))
        return (datetime.now(timezone.utc) - datetime.fromisoformat(t)).total_seconds() < 30
    except ValueError:
        return False


def leggi_cfg():
    try:
        with open(CFG_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def scrivi_cfg(cfg):
    try:
        with open(CFG_FILE, "w", encoding="utf-8") as f:
            json.dump(cfg, f)
    except OSError:
        pass


# --------------------------------------------------------------------------
# Foto
# --------------------------------------------------------------------------
def importa_foto(sorgente, prefisso):
    """Copia la foto nella cartella 'foto' (ritagliata quadrata 192x192 se c'e' Pillow).
    Ritorna il nome del file salvato."""
    FOTO_DIR.mkdir(parents=True, exist_ok=True)
    base = f"{prefisso}_{secrets.token_hex(4)}"
    if PILImage:
        try:
            with PILImage.open(sorgente) as im:
                im = im.convert("RGBA")
                w, h = im.size
                s = min(w, h)
                x, y = (w - s) // 2, (h - s) // 2
                im = im.crop((x, y, x + s, y + s)).resize((192, 192), PILImage.LANCZOS)
                nome = base + ".png"
                im.save(FOTO_DIR / nome)
                return nome
        except Exception:
            pass
    nome = base + (Path(sorgente).suffix.lower() or ".png")
    shutil.copyfile(sorgente, FOTO_DIR / nome)
    return nome


def percorso_foto(nome):
    if not nome:
        return None
    p = FOTO_DIR / nome
    return str(p) if p.exists() else None


def elimina_foto(nome):
    if nome:
        try:
            (FOTO_DIR / nome).unlink()
        except OSError:
            pass


# --------------------------------------------------------------------------
# Sfondi (sfumato e scanline)
# --------------------------------------------------------------------------
def gradiente(alto, basso, n=64):
    tex = Texture.create(size=(1, n), colorfmt="rgb")
    buf = bytearray()
    for i in range(n):
        t = i / (n - 1)  # riga 0 = in basso
        buf += bytes(int(255 * (alto[j] * t + basso[j] * (1 - t))) for j in range(3))
    tex.blit_buffer(bytes(buf), colorfmt="rgb", bufferfmt="ubyte")
    tex.mag_filter = tex.min_filter = "linear"
    return tex


def tex_scanline():
    tex = Texture.create(size=(1, 4), colorfmt="rgba")
    tex.blit_buffer(bytes([0, 0, 0, 28, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0]), colorfmt="rgba", bufferfmt="ubyte")
    tex.wrap = "repeat"
    tex.mag_filter = tex.min_filter = "nearest"
    return tex


# --------------------------------------------------------------------------
# Widget in stile retro
# --------------------------------------------------------------------------
class L(Label):
    """Etichetta monospazio; wrap=True -> va a capo e la sua altezza segue il testo."""

    def __init__(self, text="", dim=14, colore="testo", wrap=False, **kw):
        kw.setdefault("halign", "left")
        kw.setdefault("valign", "middle")
        c = colore if isinstance(colore, tuple) else col(colore)
        super().__init__(text=text, font_name=FONT, font_size=fs(dim), color=(*c, 1), **kw)
        if wrap:
            self.size_hint_y = None
            self.bind(width=lambda *_: setattr(self, "text_size", (self.width, None)))
            self.bind(texture_size=lambda *_: setattr(self, "height", self.texture_size[1] + dp(6)))
        else:
            self.bind(size=lambda *_: setattr(self, "text_size", self.size))


DIAG = set(os.environ.get("FM_DIAG", "").split(","))      # prove diagnostiche: FM_DIAG=opaco,nofoto,nobordo


class Panel(BoxLayout):
    def __init__(self, alpha=0.78, bordo=True, **kw):
        super().__init__(**kw)
        if "opaco" in DIAG:
            alpha = 1.0
        with self.canvas.before:
            self._c = Color(*col("panel"), alpha)
            self._r = Rectangle()
            Color(*col("accent"), 0.55 if bordo else 0)
            self._l = Line(width=1)
        self._alpha = alpha
        self.bind(pos=self._u, size=self._u)

    def _u(self, *_):
        self._r.pos, self._r.size = self.pos, self.size
        self._l.rectangle = (self.x, self.y, self.width, self.height)


class RowBtn(ButtonBehavior, Panel):
    def __init__(self, **kw):
        super().__init__(**kw)
        self.bind(state=lambda *_: setattr(self._c, "a", 1.0 if self.state == "down" else self._alpha))


class NBtn(ButtonBehavior, Label):
    """Pulsante con bordo neon e alone."""

    def __init__(self, text="", colore=None, dim=14, **kw):
        c = colore or col("accent")
        kw.setdefault("size_hint_y", None)
        kw.setdefault("height", dp(46))
        super().__init__(text=text, font_name=FONT, font_size=fs(dim), bold=True, color=(*c, 1),
                         halign="center", valign="middle", **kw)
        with self.canvas.before:
            self._cf = Color(*c, 0.10)
            self._rf = Rectangle()
            Color(*c, 0.22)
            self._lg = Line(width=2.4)
            Color(*c, 1)
            self._ll = Line(width=1.1)
        self.bind(pos=self._u, size=self._u, state=self._s)
        self.bind(size=lambda *_: setattr(self, "text_size", self.size))

    def _u(self, *_):
        self._rf.pos, self._rf.size = self.pos, self.size
        r = (self.x, self.y, self.width, self.height)
        self._lg.rectangle = r
        self._ll.rectangle = r

    def _s(self, *_):
        self._cf.a = 0.45 if self.state == "down" else 0.10


class Avatar(Panel):
    """Miniatura quadrata a dimensione fissa (dim in dp): una Panel con dentro un'Image (foto, ritaglio centrale)
    o una Label con le iniziali. azione = funzione chiamata al tocco."""

    def __init__(self, foto=None, nome="?", dim=44, azione=None, **kw):
        d = dp(dim)
        super().__init__(alpha=1.0, size_hint=(None, None), size=(d, d), padding=dp(1), **kw)
        self.azione = azione
        tex = texture_foto(foto)
        if tex is not None:
            self.add_widget(Image(texture=tex, allow_stretch=True, keep_ratio=False))
        else:
            ini = "".join(w[0] for w in str(nome).split()[:2]).upper() or "?"
            self.add_widget(etichetta_iniziali(ini, dim, d))

    def on_touch_down(self, touch):
        if self.azione and self.collide_point(*touch.pos):
            touch.grab(self)
            return True
        return super().on_touch_down(touch)

    def on_touch_up(self, touch):
        if touch.grab_current is self:
            touch.ungrab(self)
            if self.collide_point(*touch.pos):
                Clock.schedule_once(lambda dt: self.azione(), 0)
            return True
        return super().on_touch_up(touch)


def texture_foto(foto):
    """Texture quadrata (ritaglio centrale) della foto, oppure None."""
    p = percorso_foto(foto)
    if not p or "nofoto" in DIAG:
        return None
    try:
        tex = CoreImage(p).texture
        w, h = tex.size
        if w != h:
            s = min(w, h)
            tex = tex.get_region((w - s) // 2, (h - s) // 2, s, s)
        return tex
    except Exception:
        return None


SU_INIZIALI = 0.10      # quanto alzare le iniziali (frazione del lato): il font ha il baricentro verso il basso


def etichetta_iniziali(testo, dim_px_dp, d):
    """Label centrata nel quadrato di lato d (px). Il padding in basso compensa lo spazio sotto la linea di base."""
    lb = Label(text=testo, font_name=FONT, font_size=sp(max(10, dim_px_dp * 0.4)), bold=True,
               color=(*col("accent"), 1), halign="center", valign="middle",
               padding=[0, 0, 0, d * SU_INIZIALI * 2])
    lb.bind(size=lambda w, *_: setattr(w, "text_size", w.size))
    return lb


def avatar_nella_riga(riga, foto, nome, dim, sposta=0):
    """Miniatura come figlio diretto della riga: una Panel (la stessa delle righe, già collaudata)
    con dentro solo un'Image o una Label standard. Nessuna istruzione grafica scritta a mano."""
    d = dp(dim)
    cornice = Panel(alpha=1.0, size_hint=(None, None), size=(d, d), padding=dp(1),
                    pos_hint={"center_y": 0.5})
    tex = texture_foto(foto)
    if tex is not None:
        cornice.add_widget(Image(texture=tex, allow_stretch=True, keep_ratio=False))
    else:
        testo = "".join(w[0] for w in str(nome).split()[:2]).upper() or "?"
        cornice.add_widget(etichetta_iniziali(testo, dim, d))
    riga.add_widget(cornice)


def fissa_info(top, info, minimo=150, gap=4):
    """Righe di testo con altezza propria (seguono la dimensione del carattere) e un po' d'aria fra loro;
    il riquadro si allunga quanto serve."""
    for c in info.children:
        c.size_hint_y = None
        c.height = c.font_size * 1.3 + dp(6)
    info.spacing = dp(gap)
    info.size_hint_y = None
    info.pos_hint = {"center_y": 0.5}
    n = len(info.children)
    info.height = sum(c.height for c in info.children) + dp(gap) * max(0, n - 1)
    top.height = max(dp(minimo), info.height + dp(24))


def ancora(w):
    """Contenitore che centra il widget (di dimensione fissa) in verticale e in orizzontale."""
    a = AnchorLayout(size_hint=(None, 1), width=w.width)
    a.add_widget(w)
    return a


def campo(testo="", hint="", **kw):
    return TextInput(text=testo, hint_text=hint, multiline=False, font_name=FONT, font_size=fs(14),
                     background_normal="", background_active="", background_color=(*col("bg1"), 1),
                     foreground_color=(*col("testo"), 1), cursor_color=(*col("accent"), 1),
                     hint_text_color=(*col("testo"), 0.35), size_hint_y=None, height=dp(42),
                     padding=[dp(8), dp(11)], write_tab=False, **kw)


def spinner(testo, valori, **kw):
    kw.setdefault("size_hint_y", None)
    kw.setdefault("height", dp(42))
    return Spinner(text=testo, values=valori, font_name=FONT, font_size=fs(13), background_normal="",
                   background_color=(*col("panel"), 1), color=(*col("accent"), 1), **kw)


def scroll_list(spacing=6):
    sv = ScrollView(bar_color=(*col("accent"), 0.8), bar_inactive_color=(*col("accent"), 0.3),
                    bar_width=dp(4), scroll_type=["bars", "content"])
    g = GridLayout(cols=1, spacing=dp(spacing), size_hint_y=None, padding=[0, 0, dp(6), 0])
    g.bind(minimum_height=g.setter("height"))
    sv.add_widget(g)
    sv.bind(scroll_y=lambda *_: g.do_layout())     # le righe seguono subito lo scorrimento (niente ritardo di un frame)
    return sv, g


def fmt_pt(n):
    return f"{n:+d}"


# --------------------------------------------------------------------------
# Applicazione
# --------------------------------------------------------------------------
class FantaApp(App):
    title = "FANTAMUSICA"

    # ---------- avvio ----------
    def build(self):
        if platform in ("win", "linux", "macosx"):
            Window.size = (1000, 720)
        self.cfg = leggi_cfg()
        self.db = fm.carica()
        if self.db is not None and (fm.migra(self.db) | assicura_campi(self.db)):
            fm.salva(self.db)
        self.me = None
        self.g = None
        self.stack = []
        self.righe_login = []
        self.live = None
        self._poll = self._conto_ev = None
        self._bg = self._scan = None
        # gioco online (Supabase)
        self.onl = None                  # client fo.Online (None = non collegato)
        self.onl_stadio = None           # avvio -> scelta -> attivo
        self.onl_ver = None              # ultima versione online nota
        self.onl_busy = False
        self.onl_sporco = False          # dati locali da pubblicare
        self.onl_base = None             # ultima versione online nota (per unire le modifiche fatte qui)
        self.onl_testo, self.onl_err, self.onl_ultimo_errore, self.onl_fresco = "", False, "", 0
        self.imposta_tema(self.cfg.get("tema", "verde"), self.cfg.get("scanlines", False),
                          self.cfg.get("scala", 1.2))
        self.radice = FloatLayout()
        self.radice.bind(pos=self._sync, size=self._sync)
        self.ricostruisci()
        self.stack = [(self.v_setup if self.db is None else self.v_login, ())]
        self.render()
        self._tick_ev, self._tick_s = Clock.schedule_interval(self.online_tick, 4), 4
        Clock.schedule_once(self.online_avvia, 1)
        return self.radice

    def imposta_tema(self, chiave, scanlines, scala):
        chiave = chiave if chiave in TEMI else "verde"
        TEMA.clear()
        TEMA.update(TEMI[chiave], chiave=chiave, scanlines=bool(scanlines), scala=float(scala))

    def _sync(self, *_):
        r = self.radice
        if self._bg is not None:
            self._bg.pos, self._bg.size = r.pos, r.size
        if self._scan is not None:
            self._scan.pos, self._scan.size = r.pos, r.size
            try:
                self._scan.tex_coords = (0, 0, 1, 0, 1, r.height / 4.0, 0, r.height / 4.0)
            except Exception:
                pass

    def ricostruisci(self):
        """Ricostruisce tutta la cornice (sfondo, intestazione) con il tema corrente."""
        r = self.radice
        r.clear_widgets()
        r.canvas.before.clear()
        r.canvas.after.clear()
        Window.clearcolor = (*col("bg1"), 1)
        with r.canvas.before:
            Color(1, 1, 1, 1)
            self._bg = Rectangle(texture=gradiente(col("bg1"), col("bg2")))
        self._scan = None
        if TEMA["scanlines"]:
            with r.canvas.after:
                Color(1, 1, 1, 1)
                self._scan = Rectangle(texture=tex_scanline())
        shell = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        self.hdr = Panel(size_hint_y=None, height=dp(58), padding=dp(6), spacing=dp(8))
        self.corpo = BoxLayout(orientation="vertical")
        shell.add_widget(self.hdr)
        shell.add_widget(self.corpo)
        r.add_widget(shell)
        self._sync()

    # ---------- navigazione ----------
    def vai(self, fn, *args):
        self.stack.append((fn, args))
        self.render()

    def sostituisci(self, fn, *args):
        self.stack[-1] = (fn, args)
        self.render()

    def indietro(self):
        if len(self.stack) > 1:
            self.stack.pop()
        self.render()

    def home(self):
        self.stack = [(self.v_home, ())]
        self.render()

    def render(self):
        for nome in ("_poll", "_conto_ev"):      # timer dell'asta live: si fermano quando si cambia schermata
            ev = getattr(self, nome, None)
            if ev:
                ev.cancel()
                setattr(self, nome, None)
        self.live = None
        self.online_ritmo(4)
        fn, args = self.stack[-1]
        self.hdr.clear_widgets()
        if self.me and len(self.stack) > 1:
            self.hdr.add_widget(NBtn("<", size_hint=(None, 1), width=dp(46), dim=18,
                                     on_release=lambda *_: self.indietro()))
            self.hdr.add_widget(NBtn("HOME", size_hint=(None, 1), width=dp(70), dim=11,
                                     colore=col("accent2"), on_release=lambda *_: self.home()))
        self.lt = L("> FANTAMUSICA_", dim=17, colore="accent", bold=True, shorten=True)
        self.hdr.add_widget(self.lt)
        self.onl_lbl = None
        if self.onl and self.me:
            self.onl_lbl = L("", dim=10, colore="accent2", halign="right", size_hint_x=None, width=dp(110))
            self.hdr.add_widget(self.onl_lbl)
            self.online_msg(self.onl_testo, self.onl_err)
        if self.me:
            self.hdr.add_widget(ancora(Avatar(self.me.get("foto"), self.me["nome"], dim=44,
                                              azione=lambda: self.vai(self.v_squadra, self.me["nome"]))))
        self.corpo.clear_widgets()
        fn(*args)

    def titolo(self, testo):
        s = self.db["impostazioni"]["stagione"] if self.db else ""
        self.lt.text = f"FANTAMUSICA // {testo}" + (f"  [{s}]" if s else "")

    def salva(self):
        fm.salva(self.db)
        if self.onl:
            self.onl_sporco = True       # il prossimo giro (entro 4 secondi) pubblica online

    def e_admin(self):
        return bool(self.me and self.me["ruolo"] == "admin")

    # ---------- gioco online (Supabase) ----------
    def online_msg(self, testo, errore=False):
        self.onl_testo, self.onl_err = testo, errore
        lbl = getattr(self, "onl_lbl", None)
        if lbl is not None:
            lbl.text = testo
            lbl.color = (1, 0.45, 0.45, 1) if errore else (*col("accent2"), 1)

    def online_avvia(self, *_):
        c = leggi_online()
        if not c or self.db is None or self.onl:
            return
        self.onl = fo.Online(c)
        self.onl_stadio, self.onl_ver, self.onl_busy = "avvio", None, False
        self.online_msg("● COLLEGO...")
        if self.me:
            self.render()
        self.online_tick()

    def online_errore(self, e):
        self.onl_busy = False
        self.onl_ultimo_errore = str(e)
        self.online_msg("● OFFLINE", True)

    def online_primo(self, st):
        """Primo contatto all'avvio. Se questo computer ha la sua copia di riferimento (base) si parte da li':
        le modifiche fatte qui (anche dal gioco da terminale) vengono unite a quelle online."""
        self.onl_busy = False
        if st.get("vuoto"):              # online non c'e' ancora nulla: si pubblicano i dati di questo computer
            self.onl_ver, self.onl_base, self.onl_sporco, self.onl_stadio = None, None, True, "attivo"
            self.online_msg("● ONLINE")
            Clock.schedule_once(self.online_tick, 0)
            return
        base = fo.leggi_base()
        if base is not None:
            self.onl_ver, self.onl_base = base
            self.onl_sporco = fo.pulito(self.db) != fo.pulito(self.onl_base)
            self.onl_stadio = "attivo"
            self.online_msg("● ONLINE")
            Clock.schedule_once(self.online_tick, 0)
            return
        if self.cfg.get("online_versione") == st["versione"]:
            # versione precedente dell'app: l'ultima versione online l'aveva pubblicata questo computer
            self.onl_ver, self.onl_base, self.onl_sporco, self.onl_stadio = st["versione"], None, True, "attivo"
            self.online_msg("● ONLINE")
            Clock.schedule_once(self.online_tick, 0)
            return
        quando = datetime.fromtimestamp(st["aggiornato"]).strftime("%d/%m/%Y %H:%M")
        self.online_scelta(f"Online c'è un salvataggio (versione {st['versione']}, del {quando}) e questo computer "
                           f"non sa da quale versione partono i suoi dati.\n\nDi solito conviene SCARICARE I DATI "
                           f"ONLINE (i giocatori hanno giocato lì; prima viene fatto un backup di quelli di questo "
                           f"computer). Se usi i dati di questo computer, quelli online vengono sovrascritti.",
                           st["versione"])

    def online_scelta(self, testo, versione):
        self.onl_stadio = "scelta"
        self.online_msg("● DA SCEGLIERE", True)
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L(testo, wrap=True))
        box.add_widget(sv)
        pop = self.popup("DATI ONLINE DIVERSI", box, 0.92, 0.85)

        def locali(*_):
            pop.dismiss()
            self.onl_ver, self.onl_base, self.onl_sporco, self.onl_stadio = versione, None, True, "attivo"
            self.online_msg("● ONLINE")
            Clock.schedule_once(self.online_tick, 0)

        def scarica(*_):
            pop.dismiss()
            self.online_scarica()

        def no(*_):
            pop.dismiss()
            self.onl, self.onl_stadio = None, None
            self.online_msg("")
        box.add_widget(NBtn("SCARICA I DATI ONLINE", dim=11, height=dp(48), on_release=scarica))
        box.add_widget(NBtn("USA I DATI DI QUESTO COMPUTER", dim=11, height=dp(48), on_release=locali))
        box.add_widget(NBtn("NON COLLEGARE ORA", dim=11, height=dp(48), colore=attenua(col("accent"), 0.7),
                            on_release=no))

    def online_scarica(self):
        """Sostituisce i dati di questo computer con quelli online (prima fa un backup)."""
        if not self.onl:
            return

        def ok(r):
            ver, dati = r
            if not all(k in dati for k in fm.CHIAVI_OBBLIGATORIE):
                self.msg("I dati online non sembrano un database di FantaBanda.")
                return
            if self.db is not None:
                try:
                    fm.crea_backup(self.db, "prima-del-download-online")
                except OSError:
                    pass
                self.db.clear()
                self.db.update(copy.deepcopy(dati))
            else:
                self.db = copy.deepcopy(dati)
            fm.migra(self.db)
            assicura_campi(self.db)
            fm.salva(self.db)
            self.online_ricorda(ver, dati)
            self.onl_sporco = fo.pulito(self.db) != fo.pulito(dati)
            self.onl_stadio, self.onl_busy = "attivo", False
            self.online_msg("● ONLINE")
            self.me = self.g = None
            self.stack = [(self.v_login, ())]
            self.ricostruisci()
            self.render()
            self.msg("Dati scaricati da Supabase: accedi con il tuo utente.")

        def err(e):
            self.online_errore(e)
            self.msg(f"Download non riuscito: {e}")
        in_thread(self.onl.scarica, ok, err)

    def online_ricorda(self, ver, dati):
        """Annota l'ultima versione online nota (serve per unire le modifiche): in memoria e su disco."""
        self.onl_ver, self.onl_base = ver, dati
        try:
            fo.scrivi_base(ver, dati)
        except OSError:
            pass
        if ver != self.cfg.get("online_versione"):
            self.cfg["online_versione"] = ver
            scrivi_cfg(self.cfg)

    def online_ritmo(self, secondi):
        """Ritmo dei controlli: 1 s se nell'asta online ci sono 2+ squadre collegate, altrimenti 4 s."""
        if secondi == getattr(self, "_tick_s", 4) or getattr(self, "_tick_ev", None) is None:
            return
        self._tick_ev.cancel()
        self._tick_ev, self._tick_s = Clock.schedule_interval(self.online_tick, secondi), secondi

    def popup_aperto(self):
        return any(isinstance(w, Popup) for w in Window.children)

    def online_tick(self, *_):
        """Ogni pochi secondi: guarda la versione online; pubblica le modifiche fatte qui oppure prende le novità."""
        if not self.onl or self.onl_busy or self.db is None:
            return
        if self.onl_stadio == "avvio":
            self.onl_busy = True
            in_thread(self.onl.stato, self.online_primo, self.online_errore)
            return
        if self.onl_stadio != "attivo":
            return
        self.onl_busy = True
        in_thread(self.onl.stato, self.online_giro, self.online_errore)

    def online_giro(self, st):
        if self.onl_stadio != "attivo" or self.db is None:
            self.onl_busy = False
            return
        if st.get("vuoto") or st["versione"] == self.onl_ver:
            if self.onl_sporco:
                self.online_invia()
                return
            self.onl_busy = False
            if self.onl_fresco > 0:
                self.onl_fresco -= 1
            else:
                self.online_msg("● ONLINE")
            return
        # online c'è una versione nuova (giocatori, admin dal telefono, un altro computer)
        if self.popup_aperto():          # non si cambiano i dati sotto una finestra aperta
            self.onl_busy = False
            self.online_msg("● NOVITÀ ONLINE")
            return
        in_thread(self.onl.scarica, self.online_ricevi, self.online_errore)

    def online_ricevi(self, r):
        self.onl_busy = False
        ver, remoto = r
        if self.onl_stadio != "attivo" or self.db is None or self.popup_aperto():
            return                       # ci si riprova al prossimo giro
        if not all(k in remoto for k in fm.CHIAVI_OBBLIGATORIE):
            self.online_errore(RuntimeError("i dati online non sembrano un database di FantaBanda"))
            return
        if self.onl_sporco and self.onl_base is None:
            self.online_scelta("Online è comparsa una versione nuova mentre questo computer aveva modifiche da "
                               "pubblicare, e non c'è una copia di riferimento per unirle.\n\nSe scarichi i dati "
                               "online perdi le modifiche fatte qui (resta un backup); se usi i dati di questo "
                               "computer sovrascrivi quelli online.", ver)
            return
        if self.onl_sporco:
            nuovo = fo.unisci(self.onl_base, self.db, remoto)
        else:
            nuovo = copy.deepcopy(remoto)
        self.online_sostituisci(nuovo)
        self.online_ricorda(ver, remoto)
        self.onl_sporco = fo.pulito(self.db) != fo.pulito(remoto)
        self.online_msg("● AGGIORNATO")
        self.onl_fresco = 2
        if self.onl_sporco:
            Clock.schedule_once(self.online_tick, 0)     # pubblica subito l'unione
        self.online_aggiorna_vista()

    def online_sostituisci(self, nuovo):
        """Mette 'nuovo' al posto dei dati in memoria (stesso oggetto db) e lo salva sul disco."""
        fm.migra(nuovo)
        assicura_campi(nuovo)
        self.db.clear()
        self.db.update(nuovo)
        fm.salva(self.db)
        if self.me:
            u = fm.utente(self.db, self.me["nome"])
            if u is None:
                self.me = self.g = None
                self.stack = [(self.v_login, ())]
                self.ricostruisci()
                self.render()
                self.msg("Il tuo utente non esiste più nei dati online.")
                return
            self.me = u
            self.g = fm.Gioco(self.db, u)

    def online_invia(self):
        """Pubblica i dati di questo computer partendo dalla versione online nota (se nel frattempo è cambiata,
        il giro successivo scarica la nuova e unisce)."""
        if fo.assicura_codici(self.db):
            fm.salva(self.db)
        dati = fo.copia_dati(self.db)
        dati.pop("richieste_applicate", None)
        self.onl_sporco = False
        base = self.onl_ver

        def ok(r):
            self.onl_busy = False
            if r.get("conflitto"):
                self.onl_sporco = True
                Clock.schedule_once(self.online_tick, 0)
                return
            self.online_ricorda(r["versione"], dati)
            if self.onl_fresco <= 0:
                self.online_msg("● ONLINE")

        def err(e):
            self.onl_sporco = True
            self.online_errore(e)
        in_thread(lambda: self.onl.push(dati, base), ok, err)

    def online_aggiorna_vista(self):
        """Dopo aver preso le novità online, ridisegna la schermata (se non c'è un popup aperto)."""
        if not self.me or self.popup_aperto() or not self.stack:
            return
        if self.stack[-1][0] in (self.v_pending, self.v_mercato, self.v_home, self.v_classifica):
            self.render()

    def on_stop(self):
        """Alla chiusura pubblica un'ultima volta le modifiche non ancora inviate (se online nel frattempo è
        cambiato, verranno unite al prossimo avvio)."""
        try:
            if self.onl and self.onl_sporco and self.onl_stadio == "attivo" and self.db is not None:
                fo.assicura_codici(self.db)
                fm.salva(self.db)
                self.onl.timeout = 8
                dati = fo.copia_dati(self.db)
                dati.pop("richieste_applicate", None)
                r = self.onl.push(dati, self.onl_ver)
                if r.get("ok"):
                    self.online_ricorda(r["versione"], dati)
        except Exception:
            pass

    def v_online(self):
        if not self._solo_admin:
            return self.indietro()
        self.titolo("GIOCO ONLINE")
        sv, g = scroll_list(10)
        c = leggi_online()
        if not c:
            g.add_widget(L("Manca il file fantamusica_online.json accanto ai dati: servono url, anon_key, "
                           "admin_code e web_url (vedi la guida).", wrap=True))
        else:
            righe = [f"Stato: {self.onl_testo or 'non collegato'}",
                     f"Versione online: {self.onl_ver if self.onl_ver is not None else '-'}",
                     f"Pagina dei giocatori: {c.get('web_url') or '(scrivi l’indirizzo in web_url dentro fantamusica_online.json)'}",
                     "Il gioco gira online da solo: giocatori e admin (dal telefono) usano la pagina web. "
                     "Questa app scarica le novità e pubblica le modifiche fatte qui, unendole a quelle online. "
                     "Non serve tenerla aperta."]
            if self.onl_ultimo_errore and self.onl_err:
                righe.append(f"Ultimo errore: {self.onl_ultimo_errore}")
            for r in righe:
                g.add_widget(L(r, wrap=True, dim=13))
            def pubblica():
                if not self.onl:
                    self.online_avvia()
                else:
                    self.onl_sporco = True
                    self.online_tick()
                self.msg("Pubblicazione avviata: tra qualche secondo i giocatori vedono i dati aggiornati.")

            def scarica():
                if not self.onl:
                    self.msg("Non sei collegato a Supabase.")
                    return
                self.conferma("Scaricare i dati online? Quelli di questo computer vengono sostituiti "
                              "(prima ne viene fatto un backup).", self.online_scarica, "SCARICA DA ONLINE", "SCARICA")
            for t, f in (("PUBBLICA ORA", pubblica), ("CODICI DEI GIOCATORI", self.f_codici),
                         ("SCARICA I DATI DA ONLINE", scarica)):
                g.add_widget(NBtn(t, dim=13, height=dp(56), on_release=lambda *_, f=f: f()))
        self.corpo.add_widget(sv)

    # ---------- popup e form ----------
    def popup(self, titolo, contenuto, w=0.9, h=0.85):
        p = Popup(title=titolo, content=contenuto, size_hint=(w, h), auto_dismiss=False,
                  background="", background_color=(*col("bg1"), 0.98), separator_color=(*col("accent"), 1),
                  title_color=(*col("accent"), 1), title_font=FONT, title_size=fs(15))
        p.open()
        return p

    def msg(self, testo, titolo="INFO"):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L(testo, wrap=True))
        box.add_widget(sv)
        ok = NBtn("OK")
        box.add_widget(ok)
        p = self.popup(titolo, box, 0.85, 0.6)
        ok.bind(on_release=lambda *_: p.dismiss())

    def conferma(self, testo, cb, titolo="CONFERMA", si="CONFERMA"):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L(testo, wrap=True))
        box.add_widget(sv)
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, ok = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn(si)
        riga.add_widget(no)
        riga.add_widget(ok)
        box.add_widget(riga)
        p = self.popup(titolo, box, 0.85, 0.6)
        no.bind(on_release=lambda *_: p.dismiss())

        def vai(*_):
            p.dismiss()
            cb()
        ok.bind(on_release=vai)

    def form(self, titolo, campi, cb, ok="OK", intro=None, h=0.8):
        """campi: [(chiave, etichetta, valore iniziale, {opzioni TextInput})].
        cb(valori) -> False per lasciare il form aperto."""
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list(8)
        if intro:
            g.add_widget(L(intro, wrap=True, colore="accent2"))
        campi_w = {}
        for chiave, etichetta, valore, opz in campi:
            g.add_widget(L(etichetta, dim=12, size_hint_y=None, height=dp(20), colore="accent2"))
            if "valori" in opz:
                w = spinner(str(valore) if str(valore) in opz["valori"] else opz["valori"][0], opz["valori"])
            else:
                w = campo(str(valore), **opz)
            g.add_widget(w)
            campi_w[chiave] = w
        box.add_widget(sv)
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, si = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn(ok)
        riga.add_widget(no)
        riga.add_widget(si)
        box.add_widget(riga)
        p = self.popup(titolo, box, 0.9, h)
        no.bind(on_release=lambda *_: p.dismiss())

        def invia(*_):
            if cb({k: w.text.strip() for k, w in campi_w.items()}) is not False:
                p.dismiss()
        si.bind(on_release=invia)
        return p

    def scegli_foto(self, cb):
        fc = FileChooserListView(path=str(Path.home()),
                                 filters=["*.png", "*.jpg", "*.jpeg", "*.bmp", "*.gif", "*.webp",
                                          "*.PNG", "*.JPG", "*.JPEG"])
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(fc)
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, ok = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn("USA QUESTA FOTO")
        riga.add_widget(no)
        riga.add_widget(ok)
        box.add_widget(riga)
        p = self.popup("SCEGLI UNA FOTO", box, 0.95, 0.9)
        no.bind(on_release=lambda *_: p.dismiss())

        def scelto(*_):
            if fc.selection:
                p.dismiss()
                cb(fc.selection[0])
        ok.bind(on_release=scelto)

    def cambia_foto(self, elemento, prefisso):
        def fatto(percorso):
            try:
                nuovo = importa_foto(percorso, prefisso)
            except Exception as e:
                self.msg(f"Impossibile usare questa foto: {e}")
                return
            elimina_foto(elemento.get("foto"))
            elemento["foto"] = nuovo
            self.salva()
            self.render()
        self.scegli_foto(fatto)

    def togli_foto(self, elemento):
        elimina_foto(elemento.get("foto"))
        elemento["foto"] = None
        self.salva()
        self.render()

    # ---------- componenti di lista ----------
    def riga(self, foto, nome, titolo, sotto="", destra="", azione=None, h=62):
        p = (RowBtn if azione else Panel)(size_hint_y=None, height=dp(h), padding=dp(7), spacing=dp(10))
        avatar_nella_riga(p, foto, nome, h - 16)
        c = BoxLayout(orientation="vertical")
        c.add_widget(L(titolo, dim=15, colore="accent", bold=True, shorten=True))
        if sotto:
            c.add_widget(L(sotto, dim=11, shorten=True))
        p.add_widget(c)
        if destra != "":
            p.add_widget(L(str(destra), dim=16, colore="accent2", bold=True, halign="right",
                           size_hint_x=None, width=dp(125)))
        if azione:
            p.bind(on_release=lambda *_: azione())
        return p

    def sezione(self, g, testo):
        g.add_widget(L(testo, dim=12, colore="accent2", size_hint_y=None, height=dp(26)))

    # ---------- primo avvio e login ----------
    def v_setup(self):
        self.titolo("PRIMO AVVIO")
        a = AnchorLayout()
        p = Panel(orientation="vertical", size_hint=(None, None), size=(dp(400), dp(440)),
                  padding=dp(18), spacing=dp(8))
        p.add_widget(L("CREA L'ACCOUNT AMMINISTRATORE", colore="accent", bold=True, size_hint_y=None,
                       height=dp(30)))
        n, p1, p2 = campo(hint="nome admin"), campo(hint="password (min. 4)", password=True), \
            campo(hint="ripeti password", password=True)
        for w in (n, p1, p2):
            p.add_widget(w)

        def crea(*_):
            if not n.text.strip() or len(p1.text) < 4 or p1.text != p2.text:
                self.msg("Serve un nome e una password di almeno 4 caratteri, scritta due volte uguale.")
                return
            self.db = fm.nuovo_db()
            assicura_campi(self.db)
            fm.crea_utente(self.db, n.text.strip(), p1.text, "admin")
            self.salva()
            self.stack = [(self.v_login, ())]
            self.render()
            self.online_avvia()
        p.add_widget(NBtn("CREA", on_release=crea))

        def da_online(*_):
            c = leggi_online()
            if not c:
                self.msg("Serve il file fantamusica_online.json accanto al programma.")
                return
            self.onl = fo.Online(c)
            self.online_scarica()
        p.add_widget(NBtn("OPPURE SCARICA I DATI ONLINE", dim=11, colore=col("accent2"), on_release=da_online))
        a.add_widget(p)
        self.corpo.add_widget(a)

    def v_login(self):
        self.titolo("ACCESSO")
        a = AnchorLayout()
        p = Panel(orientation="vertical", size_hint=(None, None), size=(dp(400), dp(400)),
                  padding=dp(18), spacing=dp(8))
        p.add_widget(L("> ACCESSO_", dim=22, colore="accent", bold=True, size_hint_y=None, height=dp(44)))
        n = campo(hint="utente")
        pw = campo(hint="password", password=True)
        p.add_widget(n)
        p.add_widget(pw)

        def accedi(*_):
            u = fm.utente(self.db, n.text)
            if u and fm.verifica_password(u, pw.text):
                self.entra(u)
            else:
                self.msg("Credenziali errate.")
        pw.bind(on_text_validate=accedi)
        p.add_widget(NBtn("ACCEDI", on_release=accedi))
        p.add_widget(NBtn("PASSWORD DIMENTICATA", dim=11, colore=col("accent2"),
                          on_release=lambda *_: self.f_recupero()))
        p.add_widget(NBtn("ESCI", dim=11, colore=attenua(col("accent"), 0.7), on_release=lambda *_: self.stop()))
        a.add_widget(p)
        self.corpo.add_widget(a)

    def f_recupero(self):
        def passo1(v):
            u = fm.utente(self.db, v["nome"])
            if not u or not u.get("recupero"):
                self.msg("Recupero non disponibile: chiedi all'admin di reimpostare la password.")
                return False
            r = u["recupero"]

            def passo2(w):
                _, h = fm.hash_password(fm.normalizza_risposta(w["risp"]), r["salt"])
                if not fm.secrets.compare_digest(h, r["hash"]):
                    self.msg("Risposta errata.")
                    return False
                if len(w["p1"]) < 4 or w["p1"] != w["p2"]:
                    self.msg("Password troppo corta o non coincidente.")
                    return False
                u["salt"], u["hash"] = fm.hash_password(w["p1"])
                self.salva()
                self.msg("Password aggiornata: ora puoi accedere.")
            self.form("RECUPERO PASSWORD", [
                ("risp", "Risposta", "", {}),
                ("p1", "Nuova password", "", {"password": True}),
                ("p2", "Ripeti password", "", {"password": True})], passo2, intro=f"Domanda: {r['domanda']}")
        self.form("RECUPERO PASSWORD", [("nome", "Nome utente", "", {})], passo1, h=0.45)

    def entra(self, u):
        self.me = u
        self.g = fm.Gioco(self.db, u)
        a = self.asp()
        self.imposta_tema(a["tema"], a["scanlines"], a["scala"])
        self.righe_login = self.calcola_riepilogo()
        fm.prefs(u)["ultimo_accesso"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        self.salva()
        self.ricostruisci()
        self.home()

    def esci_account(self):
        self.me = self.g = None
        self.imposta_tema(self.cfg.get("tema", "verde"), self.cfg.get("scanlines", False),
                          self.cfg.get("scala", 1.2))
        self.ricostruisci()
        self.stack = [(self.v_login, ())]
        self.render()

    def asp(self):
        a = fm.prefs(self.me).setdefault("aspetto", {})
        for k, v in ASPETTO_BASE.items():
            a.setdefault(k, v)
        return a

    def calcola_riepilogo(self):
        db, me = self.db, self.me
        p = fm.prefs(me)
        da = p["ultimo_accesso"]
        righe = []
        if not p["riepilogo_login"]:
            return righe
        if me["gioca"]:
            mia = next((x for x in fm.classifica_giocatori(db) if x[1] == me["nome"]), None)
            if mia:
                righe.append(f"Sei {mia[0]}° in classifica con {mia[2]} punti.")
            if da:
                nuovi = [e for e in fm.eventi_ok(db) if e["proprietario"] == me["nome"]
                         and (e.get("data_completamento") or e["data"]) > da]
                righe.append(f"Dall'ultimo accesso ({da}): {len(nuovi)} eventi per la tua squadra "
                             f"({sum(e['punti'] for e in nuovi):+d} punti).")
        n_pend = len(fm.eventi_pending(db))
        if n_pend:
            righe.append(f"Eventi in pending (sondaggi da completare): {n_pend}.")
        nprop = sum(1 for x in db["scambi"] if x["stato"] == "proposto" and x["a"] == me["nome"])
        if nprop:
            righe.append(f"Hai {nprop} proposte di scambio da valutare (Mercato).")
        return righe

    # ---------- home ----------
    def v_home(self):
        me = self.me
        p = fm.prefs(me)
        self.titolo(f"BENVENUTO {p['soprannome'] or me['nome']}".upper())
        sv, g = scroll_list(10)
        if self.righe_login:
            b = Panel(orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(2))
            for r in self.righe_login:
                b.add_widget(L(r, wrap=True, dim=12))
            b.bind(minimum_height=b.setter("height"))
            g.add_widget(b)
        griglia = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, row_default_height=dp(78),
                             row_force_default=True)
        griglia.bind(minimum_height=griglia.setter("height"))
        voci = [("CLASSIFICA", lambda: self.vai(self.v_classifica, "giocatori")),
                ("LA MIA SQUADRA", lambda: self.vai(self.v_squadra, me["nome"])),
                ("REGISTRA EVENTO" if self.e_admin() else "PROPONI UN EVENTO", lambda: self.f_evento(False)),
                ("MERCATO E SCAMBI", lambda: self.vai(self.v_mercato)),
                ("ASPETTO E PREFERENZE", lambda: self.vai(self.v_aspetto))]
        if self.e_admin():
            voci.append(("PANNELLO ADMIN", lambda: self.vai(self.v_admin)))
        voci.append(("CAMBIA ACCOUNT / ESCI", self.esci_account))
        for i, (t, f) in enumerate(voci):
            griglia.add_widget(NBtn(t, dim=15, height=dp(78), colore=col("accent2") if i % 3 == 1 else None,
                                    on_release=lambda *_, f=f: f()))
        g.add_widget(griglia)
        self.corpo.add_widget(sv)

    # ---------- classifica ----------
    TABS = [("giocatori", "GIOCATORI"), ("musicisti", "MUSICISTI"), ("eventi", "EVENTI"),
            ("pending", "PENDING"), ("cumulativa", "CUMULATIVA"), ("storico", "STORICO")]

    def v_classifica(self, tab="giocatori"):
        self.titolo("CLASSIFICA")
        barra = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for k, nome in self.TABS:
            barra.add_widget(NBtn(nome, dim=10, height=dp(40),
                                  colore=col("accent") if k == tab else attenua(col("accent"), 0.55),
                                  on_release=lambda *_, k=k: self.sostituisci(self.v_classifica, k)))
        self.corpo.add_widget(barra)
        self.corpo.add_widget(BoxLayout(size_hint_y=None, height=dp(6)))
        sv, g = scroll_list()
        getattr(self, "tab_" + tab)(g)
        self.corpo.add_widget(sv)

    def tab_giocatori(self, g):
        db = self.db
        n_max = db["impostazioni"]["musicisti_per_squadra"]
        cl = fm.classifica_giocatori(db)
        if not cl:
            g.add_widget(L("Nessun giocatore.", wrap=True))
        for pos, (_, nome, punti) in enumerate(cl, 1):
            u = fm.utente(db, nome)
            g.add_widget(self.riga(u.get("foto"), nome, f"{pos}. {fm.etichetta_utente(db, nome)}",
                                   f"crediti {fm.crediti(db, nome)} | rosa {len(fm.rosa(db, nome))}/{n_max}",
                                   punti, lambda n=nome: self.vai(self.v_squadra, n)))

    def tab_musicisti(self, g):
        db = self.db
        dati = sorted(((m, fm.punti_musicista(db, m["id"])) for m in db["musicisti"]),
                      key=lambda x: (-x[1], x[0]["nome"].lower()))
        if not dati:
            g.add_widget(L("Nessun musicista.", wrap=True))
        for ps, (m, p) in enumerate(dati, 1):
            sopr = m.get("soprannome")
            mio = fm.prefs(self.me)["soprannomi_musicisti"].get(str(m["id"]))
            nome = f"{ps}. {m['nome']}" + (f" «{sopr}»" if sopr else "") + (f" ({mio})" if mio else "")
            sotto = f"{m['proprietario']} - {m['prezzo']} crediti" if m["proprietario"] else "senza squadra"
            g.add_widget(self.riga(m.get("foto"), m["nome"], nome, sotto, p,
                                   lambda i=m["id"]: self.vai(self.v_musicista, i)))

    def righe_eventi(self, g, eventi):
        db = self.db
        if not eventi:
            g.add_widget(L("Nessun evento.", wrap=True))
        for e in eventi:
            m = next((x for x in db["musicisti"] if x["id"] == e["musicista_id"]), None)
            pts = "PENDING" if e.get("stato") == "pending" else fmt_pt(e["punti"]) + ("*" if e.get("dittatura") else "")
            calc = fm.descrivi_calcolo(e)
            sotto = f"{e.get('data_completamento') or e['data']} | {e['proprietario'] or '-'}" + \
                    (f" | {calc}" if calc else "") + \
                    (f" | proposto da {e['proposto_da']}" if e.get("proposto_da") else "")
            g.add_widget(self.riga(m.get("foto") if m else None, m["nome"] if m else "?",
                                   f"{m['nome'] if m else '?'} - {e['azione']}", sotto, pts))

    def tab_eventi(self, g):
        self.righe_eventi(g, fm.eventi_recenti(self.db, fm.prefs(self.me)["righe_eventi"]))

    def tab_pending(self, g):
        self.righe_eventi(g, fm.eventi_pending(self.db))

    def tab_cumulativa(self, g):
        db = self.db
        dati = fm.classifica_cumulativa(db)
        if not dati:
            g.add_widget(L("Nessun dato: non ci sono stagioni archiviate né eventi.", wrap=True))
        for pos, (_, nome, d) in enumerate(dati, 1):
            u = fm.utente(db, nome)
            g.add_widget(self.riga(u.get("foto") if u else None, nome, f"{pos}. {nome}",
                                   f"{d['stagioni']} stagioni | {d['titoli']} titoli | media "
                                   f"{d['punti'] / d['stagioni']:.1f}", d["punti"]))

    def tab_storico(self, g):
        st = self.db["storico"]
        if not st:
            g.add_widget(L("Nessuna stagione archiviata.", wrap=True))
        for s in reversed(st):
            vinc = s["classifica"][0] if s["classifica"] else None
            u = fm.utente(self.db, vinc["nome"]) if vinc else None
            g.add_widget(self.riga(u.get("foto") if u else None, vinc["nome"] if vinc else "?", s["nome"],
                                   f"chiusa il {s['chiusa']} - vincitore: {vinc['nome'] if vinc else '-'}",
                                   vinc["punti"] if vinc else ""))

    # ---------- profili ----------
    def v_squadra(self, nome):
        db = self.db
        u = fm.utente(db, nome)
        if not u:
            return self.indietro()
        s = db["impostazioni"]
        self.titolo(f"SQUADRA {nome}".upper())
        sv, g = scroll_list(8)
        top = Panel(size_hint_y=None, height=dp(150), padding=dp(10), spacing=dp(12))
        top.add_widget(ancora(Avatar(u.get("foto"), nome, dim=120)))
        info = BoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(L(fm.etichetta_utente(db, nome), dim=18, colore="accent", bold=True, shorten=True))
        r = fm.rosa(db, nome)
        info.add_widget(L(f"{fm.punti_utente(db, nome)} punti", dim=16, colore="accent2"))
        info.add_widget(L(f"crediti {fm.crediti(db, nome)}/{s['budget_iniziale']}", dim=12))
        info.add_widget(L(f"musicisti {len(r)}/{s['musicisti_per_squadra']}", dim=12))
        top.add_widget(info)
        fissa_info(top, info)
        g.add_widget(top)
        if self.me is u or self.e_admin():
            r2 = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(8))
            r2.add_widget(NBtn("CAMBIA FOTO", dim=11, height=dp(40), on_release=lambda *_: self.cambia_foto(u, "g")))
            if u.get("foto"):
                r2.add_widget(NBtn("TOGLI FOTO", dim=11, height=dp(40), colore=attenua(col("accent"), 0.7),
                                   on_release=lambda *_: self.togli_foto(u)))
            g.add_widget(r2)
        self.sezione(g, "MUSICISTI IN SQUADRA")
        if not r:
            g.add_widget(L("Nessun musicista in squadra.", wrap=True))
        for m in sorted(r, key=lambda x: -fm.punti_musicista(db, x["id"], nome)):
            p = fm.punti_musicista(db, m["id"], nome)
            g.add_widget(self.riga(m.get("foto"), m["nome"], m["nome"],
                                   f"prezzo {m['prezzo']} | punti/credito "
                                   f"{(p / m['prezzo']) if m['prezzo'] else 0:.2f}", p,
                                   lambda i=m["id"]: self.vai(self.v_musicista, i)))
        ex = fm.punti_utente(db, nome) - sum(fm.punti_musicista(db, m["id"], nome) for m in r)
        if ex:
            g.add_widget(L(f"Punti maturati da musicisti non più in squadra: {ex:+d}", dim=11, wrap=True))
        self.sezione(g, "ULTIMI EVENTI DELLA SQUADRA")
        self.righe_eventi(g, fm.eventi_recenti(db, 8, lambda e: e["proprietario"] == nome))
        self.corpo.add_widget(sv)

    def v_musicista(self, mid):
        db = self.db
        m = next((x for x in db["musicisti"] if x["id"] == mid), None)
        if not m:
            return self.indietro()
        self.titolo(m["nome"].upper())
        sv, g = scroll_list(8)
        top = Panel(size_hint_y=None, height=dp(150), padding=dp(10), spacing=dp(12))
        top.add_widget(ancora(Avatar(m.get("foto"), m["nome"], dim=120)))
        info = BoxLayout(orientation="vertical", spacing=dp(2))
        info.add_widget(L(m["nome"], dim=18, colore="accent", bold=True, shorten=True))
        if m.get("soprannome"):
            info.add_widget(L(f"«{m['soprannome']}»", dim=12, colore="accent2"))
        mio = fm.prefs(self.me)["soprannomi_musicisti"].get(str(m["id"]))
        if mio:
            info.add_widget(L(f"per te: {mio}", dim=11))
        info.add_widget(L(f"{fm.punti_musicista(db, m['id'])} punti totali", dim=15, colore="accent2"))
        info.add_widget(L(f"squadra: {m['proprietario'] or 'nessuna'}" +
                          (f" ({m['prezzo']} crediti)" if m["proprietario"] else ""), dim=12))
        for c in fm.campi_per(db, "musicisti"):
            info.add_widget(L(f"{c['nome']}: {fm.valore_profilo(m, c)}", dim=11))
        top.add_widget(info)
        fissa_info(top, info)
        g.add_widget(top)
        g.add_widget(NBtn("IL MIO SOPRANNOME PER QUESTO MUSICISTA", dim=11, height=dp(40),
                          on_release=lambda *_: self.f_mio_soprannome(m)))
        if self.e_admin():
            self.sezione(g, "ADMIN")
            griglia = GridLayout(cols=2, spacing=dp(8), size_hint_y=None, row_default_height=dp(40),
                                 row_force_default=True)
            griglia.bind(minimum_height=griglia.setter("height"))
            azioni = [("CAMBIA FOTO", lambda: self.cambia_foto(m, "m")),
                      ("TOGLI FOTO", lambda: self.togli_foto(m)),
                      ("RINOMINA / SOPRANNOME", lambda: self.f_rinomina_musicista(m)),
                      ("CARATTERISTICHE", lambda: self.f_caratteristiche(m, "musicisti")),
                      ("SVINCOLA", lambda: self.svincola(m)),
                      ("ELIMINA", lambda: self.elimina_musicista(m))]
            for t, f in azioni:
                griglia.add_widget(NBtn(t, dim=11, height=dp(40), on_release=lambda *_, f=f: f()))
            g.add_widget(griglia)
        self.sezione(g, "EVENTI")
        self.righe_eventi(g, fm.eventi_recenti(db, 10, lambda e: e["musicista_id"] == mid))
        self.corpo.add_widget(sv)

    def f_mio_soprannome(self, m):
        mio = fm.prefs(self.me)["soprannomi_musicisti"]

        def ok(v):
            s = v["s"]
            if s in ("-", ""):
                mio.pop(str(m["id"]), None)
            else:
                mio[str(m["id"])] = s[:30]
            self.salva()
            self.render()
        self.form(f"SOPRANNOME PER {m['nome'].upper()}", [("s", "Soprannome (max 30, vuoto = toglilo)",
                                                           mio.get(str(m["id"]), ""), {})], ok, h=0.45)

    def f_rinomina_musicista(self, m):
        def ok(v):
            if v["nome"] and v["nome"] != m["nome"]:
                if any(x is not m and x["nome"].lower() == v["nome"].lower() for x in self.db["musicisti"]):
                    self.msg("Esiste già un musicista con questo nome.")
                    return False
                m["nome"] = v["nome"]
            m["soprannome"] = v["sopr"][:30]
            self.salva()
            self.render()
        self.form("MODIFICA MUSICISTA", [("nome", "Nome", m["nome"], {}),
                                         ("sopr", "Soprannome ufficiale", m.get("soprannome") or "", {})],
                  ok, h=0.55)

    def f_caratteristiche(self, elemento, per):
        campi = fm.campi_per(self.db, per)
        if not campi:
            self.msg("Nessuna caratteristica definita (si creano dalla versione testuale: "
                     "Pannello admin > Caratteristiche dei profili).")
            return

        def ok(v):
            prof = elemento.setdefault("profilo", {})
            for c in campi:
                s = v[str(c["id"])]
                if not s:
                    continue
                if s == "-":
                    prof.pop(str(c["id"]), None)
                elif c["tipo"] == "numero":
                    n = fm.parse_numero(s)
                    if n is None:
                        self.msg(f"'{c['nome']}' richiede un numero.")
                        return False
                    prof[str(c["id"])] = n
                else:
                    prof[str(c["id"])] = s
            self.salva()
            self.render()
        self.form("CARATTERISTICHE", [(str(c["id"]), c["nome"] + (" (sì/no)" if c["tipo"] == "sino" else ""),
                                       elemento.get("profilo", {}).get(str(c["id"]), ""),
                                       {"valori": ["-", "Sì", "No"]} if c["tipo"] == "sino" else {})
                                      for c in campi],
                  ok, intro="Vuoto = lascia com'è, '-' = cancella il valore.")

    def svincola(self, m):
        if not m["proprietario"]:
            self.msg("Il musicista è già libero.")
            return

        def ok():
            m["proprietario"], m["prezzo"] = None, 0
            self.salva()
            self.render()
        self.conferma(f"{m['nome']} torna libero e {m['proprietario']} recupera {m['prezzo']} crediti. "
                      f"I punti già maturati restano alla squadra.", ok)

    def elimina_musicista(self, m):
        db = self.db
        if m["proprietario"]:
            self.msg("Prima svincolalo dalla squadra.")
            return
        if any(e["musicista_id"] == m["id"] for e in db["eventi"]):
            self.msg("Ha eventi registrati: eliminali prima oppure lascialo in elenco.")
            return

        def ok():
            db["musicisti"].remove(m)
            elimina_foto(m.get("foto"))
            for u in db["utenti"]:
                fm.prefs(u)["soprannomi_musicisti"].pop(str(m["id"]), None)
            sp_ = fm.riempi_buco(db, "musicisti", "musicista", m["id"])
            if sp_:
                for u in db["utenti"]:
                    sopr = fm.prefs(u)["soprannomi_musicisti"]
                    if str(sp_[0]) in sopr:
                        sopr[str(sp_[1])] = sopr.pop(str(sp_[0]))
                for e in db["eventi"]:
                    if e["musicista_id"] == sp_[0]:
                        e["musicista_id"] = sp_[1]
                for x in db["scambi"]:
                    x["offro"] = [sp_[1] if i == sp_[0] else i for i in x["offro"]]
                    x["chiedo"] = [sp_[1] if i == sp_[0] else i for i in x["chiedo"]]
            self.salva()
            self.indietro()
        self.conferma(f"Rimuovere {m['nome']}?", ok)

    # ---------- mercato ----------
    def v_mercato(self):
        db, me = self.db, self.me
        fatti = fm.scambi_fatti(db, me["nome"])
        massimo = db["impostazioni"].get("scambi_max", fm.SCAMBI_PREDEFINITI)
        aperto = self.g.mercato_aperto()
        self.titolo("MERCATO")
        sv, g = scroll_list(10)
        g.add_widget(L(f"Mercato {'APERTO' if aperto else 'CHIUSO'} - i tuoi scambi: {fatti}/{massimo}",
                       wrap=True, colore="accent2"))
        n_prop = sum(1 for p in db["scambi"] if p["stato"] == "proposto"
                     and (self.e_admin() or me["nome"] in (p["da"], p["a"])))
        g.add_widget(NBtn("NUOVA PROPOSTA (SCAMBIO O VENDITA)", height=dp(60), on_release=lambda *_: self.f_nuova_proposta()))
        g.add_widget(NBtn(f"PROPOSTE IN SOSPESO ({n_prop})", height=dp(60), on_release=lambda *_: self.vai(self.v_proposte)))
        g.add_widget(NBtn("STORICO SCAMBI", height=dp(60), on_release=lambda *_: self.vai(self.v_storico_scambi)))
        self.corpo.add_widget(sv)

    def testo_scambio(self, p, dopo):
        r = [f"{p['da']} cede: {', '.join(p['nomi_offro']) or 'nessun musicista'}",
             f"{p['a']} cede: {', '.join(p['nomi_chiedo']) or 'nessun musicista'}"]
        if p["crediti"] > 0:
            r.append(f"Conguaglio: {p['da']} paga {p['crediti']} crediti a {p['a']}")
        elif p["crediti"] < 0:
            r.append(f"Conguaglio: {p['a']} paga {-p['crediti']} crediti a {p['da']}")
        else:
            r.append("Nessun conguaglio (ogni musicista porta con sé il suo prezzo d'asta)")
        for nome, (n, cr) in (dopo or {}).items():
            r.append(f"Dopo lo scambio {nome}: {n} musicisti, {cr} crediti")
        return "\n".join(r)

    def f_nuova_proposta(self):
        db, me = self.db, self.me
        if not self.g.mercato_aperto():
            self.msg("Il mercato è chiuso.")
            return
        if not me["gioca"]:
            self.msg("Solo chi partecipa alla classifica può fare scambi.")
            return
        altri = [u["nome"] for u in fm.giocatori(db) if u is not me]
        if not altri:
            self.msg("Non ci sono altri giocatori.")
            return
        stato = {"offro": set(), "chiedo": set()}
        sp_ = spinner(altri[0], altri)
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(L("Con chi vuoi fare lo scambio?", dim=12, colore="accent2", size_hint_y=None, height=dp(20)))
        box.add_widget(sp_)
        colonne = BoxLayout(spacing=dp(8))
        liste = {}
        for chiave, titolo in (("offro", "CEDI (i tuoi)"), ("chiedo", "RICEVI")):
            c = BoxLayout(orientation="vertical")
            c.add_widget(L(titolo, dim=12, colore="accent2", size_hint_y=None, height=dp(22)))
            sv, gr = scroll_list(4)
            c.add_widget(sv)
            colonne.add_widget(c)
            liste[chiave] = gr
        box.add_widget(colonne)

        def riempi(chiave, musicisti):
            gr = liste[chiave]
            gr.clear_widgets()
            stato[chiave].clear()
            for m in musicisti:
                r = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
                cb = CheckBox(size_hint_x=None, width=dp(34), color=(*col("accent"), 1))
                cb.bind(active=lambda w, v, i=m["id"], k=chiave: stato[k].add(i) if v else stato[k].discard(i))
                r.add_widget(cb)
                avatar_nella_riga(r, m.get("foto"), m["nome"], 32, sposta=dp(34) + dp(6))
                r.add_widget(L(f"{m['nome']} ({m['prezzo']})", dim=11, shorten=True))
                gr.add_widget(r)
        riempi("offro", fm.rosa(db, me["nome"]))
        riempi("chiedo", fm.rosa(db, sp_.text))
        sp_.bind(text=lambda *_: riempi("chiedo", fm.rosa(db, sp_.text)))
        box.add_widget(L("Conguaglio: crediti che TU paghi oltre ai prezzi (negativo = li ricevi)", dim=11,
                         colore="accent2", size_hint_y=None, height=dp(20)))
        cong = campo("0")
        box.add_widget(cong)
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, si = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn("VERIFICA E INVIA")
        riga.add_widget(no)
        riga.add_widget(si)
        box.add_widget(riga)
        pop = self.popup("NUOVA PROPOSTA", box, 0.95, 0.92)
        no.bind(on_release=lambda *_: pop.dismiss())

        def invia(*_):
            try:
                c = int(cong.text.strip() or "0")
            except ValueError:
                self.msg("Il conguaglio deve essere un numero intero.")
                return
            offro, chiedo = sorted(stato["offro"]), sorted(stato["chiedo"])
            if not offro and not chiedo:
                self.msg("Seleziona almeno un musicista.")
                return

            def nomi(ids):
                return [m["nome"] for i in ids for m in db["musicisti"] if m["id"] == i]
            p = {"data": datetime.now().strftime("%Y-%m-%d %H:%M"), "da": me["nome"], "a": sp_.text,
                 "offro": offro, "chiedo": chiedo, "nomi_offro": nomi(offro), "nomi_chiedo": nomi(chiedo),
                 "crediti": c, "stato": "proposto"}
            errore, dopo = fm.simula_scambio(db, p)
            testo = self.testo_scambio(p, dopo)
            if errore:
                self.msg(testo + f"\n\nNon fattibile ora: {errore}")
                return

            def conferma():
                p["id"] = fm.prossimo_id(db, "scambio")
                db["scambi"].append(p)
                self.salva()
                pop.dismiss()
                self.msg(f"Proposta {p['id']} inviata a {p['a']}.")
                self.render()
            self.conferma(testo, conferma, "INVIARE LA PROPOSTA?", "INVIA")
        si.bind(on_release=invia)

    def colonne_scambio(self, g, lista, azione=True):
        if not lista:
            g.add_widget(L("Nessuno scambio.", wrap=True))
        for p in lista:
            u = fm.utente(self.db, p["da"])
            cr = f" | conguaglio {p['crediti']:+d}" if p["crediti"] else ""
            g.add_widget(self.riga(u.get("foto") if u else None, p["da"],
                                   f"#{p['id']} {p['da']} -> {p['a']}",
                                   f"cede {', '.join(p['nomi_offro']) or '-'} | riceve "
                                   f"{', '.join(p['nomi_chiedo']) or '-'}{cr}",
                                   "" if azione else p["stato"].upper(),
                                   (lambda p=p: self.f_proposta(p)) if azione else None, h=70))

    def v_proposte(self):
        me = self.me
        self.titolo("PROPOSTE IN SOSPESO")
        sv, g = scroll_list()
        aperte = [p for p in self.db["scambi"] if p["stato"] == "proposto"
                  and (self.e_admin() or me["nome"] in (p["da"], p["a"]))]
        self.colonne_scambio(g, aperte)
        self.corpo.add_widget(sv)

    def v_storico_scambi(self):
        self.titolo("STORICO SCAMBI")
        sv, g = scroll_list()
        self.colonne_scambio(g, [p for p in self.db["scambi"] if p["stato"] != "proposto"], azione=False)
        self.corpo.add_widget(sv)

    def f_proposta(self, p):
        db, me = self.db, self.me
        errore, dopo = fm.simula_scambio(db, p)
        testo = self.testo_scambio(p, dopo) + (f"\n\nNon fattibile ora: {errore}" if errore else "")
        sono_dest = self.e_admin() or me["nome"] == p["a"]
        sono_prop = self.e_admin() or me["nome"] == p["da"]
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L(testo, wrap=True))
        box.add_widget(sv)
        pop = self.popup(f"PROPOSTA #{p['id']}", box, 0.9, 0.7)
        now = lambda: datetime.now().strftime("%Y-%m-%d %H:%M")

        def chiudi_con(fn):
            def f(*_):
                fn()
                self.salva()
                pop.dismiss()
                self.render()
            return f

        def accetta():
            if not self.g.mercato_aperto():
                self.msg("Il mercato è chiuso.")
            elif errore:
                self.msg(f"Non fattibile ora: {errore}")
            else:
                fm.esegui_scambio(db, p)
                self.msg("Scambio completato.")

        def rifiuta():
            p["stato"], p["data_esito"] = "rifiutato", now()

        def annulla():
            p["stato"], p["data_esito"] = "annullato", now()
        if sono_dest:
            box.add_widget(NBtn("ACCETTA", on_release=chiudi_con(accetta)))
            box.add_widget(NBtn("RIFIUTA", on_release=chiudi_con(rifiuta)))
        if sono_prop:
            box.add_widget(NBtn("ANNULLA LA PROPOSTA", on_release=chiudi_con(annulla)))
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))

    # ---------- aspetto e preferenze ----------
    def set_aspetto(self, **kw):
        a = self.asp()
        a.update(kw)
        self.cfg.update(tema=a["tema"], scanlines=a["scanlines"], scala=a["scala"])
        scrivi_cfg(self.cfg)
        self.salva()
        self.imposta_tema(a["tema"], a["scanlines"], a["scala"])
        self.ricostruisci()
        self.render()

    def v_aspetto(self):
        me = self.me
        p = fm.prefs(me)
        a = self.asp()
        self.titolo("ASPETTO E PREFERENZE")
        sv, g = scroll_list(8)
        self.sezione(g, "TEMA COLORE (sfondo sfumato)")
        riga = BoxLayout(size_hint_y=None, height=dp(60), spacing=dp(8))
        for k, t in TEMI.items():
            riga.add_widget(NBtn(("● " if k == a["tema"] else "") + t["nome"], dim=12, height=dp(60),
                                 colore=t["accent"], on_release=lambda *_, k=k: self.set_aspetto(tema=k)))
        g.add_widget(riga)
        self.sezione(g, "EFFETTO CRT")
        g.add_widget(NBtn(f"SCANLINE: {'ACCESE' if a['scanlines'] else 'SPENTE'}  (tocca per cambiare)",
                          dim=12, on_release=lambda *_: self.set_aspetto(scanlines=not a["scanlines"])))
        self.sezione(g, "DIMENSIONE DEL TESTO")
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        for nome, v in SCALE.items():
            riga.add_widget(NBtn(("● " if abs(a["scala"] - v) < 0.01 else "") + nome, dim=12,
                                 on_release=lambda *_, v=v: self.set_aspetto(scala=v)))
        g.add_widget(riga)
        self.sezione(g, "LA MIA FOTO")
        top = Panel(size_hint_y=None, height=dp(100), padding=dp(8), spacing=dp(10))
        top.add_widget(ancora(Avatar(me.get("foto"), me["nome"], dim=80)))
        col_ = BoxLayout(orientation="vertical", spacing=dp(6))
        col_.add_widget(NBtn("CAMBIA FOTO", dim=11, height=dp(38), on_release=lambda *_: self.cambia_foto(me, "g")))
        col_.add_widget(NBtn("TOGLI FOTO", dim=11, height=dp(38), colore=attenua(col("accent"), 0.7),
                             on_release=lambda *_: self.togli_foto(me)))
        top.add_widget(col_)
        g.add_widget(top)
        self.sezione(g, "PREFERENZE PERSONALI")
        g.add_widget(NBtn(f"SOPRANNOME: {p['soprannome'] or '-'}", dim=12, on_release=lambda *_: self.f_soprannome()))
        g.add_widget(NBtn(f"RIEPILOGO ALL'ACCESSO: {'SI' if p['riepilogo_login'] else 'NO'}", dim=12,
                          on_release=lambda *_: self.toggle_riepilogo()))
        g.add_widget(NBtn(f"EVENTI NEGLI ELENCHI: {p['righe_eventi'] or 'TUTTI'}", dim=12,
                          on_release=lambda *_: self.f_righe_eventi()))
        g.add_widget(NBtn("CAMBIA PASSWORD", dim=12, on_release=lambda *_: self.f_password()))
        g.add_widget(NBtn("IMPOSTAZIONI DELLA STAGIONE (lettura)", dim=12,
                          on_release=lambda *_: self.vai(self.v_impostazioni)))
        self.corpo.add_widget(sv)

    def toggle_riepilogo(self):
        p = fm.prefs(self.me)
        p["riepilogo_login"] = not p["riepilogo_login"]
        self.salva()
        self.render()

    def f_soprannome(self):
        p = fm.prefs(self.me)

        def ok(v):
            p["soprannome"] = v["s"][:20] if v["s"] != "-" else ""
            self.salva()
            self.render()
        self.form("SOPRANNOME", [("s", "Soprannome (max 20, '-' per toglierlo)", p["soprannome"], {})], ok, h=0.45)

    def f_righe_eventi(self):
        p = fm.prefs(self.me)

        def ok(v):
            if not v["n"].isdigit():
                self.msg("Inserisci un numero intero (0 = tutti).")
                return False
            p["righe_eventi"] = int(v["n"])
            self.salva()
            self.render()
        self.form("EVENTI MOSTRATI", [("n", "Quanti eventi mostrare (0 = tutti)", p["righe_eventi"], {})], ok, h=0.45)

    def f_password(self):
        def ok(v):
            if not fm.verifica_password(self.me, v["old"]):
                self.msg("Password attuale errata.")
                return False
            if len(v["p1"]) < 4 or v["p1"] != v["p2"]:
                self.msg("La nuova password deve avere almeno 4 caratteri e coincidere nei due campi.")
                return False
            self.me["salt"], self.me["hash"] = fm.hash_password(v["p1"])
            self.salva()
            self.msg("Password aggiornata.")
        self.form("CAMBIA PASSWORD", [("old", "Password attuale", "", {"password": True}),
                                      ("p1", "Nuova password", "", {"password": True}),
                                      ("p2", "Ripeti nuova password", "", {"password": True})], ok, h=0.65)

    def v_impostazioni(self):
        s = self.db["impostazioni"]
        self.titolo("IMPOSTAZIONI STAGIONE")
        sv, g = scroll_list()
        for t, v in (("Nome stagione", s["stagione"]), ("Musicisti per squadra", s["musicisti_per_squadra"]),
                     ("Budget iniziale (crediti)", s["budget_iniziale"]), ("Rilancio minimo all'asta", s["rilancio_minimo"]),
                     ("Mercato", "aperto" if s.get("mercato_aperto", True) else "chiuso"),
                     ("Scambi a testa per stagione", s.get("scambi_max", fm.SCAMBI_PREDEFINITI))):
            r = Panel(size_hint_y=None, height=dp(44), padding=dp(10))
            r.add_widget(L(t))
            r.add_widget(L(str(v), colore="accent2", halign="right", bold=True))
            g.add_widget(r)
        if self.e_admin():
            g.add_widget(NBtn("MODIFICA (ADMIN)", on_release=lambda *_: self.f_impostazioni()))
        self.corpo.add_widget(sv)

    @property
    def _solo_admin(self):
        if not self.e_admin():
            self.msg("Permesso negato: serve il ruolo admin.")
            return False
        return True

    def f_impostazioni(self):
        if not self._solo_admin:
            return
        db = self.db
        s = db["impostazioni"]

        def ok(v):
            for k in ("n", "b", "r", "x"):
                if not v[k].isdigit():
                    self.msg("I valori numerici devono essere interi.")
                    return False
            n, b, r, x = int(v["n"]), int(v["b"]), int(v["r"]), int(v["x"])
            if n < 1 or b < 1 or r < 1:
                self.msg("Musicisti, budget e rilancio devono essere almeno 1.")
                return False
            troppi = [u["nome"] for u in db["utenti"] if len(fm.rosa(db, u["nome"])) > n]
            oltre = [u["nome"] for u in db["utenti"] if fm.speso(db, u["nome"]) - u.get("saldo", 0) > b]
            if troppi:
                self.msg("Queste squadre hanno già più musicisti: " + ", ".join(troppi))
                return False
            if oltre:
                self.msg("Hanno già speso di più del nuovo budget: " + ", ".join(oltre))
                return False
            if n > b:
                self.msg("Serve almeno 1 credito di budget per ogni posto in squadra.")
                return False
            if v["nome"]:
                s["stagione"] = v["nome"]
            s["musicisti_per_squadra"], s["budget_iniziale"], s["rilancio_minimo"], s["scambi_max"] = n, b, r, x
            self.salva()
            self.render()
        self.form("IMPOSTAZIONI STAGIONE", [
            ("nome", "Nome stagione", s["stagione"], {}),
            ("n", "Musicisti per squadra", s["musicisti_per_squadra"], {}),
            ("b", "Budget iniziale", s["budget_iniziale"], {}),
            ("r", "Rilancio minimo", s["rilancio_minimo"], {}),
            ("x", "Scambi a testa per stagione", s.get("scambi_max", fm.SCAMBI_PREDEFINITI), {})], ok)

    # ---------- pannello admin ----------
    def v_admin(self):
        if not self._solo_admin:
            return self.indietro()
        self.titolo("PANNELLO ADMIN")
        sv, g = scroll_list(10)
        aperto = self.g.mercato_aperto()
        griglia = GridLayout(cols=2, spacing=dp(10), size_hint_y=None, row_default_height=dp(70),
                             row_force_default=True)
        griglia.bind(minimum_height=griglia.setter("height"))
        voci = [("REGISTRA EVENTO", lambda: self.f_evento(False)),
                ("DITTATURA (punteggio a mano)", lambda: self.f_evento(True)),
                ("PENDING: VOTI E COMPLETAMENTO", lambda: self.vai(self.v_pending)),
                ("ASTA MUSICISTI", lambda: self.vai(self.v_asta)),
                ("GESTIONE MUSICISTI", lambda: self.vai(self.v_gest_musicisti)),
                ("GESTIONE UTENTI", lambda: self.vai(self.v_gest_utenti)),
                ("ELIMINA UN EVENTO", lambda: self.vai(self.v_elimina_evento)),
                (f"MERCATO: {'CHIUDI' if aperto else 'APRI'}", self.toggle_mercato),
                ("IMPOSTAZIONI STAGIONE", self.f_impostazioni),
                ("GIOCO ONLINE", lambda: self.vai(self.v_online)),
                ("BACKUP E CSV", self.v_backup_popup)]
        for t, f in voci:
            griglia.add_widget(NBtn(t, dim=12, height=dp(70), on_release=lambda *_, f=f: f()))
        g.add_widget(griglia)
        self.corpo.add_widget(sv)

    def toggle_mercato(self):
        s = self.db["impostazioni"]
        s["mercato_aperto"] = not s.get("mercato_aperto", True)
        self.salva()
        self.render()

    def v_backup_popup(self):
        box = BoxLayout(orientation="vertical", spacing=dp(10), padding=dp(8))
        pop = self.popup("BACKUP E ESPORTAZIONE", box, 0.85, 0.55)

        def backup(*_):
            try:
                self.msg(f"Backup creato:\n{fm.crea_backup(self.db, 'manuale')}")
            except OSError as e:
                self.msg(f"Impossibile scrivere il backup: {e.strerror or e}")

        def csv_(*_):
            try:
                scritti = fm.esporta_csv(self.db, fm.cartella_esportazioni())
                self.msg("Creati (separatore ';', si aprono con Excel):\n" + "\n".join(map(str, scritti)))
            except OSError as e:
                self.msg(f"Impossibile scrivere i file: {e.strerror or e}")
        box.add_widget(NBtn("CREA UN BACKUP ORA", on_release=backup))
        box.add_widget(NBtn("ESPORTA CLASSIFICHE ED EVENTI IN CSV", on_release=csv_))
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))

    # ----- registrazione eventi -----
    def f_evento(self, dittatura=False):
        proposta = not self.e_admin()   # i giocatori propongono: l'evento resta in pending finché l'admin lo conferma
        if dittatura and not self._solo_admin:
            return
        db, me = self.db, self.me
        if not db["musicisti"] or not db["azioni"]:
            self.msg("Servono almeno un musicista e un'azione.")
            return
        mus = sorted(db["musicisti"], key=lambda m: m["id"])
        etichette = [f"{m['id']} - {m['nome']}" for m in mus]
        az_et = [f"{a['id']} - {a['nome']}" for a in db["azioni"]]
        st = {}
        corpo = BoxLayout(spacing=dp(10), padding=dp(8))
        sinistra = BoxLayout(orientation="vertical", spacing=dp(8))
        sv, g = scroll_list(8)
        if proposta:
            g.add_widget(L("Il tuo evento resterà in pending finché l'admin non lo conferma.", wrap=True,
                           dim=11, colore="accent2"))
        g.add_widget(L("Azione", dim=12, colore="accent2", size_hint_y=None, height=dp(20)))
        sp_az = spinner(az_et[0], az_et)
        g.add_widget(sp_az)
        dyn = GridLayout(cols=1, spacing=dp(8), size_hint_y=None)
        dyn.bind(minimum_height=dyn.setter("height"))
        g.add_widget(dyn)
        sinistra.add_widget(sv)
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, si = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn("PROPONI" if proposta else "REGISTRA")
        riga.add_widget(no)
        riga.add_widget(si)
        sinistra.add_widget(riga)

        # elenco musicisti a destra: un tocco aggiunge «Nome:» al campo degli altri coinvolti
        destra = BoxLayout(orientation="vertical", size_hint_x=0.42, spacing=dp(4))
        destra.add_widget(L("MUSICISTI: tocca per aggiungerlo agli altri coinvolti", dim=11, colore="accent2",
                            size_hint_y=None, height=dp(34), halign="left"))
        svd, gd = scroll_list(4)

        def aggiungi_altro(nome):
            w = st.get("altri")
            if w is None:
                return
            base = w.text.strip().rstrip(",").strip()
            w.text = (base + ", " if base else "") + f"{nome}:"
            w.focus = True
            w.cursor = (len(w.text), 0)
        for m in mus:
            r = RowBtn(size_hint_y=None, height=dp(44), padding=dp(4), spacing=dp(6))
            avatar_nella_riga(r, m.get("foto"), m["nome"], 32)
            r.add_widget(L(m["nome"], dim=12, shorten=True))
            r.bind(on_release=lambda *_, n=m["nome"]: aggiungi_altro(n))
            gd.add_widget(r)
        destra.add_widget(svd)
        corpo.add_widget(sinistra)
        corpo.add_widget(destra)
        titolo = "DITTATURA" if dittatura else ("PROPONI UN EVENTO" if proposta else "REGISTRA EVENTO")
        pop = self.popup(titolo, corpo, 0.97, 0.92)
        no.bind(on_release=lambda *_: pop.dismiss())

        def azione_corrente():
            return next(a for a in db["azioni"] if a["id"] == int(sp_az.text.split(" - ")[0]))

        def ricostruisci(*_):
            a = azione_corrente()
            dyn.clear_widgets()
            slot = fm.slot_azione(a)
            st.update(a=a, slot=slot, spin=[], val=[], qta=None, bonus=[], altri=None)
            for i, s in enumerate(slot):
                if len(slot) > 1:
                    dyn.add_widget(L(f"Ruolo «{s['ruolo']}» ({fm.descrivi_slot(a, s)})", dim=12,
                                     colore="accent", size_hint_y=None, height=dp(22)))
                else:
                    dyn.add_widget(L(f"Musicista ({fm.descrivi_slot(a, s)})", dim=12, colore="accent2",
                                     size_hint_y=None, height=dp(22)))
                sm = spinner(etichette[min(i, len(etichette) - 1)], etichette)
                dyn.add_widget(sm)
                st["spin"].append(sm)
                if dittatura:
                    w = campo(hint="punteggio finale (anche negativo)")
                elif a["modalita"] == "sondaggio":
                    w = campo(hint=(f"il tuo voto da {s['min']} a {s['max']} (facoltativo)" if proposta else
                                    f"voto da {s['min']} a {s['max']}: registrato subito (vuoto = PENDING)"))
                else:
                    w = None
                if w:
                    dyn.add_widget(w)
                st["val"].append(w)
            if a["modalita"] == "tempo" and not dittatura:
                dyn.add_widget(L(f"Quantità in {a['unita']}", dim=12, colore="accent2", size_hint_y=None,
                                 height=dp(20)))
                st["qta"] = campo(hint="es. 90 oppure 1,5")
                dyn.add_widget(st["qta"])
            dyn.add_widget(L("Altri musicisti coinvolti (facoltativo), formato NOME:punti, es. Mario Rossi:5, Anna:-2",
                             dim=11, colore="accent2", size_hint_y=None, height=dp(34)))
            st["altri"] = campo()
            dyn.add_widget(st["altri"])
            if not dittatura and a["bonus_ids"]:
                dyn.add_widget(L("Bonus/malus da applicare", dim=12, colore="accent2", size_hint_y=None, height=dp(22)))
                for i in a["bonus_ids"]:
                    b = next((x for x in db["bonus"] if x["id"] == i), None)
                    if b:
                        r = BoxLayout(size_hint_y=None, height=dp(36))
                        cb = CheckBox(size_hint_x=None, width=dp(36), color=(*col("accent"), 1))
                        r.add_widget(cb)
                        r.add_widget(L(fm.descrivi_bonus(b), dim=12))
                        dyn.add_widget(r)
                        st["bonus"].append((cb, b))
            dyn.add_widget(L("Nota (facoltativa)", dim=12, colore="accent2", size_hint_y=None, height=dp(20)))
            st["nota"] = campo()
            dyn.add_widget(st["nota"])
        sp_az.bind(text=ricostruisci)
        ricostruisci()

        def invia(*_):
            a, slot = st["a"], st["slot"]
            ids = [int(sm.text.split(" - ")[0]) for sm in st["spin"]]
            if len(set(ids)) < len(ids):
                self.msg("Ogni ruolo deve avere un musicista diverso.")
                return
            coppie = [(next(m for m in db["musicisti"] if m["id"] == i), s) for i, s in zip(ids, slot)]
            basi = []
            for (m, s), w in zip(coppie, st["val"]):
                if dittatura:
                    try:
                        p = int(w.text.strip())
                    except ValueError:
                        self.msg(f"Punteggio finale non valido per {m['nome']}.")
                        return
                    basi.append((p, "", False, []))
                elif a["modalita"] == "sondaggio":
                    if not w.text.strip():
                        basi.append((None, "", True, []))
                    else:
                        voti = fm.parse_voti(w.text, s["min"], s["max"])
                        if voti is None:
                            self.msg(f"Per {m['nome']} inserisci interi da {s['min']} a {s['max']}.")
                            return
                        b, d = fm.base_da_voti(voti)
                        basi.append((b, d, False, voti))
                elif a["modalita"] == "tempo":
                    q = fm.parse_numero(st["qta"].text.strip()) if st["qta"].text.strip() else None
                    if q is None or q <= 0:
                        self.msg("Serve una quantità maggiore di zero.")
                        return
                    basi.append((fm.arrotonda(q * s["punti"]),
                                 f"{fm.fmt_valore(q)} {a['unita']} x {s['punti']:+d}", False, []))
                else:
                    basi.append((s["punti"], "", False, []))
            txt = st["altri"].text.strip()
            for pezzo in txt.replace(";", ",").split(","):
                if not pezzo.strip():
                    continue
                nome_, _, pt = pezzo.rpartition(":")
                m = next((x for x in db["musicisti"] if x["nome"].lower() == nome_.strip().lower()), None)
                try:
                    p = int(pt.strip())
                except ValueError:
                    p = None
                if not m or p is None:
                    self.msg(f"'{pezzo.strip()}' non valido: usa NOME:punti con un musicista esistente "
                             f"(es. Mario Rossi:5).")
                    return
                if any(x["id"] == m["id"] for x, _s in coppie):
                    self.msg(f"{m['nome']} è già coinvolto.")
                    return
                coppie.append((m, None))
                basi.append((p, "" if dittatura else "punteggio libero", False, []))
            bonus = [{"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"]}
                     for cb, b in st["bonus"] if cb.active]
            nota = st["nota"].text.strip()
            gruppo = fm.prossimo_id(db, "gruppo") if len(coppie) > 1 else None
            esiti = []
            for (m, s), (base, dett, pending, voti) in zip(coppie, basi):
                ruolo = self.g.ruolo_evento(a, s)
                fascia = (s["min"], s["max"]) if s and a["modalita"] == "sondaggio" else None
                if dittatura:
                    self.g.aggiungi_evento(m, a, base, base, [], "", False, nota, dittatura=True,
                                           gruppo=gruppo, ruolo=ruolo)
                    esiti.append(f"{base:+d} a {m['nome']} (DITTATURA)")
                elif proposta:
                    e = self.g.aggiungi_evento(m, a, None, base, bonus, dett, True, nota, fascia=fascia,
                                               voti=voti, gruppo=gruppo, ruolo=ruolo)
                    # sondaggio: il voto del giocatore resta fra i voti, l'admin può aggiungerne altri e chiudere
                    e["da_approvare"], e["proposto_da"] = True, me["nome"]
                    e["proposta_base"] = None if (s and a["modalita"] == "sondaggio") else base
                    esiti.append(f"{m['nome']}: in attesa di conferma")
                else:
                    punti = None if pending else fm.calcola_punti(base, bonus)
                    self.g.aggiungi_evento(m, a, punti, base, bonus, dett, pending, nota, fascia=fascia,
                                           voti=voti, gruppo=gruppo, ruolo=ruolo)
                    esiti.append(f"{m['nome']}: " + ("PENDING" if pending else f"{punti:+d}"))
            self.salva()
            pop.dismiss()
            self.msg(("Proposta inviata: l'admin la confermerà dalla sezione Pending.\n" if proposta
                      else "Registrato:\n") + "\n".join(esiti))
            self.render()
        si.bind(on_release=invia)

    # ----- pending -----
    def v_pending(self):
        self.titolo("EVENTI IN PENDING")
        sv, g = scroll_list()
        pend = fm.eventi_pending(self.db)
        if not pend:
            g.add_widget(L("Nessun evento in pending.", wrap=True))
        for e in pend:
            m = next((x for x in self.db["musicisti"] if x["id"] == e["musicista_id"]), None)
            voti = e.get("voti", [])
            g.add_widget(self.riga(m.get("foto") if m else None, m["nome"] if m else "?",
                                   f"#{e['id']} {m['nome'] if m else '?'} - {e['azione']}",
                                   f"{e['data']} | " + (f"proposto da {e['proposto_da']}" if e.get("proposto_da") else
                                                        f"voti: {', '.join(map(str, voti)) or 'nessuno'}"),
                                   "DA CONFERMARE" if e.get("proposta_base") is not None else "PENDING",
                                   lambda e=e: self.f_pending(e)))
        self.corpo.add_widget(sv)

    def f_pending(self, e):
        db = self.db
        gruppo = [x for x in fm.eventi_pending(db) if e.get("gruppo") and x.get("gruppo") == e["gruppo"]
                  and (x.get("ruolo") or "") == (e.get("ruolo") or "")] or [e]
        tutto_gruppo = [x for x in fm.eventi_pending(db) if e.get("gruppo") and x.get("gruppo") == e["gruppo"]] or [e]
        az = next((a for a in db["azioni"] if a["id"] == e.get("azione_id")), None)
        lo, hi = (e.get("fascia") or ((az["min"], az["max"]) if az else (1, 10)))
        voti = list(e.get("voti", []))
        ha_proposta = e.get("proposta_base") is not None
        info = e["azione"]
        if e.get("da_approvare"):
            info = f"Proposto da {e.get('proposto_da', '?')}: " + info
        if ha_proposta:
            info += (f"\nPunteggio proposto: {fm.calcola_punti(e['proposta_base'], e['bonus']):+d} "
                     f"(base {e['proposta_base']})" + (f" - {e['dettaglio']}" if e.get("dettaglio") else ""))
        else:
            info += f" - voti finora: {', '.join(map(str, voti)) or 'nessuno'}" + \
                    (f" (media {fm.media_voti(voti)})" if voti else "")
        if len(tutto_gruppo) > 1:
            info += "\nL'evento vale per: " + ", ".join(fm.nome_musicista(db, x["musicista_id"]) for x in tutto_gruppo)
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, gi = scroll_list()
        gi.add_widget(L(info, wrap=True))
        box.add_widget(sv)
        inp = None
        if not ha_proposta:
            inp = campo(hint=f"voti da aggiungere ({lo}-{hi}), spazio o virgola")
            box.add_widget(inp)
        pop = self.popup(f"EVENTO #{e['id']}", box, 0.9, 0.85)

        def applica(chiudi, azzera=False):
            if azzera:
                for x in gruppo:
                    x["voti"], x["dettaglio"] = [], ""
                self.finito(pop)
                return
            tot = list(voti)
            if inp is not None and inp.text.strip():
                nuovi = fm.parse_voti(inp.text, lo, hi)
                if nuovi is None:
                    self.msg(f"Inserisci interi da {lo} a {hi}.")
                    return
                tot += nuovi
            if not tot:
                self.msg("Nessun voto: l'evento resta in pending.")
                return
            if chiudi:
                base, dett = fm.base_da_voti(tot)
                for x in gruppo:
                    x["voti"], x["base"], x["dettaglio"] = list(tot), base, dett
                    x["punti"] = fm.calcola_punti(base, x["bonus"])
                    x["stato"] = "ok"
                    x["da_approvare"] = False
                    x["data_completamento"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            else:
                for x in gruppo:
                    x["voti"] = list(tot)
                    x["dettaglio"] = f"voti finora: {', '.join(map(str, tot))}"
            self.finito(pop)

        def conferma():
            adesso = datetime.now().strftime("%Y-%m-%d %H:%M")
            for x in tutto_gruppo:
                if x.get("proposta_base") is not None:
                    x["base"] = x["proposta_base"]
                    x["punti"] = fm.calcola_punti(x["base"], x["bonus"])
                    x["stato"], x["da_approvare"], x["data_completamento"] = "ok", False, adesso
            self.finito(pop)

        def rifiuta():
            for x in list(tutto_gruppo):
                if x.get("da_approvare"):
                    db["eventi"].remove(x)
                    fm.riempi_buco(db, "eventi", "evento", x["id"])
            self.finito(pop)
        if ha_proposta:
            box.add_widget(NBtn("CONFERMA COME PROPOSTO", on_release=lambda *_: conferma()))
        else:
            box.add_widget(NBtn("SALVA I VOTI (RESTA IN PENDING)", on_release=lambda *_: applica(False)))
            box.add_widget(NBtn("CHIUDI L'EVENTO CON LA MEDIA", on_release=lambda *_: applica(True)))
            box.add_widget(NBtn("AZZERA I VOTI", on_release=lambda *_: applica(False, True)))
        if e.get("da_approvare"):
            box.add_widget(NBtn("RIFIUTA ED ELIMINA", colore=attenua(col("accent"), 0.7),
                                on_release=lambda *_: rifiuta()))
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))

    def finito(self, pop):
        self.salva()
        pop.dismiss()
        self.render()

    # ----- elimina evento -----
    def v_elimina_evento(self):
        self.titolo("ELIMINA UN EVENTO")
        sv, g = scroll_list()
        db = self.db
        ev = fm.eventi_recenti(db, 0)
        if not ev:
            g.add_widget(L("Nessun evento registrato.", wrap=True))
        for e in ev:
            m = next((x for x in db["musicisti"] if x["id"] == e["musicista_id"]), None)
            pts = "PENDING" if e.get("stato") == "pending" else fmt_pt(e["punti"])
            g.add_widget(self.riga(m.get("foto") if m else None, m["nome"] if m else "?",
                                   f"#{e['id']} {m['nome'] if m else '?'} - {e['azione']}",
                                   f"{e['data']} | {e['proprietario'] or '-'}", pts,
                                   lambda e=e: self.elimina_evento(e)))
        self.corpo.add_widget(sv)

    def elimina_evento(self, e):
        db = self.db
        ev = db["eventi"]
        compagni = [x for x in ev if e.get("gruppo") and x.get("gruppo") == e["gruppo"] and x is not e]

        def esegui(tutti):
            for x in ([e] + compagni if tutti else [e]):
                ev.remove(x)
                fm.riempi_buco(db, "eventi", "evento", x["id"])
            self.salva()
            self.render()
        if compagni:
            box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
            box.add_widget(L(f"L'evento fa parte di un gruppo di {len(compagni) + 1}.", wrap=True))
            pop = self.popup("ELIMINA EVENTO", box, 0.85, 0.5)

            def f(tutti):
                def g_(*_):
                    pop.dismiss()
                    esegui(tutti)
                return g_
            box.add_widget(NBtn("ELIMINA SOLO QUESTO", on_release=f(False)))
            box.add_widget(NBtn("ELIMINA TUTTO IL GRUPPO", on_release=f(True)))
            box.add_widget(NBtn("ANNULLA", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))
        else:
            self.conferma(f"Eliminare l'evento #{e['id']}? I punti vengono tolti alla squadra.",
                          lambda: esegui(False))

    # ----- asta -----
    def v_asta(self, modo=None):
        if not self._solo_admin:
            return self.indietro()
        modo = modo or self.cfg.get("asta_modo", "locale")
        self.titolo("ASTA MUSICISTI")
        barra = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        for k, nome in (("locale", "ASTA LOCALE"), ("live", "ASTA LIVE ONLINE")):
            barra.add_widget(NBtn(("● " if k == modo else "") + nome, dim=12,
                                  colore=col("accent") if k == modo else attenua(col("accent"), 0.55),
                                  on_release=lambda *_, k=k: self.scegli_modo_asta(k)))
        self.corpo.add_widget(barra)
        self.corpo.add_widget(BoxLayout(size_hint_y=None, height=dp(6)))
        if modo == "live":
            self.asta_live()
        else:
            self.asta_locale()

    def scegli_modo_asta(self, k):
        self.cfg["asta_modo"] = k
        scrivi_cfg(self.cfg)
        self.sostituisci(self.v_asta, k)

    # ----- asta live online -----
    def payload_sync(self):
        db = self.db
        gio = fm.giocatori(db)
        fo.assicura_codici(db)
        self.salva()
        n_max = db["impostazioni"]["musicisti_per_squadra"]
        squadre = [{"nome": u["nome"], "crediti": fm.crediti(db, u["nome"]),
                    "posti": n_max - len(fm.rosa(db, u["nome"]))} for u in gio]
        musicisti = [{"id": m["id"], "nome": m["nome"], "soprannome": m.get("soprannome") or "",
                      "proprietario": m["proprietario"], "prezzo": m["prezzo"]} for m in db["musicisti"]]
        return squadre, musicisti, fo.codici(db)

    def live_stato(self, testo, errore=False):
        st = self.live
        if st:
            st["stato"].text = testo
            st["stato"].color = (1, 0.45, 0.45, 1) if errore else (*col("accent2"), 1)

    def live_errore(self, e):
        self.live_stato(f"ERRORE: {e}", True)

    def live_sync(self, mostra=True):
        st = self.live
        if not st:
            return
        if self.onl and self.onl_stadio == "attivo":
            # col gioco online squadre, crediti e codici dell'asta si aggiornano da soli a ogni modifica:
            # basta pubblicare le eventuali modifiche fatte da qui
            self.onl_sporco = True
            self.online_tick()
            self.live_stato("Squadre e musicisti dell'asta seguono i dati online")
            if mostra:
                self.msg("Col gioco online squadre, crediti e codici dell'asta si aggiornano da soli.")
            self.live_poll()
            return
        sq, mu, co = self.payload_sync()
        c = st["c"]

        def ok(r):
            if self.live is not st:
                return
            if r and r.get("ok") is False:
                self.live_stato(f"Sincronizzazione fallita: {r.get('errore')}", True)
                if mostra:
                    self.msg(f"Sincronizzazione fallita: {r.get('errore')}")
                return
            self.live_stato("Sincronizzato con Supabase")
            if mostra:
                self.msg("Giocatori, crediti e musicisti sincronizzati.")
            self.live_poll()
        in_thread(lambda: sb_rpc(c, "asta_a_sync", p_admin=c["admin_code"], p_squadre=sq, p_musicisti=mu,
                                 p_codici=co), ok, self.live_errore)

    def asta_live(self):
        c = leggi_online()
        if not c:
            self.corpo.add_widget(L("Manca il file di configurazione fantamusica_online.json accanto ai dati "
                                    "(servono url, anon_key e admin_code).", wrap=True))
            return
        db = self.db
        st = self.live = {"c": c, "busy": False}
        cont = BoxLayout(orientation="vertical", spacing=dp(6))
        self.corpo.add_widget(cont)
        st["stato"] = L("Connessione in corso...", dim=11, colore="accent2", size_hint_y=None, height=dp(20))
        cont.add_widget(st["stato"])
        voci = [("SINCRONIZZA", lambda: self.live_sync(True)), ("CODICI GIOCATORI", self.f_codici),
                ("AGGIUDICA", self.live_aggiudica), ("ANNULLA ASTA", self.live_annulla),
                ("MESSAGGIO", self.f_messaggio_live), ("POCO TEMPO", lambda: self.live_invia("Poco tempo!")),
                ("ULTIMA CHIAMATA", lambda: self.live_invia("Ultima chiamata!")),
                ("CONTO 5", lambda: self.live_conto(5)), ("CONTO 10", lambda: self.live_conto(10))]
        # 3 pulsanti per riga (testo a capo): stanno anche in una finestra stretta; la parte fissa e' compatta
        gb = GridLayout(cols=3, spacing=dp(5), size_hint_y=None, row_default_height=dp(38), row_force_default=True)
        gb.bind(minimum_height=gb.setter("height"))
        for t, f in voci:
            gb.add_widget(NBtn(t, dim=9, height=dp(38), on_release=lambda *_, f=f: f()))
        cont.add_widget(gb)
        pan = Panel(orientation="vertical", size_hint_y=None, height=dp(62), padding=dp(6), spacing=dp(2))
        st["titolo"] = L("Nessuna asta aperta", dim=15, colore="accent", bold=True, shorten=True)
        st["dettaglio"] = L("", dim=11, colore="accent2", shorten=True)
        pan.add_widget(st["titolo"])
        pan.add_widget(st["dettaglio"])
        cont.add_widget(pan)
        cols = BoxLayout(size_hint_y=None, height=dp(120), spacing=dp(5))
        for chiave, tit in (("off", "OFFERTE"), ("msg", "MESSAGGI"), ("on", "SQUADRE")):
            b = BoxLayout(orientation="vertical")
            b.add_widget(L(tit, dim=9, colore="accent2", size_hint_y=None, height=dp(18)))
            sv_, gr = scroll_list(2)
            b.add_widget(sv_)
            cols.add_widget(b)
            st[chiave] = gr
        cont.add_widget(cols)
        cont.add_widget(L("MUSICISTI DISPONIBILI (tocca per metterli in asta)", dim=10, colore="accent2",
                          size_hint_y=None, height=dp(20)))
        sv, gr = scroll_list()
        liberi = [m for m in db["musicisti"] if not m["proprietario"]]
        if not liberi:
            gr.add_widget(L("Nessun musicista disponibile.", wrap=True))
        for m in liberi:
            gr.add_widget(self.riga(m.get("foto"), m["nome"], m["nome"], "base 1 credito", "",
                                    lambda m=m: self.live_apri(m), h=54))
        cont.add_widget(sv)      # l'unico elemento che scorre
        self.live_sync(False)
        self._poll = Clock.schedule_interval(self.live_poll, 2)

    def live_poll(self, *_):
        st = self.live
        if not st or st["busy"]:
            return
        st["busy"] = True
        c = st["c"]

        def lavoro():
            corr = (sb_leggi(c, "asta_corrente", "select=*&id=eq.1") or [{}])[0]
            off = sb_leggi(c, "asta_offerte", f"select=*&musicista_id=eq.{corr['musicista_id']}&order=id.desc&limit=20") \
                if corr.get("musicista_id") is not None else []
            msgs = sb_leggi(c, "asta_messaggi", "select=*&order=id.desc&limit=15")
            sq = sb_leggi(c, "asta_squadre", "select=nome,crediti,posti,visto&order=nome")
            return corr, off, msgs, sq

        def ok(dati):
            st["busy"] = False
            self.live_applica(st, dati)

        def err(e):
            st["busy"] = False
            if self.live is st:
                self.live_errore(e)
        in_thread(lavoro, ok, err)

    def live_applica(self, st, dati):
        if self.live is not st:
            return
        corr, off, msgs, sq = dati
        st["corr"] = corr
        if corr.get("aperta"):
            st["titolo"].text = f"IN ASTA: {corr.get('musicista')}"
            if corr.get("miglior_importo") is not None:
                st["dettaglio"].text = (f"Miglior offerta: {corr['miglior_importo']} di {corr['miglior_offerente']} "
                                        f"(rilancio min {corr['rilancio_min']})")
            else:
                st["dettaglio"].text = f"Nessuna offerta (base 1, rilancio min {corr['rilancio_min']})"
        else:
            st["titolo"].text = "Nessuna asta aperta"
            st["dettaglio"].text = ""
        self.live_stato("Connesso - aggiornato " + datetime.now().strftime("%H:%M:%S"))

        def voce(g, testo, colore="testo"):
            g.add_widget(L(testo, dim=11, colore=colore, size_hint_y=None, height=dp(22), shorten=True))
        for chiave in ("off", "msg", "on"):
            st[chiave].clear_widgets()
        if not off:
            voce(st["off"], "nessuna offerta")
        for o in off:
            voce(st["off"], f"{o['giocatore']}: {o['importo']}", "accent2" if o is off[0] else "testo")
        for m in msgs:
            st["msg"].add_widget(L(m["testo"], dim=11, wrap=True))
        for t in sq:
            voce(st["on"], ("● " if e_collegato(t.get("visto")) else "○ ") + f"{t['nome']} ({t['crediti']} cr.)",
                 "accent" if e_collegato(t.get("visto")) else "testo")
        self.online_ritmo(1 if sum(1 for t in sq if e_collegato(t.get("visto"))) >= 2 else 4)

    def live_chiamata(self, rpc, ok, **par):
        st = self.live
        if not st:
            return
        c = st["c"]
        in_thread(lambda: sb_rpc(c, rpc, p_admin=c["admin_code"], **par), ok, self.live_errore)

    def live_invia(self, testo):
        def ok(r):
            if r and r.get("ok") is False:
                self.live_stato(r.get("errore", "Errore"), True)
            self.live_poll()
        self.live_chiamata("asta_a_messaggio", ok, p_testo=testo)

    def f_messaggio_live(self):
        def ok(v):
            if not v["t"]:
                return False
            self.live_invia(v["t"])
        self.form("MESSAGGIO NEL CANALE DELL'ASTA", [("t", "Testo (max 300 caratteri)", "", {})], ok, h=0.45)

    def live_conto(self, n):
        if self._conto_ev:
            self._conto_ev.cancel()
            self._conto_ev = None
        cnt = {"n": n}

        def tick(dt):
            if not self.live:
                return False
            self.live_invia(str(cnt["n"]))
            cnt["n"] -= 1
            return cnt["n"] > 0
        if tick(0):
            self._conto_ev = Clock.schedule_interval(tick, 1)

    def live_apri(self, m):
        rl = self.db["impostazioni"]["rilancio_minimo"]

        def esito(r):
            if r and r.get("ok") is False:
                self.msg(r.get("errore", "Errore"))
            self.live_poll()

        def vai():
            self.live_chiamata("asta_a_apri", esito, p_musicista_id=m["id"], p_rilancio=rl)
        self.conferma(f"Mettere in asta {m['nome']}? Rilancio minimo {rl}.", vai, "APRI ASTA", "APRI")

    def live_aggiudica(self):
        st = self.live
        corr = (st or {}).get("corr") or {}
        if not corr.get("aperta"):
            self.msg("Nessuna asta aperta.")
            return
        if corr.get("miglior_importo") is None:
            self.msg("Nessuna offerta: aspetta un rilancio oppure usa ANNULLA ASTA.")
            return
        db = self.db

        def esito(r):
            if not r or not r.get("ok"):
                self.msg((r or {}).get("errore", "Errore"))
                return
            m = next((x for x in db["musicisti"] if x["id"] == r["musicista_id"]), None)
            u = fm.utente(db, r["giocatore"])
            if m and u and m["proprietario"] == u["nome"] and m["prezzo"] == int(r["importo"]):
                # online l'aggiudicazione e' gia' nei dati del gioco (e questo computer li ha gia' scaricati)
                self.msg(f"AGGIUDICATO: {m['nome']} a {u['nome']} per {r['importo']} crediti.")
                self.sostituisci(self.v_asta, "live")
                return
            if not m or not u or m["proprietario"]:
                self.msg("Aggiudicato online, ma non applicabile ai dati locali (musicista o giocatore non "
                         "trovato, oppure già assegnato). Controlla e premi SINCRONIZZA.")
                return
            m["proprietario"], m["prezzo"] = u["nome"], int(r["importo"])
            self.salva()
            self.msg(f"AGGIUDICATO: {m['nome']} a {u['nome']} per {r['importo']} crediti.")
            self.sostituisci(self.v_asta, "live")

        def vai():
            self.live_chiamata("asta_a_aggiudica", esito)
        self.conferma(f"Aggiudicare {corr['musicista']} a {corr['miglior_offerente']} per "
                      f"{corr['miglior_importo']} crediti?", vai, "AGGIUDICA", "AGGIUDICA")

    def live_annulla(self):
        corr = (self.live or {}).get("corr") or {}
        if not corr.get("aperta"):
            self.msg("Nessuna asta aperta.")
            return

        def esito(r):
            if r and r.get("ok") is False:
                self.msg(r.get("errore", "Errore"))
            self.live_poll()

        def vai():
            self.live_chiamata("asta_a_annulla", esito)
        self.conferma(f"Annullare l'asta di {corr['musicista']}? Le offerte vengono cancellate.", vai,
                      "ANNULLA ASTA", "ANNULLA ASTA")

    def f_codici(self):
        db = self.db
        c = leggi_online() or {}
        fo.assicura_codici(db)
        self.salva()
        testo = "\n".join(f"{u['nome']}: {u['codice_asta']}" for u in db["utenti"]) or "Nessun utente."
        web = c.get("web_url") or "(scrivi l'indirizzo della pagina web in web_url dentro fantamusica_online.json)"
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L("Pagina dei giocatori: " + web, wrap=True, colore="accent2", dim=12))
        g.add_widget(L(testo, wrap=True))
        box.add_widget(sv)
        pop = self.popup("CODICI DEI GIOCATORI", box, 0.9, 0.8)

        def copia(*_):
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(f"{web}\n{testo}")
            except Exception:
                self.msg("Copia non disponibile su questo sistema.")

        def rigenera(*_):
            def ok():
                for u in db["utenti"]:
                    u["codice_asta"] = None
                fo.assicura_codici(db)
                self.salva()
                pop.dismiss()
                if self.live:
                    self.live_sync(True)
            self.conferma("Rigenerare tutti i codici? I vecchi smettono di funzionare e vanno ridati ai giocatori.", ok)
        box.add_widget(NBtn("COPIA TUTTO", dim=12, on_release=copia))
        box.add_widget(NBtn("RIGENERA I CODICI", dim=12, on_release=rigenera))
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))

    def asta_locale(self):
        db = self.db
        sv, g = scroll_list()
        liberi = [m for m in db["musicisti"] if not m["proprietario"]]
        n_max = db["impostazioni"]["musicisti_per_squadra"]
        self.sezione(g, "CREDITI E POSTI LIBERI")
        for u in fm.giocatori(db):
            g.add_widget(self.riga(u.get("foto"), u["nome"], u["nome"],
                                   f"posti liberi {n_max - len(fm.rosa(db, u['nome']))}", fm.crediti(db, u["nome"]),
                                   h=52))
        self.sezione(g, "MUSICISTI DISPONIBILI (tocca per aggiudicare)")
        if not liberi:
            g.add_widget(L("Nessun musicista disponibile all'asta.", wrap=True))
        for m in liberi:
            g.add_widget(self.riga(m.get("foto"), m["nome"], m["nome"], "base 1 credito", "",
                                   lambda m=m: self.f_aggiudica(m)))
        self.corpo.add_widget(sv)

    def f_aggiudica(self, m):
        db = self.db
        s = db["impostazioni"]
        n_max = s["musicisti_per_squadra"]
        gio = [u["nome"] for u in fm.giocatori(db)]
        if not gio:
            self.msg("Non ci sono giocatori.")
            return
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(L(f"AGGIUDICA {m['nome']} (base 1 credito, rilancio minimo {s['rilancio_minimo']})",
                         wrap=True, colore="accent2"))
        sp_ = spinner(gio[0], gio)
        box.add_widget(sp_)
        imp = campo(hint="importo finale in crediti")
        box.add_widget(imp)
        box.add_widget(BoxLayout())
        riga = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        no, si = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7)), NBtn("AGGIUDICA")
        riga.add_widget(no)
        riga.add_widget(si)
        box.add_widget(riga)
        pop = self.popup("ASTA", box, 0.9, 0.55)
        no.bind(on_release=lambda *_: pop.dismiss())

        def ok(*_):
            if not imp.text.strip().isdigit():
                self.msg("Inserisci un importo intero.")
                return
            importo = int(imp.text.strip())
            nome = sp_.text
            posti = n_max - len(fm.rosa(db, nome))
            if posti <= 0:
                self.msg(f"{nome} ha già la squadra completa.")
                return
            massimo = fm.crediti(db, nome) - (posti - 1)
            if importo < 1:
                self.msg("Minimo 1 credito.")
            elif importo > massimo:
                self.msg(f"{nome} può offrire al massimo {massimo} "
                         f"(deve tenere 1 credito per ogni altro posto da riempire).")
            else:
                m["proprietario"], m["prezzo"] = nome, importo
                self.salva()
                pop.dismiss()
                self.render()
        si.bind(on_release=ok)

    # ----- gestione musicisti e utenti -----
    def v_gest_musicisti(self):
        self.titolo("GESTIONE MUSICISTI")
        sv, g = scroll_list()
        g.add_widget(NBtn("AGGIUNGI MUSICISTI", on_release=lambda *_: self.f_aggiungi_musicisti()))
        for m in sorted(self.db["musicisti"], key=lambda x: x["id"]):
            g.add_widget(self.riga(m.get("foto"), m["nome"], f"{m['id']}. {m['nome']}",
                                   m["proprietario"] or "senza squadra", "",
                                   lambda i=m["id"]: self.vai(self.v_musicista, i)))
        self.corpo.add_widget(sv)

    def f_aggiungi_musicisti(self):
        db = self.db

        def ok(v):
            nuovi = [n.strip() for n in v["nomi"].replace("\n", ";").split(";") if n.strip()]
            if not nuovi:
                return False
            aggiunti = 0
            for nome in nuovi:
                if any(m["nome"].lower() == nome.lower() for m in db["musicisti"]):
                    continue
                db["musicisti"].append({"id": fm.prossimo_id(db, "musicista"), "nome": nome, "soprannome": "",
                                        "proprietario": None, "prezzo": 0, "profilo": {}})
                aggiunti += 1
            self.salva()
            self.msg(f"Aggiunti {aggiunti} musicisti" + (f" ({len(nuovi) - aggiunti} già presenti)"
                                                         if aggiunti < len(nuovi) else "") +
                     ". La foto si imposta dal profilo di ognuno.")
            self.render()
        self.form("AGGIUNGI MUSICISTI", [("nomi", "Nomi separati da punto e virgola", "", {})], ok, h=0.45)

    def v_gest_utenti(self):
        db = self.db
        self.titolo("GESTIONE UTENTI")
        sv, g = scroll_list()
        g.add_widget(NBtn("AGGIUNGI UTENTE", on_release=lambda *_: self.f_aggiungi_utente()))
        for u in sorted(db["utenti"], key=lambda x: x["nome"].lower()):
            g.add_widget(self.riga(u.get("foto"), u["nome"], fm.etichetta_utente(db, u["nome"]),
                                   f"{u['ruolo']} | {'in classifica' if u['gioca'] else 'non gioca'}", "",
                                   lambda u=u: self.f_utente(u)))
        self.corpo.add_widget(sv)

    def f_aggiungi_utente(self):
        db = self.db

        def ok(v):
            if not v["nome"]:
                return False
            if fm.utente(db, v["nome"]):
                self.msg("Esiste già un utente con questo nome.")
                return False
            if len(v["p1"]) < 4 or v["p1"] != v["p2"]:
                self.msg("Password di almeno 4 caratteri, scritta due volte uguale.")
                return False
            ruolo = "admin" if v["adm"].lower() in ("s", "si", "sì") else "partecipante"
            fm.crea_utente(db, v["nome"], v["p1"], ruolo)
            self.salva()
            self.render()
        self.form("NUOVO UTENTE", [("nome", "Nome", "", {}),
                                   ("p1", "Password (min. 4)", "", {"password": True}),
                                   ("p2", "Ripeti password", "", {"password": True}),
                                   ("adm", "Admin? (s = sì, vuoto = no)", "", {})], ok)

    def f_utente(self, u):
        db = self.db
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        pop = self.popup(u["nome"].upper(), box, 0.85, 0.85)

        def e(fn):
            def f(*_):
                pop.dismiss()
                fn()
            return f

        def reset():
            def ok(v):
                if len(v["p1"]) < 4 or v["p1"] != v["p2"]:
                    self.msg("Password di almeno 4 caratteri, scritta due volte uguale.")
                    return False
                u["salt"], u["hash"] = fm.hash_password(v["p1"])
                self.salva()
                self.msg("Password reimpostata.")
            self.form("REIMPOSTA PASSWORD", [("p1", "Nuova password", "", {"password": True}),
                                             ("p2", "Ripeti", "", {"password": True})], ok, h=0.55)

        def n_admin():
            return sum(1 for x in db["utenti"] if x["ruolo"] == "admin")

        def ruolo():
            if u["ruolo"] == "admin":
                if n_admin() <= 1:
                    self.msg("Deve restare almeno un admin.")
                    return
                u["ruolo"] = "partecipante"
            else:
                u["ruolo"] = "admin"
            self.salva()
            self.render()

        def gioca():
            if u["gioca"] and fm.rosa(db, u["nome"]):
                self.msg("Ha musicisti in squadra: svincolali prima.")
                return
            u["gioca"] = not u["gioca"]
            self.salva()
            self.render()

        def elimina():
            if u is self.me:
                self.msg("Non puoi eliminare te stesso.")
                return
            if u["ruolo"] == "admin" and n_admin() <= 1:
                self.msg("Deve restare almeno un admin.")
                return

            def ok():
                for m in fm.rosa(db, u["nome"]):
                    m["proprietario"], m["prezzo"] = None, 0
                for ev in db["eventi"]:
                    if ev["proprietario"] == u["nome"]:
                        ev["proprietario"] = None
                for x in db["scambi"]:
                    if x["stato"] == "proposto" and u["nome"] in (x["da"], x["a"]):
                        x["stato"] = "annullato"
                elimina_foto(u.get("foto"))
                db["utenti"].remove(u)
                self.salva()
                self.render()
            self.conferma(f"Eliminare {u['nome']}? I suoi musicisti torneranno liberi.", ok)
        for t, fn in (("VEDI SQUADRA", lambda: self.vai(self.v_squadra, u["nome"])),
                      ("CAMBIA FOTO", lambda: self.cambia_foto(u, "g")),
                      ("REIMPOSTA PASSWORD", reset),
                      ("PROMUOVI / RETROCEDI ADMIN", ruolo),
                      ("PARTECIPA / NON PARTECIPA ALLA CLASSIFICA", gioca),
                      ("ELIMINA UTENTE", elimina)):
            box.add_widget(NBtn(t, dim=12, on_release=e(fn)))
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))


if __name__ == "__main__":
    FantaApp().run()
