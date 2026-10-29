#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Launcher di compatibilità FantaBanda.

La vecchia interfaccia a terminale è dismessa.
L'app supportata è ``fantamusica_kivy.py``.
"""
import sys


def main():
    if len(sys.argv) > 1:
        print("La modalità terminale e i comandi CLI sono stati dismessi.")
        print("Avvia FantaBanda con: python3 fantamusica_kivy.py")
        return 2

    from fantamusica_kivy import FantaApp
    FantaApp().run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
