#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Test automatici di FANTAMUSICA.

Esecuzione (dalla cartella dove si trovano i due file):
    python3 -m unittest -v test_fantamusica

I test non toccano i dati reali: usano un file temporaneo. Gli input dell'utente sono
simulati riga per riga; se un flusso chiede piu' (o meno) input del previsto il test fallisce,
cosi' si accorgono anche i cambi di domande nei menu.
"""
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import fantamusica as f


def crea_db():
    """Stagione di prova: admin Anna (non gioca), Bruno e Carla con due musicisti a testa."""
    db = f.nuovo_db()
    db["impostazioni"].update(musicisti_per_squadra=3, budget_iniziale=100)
    f.crea_utente(db, "Anna", "admin1", "admin")["gioca"] = False
    f.crea_utente(db, "Bruno", "bruno1")
    f.crea_utente(db, "Carla", "carla1")
    assegnazioni = [("M1", "Bruno", 20), ("M2", "Bruno", 10), ("M3", "Carla", 30),
                    ("M4", "Carla", 5), ("M5", None, 0), ("M6", None, 0)]
    for nome, squadra, prezzo in assegnazioni:
        db["musicisti"].append({"id": f.prossimo_id(db, "musicista"), "nome": nome,
                                "proprietario": squadra, "prezzo": prezzo, "profilo": {}})
    return db


def aggiungi_azione(db, modalita, **kw):
    a = f.nuova_azione(f.prossimo_id(db, "azione"), kw.pop("nome", modalita), kw.pop("punti", 0))
    a["modalita"] = modalita
    a.update(kw)
    db["azioni"].append(a)
    return a


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        patcher = mock.patch.object(f, "DATA_FILE", Path(self.tmp.name) / "dati.json")
        patcher.start()
        self.addCleanup(patcher.stop)
        self.db = crea_db()

    def gioco(self, nome):
        return f.Gioco(self.db, f.utente(self.db, nome))

    def esegui(self, fn, *righe, password=(), rigido=True):
        """Esegue fn simulando gli input; ritorna l'output stampato.
        rigido=False: gli input mancanti vengono sostituiti da 'n' e quelli in piu' ignorati."""
        it, pw = iter(righe), iter(password)
        self.prompts = []

        def finto_input(prompt=""):
            self.prompts.append(prompt)
            try:
                return next(it)
            except StopIteration:
                if not rigido:
                    return "n"
                raise AssertionError(f"Input esaurito al prompt: {prompt!r}")

        def finto_getpass(prompt=""):
            try:
                return next(pw)
            except StopIteration:
                raise AssertionError(f"Password esaurite al prompt: {prompt!r}")

        out = io.StringIO()
        with mock.patch("builtins.input", finto_input), \
                mock.patch.object(f.getpass, "getpass", finto_getpass), \
                contextlib.redirect_stdout(out):
            fn()
        if rigido:
            self.assertEqual(list(it), [], "Input non consumati: il flusso chiede meno del previsto")
        self.assertEqual(list(pw), [], "Password non consumate")
        return out.getvalue()

    def evento(self, mid, aid, punti, **kw):
        m = next(x for x in self.db["musicisti"] if x["id"] == mid)
        a = next(x for x in self.db["azioni"] if x["id"] == aid)
        return self.gioco("Anna").aggiungi_evento(m, a, punti, punti, [], "", False, "", **kw)

    def punti(self, nome):
        return f.punti_utente(self.db, nome)


# --------------------------------------------------------------------------
class TestCalcoli(unittest.TestCase):
    def test_bonus_a_punti_e_percentuale(self):
        punti = {"nome": "b", "tipo": "punti", "valore": 5}
        perc = {"nome": "p", "tipo": "percentuale", "valore": 20}
        self.assertEqual(f.calcola_punti(10, [punti]), 15)
        self.assertEqual(f.calcola_punti(10, [perc]), 12)
        self.assertEqual(f.calcola_punti(10, [{"nome": "m", "tipo": "punti", "valore": -3}]), 7)
    def test_i_bonus_si_sommano_sulla_base_in_qualsiasi_ordine(self):
        perc = {"nome": "p", "tipo": "percentuale", "valore": 20}
        malus = {"nome": "m", "tipo": "punti", "valore": -3}
        # prima i punti interi (10 - 3 = 7), poi la percentuale sul totale (+20% di 7 = 1,4 -> 1)
        self.assertEqual(f.calcola_punti(10, [perc, malus]), 8)
        self.assertEqual(f.calcola_punti(10, [malus, perc]), 8)

    def test_piu_percentuali_si_sommano_sul_totale_dei_punti(self):
        def perc(v):
            return {"nome": "p", "tipo": "percentuale", "valore": v}
        punti = {"nome": "b", "tipo": "punti", "valore": 10}
        # 20 + 10 = 30; +50% e -20% = +30% di 30 = +9
        self.assertEqual(f.calcola_punti(20, [perc(50), punti, perc(-20)]), 39)

    def test_percentuali_arrotondate_per_difetto(self):
        def perc(v):
            return {"nome": "p", "tipo": "percentuale", "valore": v}
        self.assertEqual(f.calcola_punti(7, [perc(20)]), 8)     # +1,4 -> +1
        self.assertEqual(f.calcola_punti(9, [perc(50)]), 13)    # +4,5 -> +4
        self.assertEqual(f.calcola_punti(10, [perc(-25)]), 7)   # -2,5 -> -3 (verso il basso)
        self.assertEqual(f.calcola_punti(7, [perc(-10)]), 6)    # -0,7 -> -1
        self.assertEqual(f.calcola_punti(3, [perc(10)]), 3)     # +0,3 -> +0

    def test_scrittura_dei_bonus(self):
        self.assertEqual(f.parse_bonus("5"), ("punti", 5))
        self.assertEqual(f.parse_bonus("+5"), ("punti", 5))
        self.assertEqual(f.parse_bonus("-3"), ("punti", -3))
        self.assertEqual(f.parse_bonus("20%"), ("percentuale", 20))
        self.assertEqual(f.parse_bonus("-10 %"), ("percentuale", -10))
        self.assertEqual(f.parse_bonus("2,5%"), ("percentuale", 2.5))
        for male in ("", "0", "0%", "1,5", "abc", "%"):
            self.assertIsNone(f.parse_bonus(male), male)

    def test_scrittura_del_range(self):
        self.assertEqual(f.parse_range("1-10"), (1, 10))
        self.assertEqual(f.parse_range(" 6 - 10 "), (6, 10))
        self.assertEqual(f.parse_range("0–5"), (0, 5))
        for male in ("", "10", "5-5", "9-3", "a-b", "1-2-3", "-3-5"):
            self.assertIsNone(f.parse_range(male), male)
    def test_arrotondamento_per_eccesso_sulla_meta(self):
        self.assertEqual(f.arrotonda(2.5), 3)
        self.assertEqual(f.arrotonda(2.4), 2)
        self.assertEqual(f.arrotonda(-2.5), -2)

    def test_voti_e_media(self):
        self.assertEqual(f.parse_voti("3 4,5", 1, 5), [3, 4, 5])
        self.assertIsNone(f.parse_voti("3 9", 1, 5))
        self.assertIsNone(f.parse_voti("abc", 1, 5))
        self.assertIsNone(f.parse_voti("", 1, 5))
        self.assertEqual(f.base_da_voti([4])[0], 4)
        self.assertEqual(f.base_da_voti([3, 4, 5])[0], 4)

    def test_media_per_difetto(self):
        self.assertEqual(f.media_voti([3, 4]), 3)        # 3,5 -> 3
        self.assertEqual(f.media_voti([7, 8, 10]), 8)    # 8,33 -> 8
        self.assertEqual(f.media_voti([2, 4]), 3)
        self.assertEqual(f.media_voti([9, 10]), 9)       # 9,5 -> 9

    def test_media_tra_zero_e_uno_vale_un_punto(self):
        self.assertEqual(f.media_voti([0, 1]), 1)        # 0,5 -> 1
        self.assertEqual(f.media_voti([0, 0, 1]), 1)     # 0,33 -> 1
        self.assertEqual(f.media_voti([0, 0]), 0)        # esattamente zero resta zero
        self.assertEqual(f.base_da_voti([0, 1])[0], 1)
    def test_parse_numero_e_ids(self):
        self.assertEqual(f.parse_numero("3,5"), 3.5)
        self.assertEqual(f.parse_numero("12"), 12)
        self.assertIsNone(f.parse_numero("abc"))
        self.assertIsNone(f.parse_numero("inf"))
        self.assertEqual(f.parse_ids("3, 1 2", {1, 2, 3}), [1, 2, 3])
        self.assertEqual(f.parse_ids("3, 1", {1, 3}, ordina=False), [3, 1])
        self.assertIsNone(f.parse_ids("4", {1, 2, 3}))

    def test_ordinamento_con_valori_mancanti_in_fondo(self):
        righe = [{"v": 3}, {"v": None}, {"v": 1}]
        col = f.Col("v", "V", lambda r: r["v"])
        self.assertEqual([r["v"] for r in f.ordina_righe(righe, col, False)], [1, 3, None])
        self.assertEqual([r["v"] for r in f.ordina_righe(righe, col, True)], [3, 1, None])
        nomi = [{"v": "bruno"}, {"v": "Anna"}]
        self.assertEqual([r["v"] for r in f.ordina_righe(nomi, col, False)], ["Anna", "bruno"])


# --------------------------------------------------------------------------
class TestMigrazione(unittest.TestCase):
    def db_v1(self):
        salt, h = f.hash_password("pw")
        return {
            "impostazioni": {"stagione": "S", "musicisti_per_squadra": 2, "budget_iniziale": 100,
                             "rilancio_minimo": 1},
            "utenti": [{"nome": "A", "ruolo": "admin", "salt": salt, "hash": h, "gioca": True}],
            "musicisti": [{"id": 1, "nome": "M", "proprietario": "A", "prezzo": 5}],
            "azioni": [{"id": 1, "nome": "Singolo", "punti": 10}],
            "eventi": [{"id": 1, "data": "2026-01-01 10:00", "musicista_id": 1, "azione": "Singolo",
                        "punti": 10, "proprietario": "A", "nota": ""}],
            "contatori": {"musicista": 2, "azione": 2, "evento": 2},
        }

    def test_vecchio_salvataggio(self):
        db = self.db_v1()
        self.assertTrue(f.migra(db))
        self.assertEqual([c["nome"] for c in db["campi"]],
                         ["Strumento", "Genere musicale", "Anni di carriera", "Città"])
        a = db["azioni"][0]
        self.assertEqual((a["modalita"], a["bonus_ids"], a["ruolo"], a["extra"]), ("fisso", [], "", []))
        e = db["eventi"][0]
        self.assertEqual((e["azione_id"], e["stato"], e["base"], e["voti"], e["gruppo"]), (1, "ok", 10, [], None))
        u = db["utenti"][0]
        self.assertEqual((u["saldo"], u["recupero"], u["profilo"]), (0, None, {}))
        self.assertEqual(f.prefs(u)["righe_eventi"], 15)
        self.assertTrue(db["impostazioni"]["mercato_aperto"])
        self.assertEqual(db["impostazioni"]["scambi_max"], 3)
        for k in ("bonus", "scambio", "gruppo", "stagione", "campo"):
            self.assertIn(k, db["contatori"])
        self.assertFalse(f.migra(db), "la migrazione deve essere idempotente")
    def test_bonus_con_il_tipo_dentro_il_bonus(self):
        db = self.db_v1()
        f.migra(db)
        db["bonus"] = [{"id": 1, "nome": "b", "tipo": "percentuale", "valore": 10}]
        db["azioni"][0]["bonus_ids"] = [1]
        db["eventi"][0]["bonus"] = [{"nome": "b", "tipo": "punti", "valore": 3}]
        self.assertFalse(f.migra(db), "gia' nel formato attuale")
        self.assertEqual(db["azioni"][0]["bonus_ids"], [1])
        self.assertEqual(f.calcola_punti(10, db["eventi"][0]["bonus"]), 13)

    def test_bonus_con_formula_scelta_nel_collegamento(self):
        db = self.db_v1()
        f.migra(db)
        db["bonus"] = [{"id": 1, "nome": "a", "valore": 5}, {"id": 2, "nome": "b", "valore": 20},
                       {"id": 3, "nome": "c", "valore": 1.5}, {"id": 4, "nome": "scollegato", "valore": 2}]
        db["azioni"][0].pop("bonus_ids")
        db["azioni"][0]["bonus_links"] = [{"id": 1, "formula": "somma"}, {"id": 2, "formula": "percentuale"},
                                          {"id": 3, "formula": "moltiplicatore"}]
        db["eventi"][0]["bonus"] = [{"nome": "a", "formula": "somma", "valore": 5},
                                    {"nome": "c", "formula": "moltiplicatore", "valore": 1.5}]
        self.assertTrue(f.migra(db))
        self.assertNotIn("bonus_links", db["azioni"][0])
        self.assertEqual(db["azioni"][0]["bonus_ids"], [1, 2, 3])
        self.assertEqual([(b["tipo"], b["valore"]) for b in db["bonus"]],
                         [("punti", 5), ("percentuale", 20), ("percentuale", 50), ("punti", 2)])
        self.assertEqual(db["eventi"][0]["bonus"],
                         [{"nome": "a", "tipo": "punti", "valore": 5},
                          {"nome": "c", "tipo": "percentuale", "valore": 50}])
        self.assertFalse(f.migra(db))
    def test_db_nuovo_ha_le_caratteristiche_di_partenza(self):
        db = f.nuovo_db()
        self.assertEqual(len(db["campi"]), 4)
        self.assertEqual(db["contatori"]["campo"], 5)
        self.assertFalse(f.migra(db))


# --------------------------------------------------------------------------
class TestEventi(Base):
    def test_evento_fisso_con_bonus_percentuale(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        self.db["azioni"][0]["bonus_ids"] = [1]
        # azione 1, musicista 1, applico il bonus, nessuna nota
        self.esegui(self.gioco("Anna").registra_evento, "1", "1", "n", "s", "")
        self.assertTrue(any("Tour (+20%)" in p for p in self.prompts),
                        "il valore gia' salvato e' mostrato alla richiesta")
        e = self.db["eventi"][0]
        self.assertEqual((e["punti"], e["base"], e["proprietario"]), (12, 10, "Bruno"))
        self.assertEqual(e["bonus"], [{"nome": "Tour", "tipo": "percentuale", "valore": 20}])
        self.assertEqual(self.punti("Bruno"), 12)

    def test_piu_bonus_collegati_si_sommano(self):
        self.db["bonus"] += [{"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20}, {"id": 2, "nome": "Ritardo", "tipo": "punti", "valore": -3}]
        self.db["azioni"][0]["bonus_ids"] = [1, 2]
        self.esegui(self.gioco("Anna").registra_evento, "1", "1", "n", "s", "s", "")
        self.assertEqual(self.db["eventi"][0]["punti"], 8)
    def test_bonus_non_applicato_se_rifiutato(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        self.db["azioni"][0]["bonus_ids"] = [1]
        self.esegui(self.gioco("Anna").registra_evento, "1", "1", "n", "n", "")
        self.assertEqual(self.db["eventi"][0]["punti"], 10)
    def test_azione_su_piu_musicisti_con_punteggi_diversi(self):
        a = aggiungi_azione(self.db, "fisso", nome="Feat", punti=10, ruolo="Principale",
                            extra=[{"ruolo": "Ospite", "punti": 4, "min": None, "max": None}])
        # azione, musicista per «Principale» (M1, Bruno), musicista per «Ospite» (M3, Carla), nota
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "3", "n", "")
        ev = self.db["eventi"]
        self.assertEqual([(e["musicista_id"], e["punti"], e["ruolo"]) for e in ev],
                         [(1, 10, "Principale"), (3, 4, "Ospite")])
        self.assertEqual(ev[0]["gruppo"], ev[1]["gruppo"])
        self.assertIsNotNone(ev[0]["gruppo"])
        self.assertEqual((self.punti("Bruno"), self.punti("Carla")), (10, 4))

    def test_lo_stesso_musicista_non_ricopre_due_ruoli(self):
        a = aggiungi_azione(self.db, "fisso", nome="Feat", punti=10, ruolo="Principale",
                            extra=[{"ruolo": "Ospite", "punti": 4, "min": None, "max": None}])
        out = self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "1", "3", "n", "")
        self.assertIn("non valido", out.lower())
        self.assertEqual(len(self.db["eventi"]), 2)

    def test_bonus_su_azione_con_piu_musicisti_vale_per_tutti(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        a = aggiungi_azione(self.db, "fisso", nome="Feat", punti=10, ruolo="P", bonus_ids=[1],
                            extra=[{"ruolo": "O", "punti": 5, "min": None, "max": None}])
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "3", "n", "s", "")
        self.assertEqual([e["punti"] for e in self.db["eventi"]], [12, 6])

    def test_altri_coinvolti_con_punteggio_libero_su_azione_senza_ruoli(self):
        # azione 1 (+10) per M1, poi "qualcun altro?" si: M3 e M5, con punteggi liberi 7 e -4
        self.esegui(self.gioco("Anna").registra_evento, "1", "1", "s", "3, 5", "7", "-4", "")
        ev = self.db["eventi"]
        self.assertEqual([(e["musicista_id"], e["punti"], e["ruolo"]) for e in ev],
                         [(1, 10, ""), (3, 7, "extra"), (5, -4, "extra")])
        self.assertEqual(len({e["gruppo"] for e in ev}), 1)
        self.assertEqual((self.punti("Bruno"), self.punti("Carla")), (10, 7))

    def test_altri_coinvolti_su_azione_con_ruoli_ricevono_anche_i_bonus(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        a = aggiungi_azione(self.db, "fisso", nome="Feat", punti=10, ruolo="P", bonus_ids=[1],
                            extra=[{"ruolo": "O", "punti": 5, "min": None, "max": None}])
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "3", "s", "4", "20", "s", "")
        self.assertEqual([(e["punti"], e["ruolo"]) for e in self.db["eventi"]],
                         [(12, "P"), (6, "O"), (24, "extra")])

    def test_altri_coinvolti_non_validi_vengono_richiesti(self):
        out = self.esegui(self.gioco("Anna").registra_evento, "1", "1", "s", "1", "99", "2", "3", "")
        self.assertIn("ID non validi", out)
        self.assertEqual(len(self.db["eventi"]), 2)

    def test_altri_coinvolti_nella_dittatura(self):
        self.esegui(self.gioco("Anna").dittatura, "1", "1", "s", "3", "5", "6", "")
        self.assertEqual((self.punti("Bruno"), self.punti("Carla")), (5, 6))
    def test_azione_tempo(self):
        a = aggiungi_azione(self.db, "tempo", nome="Durata", punti=4, unita="ore")
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "1,5", "")
        e = self.db["eventi"][0]
        self.assertEqual((e["punti"], e["base"]), (6, 6))
        self.assertIn("1.5 ore", e["dettaglio"])

    def test_azione_con_unita_personalizzata_e_punteggi_diversi(self):
        a = aggiungi_azione(self.db, "tempo", nome="Corsa", punti=3, unita="km", ruolo="Primo",
                            extra=[{"ruolo": "Secondo", "punti": 1, "min": None, "max": None}])
        out = self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "3", "n", "10", "")
        self.assertTrue(any("Quantità in km" in p for p in self.prompts))
        self.assertEqual([(e["punti"], e["ruolo"]) for e in self.db["eventi"]], [(30, "Primo"), (10, "Secondo")])
        self.assertIn("km", self.db["eventi"][0]["dettaglio"])
    def test_tempo_non_valido_viene_richiesto(self):
        a = aggiungi_azione(self.db, "tempo", nome="Durata", punti=4, unita="minuti")
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "0", "abc", "30", "")
        self.assertEqual(self.db["eventi"][0]["punti"], 120)
    def test_sondaggio_con_piu_voti_fa_la_media(self):
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5)
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "9", "3 4", "")
        e = self.db["eventi"][0]
        self.assertEqual((e["stato"], e["punti"], e["voti"]), ("ok", 3, [3, 4]))  # 3,5 -> 3

    def test_sondaggio_con_range_personalizzato(self):
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=0, max=20)
        out = self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "21", "0 1", "")
        self.assertIn("da 0 a 20", out)
        self.assertEqual(self.db["eventi"][0]["punti"], 1, "media 0,5: vale comunque un punto")

    def test_sondaggio_con_range_diverso_per_musicista(self):
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5, ruolo="P",
                            extra=[{"ruolo": "O", "punti": 0, "min": 6, "max": 10}])
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "3", "n", "4", "", "")
        self.assertEqual([(e["stato"], e["fascia"]) for e in self.db["eventi"]],
                         [("ok", [1, 5]), ("pending", [6, 10])])
        self.esegui(self.gioco("Anna").gestisci_pending, "2", "3", "9", "", "s")
        self.assertEqual(self.db["eventi"][1]["punti"], 9)
    def test_pending_voti_in_piu_momenti_e_media(self):
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=6, max=10)
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "", "")
        e = self.db["eventi"][0]
        self.assertEqual((e["stato"], e["punti"]), ("pending", 0))
        self.assertEqual(self.punti("Bruno"), 0, "un evento in pending non conta")
        g = self.gioco("Anna")
        # primo giro: due voti, non chiudo
        self.esegui(g.gestisci_pending, "1", "7 8", "", "n")
        self.assertEqual((e["stato"], e["voti"]), ("pending", [7, 8]))
        # secondo giro: voto fuori range rifiutato, poi 10, chiudo con la media (8,33 -> 8)
        self.esegui(g.gestisci_pending, "1", "11", "10", "", "s")
        self.assertEqual((e["stato"], e["voti"], e["punti"]), ("ok", [7, 8, 10], 8))
        self.assertEqual(self.punti("Bruno"), 8)
    def test_pending_di_gruppo_senza_ruoli_si_chiude_per_tutti(self):
        # formato dei salvataggi vecchi: stesso gruppo, nessun ruolo, voti condivisi
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5)
        g = self.gioco("Anna")
        for mid in (1, 3):
            m = next(x for x in self.db["musicisti"] if x["id"] == mid)
            g.aggiungi_evento(m, a, None, None, [], "", True, "", fascia=(1, 5), gruppo=7)
        self.esegui(g.gestisci_pending, "1", "4", "", "s")
        self.assertEqual([(e["stato"], e["punti"]) for e in self.db["eventi"]], [("ok", 4), ("ok", 4)])
    def test_pending_con_bonus_scelto_alla_registrazione(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5, bonus_ids=[1])
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "1", "n", "", "s", "")
        self.esegui(self.gioco("Anna").gestisci_pending, "1", "5", "", "s")
        self.assertEqual(self.db["eventi"][0]["punti"], 6)
    def test_dittatura(self):
        self.esegui(self.gioco("Anna").dittatura, "1", "1", "n", "-7", "")
        e = self.db["eventi"][0]
        self.assertEqual((e["punti"], e["dittatura"], e["bonus"]), (-7, True, []))
        self.assertEqual(self.punti("Bruno"), -7)

    def test_dittatura_con_un_punteggio_per_musicista(self):
        a = aggiungi_azione(self.db, "fisso", nome="Feat", punti=10, ruolo="P",
                            extra=[{"ruolo": "O", "punti": 4, "min": None, "max": None}])
        self.esegui(self.gioco("Anna").dittatura, str(a["id"]), "1", "3", "n", "50", "-2", "")
        self.assertEqual((self.punti("Bruno"), self.punti("Carla")), (50, -2))
    def test_modifica_evento_punteggio_a_mano(self):
        self.evento(1, 1, 10)
        self.esegui(self.gioco("Anna").modifica_evento, "1", "3", "25", "0")
        e = self.db["eventi"][0]
        self.assertEqual((e["punti"], e["dittatura"]), (25, True))
        self.assertEqual(self.punti("Bruno"), 25)

    def test_modifica_evento_squadra_e_musicista(self):
        self.evento(1, 1, 10)
        self.esegui(self.gioco("Anna").modifica_evento, "1", "4", "Carla", "0")
        self.assertEqual((self.punti("Bruno"), self.punti("Carla")), (0, 10))
        self.esegui(self.gioco("Anna").modifica_evento, "1", "1", "2", "0")  # musicista M2 (Bruno)
        e = self.db["eventi"][0]
        self.assertEqual((e["musicista_id"], e["proprietario"]), (2, "Bruno"))

    def test_modifica_evento_ricalcolo_con_altra_azione(self):
        self.evento(1, 1, 10)
        # azione 2 (+25 fisso): nessun bonus collegato
        self.esegui(self.gioco("Anna").modifica_evento, "1", "2", "2", "0")
        e = self.db["eventi"][0]
        self.assertEqual((e["azione_id"], e["punti"], e["dittatura"]), (2, 25, False))

    def test_modifica_evento_data_non_valida_rifiutata(self):
        self.evento(1, 1, 10)
        data = self.db["eventi"][0]["data"]
        self.esegui(self.gioco("Anna").modifica_evento, "1", "6", "ieri", "0")
        self.assertEqual(self.db["eventi"][0]["data"], data)
        self.esegui(self.gioco("Anna").modifica_evento, "1", "6", "2026-03-04 12:30", "0")
        self.assertEqual(self.db["eventi"][0]["data"], "2026-03-04 12:30")

    def test_elimina_evento_di_gruppo(self):
        self.evento(1, 1, 10, gruppo=5)
        self.evento(3, 1, 10, gruppo=5)
        self.evento(2, 1, 10)
        self.esegui(self.gioco("Anna").elimina_evento, "1", "s", "s")
        self.assertEqual(len(self.db["eventi"]), 1)
        self.assertEqual(self.db["eventi"][0]["id"], 1)  # l'ultimo ha preso l'ID libero

    def test_modifica_azione_aggiorna_gli_eventi_con_il_vecchio_punteggio(self):
        self.evento(1, 1, 10)
        self.evento(2, 1, 99, dittatura=True)
        # azione 1, nome invariato, stesso numero di musicisti, nuovi punti 12, aggiorno gli eventi
        self.esegui(self.gioco("Anna").modifica_azione, "1", "", "", "12", "s")
        self.assertEqual([e["punti"] for e in self.db["eventi"]], [12, 99])

    def test_modifica_azione_aggiunge_un_musicista(self):
        # 2 musicisti: ruolo del primo, punti del primo (invariati), ruolo e punti del secondo
        self.esegui(self.gioco("Anna").modifica_azione, "1", "", "2", "Solista", "", "Ospite", "3")
        a = self.db["azioni"][0]
        self.assertEqual((a["ruolo"], a["punti"]), ("Solista", 10))
        self.assertEqual(a["extra"], [{"ruolo": "Ospite", "punti": 3, "min": None, "max": None}])
        self.assertEqual(f.descrivi_punteggio(a), "Solista: +10 | Ospite: +3")

    def test_modifica_azione_range_e_unita(self):
        s = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5)
        t = aggiungi_azione(self.db, "tempo", nome="Dur", punti=2, unita="ore")
        self.esegui(self.gioco("Anna").modifica_azione, str(s["id"]), "", "", "x-y", "2-8")
        self.assertEqual((s["min"], s["max"]), (2, 8))
        self.esegui(self.gioco("Anna").modifica_azione, str(t["id"]), "", "pagine", "", "")
        self.assertEqual((t["unita"], t["punti"]), ("pagine", 2))

    def test_crea_azione_sondaggio_con_range_personalizzato(self):
        self.esegui(self.gioco("Anna").aggiungi_azione, "Sond", "2", "", "9-3", "abc", "3 - 9")
        a = self.db["azioni"][-1]
        self.assertEqual((a["modalita"], a["min"], a["max"], a["extra"]), ("sondaggio", 3, 9, []))
        self.assertEqual(f.descrivi_punteggio(a), "sondaggio 3-9")

    def test_crea_azione_con_unita_libera_e_piu_musicisti(self):
        self.esegui(self.gioco("Anna").aggiungi_azione, "Corsa", "3", "km", "2", "Primo", "3", "Primo", "Secondo", "1")
        a = self.db["azioni"][-1]
        self.assertEqual((a["modalita"], a["unita"], a["ruolo"], a["punti"]), ("tempo", "km", "Primo", 3))
        self.assertEqual(a["extra"], [{"ruolo": "Secondo", "punti": 1, "min": None, "max": None}])
        self.assertEqual(f.descrivi_punteggio(a), "Primo: +3 per km | Secondo: +1 per km")

    def test_crea_azione_fissa_con_bonus_collegati(self):
        self.db["bonus"] += [{"id": 1, "nome": "A", "tipo": "punti", "valore": 2},
                             {"id": 2, "nome": "B", "tipo": "percentuale", "valore": -10}]
        out = self.esegui(self.gioco("Anna").aggiungi_azione, "Fissa", "1", "", "5", "9", "2, 1")
        self.assertIn("+2", out)
        self.assertIn("-10%", out)
        self.assertEqual(self.db["azioni"][-1]["bonus_ids"], [1, 2])

    def test_crea_bonus_e_collegalo_a_piu_azioni(self):
        out = self.esegui(self.gioco("Anna").aggiungi_bonus, "Tour", "abc", "1,5", "0", "20%", "1, 3")
        b = self.db["bonus"][0]
        self.assertEqual((b["nome"], b["tipo"], b["valore"]), ("Tour", "percentuale", 20))
        self.assertTrue(any("Tour (+20%)" in p for p in self.prompts),
                        "alla richiesta di collegamento si vede il valore salvato")
        self.assertEqual([a["id"] for a in self.db["azioni"] if 1 in a["bonus_ids"]], [1, 3])

    def test_crea_bonus_a_punti_senza_collegare(self):
        self.esegui(self.gioco("Anna").aggiungi_bonus, "Ritardo", "-3", "")
        b = self.db["bonus"][0]
        self.assertEqual((b["tipo"], b["valore"]), ("punti", -3))
        self.assertTrue(all(not a["bonus_ids"] for a in self.db["azioni"]))

    def test_modifica_bonus_mantiene_o_cambia_il_valore(self):
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        self.esegui(self.gioco("Anna").modifica_bonus, "1", "", "")
        self.assertEqual((self.db["bonus"][0]["tipo"], self.db["bonus"][0]["valore"]), ("percentuale", 20))
        self.esegui(self.gioco("Anna").modifica_bonus, "1", "Tour 2", "+4")
        self.assertEqual((self.db["bonus"][0]["nome"], self.db["bonus"][0]["tipo"], self.db["bonus"][0]["valore"]),
                         ("Tour 2", "punti", 4))


# --------------------------------------------------------------------------
class TestIdConsecutivi(Base):
    def test_rimozione_musicista_sposta_l_ultimo(self):
        self.evento(6, 1, 7)
        self.esegui(self.gioco("Anna").rimuovi_musicista, "5", "s")
        self.assertEqual([m["id"] for m in self.db["musicisti"]], [1, 2, 3, 4, 5])
        self.assertEqual(self.db["musicisti"][-1]["nome"], "M6")
        self.assertEqual(self.db["eventi"][0]["musicista_id"], 5)
        self.assertEqual(self.db["contatori"]["musicista"], 6)

    def test_eliminazione_bonus_aggiorna_i_collegamenti(self):
        for i in (1, 2, 3):
            self.db["bonus"].append({"id": i, "nome": f"B{i}", "tipo": "punti", "valore": i})
        self.db["contatori"]["bonus"] = 4
        self.db["azioni"][0]["bonus_ids"] = [3, 2]
        self.esegui(self.gioco("Anna").elimina_bonus, "1", "s")
        self.assertEqual(sorted(b["id"] for b in self.db["bonus"]), [1, 2])
        self.assertEqual({b["nome"]: b["id"] for b in self.db["bonus"]}, {"B3": 1, "B2": 2})
        self.assertEqual(self.db["azioni"][0]["bonus_ids"], [1, 2])
        self.assertEqual(self.db["contatori"]["bonus"], 3)
    def test_eliminazione_azione_scollega_lo_storico(self):
        self.evento(1, 10, 5)
        self.evento(2, 3, 5)
        self.esegui(self.gioco("Anna").elimina_azione, "3", "s")
        self.assertEqual([a["id"] for a in self.db["azioni"]], list(range(1, 10)))
        self.assertEqual([e["azione_id"] for e in self.db["eventi"]], [3, None])


# --------------------------------------------------------------------------
class TestMercato(Base):
    def proponi(self, *righe):
        self.esegui(self.gioco("Bruno").nuova_proposta, *righe)

    def test_scambio_con_conguaglio_conserva_i_crediti(self):
        self.evento(1, 1, 10)  # i punti gia' maturati restano a Bruno
        totale_prima = f.crediti(self.db, "Bruno") + f.crediti(self.db, "Carla")
        # Bruno cede M1 (20) e riceve M3 (30), pagando 5 di conguaglio
        self.proponi("Carla", "1", "3", "5", "s")
        self.assertEqual(self.db["scambi"][0]["stato"], "proposto")
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        owner = {m["nome"]: m["proprietario"] for m in self.db["musicisti"]}
        self.assertEqual((owner["M1"], owner["M3"]), ("Carla", "Bruno"))
        self.assertEqual(f.crediti(self.db, "Bruno"), 55)
        self.assertEqual(f.crediti(self.db, "Carla"), 80)
        self.assertEqual(f.crediti(self.db, "Bruno") + f.crediti(self.db, "Carla"), totale_prima)
        self.assertEqual(self.punti("Bruno"), 10)
        self.assertEqual(self.db["scambi"][0]["stato"], "accettato")

    def test_vendita_senza_scambio(self):
        # Bruno vende M2 (prezzo 10) a Carla con 3 di extra
        self.proponi("Carla", "2", "", "-3", "s")   # conguaglio negativo: li riceve Bruno
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        self.assertEqual(f.crediti(self.db, "Bruno"), 70 + 10 + 3)
        self.assertEqual(f.crediti(self.db, "Carla"), 65 - 10 - 3)

    def test_rifiuto_e_annullamento(self):
        self.proponi("Carla", "1", "3", "0", "s")
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "2")
        self.assertEqual(self.db["scambi"][0]["stato"], "rifiutato")
        self.proponi("Carla", "1", "3", "0", "s")
        self.esegui(self.gioco("Bruno").proposte_in_sospeso, "2", "3")
        self.assertEqual(self.db["scambi"][1]["stato"], "annullato")
        self.assertEqual(f.rosa(self.db, "Bruno")[0]["nome"], "M1")

    def test_squadra_troppo_grande(self):
        out = self.esegui(self.gioco("Bruno").nuova_proposta, "Carla", "", "3,4", "0")
        self.assertIn("massimo 3", out)
        self.assertEqual(self.db["scambi"], [])

    def test_crediti_insufficienti(self):
        out = self.esegui(self.gioco("Bruno").nuova_proposta, "Carla", "", "4", "500")
        self.assertIn("crediti sufficienti", out)
        self.assertEqual(self.db["scambi"], [])


    def test_limite_di_scambi_per_stagione(self):
        self.db["impostazioni"]["scambi_max"] = 1
        self.proponi("Carla", "1", "3", "0", "s")
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        out = self.esegui(self.gioco("Bruno").nuova_proposta, "Carla", "2", "4", "0")
        self.assertIn("ha già fatto 1 scambi su 1", out)
        self.assertEqual(len(self.db["scambi"]), 1)

    def test_limite_scambi_controllato_anche_all_accettazione(self):
        self.db["impostazioni"]["scambi_max"] = 1
        self.proponi("Carla", "1", "3", "0", "s")
        self.proponi("Carla", "2", "4", "0", "s")
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        out = self.esegui(self.gioco("Carla").proposte_in_sospeso, "2", "1")
        self.assertIn("scambi su 1 consentiti", out)
        self.assertEqual([p["stato"] for p in self.db["scambi"]], ["accettato", "proposto"])

    def test_limite_zero_blocca_gli_scambi(self):
        self.db["impostazioni"]["scambi_max"] = 0
        out = self.esegui(self.gioco("Bruno").nuova_proposta, "Carla", "1", "3", "0")
        self.assertIn("scambi su 0", out)

    def test_il_limite_riparte_con_la_nuova_stagione(self):
        self.db["impostazioni"]["scambi_max"] = 1
        self.proponi("Carla", "1", "3", "0", "s")
        self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        self.assertEqual(f.scambi_fatti(self.db, "Bruno"), 1)
        self.esegui(self.gioco("Anna").chiudi_stagione, "CHIUDI", "")
        self.assertEqual(f.scambi_fatti(self.db, "Bruno"), 0)

    def test_impostazione_scambi_consentiti(self):
        self.assertEqual(self.db["impostazioni"]["scambi_max"], 3)
        self.esegui(lambda: self.gioco("Anna").modifica_impostazione("6"), "-1", "5")
        self.assertEqual(self.db["impostazioni"]["scambi_max"], 5)
    def test_mercato_chiuso(self):
        self.db["impostazioni"]["mercato_aperto"] = False
        out = self.esegui(self.gioco("Bruno").nuova_proposta)
        self.assertIn("chiuso", out)

    def test_il_proponente_non_puo_accettare_per_l_altro(self):
        self.proponi("Carla", "1", "3", "0", "s")
        out = self.esegui(self.gioco("Bruno").proposte_in_sospeso, "1", "1")
        self.assertIn("Permesso negato", out)
        self.assertEqual(self.db["scambi"][0]["stato"], "proposto")

    def test_l_admin_puo_accettare(self):
        self.proponi("Carla", "1", "3", "0", "s")
        self.esegui(self.gioco("Anna").proposte_in_sospeso, "1", "1")
        self.assertEqual(self.db["scambi"][0]["stato"], "accettato")

    def test_proposta_non_piu_valida_se_il_musicista_ha_cambiato_squadra(self):
        self.proponi("Carla", "1", "3", "0", "s")
        self.db["musicisti"][0]["proprietario"] = None  # M1 svincolato nel frattempo
        out = self.esegui(self.gioco("Carla").proposte_in_sospeso, "1", "1")
        self.assertIn("non appartiene", out)
        self.assertEqual(self.db["scambi"][0]["stato"], "proposto")


# --------------------------------------------------------------------------
class TestStagioni(Base):
    def test_chiusura_archivia_e_azzera(self):
        self.evento(1, 1, 30)
        self.evento(3, 1, 10)
        self.db["utenti"][1]["saldo"] = 5
        self.esegui(self.gioco("Anna").chiudi_stagione, "CHIUDI", "Seconda")
        st = self.db["storico"][0]
        self.assertEqual(st["nome"], "Stagione 1")
        self.assertEqual([(r["nome"], r["punti"]) for r in st["classifica"]], [("Bruno", 30), ("Carla", 10)])
        self.assertEqual(len(st["eventi"]), 2)
        self.assertEqual(self.db["eventi"], [])
        self.assertTrue(all(m["proprietario"] is None and m["prezzo"] == 0 for m in self.db["musicisti"]))
        self.assertTrue(all(u["saldo"] == 0 for u in self.db["utenti"]))
        self.assertEqual(self.db["impostazioni"]["stagione"], "Seconda")
        self.assertEqual(self.db["contatori"]["evento"], 1)
        copie = f.elenco_backup()
        self.assertEqual(len(copie), 1, "backup automatico prima della chiusura")
        self.assertIn("chiusura-stagione", copie[0].name)
        salvato = f.json.loads(copie[0].read_text(encoding="utf-8"))
        self.assertEqual(len(salvato["eventi"]), 2, "il backup contiene i dati di prima della chiusura")

    def test_chiusura_richiede_conferma(self):
        self.evento(1, 1, 30)
        self.esegui(self.gioco("Anna").chiudi_stagione, "no")
        self.assertEqual(self.db["storico"], [])
        self.assertEqual(len(self.db["eventi"]), 1)

    def test_classifica_cumulativa(self):
        self.evento(1, 1, 30)
        self.evento(3, 1, 10)
        self.esegui(self.gioco("Anna").chiudi_stagione, "CHIUDI", "")
        # seconda stagione: assegno di nuovo e Carla va forte
        for m, squadra in (("M1", "Bruno"), ("M3", "Carla")):
            x = next(y for y in self.db["musicisti"] if y["nome"] == m)
            x["proprietario"], x["prezzo"] = squadra, 10
        self.evento(3, 1, 50)
        dati = f.classifica_cumulativa(self.db)
        self.assertEqual([(p, n, d["punti"], d["stagioni"], d["titoli"]) for p, n, d in dati],
                         [(1, "Carla", 60, 2, 0), (2, "Bruno", 30, 2, 1)])
        senza_corrente = f.classifica_cumulativa(self.db, includi_corrente=False)
        self.assertEqual([(n, d["punti"]) for _, n, d in senza_corrente], [("Bruno", 30), ("Carla", 10)])

    def test_viste_dello_storico_non_si_rompono(self):
        out = self.esegui(self.gioco("Bruno").classifica_cumulativa_vista)
        self.assertIn("Nessun dato", out)
        self.evento(1, 1, 30)
        self.esegui(self.gioco("Anna").chiudi_stagione, "CHIUDI", "")
        self.esegui(self.gioco("Bruno").classifica_stagione, "1", "n", "n")
        self.esegui(self.gioco("Bruno").classifica_cumulativa_vista, "n")


# --------------------------------------------------------------------------
class TestPasswordEPreferenze(Base):
    def test_cambio_password_richiede_la_vecchia(self):
        g = self.gioco("Bruno")
        out = self.esegui(g.cambia_password, password=("x", "y", "z"))
        self.assertIn("Troppi tentativi", out)
        self.assertTrue(f.verifica_password(g.me, "bruno1"))
        self.esegui(g.cambia_password, password=("bruno1", "nuova1", "nuova1"))
        self.assertTrue(f.verifica_password(g.me, "nuova1"))
        self.assertFalse(f.verifica_password(g.me, "bruno1"))

    def test_recupero_password(self):
        g = self.gioco("Bruno")
        self.esegui(g.imposta_recupero, "Nome del gatto?", "Micio", password=("bruno1",))
        self.assertNotIn("Micio", str(self.db["utenti"]), "la risposta non va salvata in chiaro")
        # risposta sbagliata tre volte: nulla cambia
        out = self.esegui(lambda: f.recupero_password(self.db), "Bruno", "a", "b", "c")
        self.assertIn("Troppi tentativi", out)
        self.assertTrue(f.verifica_password(g.me, "bruno1"))
        # risposta giusta (maiuscole e spazi non contano)
        self.esegui(lambda: f.recupero_password(self.db), "Bruno", "  MICIO ", password=("nuova1", "nuova1"))
        self.assertTrue(f.verifica_password(g.me, "nuova1"))

    def test_recupero_non_impostato(self):
        out = self.esegui(lambda: f.recupero_password(self.db), "Carla")
        self.assertIn("admin", out)

    def test_ordinamento_ricordato_nel_file(self):
        g = self.gioco("Bruno")
        cols = [f.Col("a", "A", lambda r: r), f.Col("b", "B", lambda r: r)]
        self.esegui(lambda: g.scegli_ordine("lista", cols), "2", "2")
        col, desc = g.ordine_salvato("lista", cols, ("a", False))
        self.assertEqual((col.chiave, desc), ("b", True))
        db2 = f.carica()
        f.migra(db2)
        self.assertEqual(f.prefs(f.utente(db2, "Bruno"))["ordinamenti"]["lista"], ["b", True])

    def test_ordinamento_salvato_su_colonna_sparita_torna_al_predefinito(self):
        g = self.gioco("Bruno")
        f.prefs(g.me)["ordinamenti"]["lista"] = ["c99", True]
        cols = [f.Col("a", "A", lambda r: r)]
        col, desc = g.ordine_salvato("lista", cols, ("a", False))
        self.assertEqual((col.chiave, desc), ("a", False))

    def test_preferenze_personali(self):
        g = self.gioco("Bruno")
        self.esegui(g.preferenze, "1", "Il Capo", "2", "3", "5", "0")
        p = f.prefs(g.me)
        self.assertEqual((p["soprannome"], p["riepilogo_login"], p["righe_eventi"]), ("Il Capo", False, 5))
        self.assertEqual(f.etichetta_utente(self.db, "Bruno"), "Bruno (Il Capo)")
        self.assertNotIn("ordinamenti", self.esegui(g.preferenze, "0"), "niente piu' reset degli ordinamenti")

    def test_riepilogo_all_accesso_aggiorna_l_ultimo_accesso(self):
        g = self.gioco("Bruno")
        self.evento(1, 1, 10)
        out = self.esegui(g.riepilogo_accesso)
        self.assertIn("in classifica con 10 punti", out)
        self.assertIsNotNone(f.prefs(g.me)["ultimo_accesso"])


# --------------------------------------------------------------------------
class TestPermessi(Base):
    def test_un_partecipante_non_usa_le_funzioni_admin(self):
        g = self.gioco("Bruno")
        prima = f.json.dumps(self.db, sort_keys=True)
        nomi = ["registra_evento", "dittatura", "gestisci_pending", "modifica_evento", "elimina_evento",
                "chiudi_stagione", "menu_admin", "menu_bonus", "aggiungi_bonus", "modifica_bonus",
                "elimina_bonus", "collega_bonus", "aggiungi_azione", "modifica_azione", "elimina_azione",
                "asta", "modifica_musicista", "rimuovi_musicista", "menu_campi", "aggiungi_utente",
                "menu_backup", "backup_manuale", "ripristina_backup", "esporta_database", "importa_database",
                "esporta_csv_menu"]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            for n in nomi:
                getattr(g, n)()
        self.assertEqual(out.getvalue().count("Permesso negato"), len(nomi))
        self.assertEqual(f.json.dumps(self.db, sort_keys=True), prima)

    def test_modifica_impostazioni_solo_admin(self):
        g = self.gioco("Bruno")
        with contextlib.redirect_stdout(io.StringIO()):
            g.modifica_impostazione("5")
        self.assertTrue(self.db["impostazioni"]["mercato_aperto"])

    def test_scambi_consentiti_solo_admin(self):
        with contextlib.redirect_stdout(io.StringIO()):
            self.gioco("Bruno").modifica_impostazione("6")
        self.assertEqual(self.db["impostazioni"]["scambi_max"], 3)


# --------------------------------------------------------------------------
class TestViste(Base):
    """Le viste principali girano senza errori anche con dati di ogni tipo."""

    def test_viste_con_dati_misti(self):
        self.db["bonus"] += [{"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20},
                             {"id": 2, "nome": "Ritardo", "tipo": "punti", "valore": -3}]
        a = aggiungi_azione(self.db, "sondaggio", nome="Sond", min=1, max=5, bonus_ids=[1, 2], ruolo="P",
                            extra=[{"ruolo": "O", "punti": 0, "min": 6, "max": 10}])
        self.evento(1, 1, 10)
        self.evento(2, 2, 5, dittatura=True, gruppo=1)
        # azione, 2 musicisti, pending per entrambi, bonus si/no, nota
        self.esegui(self.gioco("Anna").registra_evento, str(a["id"]), "3", "4", "n", "", "", "s", "n", "")
        g = self.gioco("Bruno")
        for metodo in ("classifica_giocatori", "classifica_musicisti", "stat_riepilogo", "stat_azioni",
                       "stat_squadre", "stat_affari", "stat_ultimi_eventi", "stat_pending",
                       "storico_scambi"):
            self.esegui(getattr(g, metodo), rigido=False)
        for metodo in ("mostra_azioni", "mostra_bonus", "mostra_pending", "mostra_ultimi_eventi",
                       "impostazioni_stagione"):
            self.esegui(getattr(g, metodo), rigido=False)
        with contextlib.redirect_stdout(io.StringIO()):
            g.dettaglio_squadra("Bruno", interattiva=False)
    def test_classifica_musicisti_ha_tutte_le_informazioni_e_ordina_per_caratteristica(self):
        self.db["musicisti"][0]["profilo"]["1"] = "Chitarra"
        self.db["musicisti"][1]["profilo"]["1"] = "Voce"
        self.db["musicisti"][0]["soprannome"] = "Il Boss"
        g = self.gioco("Bruno")
        out = self.esegui(g.classifica_musicisti, "s", "8", "1", "n")  # 8a colonna ordinabile: Strumento
        for testo in ("Il Boss", "Squadra", "Prezzo", "Punti", "% punti", "Strumento", "Anni di carriera"):
            self.assertIn(testo, out)
        self.assertLess(out.rindex("Chitarra"), out.rindex("Voce"))

    def test_classifica_giocatori_ha_tutte_le_informazioni(self):
        f.utente(self.db, "Bruno")["profilo"]["4"] = "Roma"
        out = self.esegui(self.gioco("Carla").classifica_giocatori, "n")
        for testo in ("Pos", "Punti", "Distacco", "Rosa", "Crediti", "M1, M2", "Città", "Roma"):
            self.assertIn(testo, out)

    def test_il_menu_principale_non_ha_piu_i_profili(self):
        self.assertFalse(hasattr(f.Gioco, "menu_profili"))
        self.assertFalse(hasattr(f.Gioco, "profili_musicisti"))

# --------------------------------------------------------------------------
class TestSoprannomi(Base):
    def test_il_creatore_imposta_il_soprannome_del_musicista(self):
        self.esegui(self.gioco("Anna").modifica_musicista, "1", "", "Il Boss", "", "", "", "")
        self.assertEqual(self.db["musicisti"][0]["soprannome"], "Il Boss")
        out = self.esegui(self.gioco("Carla").classifica_musicisti, "n")
        self.assertIn("Il Boss", out)

    def test_ogni_giocatore_ha_i_suoi_soprannomi_personali(self):
        self.db["musicisti"][0]["soprannome"] = "Il Boss"
        self.esegui(self.gioco("Bruno").soprannomi_musicisti, "1", "Capo", "")
        self.esegui(self.gioco("Carla").soprannomi_musicisti, "1", "Zio", "")
        self.assertEqual(f.prefs(f.utente(self.db, "Bruno"))["soprannomi_musicisti"], {"1": "Capo"})
        out = self.esegui(self.gioco("Bruno").mostra_musicisti)
        self.assertIn("Capo", out)
        self.assertIn("Il Boss", out, "si vede anche quello impostato dal creatore")
        self.assertNotIn("Zio", out, "i soprannomi personali sono privati")
        self.assertEqual(self.db["musicisti"][0]["soprannome"], "Il Boss", "quello ufficiale non cambia")

    def test_togliere_il_soprannome_personale(self):
        self.esegui(self.gioco("Bruno").soprannomi_musicisti, "1", "Capo", "1", "-", "")
        self.assertEqual(f.prefs(f.utente(self.db, "Bruno"))["soprannomi_musicisti"], {})

    def test_i_soprannomi_seguono_gli_id_dei_musicisti(self):
        sopr = f.prefs(f.utente(self.db, "Bruno"))["soprannomi_musicisti"]
        sopr.update({"5": "Cinque", "6": "Sei"})
        self.esegui(self.gioco("Anna").rimuovi_musicista, "5", "s")   # M6 prende l'ID 5
        self.assertEqual(sopr, {"5": "Sei"})

    def test_salvataggio_vecchio_senza_soprannomi(self):
        for m in self.db["musicisti"]:
            m.pop("soprannome", None)
        for u in self.db["utenti"]:
            u["preferenze"].pop("soprannomi_musicisti")
        f.migra(self.db)
        self.esegui(self.gioco("Bruno").mostra_musicisti)
        self.assertEqual(self.db["musicisti"][0]["soprannome"], "")

# --------------------------------------------------------------------------
class TestBackup(Base):
    def test_backup_manuale_datato(self):
        out = self.esegui(self.gioco("Anna").backup_manuale)
        self.esegui(self.gioco("Anna").backup_manuale)
        copie = f.elenco_backup()
        self.assertEqual(len(copie), 2, "due backup nello stesso secondo non si sovrascrivono")
        self.assertIn("Backup creato", out)
        self.assertEqual(f.json.loads(copie[0].read_text(encoding="utf-8")), self.db)

    def test_ripristino_da_backup(self):
        self.esegui(self.gioco("Anna").backup_manuale)
        self.evento(1, 1, 10)
        self.assertEqual(len(self.db["eventi"]), 1)
        g = self.gioco("Anna")
        self.esegui(g.ripristina_backup, "1", "SOSTITUISCI")
        self.assertEqual(self.db["eventi"], [])
        self.assertEqual(len(f.elenco_backup()), 2, "prima di ripristinare si salva lo stato attuale")
        self.assertIs(g.me, f.utente(self.db, "Anna"))

    def test_ripristino_richiede_conferma_e_non_cambia_nulla(self):
        self.esegui(self.gioco("Anna").backup_manuale)
        self.evento(1, 1, 10)
        self.esegui(self.gioco("Anna").ripristina_backup, "1", "no")
        self.assertEqual(len(self.db["eventi"]), 1)
        self.esegui(self.gioco("Anna").ripristina_backup, "")
        self.esegui(self.gioco("Anna").ripristina_backup, "9", "")
        self.assertEqual(len(self.db["eventi"]), 1)

    def test_nessun_backup_da_ripristinare(self):
        out = self.esegui(self.gioco("Anna").ripristina_backup)
        self.assertIn("Nessun backup", out)

    def test_esporta_e_importa_il_database(self):
        dest = Path(self.tmp.name) / "export" / "tutto.json"
        self.evento(1, 1, 10)
        self.esegui(self.gioco("Anna").esporta_database, str(dest))
        self.assertTrue(dest.exists())
        self.evento(2, 1, 5)
        self.esegui(self.gioco("Anna").importa_database, str(dest), "SOSTITUISCI")
        self.assertEqual(len(self.db["eventi"]), 1)

    def test_esportazione_non_sovrascrive_senza_conferma(self):
        dest = Path(self.tmp.name) / "tutto.json"
        dest.write_text("vecchio", encoding="utf-8")
        self.esegui(self.gioco("Anna").esporta_database, str(dest), "n")
        self.assertEqual(dest.read_text(encoding="utf-8"), "vecchio")
        self.esegui(self.gioco("Anna").esporta_database, str(dest), "s")
        self.assertNotEqual(dest.read_text(encoding="utf-8"), "vecchio")

    def test_importazione_rifiuta_file_non_validi(self):
        prima = f.json.dumps(self.db, sort_keys=True)
        cart = Path(self.tmp.name)
        (cart / "rotto.json").write_text("{non json", encoding="utf-8")
        (cart / "altro.json").write_text('{"ciao": 1}', encoding="utf-8")
        (cart / "lista.json").write_text("[1, 2]", encoding="utf-8")
        for nome in ("rotto.json", "altro.json", "lista.json", "non_esiste.json"):
            out = self.esegui(self.gioco("Anna").importa_database, str(cart / nome))
            self.assertTrue("JSON" in out or "database" in out or "leggere" in out, out)
        self.esegui(self.gioco("Anna").importa_database, "")
        self.assertEqual(f.json.dumps(self.db, sort_keys=True), prima)

    def test_importazione_non_toglie_l_accesso_all_admin(self):
        altro = f.nuovo_db()
        f.crea_utente(altro, "Zeno", "zeno12", "admin")
        dest = Path(self.tmp.name) / "altro.json"
        dest.write_text(f.json.dumps(altro), encoding="utf-8")
        out = self.esegui(self.gioco("Anna").importa_database, str(dest))
        self.assertIn("perderesti l'accesso", out)
        self.assertIsNotNone(f.utente(self.db, "Anna"))

    def test_importazione_aggiorna_un_database_vecchio(self):
        db = TestMigrazione.db_v1(self)
        dest = Path(self.tmp.name) / "vecchio.json"
        dest.write_text(f.json.dumps(db), encoding="utf-8")
        g = f.Gioco(self.db, f.utente(self.db, "Anna"))
        db["utenti"][0]["nome"] = "Anna"
        dest.write_text(f.json.dumps(db), encoding="utf-8")
        self.esegui(g.importa_database, str(dest), "SOSTITUISCI")
        self.assertIn("bonus_ids", self.db["azioni"][0])
        self.assertEqual(self.db["impostazioni"]["scambi_max"], 3)

    def test_csv(self):
        self.db["musicisti"][0]["soprannome"] = "Il Boss"
        self.db["bonus"].append({"id": 1, "nome": "Tour", "tipo": "percentuale", "valore": 20})
        self.evento(1, 1, 10, ruolo="P")
        self.evento(3, 1, 4)
        cart = Path(self.tmp.name) / "csv"
        out = self.esegui(self.gioco("Anna").esporta_csv_menu, str(cart))
        self.assertIn("classifica_giocatori.csv", out)
        def leggi(nome):
            with open(cart / nome, encoding="utf-8-sig", newline="") as fh:
                return list(f.csv.reader(fh, delimiter=";"))
        gio = leggi("classifica_giocatori.csv")
        self.assertEqual(gio[0][:6], ["Posizione", "Giocatore", "Soprannome", "Punti", "Crediti", "Musicisti"])
        self.assertEqual([r[1] for r in gio[1:]], ["Bruno", "Carla"])
        self.assertEqual(gio[1][3], "10")
        mus = leggi("classifica_musicisti.csv")
        self.assertEqual(mus[1][:6], ["1", "M1", "Il Boss", "Bruno", "20", "10"])
        ev = leggi("eventi.csv")
        self.assertEqual(len(ev), 3)
        self.assertEqual((ev[1][3], ev[1][5], ev[1][6]), ("M1", "P", "10"))

    def test_csv_con_database_vuoto(self):
        self.db["eventi"].clear()
        cart = Path(self.tmp.name) / "csv"
        self.esegui(self.gioco("Anna").esporta_csv_menu, str(cart))
        self.assertEqual(len(list(cart.glob("*.csv"))), 3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
