#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Compatibilità con la vecchia versione a terminale di FantaMusica.

La logica condivisa vive ora in ``fantamusica_core.py``. L'app principale è
``fantamusica_kivy.py`` e non dipende più da questo file. Questo wrapper resta
solo per chi vuole ancora avviare esplicitamente la vecchia CLI.
"""
from fantamusica_core import *  # noqa: F401,F403
from fantamusica_core import main as _main

if __name__ == "__main__":
    _main()
