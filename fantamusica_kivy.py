#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
FANTAMUSICA - applicazione principale (Kivy) con stile retro-neon.

La logica condivisa vive in fantamusica_core.py. L'interfaccia supportata è questa app Kivy:
la vecchia interfaccia a terminale è dismessa.

Funzioni principali
  - Foto per giocatori e musicisti (cartella "foto" accanto ai dati). Nelle liste compaiono come
    piccole miniature quadrate (max ~46 dp), nei profili al massimo 120 dp. Le foto importate
    vengono ritagliate quadrate e ridotte (se e' installato Pillow: pip install pillow).
  - Aspetto personalizzabile (menu "Aspetto e preferenze", salvato nel profilo di ogni giocatore):
    tema verde / blu / arancio fluo con sfondo sfumato, effetto CRT a scanline, dimensione del testo.
  - Interfaccia a pulsanti: classifiche, squadre, profili, mercato e scambi, eventi, pending,
    asta, gestione musicisti e utenti, backup/CSV.

Per l'admin la schermata principale raccoglie tutte le funzioni, organizzate per area:
eventi, squadre e regole, mercato/asta, stagione/dati e preferenze.

Gioco online (facoltativo): con il file fantamusica_online.json accanto ai dati, questa app sincronizza
lo stato locale con Supabase. Il gioco web continua anche quando l'app dell'admin è chiusa.

Avvio:  pip install kivy pillow   ->   python3 fantamusica_kivy.py
"""
import copy
import json
import os
import re
import secrets
import shutil
import threading
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
from kivy.uix.togglebutton import ToggleButton
from kivy.uix.widget import Widget
from kivy.utils import platform

try:
    from PIL import Image as PILImage
except ImportError:  # senza Pillow le foto vengono copiate cosi' come sono
    PILImage = None

import fantamusica_core as fm
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
GIALLO = (0.26, 0.20, 0.02)       # sfondo delle righe degli eventi con più musicisti coinvolti
EV_PAGINA = 200                   # righe per pagina negli elenchi lunghi (le righe sono widget veri)
# Le caratteristiche sono ora solo dati descrittivi del profilo. Gli stati temporanei o di gioco
# (es. Solista, Carica/Scarica, ecc.) vanno modellati come buff/debuff, non ricreati automaticamente.
CAMPI_GUI = []
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
    """Compatibilità con i salvataggi precedenti.

    Le caratteristiche descrittive vengono create dal core; Kivy non aggiunge più automaticamente
    caratteristiche che rappresentano stati di gioco, perché ora quelli sono buff/debuff.
    """
    return False


# --------------------------------------------------------------------------
# Asta live online (Supabase)
# --------------------------------------------------------------------------
ONLINE_FILE = fm.DATA_FILE.with_name("fantamusica_online.json")   # url, anon_key, web_url
ALFABETO_CODICI = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"

def leggi_online():
    try:
        with open(ONLINE_FILE, encoding="utf-8") as f:
            c = json.load(f)
    except (OSError, ValueError):
        return None
    return c if c.get("url") and c.get("anon_key") else None


def nuovo_codice():
    return "".join(secrets.choice(ALFABETO_CODICI) for _ in range(8))


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
    def __init__(self, alpha=0.78, bordo=True, sfondo=None, **kw):
        super().__init__(**kw)
        if "opaco" in DIAG:
            alpha = 1.0
        with self.canvas.before:
            self._c = Color(*(sfondo or col("panel")), alpha)
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
        if not c or self.db is None:
            return
        if self.onl is None:
            self.onl = fo.Online(c)
        if not self.onl.ha_sessione():
            self.onl_stadio, self.onl_busy = "auth", False
            self.online_msg("● ACCESSO SUPABASE RICHIESTO", True)
            if self.me:
                self.render()
            return
        self.onl_stadio, self.onl_ver, self.onl_busy = "avvio", None, False
        self.online_msg("● COLLEGO...")
        if self.me:
            self.render()
        self.online_tick()

    def f_login_supabase(self, dopo=None):
        c = leggi_online()
        if not c:
            self.msg("Serve fantamusica_online.json con url e anon_key.")
            return
        if self.onl is None:
            self.onl = fo.Online(c)
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        box.add_widget(L("Accedi con l'account amministratore Supabase Auth. La password non viene salvata.",
                         wrap=True, colore="accent2", size_hint_y=None, height=dp(54)))
        email = campo(self.onl.email(), hint="email admin Supabase")
        password = campo(hint="password Supabase", password=True)
        box.add_widget(email); box.add_widget(password)
        rr = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
        ricorda = CheckBox(active=False, size_hint=(None, None), size=(dp(36), dp(36)))
        rr.add_widget(ricorda)
        rr.add_widget(L("Ricordami su questo computer (salva solo il refresh token)", dim=11, wrap=True))
        box.add_widget(rr)
        stato = L("", dim=11, wrap=True, size_hint_y=None, height=dp(42))
        box.add_widget(stato)
        br = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        ann = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7))
        acc = NBtn("ACCEDI")
        br.add_widget(ann); br.add_widget(acc); box.add_widget(br)
        pop = self.popup("ACCESSO SUPABASE", box, 0.88, 0.72)
        ann.bind(on_release=lambda *_: pop.dismiss())

        def ok(r):
            pop.dismiss()
            self.onl_stadio, self.onl_ver, self.onl_busy = "avvio", None, False
            self.onl_ultimo_errore = ""
            self.online_msg("● COLLEGO...")
            self.online_tick()
            if dopo:
                Clock.schedule_once(lambda _dt: dopo(), 0.2)
            elif self.me:
                self.render()

        def err(e):
            stato.text = str(e)
            stato.color = (1, 0.45, 0.45, 1)
            acc.disabled = False

        def vai(*_):
            if not email.text.strip() or not password.text:
                stato.text = "Inserisci email e password."
                return
            acc.disabled = True
            stato.text = "Accesso in corso..."
            in_thread(lambda: self.onl.login(email.text, password.text, ricorda=ricorda.active), ok, err)

        password.bind(on_text_validate=vai)
        acc.bind(on_release=vai)

    def logout_supabase(self):
        if self.onl:
            self.onl.logout()
        self.onl_stadio, self.onl_ver, self.onl_busy = "auth", None, False
        self.online_msg("● ACCESSO SUPABASE RICHIESTO", True)
        if self.me:
            self.render()

    def online_errore(self, e):
        self.onl_busy = False
        self.onl_ultimo_errore = str(e)
        msg = self.onl_ultimo_errore.lower()
        if "accesso supabase admin richiesto" in msg or "sessione supabase" in msg or "401" in msg:
            self.onl_stadio = "auth"
            self.online_msg("● ACCESSO SUPABASE RICHIESTO", True)
        elif "non è autorizzato come admin" in msg or "non appartiene a un admin" in msg or "403" in msg:
            self.onl_stadio = "auth"
            self.online_msg("● ACCOUNT NON AUTORIZZATO", True)
        elif ("push rifiutato" in msg or "controllo di integrità" in msg
              or "database locale contiene incoerenze" in msg or "validazione server" in msg):
            # La rete e Supabase Auth stanno funzionando: è soltanto la pubblicazione
            # dello snapshot generale a essere stata rifiutata. Non chiamarlo OFFLINE.
            self.online_msg("● CONNESSO — SYNC BLOCCATA", True)
        else:
            self.online_msg("● OFFLINE", True)

    def online_primo(self, st):
        """Primo contatto all'avvio. Se questo computer ha la sua copia di riferimento (base) si parte da li':
        le modifiche fatte qui (anche dal gioco da terminale) vengono unite a quelle online."""
        self.onl_busy = False
        # Se fm_a_stato ha risposto, la sessione e la connessione sono valide: non lasciare
        # una vecchia scritta OFFLINE dovuta a un errore/transitorio precedente.
        self.onl_ultimo_errore = ""
        self.onl_err = False
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
                except OSError as e:
                    self.onl_busy = False
                    self.msg(f"Download annullato: non riesco a creare il backup di sicurezza ({e.strerror or e}).\n"
                             "I dati locali NON sono stati sostituiti.")
                    return
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

    def online_ritmo(self, secondi = 0.5):
        """Ritmo dei controlli: 0.5 s se nell'asta online ci sono 2+ squadre collegate, altrimenti 4 s."""
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
        # Arrivare qui significa che fm_a_stato ha risposto con successo usando il token Auth.
        # Ripulisci immediatamente un eventuale OFFLINE rimasto visualizzato da un errore vecchio.
        self.onl_ultimo_errore = ""
        if self.onl_err or self.onl_testo == "● OFFLINE":
            self.online_msg("● ONLINE")
        else:
            self.onl_err = False
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
            precedente = self.onl_ultimo_errore
            self.online_errore(e)
            testo = str(e)
            # Un push rifiutato non deve restare invisibile: avvisa una volta per errore distinto.
            if testo != precedente and ("Push rifiutato" in testo or "integrità" in testo or "Validazione server" in testo):
                Clock.schedule_once(lambda _dt, t=testo: self.msg(
                    "Supabase è collegato e autenticato, ma la sincronizzazione generale è stata rifiutata.\n\n" + t,
                    "SYNC BLOCCATA"), 0)
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
            g.add_widget(L("Manca il file fantamusica_online.json accanto ai dati: servono url, anon_key e web_url (vedi la guida).", wrap=True))
        else:
            righe = [f"Stato: {self.onl_testo or 'non collegato'}",
                     f"Account Supabase: {(self.onl.email() if self.onl and self.onl.ha_sessione() else 'non autenticato')}",
                     f"Versione online: {self.onl_ver if self.onl_ver is not None else '-'}",
                     f"Pagina dei giocatori: {c.get('web_url') or '(scrivi l’indirizzo in web_url dentro fantamusica_online.json)'}",
                     "Kivy usa Supabase Auth come il web: nessun admin_code locale. La password non viene salvata."]
            if self.onl_ultimo_errore and self.onl_err:
                righe.append(f"Ultimo errore: {self.onl_ultimo_errore}")
            for r in righe:
                g.add_widget(L(r, wrap=True, dim=13))
            def pubblica():
                if not self.onl or not self.onl.ha_sessione():
                    self.f_login_supabase(pubblica)
                    return
                if self.onl_stadio not in ("avvio", "attivo"):
                    self.onl_stadio = "avvio"
                self.onl_sporco = True
                self.online_tick()
                self.msg("Pubblicazione avviata: tra qualche secondo i giocatori vedono i dati aggiornati.")

            def scarica():
                if not self.onl or not self.onl.ha_sessione():
                    self.f_login_supabase(scarica)
                    return
                self.conferma("Scaricare i dati online? Quelli di questo computer vengono sostituiti "
                              "(prima ne viene fatto un backup).", self.online_scarica, "SCARICA DA ONLINE", "SCARICA")
            g.add_widget(NBtn("ACCEDI / CAMBIA ACCOUNT SUPABASE", dim=12, height=dp(56),
                              on_release=lambda *_: self.f_login_supabase()))
            if self.onl and self.onl.ha_sessione():
                g.add_widget(NBtn("ESCI DA SUPABASE", dim=12, height=dp(50), colore=attenua(col("accent"), 0.75),
                                  on_release=lambda *_: self.logout_supabase()))
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
    def riga(self, foto, nome, titolo, sotto="", destra="", azione=None, h=62, sfondo=None):
        p = (RowBtn if azione else Panel)(size_hint_y=None, height=dp(h), padding=dp(7), spacing=dp(10),
                                          sfondo=sfondo)
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
            if self.onl.ha_sessione():
                self.online_scarica()
            else:
                self.f_login_supabase(self.online_scarica)
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
        n_pend = len(fm.eventi_pending_visibili(db, me["ruolo"] == "admin"))
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
        admin = self.e_admin()
        self.titolo("AMMINISTRAZIONE" if admin else f"BENVENUTO {p['soprannome'] or me['nome']}".upper())
        sv, g = scroll_list(10)

        if self.righe_login:
            b = Panel(orientation="vertical", size_hint_y=None, padding=dp(10), spacing=dp(2))
            for r in self.righe_login:
                b.add_widget(L(r, wrap=True, dim=12))
            b.bind(minimum_height=b.setter("height"))
            g.add_widget(b)

        def gruppo(titolo, voci, altezza=64):
            self.sezione(g, titolo)
            griglia = GridLayout(cols=2, spacing=dp(8), size_hint_y=None,
                                 row_default_height=dp(altezza), row_force_default=True)
            griglia.bind(minimum_height=griglia.setter("height"))
            for i, (testo, fn) in enumerate(voci):
                griglia.add_widget(NBtn(
                    testo, dim=12, height=dp(altezza),
                    colore=col("accent2") if i % 4 == 1 else None,
                    on_release=lambda *_, fn=fn: fn()))
            g.add_widget(griglia)

        if admin:
            aperto = self.g.mercato_aperto()

            gruppo("GIOCO, CLASSIFICHE ED EVENTI", [
                ("CLASSIFICA", lambda: self.vai(self.v_classifica, "giocatori")),
                ("STATISTICHE", lambda: self.vai(self.v_statistiche, "azioni")),
                ("REGISTRA EVENTO", lambda: self.f_evento(False)),
                ("PENDING / CONTROLLO SONDAGGI", lambda: self.vai(self.v_pending)),
                ("DITTATURA (PUNTEGGIO A MANO)", lambda: self.f_evento(True)),
                ("ELIMINA UN EVENTO", lambda: self.vai(self.v_elimina_evento)),
            ])

            gruppo("SQUADRE, UTENTI E REGOLE", [
                ("LA MIA SQUADRA", lambda: self.vai(self.v_squadra, me["nome"])),
                ("GESTIONE UTENTI", lambda: self.vai(self.v_gest_utenti)),
                ("GESTIONE MUSICISTI", lambda: self.vai(self.v_gest_musicisti)),
                ("GESTIONE AZIONI", lambda: self.vai(self.v_gest_azioni)),
                ("BONUS E MALUS", lambda: self.vai(self.v_gest_bonus)),
                ("CARATTERISTICHE DESCRITTIVE", lambda: self.vai(self.v_gest_campi)),
            ])

            gruppo("MERCATO E ASTA", [
                ("MERCATO E SCAMBI", lambda: self.vai(self.v_mercato)),
                (f"MERCATO: {'CHIUDI' if aperto else 'APRI'}", self.toggle_mercato),
                ("ASTA MUSICISTI", lambda: self.vai(self.v_asta)),
            ])

            gruppo("STAGIONE, ONLINE E DATI", [
                ("IMPOSTAZIONI STAGIONE", self.f_impostazioni),
                ("CHIUDI STAGIONE", self.f_chiudi_stagione_gui),
                ("GIOCO ONLINE", lambda: self.vai(self.v_online)),
                ("VERIFICA INTEGRITÀ DEI DATI", self.f_verifica_integrita),
                ("AUDIT LOG AMMINISTRATIVO", lambda: self.vai(self.v_audit_log)),
                ("BACKUP / RIPRISTINO / CSV", self.v_backup_popup),
            ])

            gruppo("ACCOUNT E ASPETTO", [
                ("ASPETTO E PREFERENZE", lambda: self.vai(self.v_aspetto)),
                ("CAMBIA ACCOUNT / ESCI", self.esci_account),
            ])
        else:
            gruppo("GIOCO", [
                ("CLASSIFICA", lambda: self.vai(self.v_classifica, "giocatori")),
                ("STATISTICHE", lambda: self.vai(self.v_statistiche, "azioni")),
                ("LA MIA SQUADRA", lambda: self.vai(self.v_squadra, me["nome"])),
                ("PROPONI UN EVENTO", lambda: self.f_evento(False)),
                ("MERCATO E SCAMBI", lambda: self.vai(self.v_mercato)),
                ("ASPETTO E PREFERENZE", lambda: self.vai(self.v_aspetto)),
                ("CAMBIA ACCOUNT / ESCI", self.esci_account),
            ], altezza=72)

        self.corpo.add_widget(sv)

    # ---------- classifica ----------
    TABS = [("giocatori", "GIOCATORI"), ("musicisti", "MUSICISTI"), ("eventi", "EVENTI"),
            ("pending", "PENDING"), ("cumulativa", "CUMULATIVA"), ("storico", "STORICO")]

    def v_classifica(self, tab="giocatori"):
        self.titolo("CLASSIFICA")
        tabs = list(self.TABS)
        if self.e_admin():
            tabs.insert(4, ("auto_chiusi", "AUTO-CHIUSI"))
        if tab == "auto_chiusi" and not self.e_admin():
            tab = "eventi"
        barra = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        for k, nome in tabs:
            barra.add_widget(NBtn(nome, dim=10, height=dp(40),
                                  colore=col("accent") if k == tab else attenua(col("accent"), 0.55),
                                  on_release=lambda *_, k=k: self.apri_tab(k)))
        self.corpo.add_widget(barra)
        self.corpo.add_widget(BoxLayout(size_hint_y=None, height=dp(6)))
        sv, g = scroll_list()
        getattr(self, "tab_" + tab)(g)
        self.corpo.add_widget(sv)

    def apri_tab(self, k, nuova=False):
        """Apre una scheda della classifica; nuova=True arriva da un'altra schermata (si può tornare indietro)."""
        self.ev_pagina = 0           # cambiando scheda si riparte dalla prima pagina degli eventi
        (self.vai if nuova else self.sostituisci)(self.v_classifica, k)

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
        dati = [(m, p) for _, m, p in fm.classifica_musicisti(db)]
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
        """Elenco di eventi: una riga ciascuno, si tocca per i dettagli e il calcolo. Quelle che
        coinvolgono più musicisti sono gialle e dicono quanti sono.

        Le proposte segnalate come probabili doppioni restano in elenco solo per l'admin: agli altri
        non vengono mostrate finché sono in pending (una volta confermate tornano visibili a tutti).
        """
        db = self.db
        eventi = fm.nascondi_duplicati(eventi, self.e_admin())
        idx = fm.indice_gruppi(db)       # una volta sola, non per ogni riga
        if not eventi:
            g.add_widget(L("Nessun evento.", wrap=True))
        for e in eventi:
            m = next((x for x in db["musicisti"] if x["id"] == e["musicista_id"]), None)
            pts = "PENDING" if e.get("stato") == "pending" else fmt_pt(e["punti"]) + ("*" if e.get("dittatura") else "")
            doppio = self.e_admin() and e.get("duplicato") and e.get("stato", "ok") == "pending"
            coinv = fm.descrivi_coinvolti(db, e, idx=idx)
            sotto = f"{e.get('data_completamento') or e['data']} | {e['proprietario'] or '-'}" + \
                    (f" | proposto da {e['proposto_da']}" if e.get("proposto_da") else "") + \
                    (f" | {coinv}" if coinv else "") + \
                    (" | probabile doppione" if doppio else "")
            g.add_widget(self.riga(m.get("foto") if m else None, m["nome"] if m else "?",
                                   f"{m['nome'] if m else '?'} - {e['azione']}" + (" *" if doppio else ""),
                                   sotto, pts,
                                   azione=lambda e=e: self.popup_evento(e),
                                   sfondo=GIALLO if (coinv or doppio) else None))

    def popup_evento(self, e):
        """Dettagli di un evento registrato: nota, calcolo e tutti i musicisti coinvolti."""
        db = self.db
        gruppo = fm.gruppo_evento(db, e)
        p = gruppo[0]
        tot = sum(x["punti"] for x in gruppo if x.get("stato", "ok") == "ok")
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list(6)
        testa = f"{p.get('data_completamento') or p['data']} | evento #{p['id']}" + \
                (f" | gruppo {p['gruppo']}" if p.get("gruppo") else "")
        g.add_widget(L(testa, dim=12, wrap=True))
        if p.get("nota"):
            g.add_widget(L(f"Nota: {p['nota']}", dim=12, wrap=True))
        if p.get("proposto_da"):
            g.add_widget(L(f"Proposto da {p['proposto_da']}", dim=12, wrap=True))
        if self.e_admin() and p.get("duplicato") and p.get("stato", "ok") == "pending":
            g.add_widget(L("PROBABILE DOPPIONE: esiste un'altra proposta in pending con lo stesso musicista e "
                           "la stessa azione. Questa proposta è registrata ma la vedi solo tu: confermala se è "
                           "un evento a sé, rifiutala se è una ripetizione.",
                           dim=11, wrap=True, colore="accent2"))
        for x in gruppo:
            m = next((y for y in db["musicisti"] if y["id"] == x["musicista_id"]), None)
            nome = m["nome"] if m else "?"
            pts = "PENDING" if x.get("stato") == "pending" else fmt_pt(x["punti"]) + ("*" if x.get("dittatura") else "")
            if x.get("stato") == "pending" and x.get("fascia"):
                fatti, necessari = fm.progresso_voti(db, x)
                calcolo = f"sondaggio segreto: {fatti}/{necessari} votanti"
            else:
                calcolo = fm.descrivi_calcolo(x, breve=True, con_ruolo=False)
            ruolo = fm.etichetta_ruolo(x)
            g.add_widget(self.riga(m.get("foto") if m else None, nome,
                                   f"{nome} - {ruolo}" if ruolo else nome,
                                   " | ".join(filter(None, [x["proprietario"] or "nessuna squadra", calcolo])),
                                   pts, sfondo=GIALLO if x["id"] == e["id"] and len(gruppo) > 1 else None))
            effetti = list(x.get("bonus", [])) + list(x.get("bonus_auto", []))
            if effetti:
                g.add_widget(L("Buff/debuff: " + "; ".join(fm.descrivi_bonus_esteso(z) for z in effetti),
                               dim=10, wrap=True, colore="accent2"))
        box.add_widget(sv)
        if len(gruppo) > 1:
            box.add_widget(L(f"Totale evento: {fmt_pt(tot)} punti", dim=14, colore="accent2", bold=True,
                             size_hint_y=None, height=dp(26)))
        pop = self.popup(p["azione"].upper(), box, 0.9, 0.85)
        box.add_widget(NBtn("CHIUDI", colore=attenua(col("accent"), 0.7), on_release=lambda *_: pop.dismiss()))

    def tab_eventi(self, g):
        """Eventi del periodo scelto, a pagine di EV_PAGINA righe."""
        periodo = fm.prefs(self.me)["periodo_eventi"]
        for fetta in (fm.PERIODI_EVENTI[:3], fm.PERIODI_EVENTI[3:]):
            r = BoxLayout(size_hint_y=None, height=dp(34), spacing=dp(4))
            for codice, etichetta in fetta:
                r.add_widget(NBtn(etichetta.upper(), dim=9, height=dp(34),
                                  colore=col("accent") if codice == periodo else attenua(col("accent"), 0.55),
                                  on_release=lambda *_, c=codice: self.cambia_periodo_eventi(c)))
            g.add_widget(r)
        eventi = fm.eventi_periodo(self.db, periodo)
        quanti = len(eventi)
        if not quanti:
            g.add_widget(L(f"Nessun evento: {fm.etichetta_periodo(periodo)}. Scegli un periodo più lungo "
                           f"qui sopra.", wrap=True))
            return
        pagine = (quanti + EV_PAGINA - 1) // EV_PAGINA
        pag = min(max(getattr(self, "ev_pagina", 0), 0), pagine - 1)
        self.ev_pagina = pag
        primo = pag * EV_PAGINA
        fetta = eventi[primo:primo + EV_PAGINA]
        g.add_widget(L(f"{fm.etichetta_periodo(periodo)}: {quanti} eventi" +
                       (f" | pagina {pag + 1} di {pagine} (righe {primo + 1}-{primo + len(fetta)})"
                        if pagine > 1 else ""),
                       dim=11, colore="accent2", size_hint_y=None, height=dp(22)))
        self.righe_eventi(g, fetta)
        if pagine > 1:
            nav = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(6))
            for testo, delta, attivo in (("< PIÙ RECENTI", -1, pag > 0), ("PIÙ VECCHI >", 1, pag < pagine - 1)):
                nav.add_widget(NBtn(testo, dim=10, height=dp(42),
                                    colore=col("accent") if attivo else attenua(col("accent"), 0.35),
                                    on_release=(lambda *_, d=delta: self.pagina_eventi(d)) if attivo
                                    else (lambda *_: None)))
            g.add_widget(nav)

    def cambia_periodo_eventi(self, codice):
        fm.prefs(self.me)["periodo_eventi"] = codice
        self.ev_pagina = 0
        self.salva()
        self.sostituisci(self.v_classifica, "eventi")

    def pagina_eventi(self, delta):
        self.ev_pagina = max(0, getattr(self, "ev_pagina", 0) + delta)
        self.sostituisci(self.v_classifica, "eventi")

    def tab_pending(self, g):
        self.righe_eventi(g, fm.eventi_pending(self.db))

    def tab_auto_chiusi(self, g):
        if not self.e_admin():
            g.add_widget(L("Sezione riservata all'admin.", wrap=True))
            return
        ev = sorted(fm.eventi_auto_chiusi(self.db),
                    key=lambda e: (e.get("data_completamento") or e.get("data", ""), e["id"]), reverse=True)
        ev = fm.comprimi_gruppi(ev)
        g.add_widget(L("Sondaggi chiusi automaticamente perché hanno votato tutti i giocatori aventi diritto. "
                       "Da qui puoi controllarli; per annullarne uno usa Pannello admin > Elimina un evento.",
                       wrap=True, dim=11, colore="accent2"))
        self.righe_eventi(g, ev)

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

    # ---------- statistiche ----------
    def tabella(self, g, intestazioni, righe, pesi=None):
        """Tabellina leggibile: una riga di intestazione e una riga (Panel) per ogni voce.
        'pesi' dà la larghezza relativa delle colonne; la prima è allineata a sinistra, le altre a destra."""
        pesi = pesi or ([2] + [1] * (len(intestazioni) - 1))

        def fila(valori, testa=False):
            r = (BoxLayout if testa else Panel)(size_hint_y=None, height=dp(26 if testa else 32),
                                                padding=[dp(7), dp(2)], spacing=dp(6))
            for i, (v, w) in enumerate(zip(valori, pesi)):
                r.add_widget(L(str(v), dim=10 if testa else 12, bold=testa, size_hint_x=w, shorten=True,
                               colore="accent2" if testa else ("accent" if i == 0 else "testo"),
                               halign="left" if i == 0 else "right"))
            return r
        g.add_widget(fila(intestazioni, True))
        if not righe:
            g.add_widget(L("Nessun dato ancora.", wrap=True))
            return
        for valori in righe:
            g.add_widget(fila(valori))

    TABS_STAT = [("azioni", "TIPI DI EVENTO"), ("musicisti", "PUNTI MUSICISTI"),
                 ("distribuzione", "POSITIVI/NEGATIVI"), ("buff", "BUFF/DEBUFF"),
                 ("top", "TOP 5"), ("peggio", "PEGGIO 5"), ("mercato", "MERCATO"),
                 ("valore", "VALORE/RESA")]

    def v_statistiche(self, tab="azioni"):
        self.titolo("STATISTICHE")
        if tab not in dict(self.TABS_STAT):
            tab = "azioni"
        barra = GridLayout(cols=4, size_hint_y=None, spacing=dp(5), row_default_height=dp(36),
                           row_force_default=True)
        barra.bind(minimum_height=barra.setter("height"))
        for k, nome in self.TABS_STAT:
            barra.add_widget(NBtn(nome, dim=9, height=dp(36),
                                  colore=col("accent") if k == tab else attenua(col("accent"), 0.55),
                                  on_release=lambda *_, k=k: self.sostituisci(self.v_statistiche, k)))
        self.corpo.add_widget(barra)
        self.corpo.add_widget(BoxLayout(size_hint_y=None, height=dp(6)))
        sv, g = scroll_list(6)
        getattr(self, "st_" + tab)(g)
        self.corpo.add_widget(sv)

    def st_azioni(self, g):
        g.add_widget(L("Quante volte si verifica ogni tipo di evento, i punti che ha prodotto in tutto e "
                       "la media per singolo evento.", wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["TIPO DI EVENTO", "VOLTE", "PUNTI", "MEDIA"],
                     [[r["nome"], r["volte"], fmt_pt(r["punti"]), f"{r['media']:+.2f}"]
                      for r in fm.stat_per_azione(self.db)], pesi=[3, 1, 1, 1])

    def st_musicisti(self, g):
        g.add_widget(L("Punti totali generati da ciascun musicista e punti per credito d'asta "
                       "(il rapporto compare solo per chi è stato comprato all'asta).",
                       wrap=True, dim=11, colore="accent2"))
        righe = []
        for _ps, m, p in fm.classifica_musicisti(self.db):
            prezzo = m["prezzo"] if m.get("proprietario") else 0
            righe.append([m["nome"], fmt_pt(p), prezzo or "-", f"{p / prezzo:+.2f}" if prezzo else "-"])
        self.tabella(g, ["MUSICISTA", "PUNTI", "PREZZO", "PT/CREDITO"], righe, pesi=[3, 1, 1, 1.2])

    def st_distribuzione(self, g):
        d = fm.stat_distribuzione(self.db)
        n = d["eventi"]
        quota = lambda x: f"{100 * x / n:.1f}%" if n else "-"
        g.add_widget(L("Come si dividono gli eventi validi fra punteggi positivi, negativi e neutri.",
                       wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["SEGNO", "EVENTI", "QUOTA", "PUNTI"],
                     [["Positivi", d["pos_n"], quota(d["pos_n"]), fmt_pt(d["pos_pt"])],
                      ["Negativi", d["neg_n"], quota(d["neg_n"]), fmt_pt(d["neg_pt"])],
                      ["Neutri (zero)", d["zero_n"], quota(d["zero_n"]), "0"],
                      ["TOTALE", n, "100%" if n else "-", fmt_pt(d["tot_pt"])]], pesi=[2, 1, 1, 1])

    def st_buff(self, g):
        d = fm.stat_impatto_bonus(self.db)
        g.add_widget(L("Quanto i buff/debuff hanno spostato i punteggi: si confronta il punteggio finale con "
                       "la base, negli eventi non in dittatura che avevano almeno un bonus o malus.",
                       wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["VOCE", "VALORE"],
                     [["Eventi con buff/debuff", d["eventi_con_bonus"]],
                      ["Di cui con effetto reale", d["eventi_con_effetto"]],
                      ["Punti aggiunti", fmt_pt(d["su"])],
                      ["Punti sottratti", fmt_pt(d["giu"])],
                      ["Effetto netto", fmt_pt(d["netto"])]], pesi=[3, 1])

    def st_top(self, g):
        d = fm.stat_top_musicisti(self.db, 5)
        perc = f"{d['perc']:.1f}%" if d["perc"] is not None else "-"
        g.add_widget(L(f"I {d['k']} musicisti migliori hanno prodotto {fmt_pt(d['somma_top'])} punti sui "
                       f"{fmt_pt(d['totale'])} totali: il {perc} di tutto il punteggio.",
                       wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["MUSICISTA", "SQUADRA", "PUNTI", "QUOTA"],
                     [[m["nome"], m.get("proprietario") or "-", fmt_pt(p),
                       f"{100 * p / d['totale']:.1f}%" if d["totale"] else "-"] for m, p in d["top"]],
                     pesi=[2.5, 2, 1, 1])

    def st_peggio(self, g):
        d = fm.stat_peggiori_musicisti(self.db, 5)
        intro = (f"I 5 musicisti con meno punti hanno totalizzato {fmt_pt(d['somma_peggio'])} punti sui "
                 f"{fmt_pt(d['totale'])} totali del campo.")
        if d["perc"] is not None:
            intro += f" Pesano per il {d['perc']:.1f}% dei punti negativi del campo."
        g.add_widget(L(intro, wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["MUSICISTA", "SQUADRA", "PUNTI"],
                     [[m["nome"], m.get("proprietario") or "-", fmt_pt(p)] for m, p in d["peggio"]],
                     pesi=[2.5, 2, 1])

    def st_mercato(self, g):
        g.add_widget(L("Giocatori più efficienti nel mercato: punti ottenuti per ogni credito speso in rosa.",
                       wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["GIOCATORE", "SPESO", "PUNTI", "PT/CREDITO"],
                     [[r["nome"], r["speso"], fmt_pt(r["punti"]), f"{r['resa']:+.2f}"]
                      for r in fm.stat_efficienza_mercato(self.db)], pesi=[2.5, 1, 1, 1.2])

    def st_valore(self, g):
        resa, righe = fm.stat_valore_rendimento(self.db)
        g.add_widget(L(f"Valore d'asta contro rendimento reale. La resa media è {resa:+.2f} punti per credito: "
                       f"«atteso» è quanto avrebbe dovuto rendere un musicista pagato quel prezzo, «scarto» "
                       f"quanto ha reso in più (o in meno).", wrap=True, dim=11, colore="accent2"))
        self.tabella(g, ["MUSICISTA", "PREZZO", "PUNTI", "ATTESO", "SCARTO"],
                     [[r["musicista"]["nome"], r["prezzo"], fmt_pt(r["punti"]), r["atteso"],
                       fmt_pt(r["delta"])] for r in righe], pesi=[2.5, 1, 1, 1, 1])

    # ---------- verifica integrità dei dati (solo lettura) ----------
    def f_verifica_integrita(self):
        if not self._solo_admin:
            return
        problemi = fm.valida_integrita(self.db)
        if not problemi:
            self.msg("Nessun problema: riferimenti, ID, proprietari, bonus, azioni, scambi, contatori, crediti "
                     "e rose risultano coerenti.\n\nIl controllo è di sola lettura: non ha modificato nulla.",
                     "VERIFICA INTEGRITÀ")
            return
        self.msg(f"Trovati {len(problemi)} problemi. Il controllo è di sola lettura: non ha modificato nulla, "
                 f"decidi tu cosa correggere.\n\n" + "\n".join("- " + p for p in problemi),
                 "VERIFICA INTEGRITÀ")

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
        _, tot_ut, tot_coppie = fm.totali_punti(db)      # sommati una volta sola per tutta la schermata
        punti_in_squadra = lambda x: tot_coppie.get((x["id"], nome), 0)
        info.add_widget(L(f"{tot_ut.get(nome, 0)} punti", dim=16, colore="accent2"))
        info.add_widget(L(f"crediti {fm.crediti(db, nome)}/{s['budget_iniziale']}", dim=12))
        info.add_widget(L(f"musicisti {len(r)}/{s['musicisti_per_squadra']}", dim=12))
        profilo_u = u.get("profilo", {})
        for c in fm.campi_per(db, "giocatori"):
            # Nei profili mostriamo solo le caratteristiche realmente assegnate a questo giocatore.
            if str(c["id"]) not in profilo_u:
                continue
            val = fm.valore_profilo(u, c)
            if val != "-":
                info.add_widget(L(f"{c['nome']}: {val}", dim=11))
        top.add_widget(info)
        fissa_info(top, info)
        g.add_widget(top)
        buff_giocatore = [b for b in db["bonus"]
                          if b.get("bersaglio") == "giocatore" and b.get("giocatore") == nome
                          and fm.bonus_attivo(b, datetime.now().strftime("%Y-%m-%d"))]
        if buff_giocatore:
            self.sezione(g, "BUFF / DEBUFF ATTIVI")
            for b in buff_giocatore:
                g.add_widget(L(fm.descrivi_bonus_esteso(b), dim=11, wrap=True))
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
        for m in sorted(r, key=lambda x: -punti_in_squadra(x)):
            p = punti_in_squadra(m)
            g.add_widget(self.riga(m.get("foto"), m["nome"], m["nome"],
                                   f"prezzo {m['prezzo']} | punti/credito "
                                   f"{(p / m['prezzo']) if m['prezzo'] else 0:.2f}", p,
                                   lambda i=m["id"]: self.vai(self.v_musicista, i)))
        ex = tot_ut.get(nome, 0) - sum(punti_in_squadra(m) for m in r)
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
        profilo_m = m.get("profilo", {})
        for c in fm.campi_per(db, "musicisti"):
            # Evita elenchi infiniti di caratteristiche vuote: compaiono solo quelle possedute.
            if str(c["id"]) not in profilo_m:
                continue
            val = fm.valore_profilo(m, c)
            if val != "-":
                info.add_widget(L(f"{c['nome']}: {val}", dim=11))
        top.add_widget(info)
        fissa_info(top, info)
        g.add_widget(top)
        oggi = datetime.now().strftime("%Y-%m-%d")
        buff_diretti = [b for b in db["bonus"]
                        if b.get("bersaglio") == "musicista" and b.get("musicista_id") == m["id"]
                        and fm.bonus_attivo(b, oggi)]
        buff_squadra = [b for b in db["bonus"]
                        if b.get("bersaglio") == "giocatore" and m.get("proprietario")
                        and b.get("giocatore") == m.get("proprietario") and fm.bonus_attivo(b, oggi)]
        if buff_diretti or buff_squadra:
            self.sezione(g, "BUFF / DEBUFF ATTIVI")
            for b in buff_diretti:
                g.add_widget(L(fm.descrivi_bonus_esteso(b), dim=11, wrap=True))
            for b in buff_squadra:
                g.add_widget(L("Di squadra: " + fm.descrivi_bonus_esteso(b), dim=11, wrap=True))
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
                     "Pannello admin > Caratteristiche descrittive).")
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
        if any(b.get("bersaglio") == "musicista" and b.get("musicista_id") == m["id"] for b in db["bonus"]):
            self.msg("Ha un bonus/malus automatico collegato: eliminalo o spostalo prima.")
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
        g.add_widget(NBtn(f"PERIODO DEGLI EVENTI: {fm.etichetta_periodo(p['periodo_eventi']).upper()}", dim=12,
                          on_release=lambda *_: self.apri_tab("eventi", nuova=True)))
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

    # ---------- gestione azioni (GUI) ----------
    def v_gest_azioni(self):
        if not self._solo_admin:
            return self.indietro()
        self.titolo("GESTIONE AZIONI")
        sv, g = scroll_list(8)
        g.add_widget(NBtn("+ NUOVA AZIONE", on_release=lambda *_: self.f_azione_gui()))
        g.add_widget(NBtn("ELIMINA AZIONE", colore=attenua(col("accent"), 0.75),
                          on_release=lambda *_: self.f_elimina_azione_gui()))
        for a in sorted(self.db["azioni"], key=lambda x: x["id"]):
            sotto = f"{a.get('modalita', 'fisso')}  //  {fm.descrivi_punteggio(a)}"
            if a.get("bonus_ids"):
                sotto += f"  // bonus: {', '.join(map(str, a['bonus_ids']))}"
            g.add_widget(self.riga(None, a["nome"], f"#{a['id']}  {a['nome']}", sotto,
                                   azione=lambda a=a: self.f_azione_gui(a), h=66))
        self.corpo.add_widget(sv)

    @staticmethod
    def _testo_slot_azione(a):
        parti = []
        for i, s in enumerate(fm.slot_azione(a)):
            ruolo = s.get("ruolo") or ("principale" if i == 0 else f"ruolo{i+1}")
            valore = f"{s.get('min')}-{s.get('max')}" if a.get("modalita") == "sondaggio" else str(s.get("punti", 0))
            parti.append(f"{ruolo}={valore}")
        return "; ".join(parti)

    def _parse_slot_azione_gui(self, testo, modalita):
        slot = []
        for n, pezzo in enumerate(testo.split(";"), 1):
            pezzo = pezzo.strip()
            if not pezzo:
                continue
            if "=" not in pezzo:
                raise ValueError("Usa il formato ruolo=valore, separando i musicisti con ';'.")
            ruolo, valore = (x.strip() for x in pezzo.split("=", 1))
            if ruolo.lower() == "principale":
                ruolo = ""
            if modalita == "sondaggio":
                fascia = fm.parse_range(valore)
                if not fascia:
                    raise ValueError(f"Range non valido nello slot {n}: usa per esempio 1-10.")
                punti, lo, hi = 0, fascia[0], fascia[1]
            else:
                try:
                    punti = int(valore)
                except ValueError:
                    raise ValueError(f"Punteggio non valido nello slot {n}: serve un intero.")
                lo = hi = None
            slot.append({"ruolo": ruolo, "punti": punti, "min": lo, "max": hi})
        if not slot:
            raise ValueError("Definisci almeno il musicista principale.")
        ruoli = [x["ruolo"].lower() for x in slot if x["ruolo"]]
        if len(ruoli) != len(set(ruoli)):
            raise ValueError("I ruoli devono essere diversi tra loro.")
        return slot

    def f_azione_gui(self, a=None):
        db = self.db
        nuova = a is None
        if nuova:
            a = fm.nuova_azione(0, "", 0)
        bonus_txt = ",".join(map(str, a.get("bonus_ids", [])))
        intro = ("Slot: scrivi per esempio 'principale=10; ospite=5'. Per un sondaggio usa "
                 "'principale=1-10; ospite=1-5'. In modalità tempo i valori sono punti per unità. "
                 "Gli eventi già registrati conservano il punteggio storico.")

        def ok(v):
            nome = " ".join(v["nome"].split())
            if not nome:
                self.msg("Il nome dell'azione è obbligatorio.")
                return False
            if any(x is not a and x["nome"].lower() == nome.lower() for x in db["azioni"]):
                self.msg("Esiste già un'azione con questo nome.")
                return False
            modalita = v["modalita"]
            try:
                slot = self._parse_slot_azione_gui(v["slot"], modalita)
            except ValueError as e:
                self.msg(str(e))
                return False
            bonus_ids = fm.parse_ids(v["bonus"], {b["id"] for b in db["bonus"]}) if v["bonus"].strip() else []
            if bonus_ids is None:
                self.msg("La lista bonus contiene ID non validi.")
                return False
            vecchio_nome = a.get("nome")
            if nuova:
                a["id"] = fm.prossimo_id(db, "azione")
                db["azioni"].append(a)
            a["nome"], a["modalita"] = nome, modalita
            a["unita"] = (v["unita"].strip() or "ore") if modalita == "tempo" else None
            a.update(slot[0])
            a["extra"] = slot[1:]
            a["bonus_ids"] = bonus_ids
            if not nuova and vecchio_nome != nome:
                for e in db["eventi"]:
                    if e.get("azione_id") == a["id"]:
                        e["azione"] = nome
            self.salva(); self.render()

        self.form("NUOVA AZIONE" if nuova else f"AZIONE #{a['id']}", [
            ("nome", "Nome", a.get("nome", ""), {}),
            ("modalita", "Modalità", a.get("modalita", "fisso"), {"valori": ["fisso", "sondaggio", "tempo"]}),
            ("unita", "Unità (solo modalità tempo)", a.get("unita") or "ore", {}),
            ("slot", "Musicisti/ruoli e punteggi", self._testo_slot_azione(a), {}),
            ("bonus", "ID bonus/malus collegati (es. 1,3,4)", bonus_txt, {}),
        ], ok, intro=intro, h=0.9)

    def f_elimina_azione_gui(self):
        def ok(v):
            if not v["id"].isdigit():
                self.msg("Scrivi un ID numerico."); return False
            a = next((x for x in self.db["azioni"] if x["id"] == int(v["id"])), None)
            if not a:
                self.msg("Azione inesistente."); return False
            def elimina():
                for e in self.db["eventi"]:
                    if e.get("azione_id") == a["id"]:
                        e["azione_id"] = None
                self.db["azioni"].remove(a)
                fm.riempi_buco(self.db, "azioni", "azione", a["id"])
                self.salva(); self.render()
            self.conferma(f"Eliminare '{a['nome']}'? Gli eventi storici conservano nome e punti.", elimina)
        self.form("ELIMINA AZIONE", [("id", "ID azione", "", {})], ok, h=0.45)

    # ---------- gestione bonus/malus (GUI) ----------
    def v_gest_bonus(self):
        if not self._solo_admin:
            return self.indietro()
        self.titolo("BONUS E MALUS")
        sv, g = scroll_list(8)
        g.add_widget(NBtn("+ NUOVO BONUS/MALUS", on_release=lambda *_: self.f_bonus_gui()))
        g.add_widget(NBtn("ELIMINA BONUS/MALUS", colore=attenua(col("accent"), 0.75),
                          on_release=lambda *_: self.f_elimina_bonus_gui()))
        for b in sorted(self.db["bonus"], key=lambda x: x["id"]):
            bers = b.get("bersaglio", "azione")
            dest = (fm.nome_musicista(self.db, b.get("musicista_id")) if bers == "musicista" else
                    b.get("giocatore") if bers == "giocatore" else "tipi di evento selezionati")
            bers_ui = "evento" if bers == "azione" else bers
            durata = b.get("durata", "permanente")
            durata_ui = "a tempo" if durata in ("a_tempo", "date") else durata
            sotto = f"{fm.descrivi_bonus_esteso(b)} // {bers_ui}: {dest or '-'} // durata {durata_ui}"
            g.add_widget(self.riga(None, b["nome"], f"#{b['id']}  {b['nome']}", sotto,
                                   azione=lambda b=b: self.f_bonus_gui(b), h=66))
        self.corpo.add_widget(sv)

    def f_bonus_gui(self, b=None):
        """Crea/modifica un buff o debuff senza chiedere ID all'admin.

        Nell'interfaccia il bersaglio tecnico ``azione`` viene chiamato ``evento``: il buff/debuff
        viene scelto durante la registrazione dell'evento ed è disponibile solo per i tipi di evento
        spuntati qui sotto. Musicisti e giocatori, invece, lo ricevono automaticamente finché è attivo.
        """
        db = self.db
        nuovo = b is None
        if nuovo:
            b = {"id": 0, "nome": "", "tipo": "punti", "valore": 1, "descrizione": "",
                 "bersaglio": "azione", "musicista_id": None, "giocatore": None,
                 "durata": "permanente", "eventi_rimasti": None, "da": None, "a": None}

        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list(8)
        # Form volutamente molto lungo: scrollbar più visibile e rotella del mouse più efficace.
        sv.do_scroll_y = True
        sv.do_scroll_x = False
        sv.bar_width = dp(10)
        sv.scroll_wheel_distance = dp(56)
        g.add_widget(L("I buff/debuff degli eventi si scelgono quando registri l'evento; quelli di musicisti e "
                       "giocatori si applicano automaticamente. La descrizione è facoltativa e compare nelle "
                       "schede e nei dettagli degli eventi.", wrap=True, colore="accent2"))

        righe = {}
        campi = {}

        def aggiungi_campo(chiave, etichetta, widget, altezza=68):
            r = BoxLayout(orientation="vertical", spacing=dp(3), size_hint_y=None, height=dp(altezza))
            r.add_widget(L(etichetta, dim=12, size_hint_y=None, height=dp(20), colore="accent2"))
            r.add_widget(widget)
            g.add_widget(r)
            righe[chiave] = (r, dp(altezza))
            campi[chiave] = widget
            return widget

        def mostra(chiave, si):
            r, h = righe[chiave]
            r.height = h if si else 0
            r.opacity = 1 if si else 0
            r.disabled = not si

        nome_w = aggiungi_campo("nome", "Nome", campo(b.get("nome", "")))
        valore_iniziale = fm.fmt_segno(b.get("valore", 0)) + ("%" if b.get("tipo") == "percentuale" else "")
        valore_w = aggiungi_campo("valore", "Valore (+5, -3, 20%, -10%)", campo(valore_iniziale))
        desc_w = TextInput(text=str(b.get("descrizione") or ""), multiline=True, font_name=FONT, font_size=fs(13),
                           background_normal="", background_active="", background_color=(*col("bg1"), 1),
                           foreground_color=(*col("testo"), 1), cursor_color=(*col("accent"), 1),
                           hint_text="Descrizione facoltativa", hint_text_color=(*col("testo"), 0.35),
                           size_hint_y=None, height=dp(72), padding=[dp(8), dp(8)], write_tab=False)
        aggiungi_campo("descrizione", "Descrizione / caratteristica del buff o debuff", desc_w, 100)

        bers_iniziale = "evento" if b.get("bersaglio", "azione") == "azione" else b.get("bersaglio")
        if bers_iniziale not in ("evento", "musicista", "giocatore"):
            bers_iniziale = "evento"
        bers_scelto = {"tipo": bers_iniziale}

        # ToggleButton nativi: selezione esclusiva e stato visibile. Evitiamo sia Spinner sia
        # pulsanti custom, che dentro alcuni ScrollView Kivy non aggiornavano correttamente lo stato.
        bers_box = BoxLayout(spacing=dp(6), size_hint_y=None, height=dp(44))
        bers_btn = {}
        gruppo = f"bonus-bersaglio-{id(box)}"
        for _tipo, _testo in (("evento", "EVENTO / AZIONE"), ("musicista", "MUSICISTA"), ("giocatore", "GIOCATORE")):
            _b = ToggleButton(text=_testo, group=gruppo, allow_no_selection=False,
                              state="down" if _tipo == bers_iniziale else "normal",
                              font_name=FONT, font_size=fs(10), bold=True,
                              background_normal="", background_down="",
                              background_color=(*col("accent"), 0.34) if _tipo == bers_iniziale else (*col("panel"), 1),
                              color=(*col("accent2"), 1) if _tipo == bers_iniziale else (*col("testo"), 1),
                              size_hint_y=None, height=dp(42))
            bers_btn[_tipo] = _b
            bers_box.add_widget(_b)
        aggiungi_campo("bersaglio", "Collegamento", bers_box, 70)

        scelto_lbl = L("", dim=11, colore="accent2", wrap=True, size_hint_y=None, height=dp(30))
        g.add_widget(scelto_lbl)

        # Il destinatario resta sempre visibile: per evento spiega di usare l'elenco azioni;
        # per musicista/giocatore apre un popup con lista realmente scorribile.
        dest_w = aggiungi_campo("dest", "Destinatario", NBtn("", dim=11, height=dp(42)))

        def apri_destinatario(*_):
            bers = bers_scelto["tipo"]
            if bers == "musicista":
                nomi = [m["nome"] for m in sorted(db["musicisti"], key=lambda x: x["nome"].lower())]
                titolo = "SCEGLI MUSICISTA"
            elif bers == "giocatore":
                nomi = [u["nome"] for u in sorted(db["utenti"], key=lambda x: x["nome"].lower()) if u.get("gioca")]
                titolo = "SCEGLI GIOCATORE"
            else:
                self.msg("Questo bonus è collegato a EVENTO / AZIONE: scegli sotto i tipi di evento in cui sarà disponibile.")
                return
            if not nomi:
                self.msg("Non ci sono destinatari disponibili per questo tipo.")
                return
            bx = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
            svd, gd = scroll_list(6)
            svd.do_scroll_y = True; svd.do_scroll_x = False
            svd.bar_width = dp(10); svd.scroll_wheel_distance = dp(56)
            bx.add_widget(svd)
            chiudi = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7), height=dp(42))
            bx.add_widget(chiudi)
            popd = self.popup(titolo, bx, 0.86, 0.86)

            def scegli(nome):
                dest_w.text = nome
                popd.dismiss()

            for nome in nomi:
                gd.add_widget(NBtn(nome, dim=11, height=dp(44), on_release=lambda *_, n=nome: scegli(n)))
            chiudi.bind(on_release=lambda *_: popd.dismiss())

        dest_w.bind(on_release=apri_destinatario)

        durata_db = b.get("durata", "permanente")
        durata_ui = "a tempo" if durata_db in ("a_tempo", "date") else durata_db
        durata_w = aggiungi_campo("durata", "Durata", spinner(durata_ui,
                                        ["permanente", "eventi", "a tempo"]))
        eventi_w = aggiungi_campo("eventi", "Numero di eventi", campo(str(b.get("eventi_rimasti") or ""),
                                                                         input_filter="int"))
        da_w = aggiungi_campo("da", "Dal (AAAA-MM-GG)", campo(str(b.get("da") or "")))
        a_w = aggiungi_campo("a", "Al (AAAA-MM-GG)", campo(str(b.get("a") or "")))

        titolo_azioni = L("TIPI DI EVENTO IN CUI È DISPONIBILE", dim=12, colore="accent2",
                          bold=True, size_hint_y=None, height=dp(28))
        g.add_widget(titolo_azioni)
        azione_righe = []
        azione_cb = {}
        for az in sorted(db["azioni"], key=lambda x: x["nome"].lower()):
            r = BoxLayout(size_hint_y=None, height=dp(38), spacing=dp(8))
            cb = CheckBox(active=(not nuovo and b.get("id") in az.get("bonus_ids", [])),
                          size_hint=(None, None), size=(dp(36), dp(36)))
            r.add_widget(cb)
            r.add_widget(L(az["nome"], dim=11, wrap=True))
            g.add_widget(r)
            azione_righe.append(r)
            azione_cb[az["id"]] = cb

        def mostra_azioni(si):
            titolo_azioni.height = dp(28) if si else 0
            titolo_azioni.opacity = 1 if si else 0
            titolo_azioni.disabled = not si
            for r in azione_righe:
                r.height = dp(38) if si else 0
                r.opacity = 1 if si else 0
                r.disabled = not si

        def sync_durata(*_):
            automatico = bers_scelto["tipo"] in ("musicista", "giocatore")
            mostra("durata", automatico)
            mostra("eventi", automatico and durata_w.text == "eventi")
            temporaneo = automatico and durata_w.text == "a tempo"
            mostra("da", temporaneo)
            mostra("a", temporaneo)

        def sync_bersaglio(tipo):
            bers_scelto["tipo"] = tipo
            evento = tipo == "evento"
            mostra_azioni(evento)
            scelto_lbl.text = "Collegamento selezionato: " + ("EVENTO / AZIONE" if evento else tipo.upper())
            if tipo == "musicista":
                corrente = fm.nome_musicista(db, b.get("musicista_id")) if b.get("musicista_id") else None
                dest_w.text = corrente or "SCEGLI MUSICISTA"
                dest_w.disabled = False
            elif tipo == "giocatore":
                corrente = b.get("giocatore")
                dest_w.text = corrente or "SCEGLI GIOCATORE"
                dest_w.disabled = False
            else:
                dest_w.text = "USA LE AZIONI / TIPI DI EVENTO QUI SOTTO"
                dest_w.disabled = False
            for k, btn in bers_btn.items():
                attivo = (k == tipo)
                btn.background_color = (*col("accent"), 0.34) if attivo else (*col("panel"), 1)
                btn.color = (*col("accent2"), 1) if attivo else (*col("testo"), 1)
            sync_durata()

        def on_toggle(tipo, btn, stato):
            if stato == "down":
                sync_bersaglio(tipo)

        for _tipo, _btn in bers_btn.items():
            _btn.bind(state=lambda btn, stato, t=_tipo: on_toggle(t, btn, stato))
        durata_w.bind(text=sync_durata)
        sync_bersaglio(bers_iniziale)

        box.add_widget(sv)
        pulsanti = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(10))
        annulla = NBtn("ANNULLA", colore=attenua(col("accent"), 0.7))
        salva = NBtn("SALVA")
        pulsanti.add_widget(annulla); pulsanti.add_widget(salva)
        box.add_widget(pulsanti)
        pop = self.popup("NUOVO BONUS/MALUS" if nuovo else f"BONUS #{b['id']}", box, 0.94, 0.94)
        annulla.bind(on_release=lambda *_: pop.dismiss())

        def invia(*_):
            nome = " ".join(nome_w.text.split())
            valore = fm.parse_bonus(valore_w.text.strip())
            if not nome or valore is None:
                self.msg("Nome o valore del bonus/malus non valido."); return
            if any(x is not b and x["nome"].lower() == nome.lower() for x in db["bonus"]):
                self.msg("Esiste già un bonus/malus con questo nome."); return

            bers_ui = bers_scelto["tipo"]
            bers = "azione" if bers_ui == "evento" else bers_ui
            mid = None; gioc = None
            if bers == "musicista":
                m = next((x for x in db["musicisti"] if x["nome"] == dest_w.text), None)
                if not m:
                    self.msg("Scegli un musicista dall'elenco."); return
                mid = m["id"]
            elif bers == "giocatore":
                u = next((x for x in db["utenti"] if x["nome"] == dest_w.text and x.get("gioca")), None)
                if not u:
                    self.msg("Scegli un giocatore dall'elenco."); return
                gioc = u["nome"]

            durata = "permanente"
            rimasti = da = a_data = None
            if bers != "azione":
                durata = "a_tempo" if durata_w.text == "a tempo" else durata_w.text
                if durata == "eventi":
                    if not eventi_w.text.strip().isdigit() or int(eventi_w.text.strip()) <= 0:
                        self.msg("Per la durata 'eventi' serve un numero maggiore di zero."); return
                    rimasti = int(eventi_w.text.strip())
                elif durata == "a_tempo":
                    da = da_w.text.strip() or None
                    a_data = a_w.text.strip() or None
                    for etichetta, x in (("iniziale", da), ("finale", a_data)):
                        if x:
                            try:
                                datetime.strptime(x, "%Y-%m-%d")
                            except ValueError:
                                self.msg(f"La data {etichetta} deve essere una data reale nel formato AAAA-MM-GG.")
                                return
                    if da and a_data and da > a_data:
                        self.msg("La data iniziale non può essere dopo quella finale."); return

            if nuovo:
                b["id"] = fm.prossimo_id(db, "bonus")
                db["bonus"].append(b)
            for az in db["azioni"]:
                az["bonus_ids"] = [i for i in az.get("bonus_ids", []) if i != b["id"]]
            b.update(nome=nome, tipo=valore[0], valore=valore[1],
                     descrizione=desc_w.text.strip()[:240], bersaglio=bers,
                     musicista_id=mid, giocatore=gioc, durata=durata,
                     eventi_rimasti=rimasti, da=da, a=a_data)
            if bers == "azione":
                for az in db["azioni"]:
                    if azione_cb[az["id"]].active:
                        az["bonus_ids"].append(b["id"])
            pop.dismiss()
            self.salva(); self.render()

        salva.bind(on_release=invia)

    def f_elimina_bonus_gui(self):
        def ok(v):
            if not v["id"].isdigit(): self.msg("Scrivi un ID numerico."); return False
            b = next((x for x in self.db["bonus"] if x["id"] == int(v["id"])), None)
            if not b: self.msg("Bonus/malus inesistente."); return False
            def elimina():
                for a in self.db["azioni"]:
                    a["bonus_ids"] = [i for i in a.get("bonus_ids", []) if i != b["id"]]
                self.db["bonus"].remove(b)
                fm.riempi_buco(self.db, "bonus", "bonus", b["id"])
                self.salva(); self.render()
            self.conferma(f"Eliminare '{b['nome']}' e scollegarlo dalle azioni?", elimina)
        self.form("ELIMINA BONUS/MALUS", [("id", "ID bonus/malus", "", {})], ok, h=0.45)

    # ---------- caratteristiche dei profili (GUI) ----------
    def v_gest_campi(self):
        if not self._solo_admin:
            return self.indietro()
        self.titolo("CARATTERISTICHE DESCRITTIVE")
        sv, g = scroll_list(8)
        g.add_widget(NBtn("+ NUOVA CARATTERISTICA", on_release=lambda *_: self.f_campo_gui()))
        for c in sorted(self.db["campi"], key=lambda x: x["id"]):
            g.add_widget(self.riga(None, c["nome"], f"#{c['id']}  {c['nome']}",
                                   f"{c['per']} // tipo {c['tipo']}",
                                   azione=lambda c=c: self.f_campo_gui(c), h=60))
        self.corpo.add_widget(sv)

    def f_campo_gui(self, c=None):
        db = self.db; nuovo = c is None
        if nuovo: c = {"id": 0, "per": "musicisti", "nome": "", "tipo": "testo"}
        def ok(v):
            nome = " ".join(v["nome"].split())
            if not nome: self.msg("Il nome è obbligatorio."); return False
            if any(x is not c and x["per"] == v["per"] and x["nome"].lower() == nome.lower() for x in db["campi"]):
                self.msg("Esiste già una caratteristica con questo nome per quel tipo di profilo."); return False
            if nuovo:
                c["id"] = fm.prossimo_id(db, "campo"); db["campi"].append(c)
            c.update(nome=nome, per=v["per"], tipo=v["tipo"])
            self.salva(); self.render()
        p = self.form("NUOVA CARATTERISTICA" if nuovo else f"CARATTERISTICA #{c['id']}", [
            ("nome", "Nome", c["nome"], {}),
            ("per", "Profilo", c["per"], {"valori": ["musicisti", "giocatori"]}),
            ("tipo", "Tipo", c["tipo"], {"valori": ["testo", "numero", "sino"]}),
        ], ok, h=0.65)
        if not nuovo:
            # Pulsante di eliminazione dentro la stessa finestra, sotto i campi.
            elimina = NBtn("ELIMINA CARATTERISTICA", colore=(1, .45, .45), height=dp(44))
            p.content.add_widget(elimina)
            def chiedi(*_):
                p.dismiss()
                compilati = [x for x in fm.profili_di(db, c["per"]) if str(c["id"]) in x.get("profilo", {})]
                def esegui():
                    for x in compilati: x.get("profilo", {}).pop(str(c["id"]), None)
                    db["campi"].remove(c); fm.riempi_buco(db, "campi", "campo", c["id"])
                    self.salva(); self.render()
                self.conferma(f"Eliminare '{c['nome']}'? Verranno cancellati {len(compilati)} valori già compilati.", esegui)
            elimina.bind(on_release=chiedi)

    # ---------- chiusura stagione ----------
    def f_chiudi_stagione_gui(self):
        if not self._solo_admin: return
        db = self.db; s = db["impostazioni"]
        pend = len(fm.eventi_pending(db))
        intro = (f"Stai chiudendo '{s['stagione']}'. Verranno archiviati classifica, eventi validi e scambi accettati; "
                 f"squadre, crediti ed eventi ripartono da zero. Pending attuali: {pend}. Scrivi CHIUDI per confermare.")
        def ok(v):
            if v["conferma"] != "CHIUDI": self.msg("Conferma non valida: scrivi esattamente CHIUDI."); return False
            try:
                backup = fm.crea_backup(db, "chiusura-stagione")
            except OSError as e:
                self.msg(f"Chiusura annullata: non riesco a creare il backup ({e.strerror or e}).")
                return False
            cl = fm.classifica_giocatori(db); clm = fm.classifica_musicisti(db)
            db["storico"].append({
                "id": fm.prossimo_id(db, "stagione"), "nome": s["stagione"],
                "chiusa": datetime.now().strftime("%Y-%m-%d %H:%M"),
                "classifica": [{"pos": pos, "nome": n, "punti": p, "musicisti": [m["nome"] for m in fm.rosa(db, n)]}
                               for pos, n, p in cl],
                "musicisti": [{"pos": pos, "nome": m["nome"], "squadra": m["proprietario"], "punti": p}
                              for pos, m, p in clm],
                "eventi": copy.deepcopy(fm.eventi_ok(db)),
                "scambi": copy.deepcopy([x for x in db["scambi"] if x["stato"] == "accettato"]),
            })
            db["eventi"].clear(); db["scambi"].clear()
            # Gli ID non vengono riciclati: i contatori restano monotoni anche tra una stagione e l'altra.
            for m in db["musicisti"]: m["proprietario"], m["prezzo"] = None, 0
            for u in db["utenti"]: u["saldo"] = 0
            s["stagione"] = v["nome"].strip() or f"Stagione {len(db['storico']) + 1}"
            self.salva(); self.render(); self.msg(f"Stagione archiviata. Backup: {backup}")
        self.form("CHIUDI STAGIONE", [("nome", "Nome nuova stagione", f"Stagione {len(db['storico']) + 1}", {}),
                                      ("conferma", "Scrivi CHIUDI", "", {})], ok, intro=intro, h=0.65)

    # ---------- ripristino backup ----------
    def v_ripristina_backup(self):
        if not self._solo_admin: return
        backups = fm.elenco_backup()
        if not backups:
            self.msg("Non ci sono backup disponibili."); return
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list(6)
        for path in backups:
            def scegli(p=path):
                pop.dismiss()
                def ripristina():
                    nuovo, err = fm.leggi_database(p)
                    if err:
                        self.msg(err); return
                    try:
                        fm.crea_backup(self.db, "prima-del-ripristino")
                    except OSError as e:
                        self.msg(f"Ripristino annullato: backup di sicurezza non riuscito ({e.strerror or e}).")
                        return
                    nome = self.me["nome"] if self.me else None
                    self.db.clear(); self.db.update(nuovo); fm.salva(self.db)
                    self.me = fm.utente(self.db, nome) if nome else None
                    if not self.me:
                        self.g = None; self.stack = [(self.v_login, ())]
                    else:
                        self.g = fm.Gioco(self.db, self.me); self.stack = [(self.v_home, ())]
                    if self.onl: self.onl_sporco = True
                    self.render(); self.msg(f"Ripristinato: {p.name}")
                self.conferma(f"Ripristinare '{p.name}'? Prima verrà creato un backup dello stato attuale.", ripristina,
                              "RIPRISTINA BACKUP", "RIPRISTINA")
            g.add_widget(NBtn(path.name, dim=11, on_release=lambda *_, f=scegli: f()))
        box.add_widget(sv)
        chiudi = NBtn("ANNULLA", colore=attenua(col("accent"), .7)); box.add_widget(chiudi)
        pop = self.popup("RIPRISTINA BACKUP", box, .9, .85)
        chiudi.bind(on_release=lambda *_: pop.dismiss())


    # ---------- compatibilità: il vecchio pannello admin confluisce nella home ----------
    def v_admin(self):
        if not self._solo_admin:
            return self.indietro()
        self.v_home()

    def v_audit_log(self):
        """Storico amministrativo centrale, letto da Supabase."""
        if not self._solo_admin:
            return self.indietro()
        self.titolo("AUDIT LOG AMMINISTRATIVO")
        sv, g = scroll_list(8)
        sv.bar_width = dp(8)
        self.corpo.add_widget(sv)

        def intestazione(testo=None, errore=False):
            g.add_widget(L("Storico server-side delle modifiche amministrative. I codici e le password non vengono "
                           "mai salvati nel log.", wrap=True, dim=11, colore="accent2",
                           size_hint_y=None, height=dp(46)))
            g.add_widget(NBtn("AGGIORNA", dim=11, height=dp(40), on_release=lambda *_: carica()))
            if testo:
                g.add_widget(L(testo, wrap=True, dim=11, colore=(1.0, 0.35, 0.35) if errore else "testo",
                               size_hint_y=None, height=dp(42)))

        def data_locale(v):
            if not v:
                return ""
            try:
                x = str(v).replace("Z", "+00:00")
                d = datetime.fromisoformat(x).astimezone()
                return d.strftime("%d/%m/%Y %H:%M:%S")
            except Exception:
                return str(v).replace("T", " ")[:19]

        def dettaglio(voce):
            box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
            box.add_widget(L(f"{voce.get('azione','')}  //  {voce.get('actor_nome','')}  //  "
                             f"{data_locale(voce.get('creato'))}", wrap=True, dim=11, colore="accent2",
                             size_hint_y=None, height=dp(48)))
            box.add_widget(L(voce.get("riepilogo", ""), wrap=True, dim=12,
                             size_hint_y=None, height=dp(58)))
            txt = json.dumps(voce.get("dettagli") or {}, ensure_ascii=False, indent=2)
            area = TextInput(text=txt, readonly=True, multiline=True, font_name=FONT, font_size=fs(11),
                             background_normal="", background_active="", background_color=(*col("bg1"), 1),
                             foreground_color=(*col("testo"), 1), cursor_color=(*col("accent"), 1))
            box.add_widget(area)
            chiudi = NBtn("CHIUDI", height=dp(42)); box.add_widget(chiudi)
            pop = self.popup("DETTAGLIO AUDIT", box, .9, .82)
            chiudi.bind(on_release=lambda *_: pop.dismiss())

        accumulo = []

        def mostra(r, aggiungi=False):
            nuove = r.get("righe", []) if isinstance(r, dict) else []
            if not aggiungi:
                accumulo.clear()
            accumulo.extend(nuove)
            g.clear_widgets()
            intestazione()
            if not accumulo:
                g.add_widget(L("Nessuna voce nel log.", wrap=True))
                return
            for voce in accumulo:
                quando = data_locale(voce.get("creato"))
                sotto = f"{quando}  //  {voce.get('actor_nome','?')}  //  {voce.get('fonte','')}"
                g.add_widget(self.riga(None, voce.get("azione", "MODIFICA"), voce.get("riepilogo", ""),
                                       sotto, azione=lambda v=voce: dettaglio(v), h=76))
            if len(nuove) >= 100 and accumulo:
                g.add_widget(NBtn("CARICA 100 PRECEDENTI", dim=11, height=dp(42),
                                  on_release=lambda *_: carica(accumulo[-1].get("id"), True)))

        def errore(e):
            g.clear_widgets()
            intestazione(f"Impossibile leggere il log: {e}", True)

        def carica(prima_id=None, aggiungi=False):
            if not aggiungi:
                g.clear_widgets()
                intestazione("Caricamento...")
            if not self.onl:
                g.clear_widgets()
                intestazione("Il log centrale è disponibile quando il gioco online è configurato e collegato.", True)
                return
            in_thread(lambda: self.onl.audit(prima_id=prima_id, limite=100),
                      lambda r: mostra(r, aggiungi), errore)

        carica()

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
        box.add_widget(NBtn("RIPRISTINA UN BACKUP", on_release=lambda *_: (pop.dismiss(), self.v_ripristina_backup())))
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
                    if proposta:
                        w = campo(hint=f"il tuo voto segreto da {s['min']} a {s['max']} (facoltativo)")
                    else:
                        w = None
                        dyn.add_widget(L(f"Sondaggio segreto {s['min']}-{s['max']}: l'admin non inserisce voti. "
                                         "Si chiude automaticamente quando hanno votato tutti i giocatori.",
                                         dim=11, colore="accent2", wrap=True, size_hint_y=None, height=dp(42)))
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
            dyn.add_widget(L("Altri musicisti coinvolti (facoltativo), formato NOME:punti, es. Mario Rossi:5, Anna:-2 "
                             "(oppure un range come Mario Rossi:4-9, va a sondaggio)",
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
                    basi.append((p, "", False, [], None))
                elif a["modalita"] == "sondaggio":
                    if not proposta:
                        basi.append((None, "", True, [], (s["min"], s["max"])))
                    elif not w.text.strip():
                        basi.append((None, "", True, [], (s["min"], s["max"])))
                    else:
                        voti = fm.parse_voti(w.text, s["min"], s["max"])
                        if voti is None or len(voti) != 1:
                            self.msg(f"Per {m['nome']} inserisci un solo voto da {s['min']} a {s['max']}.")
                            return
                        b, d = fm.base_da_voti(voti)
                        basi.append((b, d, False, voti, (s["min"], s["max"])))
                elif a["modalita"] == "tempo":
                    q = fm.parse_numero(st["qta"].text.strip()) if st["qta"].text.strip() else None
                    if q is None or q <= 0:
                        self.msg("Serve una quantità maggiore di zero.")
                        return
                    basi.append((fm.arrotonda(q * s["punti"]),
                                 f"{fm.fmt_valore(q)} {a['unita']} x {s['punti']:+d}", False, [], None))
                else:
                    basi.append((s["punti"], "", False, [], None))
            txt = st["altri"].text.strip()
            for pezzo in txt.replace(";", ",").split(","):
                if not pezzo.strip():
                    continue
                nome_, _, pt = pezzo.rpartition(":")
                m = next((x for x in db["musicisti"] if x["nome"].lower() == nome_.strip().lower()), None)
                if not m:
                    self.msg(f"'{pezzo.strip()}' non valido: usa NOME:punti con un musicista esistente "
                             f"(es. Mario Rossi:5 o Mario Rossi:4-9).")
                    return
                if any(x["id"] == m["id"] for x, _s in coppie):
                    self.msg(f"{m['nome']} è già coinvolto.")
                    return
                coppie.append((m, None))
                if dittatura:
                    try:
                        p = int(pt.strip())
                    except ValueError:
                        self.msg(f"Punteggio di {m['nome']} non valido.")
                        return
                    basi.append((p, "", False, [], None))
                    continue
                esito = fm.parse_punteggio_libero(pt.strip())
                if esito is None:
                    self.msg(f"Punteggio di {m['nome']} non valido: usa un intero (anche negativo) o un "
                             f"range come 4-9.")
                    return
                if esito[0] == "fisso":
                    basi.append((esito[1], "punteggio libero", False, [], None))
                else:
                    basi.append((None, "", True, [], (esito[1], esito[2])))
            bonus = [{"nome": b["nome"], "tipo": b["tipo"], "valore": b["valore"],
                      "descrizione": b.get("descrizione", "")}
                     for cb, b in st["bonus"] if cb.active]
            nota = st["nota"].text.strip()
            # Probabile doppione: solo per le proposte dei giocatori. Se un'altra proposta in pending ha già
            # lo stesso musicista e la stessa azione, l'evento viene comunque registrato ma segnalato e
            # mostrato soltanto nella lista pending dell'admin. L'admin, invece, registra sempre senza blocchi.
            doppione = proposta and any(fm.evento_duplicato_pending(db, a["id"], m["id"]) for m, _s in coppie)
            gruppo = fm.prossimo_id(db, "gruppo") if len(coppie) > 1 else None
            esiti = []
            for (m, s), (base, dett, pending, voti, fascia) in zip(coppie, basi):
                ruolo = self.g.ruolo_evento(a, s)
                if dittatura:
                    self.g.aggiungi_evento(m, a, base, base, [], "", False, nota, dittatura=True,
                                           gruppo=gruppo, ruolo=ruolo)
                    esiti.append(f"{base:+d} a {m['nome']} (DITTATURA)")
                elif proposta:
                    e = self.g.aggiungi_evento(m, a, None, base, bonus, dett, True, nota, fascia=fascia,
                                               voti=voti, gruppo=gruppo, ruolo=ruolo)
                    e["da_approvare"], e["proposto_da"] = True, me["nome"]
                    e["proposta_base"] = None if fascia else base
                    e["duplicato"] = doppione
                    if fascia:
                        e["aventi_diritto_voto"] = [u["nome"] for u in fm.giocatori(db)]
                        e["votanti"] = [me["nome"]] if voti and me["nome"] in e["aventi_diritto_voto"] else []
                        chiuso = fm.chiudi_sondaggio_se_completo(db, e)
                        esiti.append(f"{m['nome']}: " + (f"chiuso automaticamente ({e['punti']:+d})" if chiuso
                                                            else "sondaggio segreto in corso"))
                    else:
                        esiti.append(f"{m['nome']}: in attesa di conferma")
                else:
                    punti = None if pending else fm.calcola_punti(base, bonus)
                    e = self.g.aggiungi_evento(m, a, punti, base, bonus, dett, pending, nota, fascia=fascia,
                                               voti=voti, gruppo=gruppo, ruolo=ruolo)
                    if pending and fascia:
                        e["aventi_diritto_voto"] = [u["nome"] for u in fm.giocatori(db)]
                        e["votanti"] = []
                    esiti.append(f"{m['nome']}: " + ("PENDING" if pending else f"{punti:+d}"))
            self.salva()
            pop.dismiss()
            if doppione:
                self.msg("Esiste già una proposta in pending con lo stesso musicista e la stessa azione: "
                         "l'evento è stato comunque registrato, ma non viene mostrato per evitare doppioni. "
                         "Rivolgiti all'admin se pensi che sia corretto.")
            else:
                self.msg(("Proposta inviata. I sondaggi sono segreti e si chiudono da soli quando hanno votato "
                          "tutti; le proposte con punteggio fisso restano da confermare dall'admin.\n" if proposta
                          else "Registrato:\n") + "\n".join(esiti))
            self.render()
        si.bind(on_release=invia)

    # ----- pending -----
    def v_pending(self):
        self.titolo("EVENTI IN PENDING")
        sv, g = scroll_list()
        pend = fm.eventi_pending_visibili(self.db, self.e_admin())
        if not pend:
            g.add_widget(L("Nessun evento in pending.", wrap=True))
        if self.e_admin() and any(e.get("duplicato") for e in pend):
            g.add_widget(L("Le righe gialle con * sono probabili doppioni: un altro giocatore aveva già proposto "
                           "lo stesso musicista con la stessa azione. Sono registrate ma le vedi solo tu; chi le "
                           "ha proposte è stato avvisato di rivolgersi a te.",
                           wrap=True, dim=11, colore="accent2"))
        for e in pend:
            m = next((x for x in self.db["musicisti"] if x["id"] == e["musicista_id"]), None)
            doppio = bool(e.get("duplicato"))
            if e.get("proposta_base") is not None:
                sotto = f"{e['data']} | proposto da {e.get('proposto_da', '?')}"
                stato = "DA CONFERMARE"
            elif e.get("fascia"):
                fatti, necessari = fm.progresso_voti(self.db, e)
                sotto = f"{e['data']} | voto segreto: {fatti}/{necessari} giocatori hanno votato"
                stato = "SONDAGGIO"
            else:
                sotto = f"{e['data']} | pending"
                stato = "PENDING"
            if doppio:
                stato = "DOPPIONE?"
            g.add_widget(self.riga(m.get("foto") if m else None, m["nome"] if m else "?",
                                   f"#{e['id']} {m['nome'] if m else '?'} - {e['azione']}" + (" *" if doppio else ""),
                                   sotto, stato, lambda e=e: self.f_pending(e),
                                   sfondo=GIALLO if doppio else None))
        self.corpo.add_widget(sv)

    def f_pending(self, e):
        db = self.db
        tutto_gruppo = [x for x in fm.eventi_pending(db) if e.get("gruppo") and x.get("gruppo") == e["gruppo"]] or [e]
        ha_proposta = e.get("proposta_base") is not None
        info = e["azione"]
        if e.get("da_approvare"):
            info = f"Proposto da {e.get('proposto_da', '?')}: " + info
        if e.get("duplicato"):
            info += ("\nPROBABILE DOPPIONE: quando è stata inviata, c'era già un'altra proposta in pending con "
                     "lo stesso musicista e la stessa azione. È registrata ma la vedi solo tu, e chi l'ha "
                     "proposta è stato avvisato di rivolgersi a te. Se è un evento a sé confermala "
                     "(torna visibile a tutti), se è una ripetizione rifiutala.")
        if ha_proposta:
            info += (f"\nPunteggio proposto: {fm.calcola_punti(e['proposta_base'], e['bonus']):+d} "
                     f"(base {e['proposta_base']})" + (f" - {e['dettaglio']}" if e.get("dettaglio") else ""))
        elif e.get("fascia"):
            fatti, necessari = fm.progresso_voti(db, e)
            info += (f"\nSondaggio segreto: {fatti}/{necessari} giocatori aventi diritto hanno votato. "
                     "I valori restano nascosti fino alla chiusura e l'evento si chiude automaticamente "
                     "quando hanno votato tutti.")
            if len(e.get("voti", [])) != len(e.get("votanti", [])):
                info += ("\nATTENZIONE: questo pending contiene dati del vecchio sistema di votazione admin; "
                         "per sicurezza non verrà auto-chiuso. Se serve, eliminalo e riproponilo.")
        else:
            info += "\nEvento in pending."
        if len(tutto_gruppo) > 1:
            info += "\nL'evento vale per: " + ", ".join(fm.nome_musicista(db, x["musicista_id"]) for x in tutto_gruppo)
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, gi = scroll_list()
        gi.add_widget(L(info, wrap=True))
        box.add_widget(sv)
        pop = self.popup(f"EVENTO #{e['id']}", box, 0.9, 0.85)

        def conferma():
            adesso = datetime.now().strftime("%Y-%m-%d %H:%M")
            for x in tutto_gruppo:
                if x.get("proposta_base") is not None:
                    x["base"] = x["proposta_base"]
                    punti = fm.calcola_punti(x["base"], x["bonus"])
                    if not x.get("dittatura"):
                        mx = fm.musicista(db, x["musicista_id"])
                        giorno = (x.get("data") or "")[:10] or None
                        punti, x["bonus_auto"] = fm.applica_bonus_automatici(
                            db, mx, punti, proprietario=x.get("proprietario"), oggi=giorno
                        ) if mx else (punti, [])
                    x["punti"] = punti
                    x["stato"], x["da_approvare"], x["data_completamento"] = "ok", False, adesso
                    # confermando, la proposta diventa un evento normale: non è più un doppione nascosto
                    x["duplicato"] = False
            self.finito(pop)

        def rifiuta():
            for x in list(tutto_gruppo):
                if x.get("da_approvare"):
                    db["eventi"].remove(x)
                    fm.riempi_buco(db, "eventi", "evento", x["id"])
            self.finito(pop)

        if ha_proposta:
            box.add_widget(NBtn("CONFERMA I PUNTI", on_release=lambda *_: conferma()))
        elif e.get("fascia"):
            box.add_widget(L("L'admin non può aggiungere, modificare, azzerare o chiudere manualmente i voti.",
                             wrap=True, dim=11, colore="accent2", size_hint_y=None, height=dp(42)))
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
        self.live_stato("Accesso Supabase richiesto", True)
        if mostra:
            self.f_login_supabase(lambda: self.live_sync(True))

    def asta_live(self):
        c = leggi_online()
        if not c:
            self.corpo.add_widget(L("Manca il file di configurazione fantamusica_online.json accanto ai dati "
                                    "(servono url e anon_key).", wrap=True))
            return
        if self.onl is None:
            self.onl = fo.Online(c)
        if not self.onl.ha_sessione():
            box = BoxLayout(orientation="vertical", spacing=dp(8))
            box.add_widget(L("Per usare l'asta live devi accedere con un account admin Supabase.", wrap=True))
            box.add_widget(NBtn("ACCEDI A SUPABASE", on_release=lambda *_: self.f_login_supabase(self.render)))
            self.corpo.add_widget(box)
            return
        db = self.db
        st = self.live = {"busy": False}
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
        def lavoro():
            if not self.onl:
                raise RuntimeError("Accesso Supabase richiesto")
            r = self.onl.rpc("asta_leggi")
            return r.get("corr") or {}, r.get("offerte") or [], r.get("messaggi") or [], r.get("squadre") or []

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
        if not self.onl:
            self.live_errore(RuntimeError("Accesso Supabase richiesto"))
            return
        in_thread(lambda: self.onl.rpc(rpc, p_admin=None, **par), ok, self.live_errore)

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
        web = c.get("web_url") or "(scrivi l'indirizzo della pagina web in web_url dentro fantamusica_online.json)"
        box = BoxLayout(orientation="vertical", spacing=dp(8), padding=dp(8))
        sv, g = scroll_list()
        g.add_widget(L("Pagina dei giocatori: " + web, wrap=True, colore="accent2", dim=12))
        g.add_widget(L("I codici sono inviti di associazione: il giocatore li usa una volta sul proprio dispositivo. "
                       "Dopo l'uso la sessione resta sul dispositivo; per un nuovo telefono genera un NUOVO codice.",
                       wrap=True, dim=11))

        def fmt(cod):
            cod = (cod or "").upper()
            return cod[:4] + "-" + cod[4:] if len(cod) == 8 else cod

        def copia_testo():
            return "\n".join(f"{u['nome']}: {fmt(u.get('codice_asta'))}" for u in db["utenti"]) or "Nessun utente."

        for u in db["utenti"]:
            r = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(6))
            r.add_widget(L(f"{u['nome']}: {fmt(u.get('codice_asta'))}", dim=12, colore="accent2", shorten=True))

            def uno(*_, u=u):
                usati = {x.get("codice_asta") for x in db["utenti"] if x is not u and x.get("codice_asta")}
                nc = fo.nuovo_codice()
                while nc in usati:
                    nc = fo.nuovo_codice()
                u["codice_asta"] = nc
                self.salva()
                pop.dismiss()
                if self.live:
                    self.live_sync(True)
                Clock.schedule_once(lambda dt: self.f_codici(), 0.2)

            r.add_widget(NBtn("NUOVO", dim=10, size_hint_x=None, width=dp(92), on_release=uno))
            g.add_widget(r)
        box.add_widget(sv)
        pop = self.popup("CODICI DI ASSOCIAZIONE", box, 0.92, 0.86)

        def copia(*_):
            try:
                from kivy.core.clipboard import Clipboard
                Clipboard.copy(f"{web}\n{copia_testo()}")
                self.msg("Codici copiati.")
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
            self.conferma("Generare un nuovo codice per tutti? I vecchi inviti non ancora usati smettono di funzionare. "
                          "Le sessioni già associate restano valide.", ok)
        box.add_widget(NBtn("COPIA TUTTO", dim=12, on_release=copia))
        box.add_widget(NBtn("NUOVI CODICI PER TUTTI", dim=12, on_release=rigenera))
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
