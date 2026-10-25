#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Server web di FantaMusica: mostra il programma (fantamusica.py) in un terminale dentro il browser.

Per ogni persona che apre la pagina parte un processo separato di fantamusica.py collegato
a un terminale virtuale (pty) tramite WebSocket. Il gioco resta identico a quello da terminale;
i dati condivisi stanno nel database indicato da DATABASE_URL.

Avvio locale:   python3 server.py            (poi apri http://localhost:8000)
Su Render:      gunicorn -k gthread -w 1 --threads 32 server:app
"""
import fcntl
import json
import os
import select
import signal
import struct
import subprocess
import sys
import termios
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

import pty
from flask import Flask, send_from_directory
from flask_sock import Sock

BASE = Path(__file__).resolve().parent
SCRIPT = BASE / "fantamusica.py"

MAX_SESSIONI = int(os.environ.get("FANTAMUSICA_MAX_SESSIONI", "12"))    # collegamenti contemporanei
INATTIVITA_MAX = int(os.environ.get("FANTAMUSICA_INATTIVITA", "1800"))  # secondi senza tasti -> chiude
TENTATIVI_MAX = int(os.environ.get("FANTAMUSICA_TENTATIVI", "20"))      # aperture per IP ...
FINESTRA_TENTATIVI = 600                                                 # ... ogni 10 minuti

app = Flask(__name__, static_folder=None)
app.config["SOCK_SERVER_OPTIONS"] = {"ping_interval": 25}
sock = Sock(app)

_lock = threading.Lock()
_attive = 0
_aperture = defaultdict(deque)  # ip -> orari delle ultime aperture

# Il figlio diventa capo di una nuova sessione e prende il terminale come terminale di controllo
# (serve a getpass, che legge la password da /dev/tty), poi si trasforma in fantamusica.py.
AVVIO_FIGLIO = ("import fcntl, os, sys, termios; "
                "fcntl.ioctl(0, termios.TIOCSCTTY, 0); "
                "os.execv(sys.executable, [sys.executable, sys.argv[1]])")


@app.route("/")
def home():
    return send_from_directory(BASE / "static", "index.html")


@app.route("/healthz")
def healthz():
    return "ok"


def _ip(richiesta):
    inoltrato = richiesta.headers.get("X-Forwarded-For", "")
    return (inoltrato.split(",")[0].strip() if inoltrato else richiesta.remote_addr) or "?"


def _consenti(ip):
    """Limita le aperture ravvicinate dallo stesso indirizzo (freno ai tentativi di indovinare le password)."""
    ora = time.time()
    coda = _aperture[ip]
    while coda and ora - coda[0] > FINESTRA_TENTATIVI:
        coda.popleft()
    if len(coda) >= TENTATIVI_MAX:
        return False
    coda.append(ora)
    return True


def _dimensioni(fd, righe, colonne):
    fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", righe, colonne, 0, 0))


@sock.route("/ws")
def terminale(ws):
    global _attive
    from flask import request
    if not _consenti(_ip(request)):
        ws.send(b"\r\nTroppi collegamenti ravvicinati: riprova fra qualche minuto.\r\n")
        return
    with _lock:
        if _attive >= MAX_SESSIONI:
            ws.send(b"\r\nServer occupato: riprova fra poco.\r\n")
            return
        _attive += 1

    master, slave = pty.openpty()
    _dimensioni(master, 30, 100)
    env = dict(os.environ,
               TERM="xterm-256color", LANG="C.UTF-8", LC_ALL="C.UTF-8",
               PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1",
               TZ=os.environ.get("TZ", "Europe/Rome"))
    proc = subprocess.Popen([sys.executable, "-c", AVVIO_FIGLIO, str(SCRIPT)],
                            stdin=slave, stdout=slave, stderr=slave, close_fds=True,
                            start_new_session=True, env=env, cwd=str(BASE))
    os.close(slave)

    def dal_programma_al_browser():
        try:
            while True:
                pronti, _, _ = select.select([master], [], [], 1.0)
                if pronti:
                    try:
                        dati = os.read(master, 4096)
                    except OSError:
                        break
                    if not dati:
                        break
                    ws.send(dati)
                elif proc.poll() is not None:
                    break
        except Exception:
            pass
        finally:
            try:
                ws.close()
            except Exception:
                pass

    lettore = threading.Thread(target=dal_programma_al_browser, daemon=True)
    lettore.start()
    ultimo = time.time()
    try:
        while lettore.is_alive():
            msg = ws.receive(timeout=5)
            if msg is None:
                if time.time() - ultimo > INATTIVITA_MAX:
                    ws.send(b"\r\n[Sessione chiusa per inattivita'. Ricarica la pagina per rientrare.]\r\n")
                    break
                continue
            ultimo = time.time()
            if isinstance(msg, str) and msg.startswith("\x00"):  # ridimensionamento: \x00{"c":colonne,"r":righe}
                try:
                    d = json.loads(msg[1:])
                    _dimensioni(master, max(5, int(d["r"])), max(20, int(d["c"])))
                except (ValueError, KeyError, TypeError, OSError):
                    pass
                continue
            os.write(master, msg.encode("utf-8") if isinstance(msg, str) else msg)
    except Exception:
        pass
    finally:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        try:
            os.close(master)
        except OSError:
            pass
        with _lock:
            _attive -= 1


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8000")), threaded=True)
