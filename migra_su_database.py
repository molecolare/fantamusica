#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Copia il tuo vecchio salvataggio locale (fantamusica_dati.json) nel database online.

Si usa UNA volta sola, dal tuo computer, prima di aprire il gioco online:

    export DATABASE_URL="postgresql://...(la stringa di Supabase)..."      # Windows: set DATABASE_URL=...
    python3 migra_su_database.py fantamusica_dati.json

Se nel database ci sono gia' dei dati, lo script si ferma (a meno di --forza).
"""
import json
import sys

import fantamusica as fm


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    forza = "--forza" in sys.argv
    if not fm.usa_database():
        sys.exit("Manca DATABASE_URL: imposta la stringa di connessione di Supabase e riprova.")
    if len(args) != 1:
        sys.exit("Uso: python3 migra_su_database.py percorso/del/fantamusica_dati.json [--forza]")

    nuovo, errore = fm.leggi_database(args[0])
    if errore:
        sys.exit(errore)

    esistente = fm.carica()
    if esistente is not None and not forza:
        sys.exit("Il database online contiene gia' dei dati: non li tocco. "
                 "Se vuoi davvero sostituirli rilancia con --forza (ne viene fatto prima un backup).")
    if esistente is not None:
        print("Backup dei dati online:", fm.crea_backup(esistente, "prima-della-migrazione"))
        nuovo_db = esistente
        nuovo_db.clear()
        nuovo_db.update(nuovo)
    else:
        nuovo_db = nuovo

    if not fm.salva(nuovo_db):
        sys.exit("Salvataggio non riuscito (qualcuno ha scritto nel frattempo): riprova.")
    print(f"Fatto: {len(nuovo_db['utenti'])} utenti, {len(nuovo_db['musicisti'])} musicisti, "
          f"{len(nuovo_db['eventi'])} eventi nella stagione '{nuovo_db['impostazioni'].get('stagione')}'.")


if __name__ == "__main__":
    main()
