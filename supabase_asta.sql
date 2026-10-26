-- ============================================================================
-- FANTAMUSICA - ASTA LIVE ONLINE
-- Incolla tutto nel SQL Editor di Supabase (Dashboard > SQL Editor > New query) e premi RUN.
-- Si puo' rieseguire senza danni: ricrea solo le funzioni e non cancella i dati.
--
-- Come funziona:
--   * le tabelle asta_* contengono solo dati pubblici dell'asta (nessuna password):
--     chiunque abbia la chiave "anon" puo' LEGGERLE (serve per vedere l'asta in tempo reale)
--   * nessuno puo' SCRIVERE direttamente: si passa solo dalle funzioni asta_* qui sotto,
--     che controllano il codice del giocatore (rilanci) o il codice admin (gestione)
--   * i codici dei giocatori e il codice admin stanno in tabelle NON leggibili dall'esterno
-- ============================================================================

-- ---------- tabelle ----------
create table if not exists asta_config (
  chiave text primary key,
  valore text not null
);

create table if not exists asta_codici (
  nome   text primary key,
  codice text not null unique
);

create table if not exists asta_squadre (
  nome    text primary key,
  crediti int  not null default 0,
  posti   int  not null default 0,
  visto   timestamptz
);

create table if not exists asta_musicisti (
  id           int primary key,
  nome         text not null,
  soprannome   text,
  proprietario text,
  prezzo       int not null default 0
);

create table if not exists asta_corrente (
  id               int primary key default 1 check (id = 1),
  musicista_id     int,
  musicista        text,
  aperta           boolean not null default false,
  rilancio_min     int not null default 1,
  miglior_importo  int,
  miglior_offerente text,
  aggiornato       timestamptz not null default now()
);
insert into asta_corrente (id) values (1) on conflict (id) do nothing;

create table if not exists asta_offerte (
  id           bigserial primary key,
  musicista_id int  not null,
  giocatore    text not null,
  importo      int  not null,
  creato       timestamptz not null default now()
);

create table if not exists asta_messaggi (
  id     bigserial primary key,
  autore text not null default 'ADMIN',
  testo  text not null,
  creato timestamptz not null default now()
);

-- ---------- codice admin (CAMBIALO se vuoi, poi aggiorna admin_code in fantamusica_online.json) ----------
insert into asta_config (chiave, valore) values ('admin_codice', 'UF96BNEX5KXEPJ')
on conflict (chiave) do update set valore = excluded.valore;

-- ---------- sicurezza: lettura pubblica delle sole tabelle dell'asta, nessuna scrittura diretta ----------
do $$
declare t text;
begin
  foreach t in array array['asta_squadre','asta_musicisti','asta_corrente','asta_offerte','asta_messaggi'] loop
    execute format('alter table %I enable row level security', t);
    execute format('drop policy if exists "lettura pubblica" on %I', t);
    execute format('create policy "lettura pubblica" on %I for select to anon, authenticated using (true)', t);
    execute format('revoke all on %I from anon, authenticated', t);
    execute format('grant select on %I to anon, authenticated', t);
  end loop;
  -- tabelle riservate: nessuna policy e nessun permesso
  alter table asta_config enable row level security;
  alter table asta_codici enable row level security;
  revoke all on asta_config from anon, authenticated;
  revoke all on asta_codici from anon, authenticated;
end $$;

-- ---------- aggiornamenti in tempo reale (Realtime) ----------
do $$
declare t text;
begin
  foreach t in array array['asta_squadre','asta_musicisti','asta_corrente','asta_offerte','asta_messaggi'] loop
    begin
      execute format('alter publication supabase_realtime add table %I', t);
    exception when duplicate_object then null;
    end;
  end loop;
end $$;

-- ---------- funzioni di servizio ----------
create or replace function asta_e_admin(p text) returns boolean
language sql security definer set search_path = public stable as $$
  select exists (select 1 from asta_config where chiave = 'admin_codice' and valore = p)
$$;
revoke execute on function asta_e_admin(text) from public, anon, authenticated;

-- ---------- funzioni per i giocatori ----------
create or replace function asta_login(p_codice text) returns json
language plpgsql security definer set search_path = public as $$
declare v_nome text;
begin
  if asta_e_admin(p_codice) then
    return json_build_object('ok', true, 'nome', 'ADMIN', 'ruolo', 'admin');
  end if;
  select nome into v_nome from asta_codici where codice = upper(trim(p_codice));
  if v_nome is null then
    return json_build_object('ok', false, 'errore', 'Codice non valido');
  end if;
  update asta_squadre set visto = now() where nome = v_nome;
  return json_build_object('ok', true, 'nome', v_nome, 'ruolo', 'giocatore');
end $$;

create or replace function asta_ping(p_codice text) returns json
language plpgsql security definer set search_path = public as $$
declare v_nome text;
begin
  select nome into v_nome from asta_codici where codice = upper(trim(p_codice));
  if v_nome is null then return json_build_object('ok', false); end if;
  update asta_squadre set visto = now() where nome = v_nome;
  return json_build_object('ok', true);
end $$;

create or replace function asta_rilancia(p_codice text, p_importo int) returns json
language plpgsql security definer set search_path = public as $$
declare
  v_nome text;
  a asta_corrente%rowtype;
  s asta_squadre%rowtype;
  v_min int;
  v_max int;
begin
  select nome into v_nome from asta_codici where codice = upper(trim(p_codice));
  if v_nome is null then
    return json_build_object('ok', false, 'errore', 'Codice non valido');
  end if;

  select * into a from asta_corrente where id = 1 for update;   -- blocca: un rilancio alla volta
  if not a.aperta then
    return json_build_object('ok', false, 'errore', 'Nessuna asta aperta in questo momento');
  end if;

  select * into s from asta_squadre where nome = v_nome;
  if s.nome is null or s.posti <= 0 then
    return json_build_object('ok', false, 'errore', 'La tua squadra è già completa');
  end if;
  if a.miglior_offerente = v_nome then
    return json_build_object('ok', false, 'errore', 'Sei già il miglior offerente');
  end if;
  if p_importo is null then
    return json_build_object('ok', false, 'errore', 'Importo mancante');
  end if;

  v_min := case when a.miglior_importo is null then 1 else a.miglior_importo + a.rilancio_min end;
  v_max := s.crediti - (s.posti - 1);     -- 1 credito per ogni altro posto da riempire
  if p_importo < v_min then
    return json_build_object('ok', false, 'errore', 'Offerta troppo bassa: minimo ' || v_min);
  end if;
  if p_importo > v_max then
    return json_build_object('ok', false, 'errore',
      'Puoi offrire al massimo ' || v_max || ' (devi tenere 1 credito per ogni altro posto da riempire)');
  end if;

  insert into asta_offerte (musicista_id, giocatore, importo) values (a.musicista_id, v_nome, p_importo);
  update asta_corrente
     set miglior_importo = p_importo, miglior_offerente = v_nome, aggiornato = now()
   where id = 1;
  update asta_squadre set visto = now() where nome = v_nome;
  return json_build_object('ok', true);
end $$;

-- ---------- funzioni per l'admin (richiedono il codice admin) ----------
create or replace function asta_a_sync(p_admin text, p_squadre jsonb, p_musicisti jsonb, p_codici jsonb) returns json
language plpgsql security definer set search_path = public as $$
begin
  if not asta_e_admin(p_admin) then
    return json_build_object('ok', false, 'errore', 'Codice admin non valido');
  end if;

  insert into asta_squadre (nome, crediti, posti)
    select x->>'nome', (x->>'crediti')::int, (x->>'posti')::int from jsonb_array_elements(p_squadre) x
  on conflict (nome) do update set crediti = excluded.crediti, posti = excluded.posti;
  delete from asta_squadre where nome not in (select x->>'nome' from jsonb_array_elements(p_squadre) x);

  delete from asta_musicisti;
  insert into asta_musicisti (id, nome, soprannome, proprietario, prezzo)
    select (x->>'id')::int, x->>'nome', x->>'soprannome', x->>'proprietario', coalesce((x->>'prezzo')::int, 0)
    from jsonb_array_elements(p_musicisti) x;

  delete from asta_codici;
  insert into asta_codici (nome, codice)
    select key, upper(value) from jsonb_each_text(p_codici);

  return json_build_object('ok', true);
end $$;

create or replace function asta_a_apri(p_admin text, p_musicista_id int, p_rilancio int) returns json
language plpgsql security definer set search_path = public as $$
declare m asta_musicisti%rowtype;
begin
  if not asta_e_admin(p_admin) then
    return json_build_object('ok', false, 'errore', 'Codice admin non valido');
  end if;
  select * into m from asta_musicisti where id = p_musicista_id;
  if m.id is null then
    return json_build_object('ok', false, 'errore', 'Musicista non trovato: premi SINCRONIZZA');
  end if;
  if m.proprietario is not null then
    return json_build_object('ok', false, 'errore', 'Il musicista ha già una squadra');
  end if;
  delete from asta_offerte where musicista_id = m.id;
  update asta_corrente
     set musicista_id = m.id, musicista = m.nome, aperta = true, rilancio_min = greatest(coalesce(p_rilancio, 1), 1),
         miglior_importo = null, miglior_offerente = null, aggiornato = now()
   where id = 1;
  insert into asta_messaggi (testo) values ('ASTA APERTA: ' || m.nome || ' (base 1 credito, rilancio minimo '
                                            || greatest(coalesce(p_rilancio, 1), 1) || ')');
  return json_build_object('ok', true);
end $$;

create or replace function asta_a_aggiudica(p_admin text) returns json
language plpgsql security definer set search_path = public as $$
declare a asta_corrente%rowtype;
begin
  if not asta_e_admin(p_admin) then
    return json_build_object('ok', false, 'errore', 'Codice admin non valido');
  end if;
  select * into a from asta_corrente where id = 1 for update;
  if not a.aperta then
    return json_build_object('ok', false, 'errore', 'Nessuna asta aperta');
  end if;
  if a.miglior_importo is null then
    return json_build_object('ok', false, 'errore', 'Nessuna offerta: usa ANNULLA ASTA oppure aspetta un rilancio');
  end if;
  update asta_squadre set crediti = crediti - a.miglior_importo, posti = posti - 1
   where nome = a.miglior_offerente;
  update asta_musicisti set proprietario = a.miglior_offerente, prezzo = a.miglior_importo
   where id = a.musicista_id;
  update asta_corrente set aperta = false, aggiornato = now() where id = 1;
  insert into asta_messaggi (testo)
    values ('AGGIUDICATO: ' || a.musicista || ' a ' || a.miglior_offerente || ' per ' || a.miglior_importo || ' crediti');
  return json_build_object('ok', true, 'musicista_id', a.musicista_id, 'musicista', a.musicista,
                           'giocatore', a.miglior_offerente, 'importo', a.miglior_importo);
end $$;

create or replace function asta_a_annulla(p_admin text) returns json
language plpgsql security definer set search_path = public as $$
declare a asta_corrente%rowtype;
begin
  if not asta_e_admin(p_admin) then
    return json_build_object('ok', false, 'errore', 'Codice admin non valido');
  end if;
  select * into a from asta_corrente where id = 1 for update;
  if not a.aperta then
    return json_build_object('ok', false, 'errore', 'Nessuna asta aperta');
  end if;
  update asta_corrente set aperta = false, miglior_importo = null, miglior_offerente = null, aggiornato = now()
   where id = 1;
  delete from asta_offerte where musicista_id = a.musicista_id;
  insert into asta_messaggi (testo) values ('ASTA ANNULLATA: ' || a.musicista);
  return json_build_object('ok', true);
end $$;

create or replace function asta_a_messaggio(p_admin text, p_testo text) returns json
language plpgsql security definer set search_path = public as $$
begin
  if not asta_e_admin(p_admin) then
    return json_build_object('ok', false, 'errore', 'Codice admin non valido');
  end if;
  if p_testo is null or length(trim(p_testo)) = 0 then
    return json_build_object('ok', false, 'errore', 'Messaggio vuoto');
  end if;
  insert into asta_messaggi (testo) values (left(trim(p_testo), 300));
  return json_build_object('ok', true);
end $$;

-- ---------- permessi di esecuzione ----------
revoke execute on function asta_login(text), asta_ping(text), asta_rilancia(text, int),
  asta_a_sync(text, jsonb, jsonb, jsonb), asta_a_apri(text, int, int), asta_a_aggiudica(text),
  asta_a_annulla(text), asta_a_messaggio(text, text) from public;
grant execute on function asta_login(text), asta_ping(text), asta_rilancia(text, int),
  asta_a_sync(text, jsonb, jsonb, jsonb), asta_a_apri(text, int, int), asta_a_aggiudica(text),
  asta_a_annulla(text), asta_a_messaggio(text, text) to anon, authenticated;
