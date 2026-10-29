# Digital Yard — Development Logbook

**Datum:** 2026-10-28  
**Projekat:** Digital Yard / Yard Assistant  
**Milestone:** YA-01 — Reliable Hive Inspection Extraction & Data Integrity  
**Faza:** Implementacija završena — pre-deployment validacija  
**Status:** Implemented / Pending Runtime Acceptance

---

## 1. Kontekst i cilj sesije

Nakon uspešnog oporavka Yard Assistant aplikacije i ponovnog uspostavljanja GPU/CUDA funkcionalnosti, izvršeno je testiranje glasovnog evidentiranja pčelarskih inspekcija.

Testni zapis *Log #25* potvrdio je da aplikacija može da primi audio snimak, izvrši Whisper transkripciju i sačuva zapis u SQLite bazu.

Međutim, identifikovan je značajan problem: iako je transkript sadržao korisne informacije o pčelinjem društvu, strukturisani podaci uglavnom su ostajali prazni (`null`), a identifikator košnice bio je `UNKNOWN`.

Dodatno su uočeni nedovoljno transparentno ponašanje aplikacije prilikom grešaka i ograničen kvalitet izvoza podataka.

**Glavni cilj ove sesije bio je unapređenje pouzdanosti ekstrakcije, očuvanja originalnih zapisa i integriteta baze podataka.**

Dogovoreno je da se sistem bodovanja društava, sezonske procene i preporuke izdvoje iz trenutnog razvojnog opsega i kasnije implementiraju kao odvojena analitička komponenta.

## 2. Analiza postojeće implementacije

Analizirani su postojeći `main.py`, `services.py`, `db.py`, prompt i struktura SQLite baze.

Identifikovani su sledeći problemi:

### 2.1. Silent fallback tokom ekstrakcije

Funkcija `ollama_extract()` prikrivala je greške Ollama zahteva, nevalidnog JSON odgovora i validacije vraćanjem podrazumevanog objekta.

Takav objekat sadržao je `UNKNOWN` identifikator košnice, pretpostavljeni tip pregleda `brzi` i uglavnom prazna polja.

Posledica: neuspešna ekstrakcija mogla je izgledati kao uspešno završen zapis.

### 2.2. Nepouzdana validacija

Postojeća implementacija bila je tolerantna prema nevalidnim vrednostima, koje su se u pojedinim slučajevima automatski pretvarale u `null`.

To je otežavalo razlikovanje stvarno nepoznate informacije od greške LLM-a.

### 2.3. Kasno čuvanje originalnog transkripta

Originalni transkript čuvao se tek nakon Ollama obrade.

Ukoliko bi LLM zahtev bio neuspešan, postojao je rizik da transkribovan sadržaj uopšte ne bude evidentiran.

### 2.4. Nedostatak povezivanja zapisa

Originalni logovi i normalizovane inspekcije nisu imali eksplicitnu relacijsku vezu.

Ponovljena ekstrakcija mogla je dovesti do dupliranja inspekcija.

### 2.5. Neadekvatan opseg LLM prompta

Prvobitni prompt zahtevao je istovremeno:

- Ekstrakciju činjenica.
- Procenu jačine društva.
- Procenu rezervi hrane.
- Predviđanje rizika.
- Generisanje preporuka.
- Izračunavanje numeričkih ocena.

Odlučeno je da LLM u ovom delu sistema bude isključivo alat za ekstrakciju zabeleženih činjenica.

## 3. Implementirane izmene — YA-01

Za implementaciju je korišćen Codex, sa zadatkom da unapredi postojeću arhitekturu bez izmene infrastrukture.

### 3.1. Nova arhitektura obrade

Implementiran je jasnije definisan pipeline:

**Audio → Whisper → Raw persistence → Ollama → Validation → Normalized persistence → Review**

Sada se originalni audio i transkript čuvaju pre poziva Ollama servisa.

Ako ekstrakcija ne uspe, izvorni zapis ostaje sačuvan i može se ponovo obraditi.

### 3.2. Nova logika ekstrakcije

Izmenjeni su `services.py` i `schemas.py`.

Implementirano je:

- Strože Pydantic validiranje.
- Eksplicitno prijavljivanje grešaka.
- Strukturisani Ollama JSON izlaz.
- Konzervativno izdvajanje činjenica.
- Normalizacija srpskih oznaka košnica.
- Odbacivanje nedozvoljenih polja i vrednosti.

Uveden je verzionisani prompt `hive_semantics_v2`.

Novi prompt ne računa ocene društava i ne generiše preporuke koje nisu eksplicitno navedene kao izvršene aktivnosti.

### 3.3. Nova SQLite šema v2

Implementirana je čistija struktura baze, prilagođena razvojnoj fazi aplikacije.

Ključne celine su:

- `hive_logs` — originalni izvori, audio i transkripti.
- `extraction_attempts` — pokušaji ekstrakcije i njihovi rezultati.
- `hives` — registar košnica.
- `inspections` — validirani strukturisani zapisi.

Svaka inspekcija povezana je sa svojim originalnim logom i pokušajem ekstrakcije.

Ponovljena obrada ne treba da kreira duplikate već evidentirane inspekcije.

Analitička tabela `inspection_metrics` uklonjena je iz aktivnog v2 modela. Scoring nije deo trenutnog procesa evidentiranja.

### 3.4. Praćenje statusa

Uvedeni su eksplicitni statusi obrade:

- `pending` — obrada nije završena.
- `completed` — obrada je uspešno završena.
- `failed` — obrada je neuspešna.

Status ekstrakcije razlikuje se od statusa normalizacije.

Uspešna LLM ekstrakcija ne podrazumeva automatski uspešno čuvanje inspekcije.

Takođe je uveden status korisničke potvrde:

- `unreviewed`
- `confirmed`

Ispravljanje pojedinačnih polja i istorija korekcija još nisu implementirani.

### 3.5. Reprocessing

Dodat je API endpoint:

`POST /api/logs/{log_id}/reprocess`

Omogućava ponovno pokretanje ekstrakcije nad prethodno sačuvanim transkriptom, bez ponovnog snimanja audio poruke.

Prethodni pokušaji ostaju evidentirani.

### 3.6. API i korisnički interfejs

Ažuriran je `main.py`, uveden je `pipeline.py` i prilagođeni su relevantni frontend template-i.

Implementirani su:

- Preciznija povratna informacija o uspehu i greškama.
- Pregled sačuvanih transkripata.
- Pregled pokušaja ekstrakcije.
- Pregled normalizovanih činjenica.
- Potvrđivanje inspekcije.

Ovim je razdvojena automatska ekstrakcija od ljudskog odobravanja zapisa.

### 3.7. Izvoz i prenosivost

Unapređen je izvoz podataka:

| Format | Namena |
|---|---|
| JSON | Kompletna evidencija, originali i metapodaci |
| CSV | Istorija inspekcija za Excel |
| SQLite | Konzistentan snapshot baze |

Dodat je `/export/inspections.csv`, koji izvozi istorijske inspekcije, a ne samo trenutno stanje košnica.

CSV izvoz sada uključuje UTF-8 BOM radi bolje kompatibilnosti sa Excelom i zaštitu od formula injection napada.

SQLite izvoz koristi backup API, umesto direktnog preuzimanja aktivnog fajla baze.

## 4. Upravljanje razvojnom bazom

Pošto su svi dosadašnji pčelarski podaci sintetički i testni, odlučeno je da nije potrebno održavati potpunu kompatibilnost sa starom šemom.

Implementiran je `db_cli.py`, koji omogućava eksplicitne operacije:

- `init` — inicijalizacija baze.
- `seed` — dodavanje determinističkih testnih podataka.
- `check` — provera kompatibilnosti šeme.
- `backup` — kreiranje konzistentnog backup-a.
- `reset` — kontrolisano resetovanje razvojne baze.
- `recover-pending` — oporavak prekinutih pokušaja.

Nova šema koristi SQLite `user_version=2`.

Pokretanje aplikacije ne izvršava automatske migracije niti resetovanje baze. Ako je šema nekompatibilna, pokretanje se odbija.

Ovo odvaja upravljanje životnim ciklusom baze od redovnog rada API-ja.

## 5. Implementirani regresioni testovi

Dodat je automatizovani testni skup koji ne zahteva aktivan Whisper, Ollama ili GPU.

Codex je prijavio:

**92 uspešno izvršena testa.**

Obuhvaćeni su:

- Validacija JSON odgovora.
- Normalizacija identifikatora košnica.
- Obrada nevalidnih podataka.
- Ollama timeout i connection error.
- Čuvanje izvornog transkripta.
- SQLite transakcije i rollback.
- Sprečavanje duplih zapisa.
- Ponovljena ekstrakcija.
- Potvrđivanje inspekcija.
- JSON/CSV/SQLite izvoz.
- Inicijalizacija i resetovanje baze.
- Odbijanje nekompatibilne šeme.

Izvršene su i Python compilation provere, JavaScript sintaksne provere i testiranje CLI reset/reseed postupka na privremenim bazama.

### Regresioni slučaj — Log #25

Korišćen je sintetički transkript koji sadrži:

- Društvo broj 1.
- Mirno ponašanje.
- Viđenu maticu.
- Četiri rama sa leglom.
- Prisustvo otvorenog i zatvorenog legla.
- Pet ramova sa medom.
- Pogaču potrošenu do pola.

Test očekuje `H1`, odgovarajuće numeričke i logičke vrednosti i očuvanje tekstualnih napomena.

Izraz „sveže zasejano“ namerno se čuva kao tekst dok se prisustvo jaja ne potvrdi, umesto da se automatski upiše nepouzdana vrednost.

**Važno:** Test je deterministički i koristi pripremljen odgovor. On ne dokazuje da će lokalni Ollama model samostalno prepoznati sve navedene činjenice.

## 6. Stanje infrastrukture

U toku ove razvojne sesije nisu menjani:

- Docker Compose infrastruktura.
- Ollama ili Whisper modeli.
- NVIDIA drajveri i CUDA konfiguracija.
- Tailscale Serve.
- Mrežna konfiguracija Digital Yard-a.
- Storage mount-ovi.
- Aktivna SQLite baza.

Izmene su implementirane u kodu i proverene automatizovanim testovima.

**Deployment nove verzije još nije izvršen.**

## 7. Preostale aktivnosti — pre-deployment i acceptance test

Sledeća sesija posvećena je bezbednom uvođenju YA-01 na `yard-mill-01`.

Plan:

1. Proveriti Git stanje i Docker Compose konfiguraciju.
2. Potvrditi prosleđivanje `DB_PATH` promenljive kontejneru.
3. Sačuvati prethodnu API image verziju, konfiguraciju i SQLite backup.
4. Izgraditi novi `assistant-api` image.
5. Inicijalizovati novu SQLite v2 bazu.
6. Pokrenuti novu API verziju, bez izmene ostalih servisa.
7. Proveriti `/health` endpoint i stabilnost kontejnera.
8. Izvršiti end-to-end test glasovnog unosa.
9. Proveriti ekstrakciju sintetičkog Log #25 primera.
10. Testirati neuspešnu ekstrakciju i očuvanje izvornog transkripta.
11. Proveriti reprocessing, potvrđivanje i izvoze.
12. Dokumentovati rezultate i eventualne probleme.

Potrebno je potvrditi da deployed Ollama verzija podržava izabrani JSON schema format.

Ako nije podržan, dokumentovana je alternativna konfiguracija sa `OLLAMA_FORMAT=json`.

## 8. Poznata ograničenja

- Stvarna tačnost ekstrakcije lokalnog LLM modela nije potvrđena.
- Whisper transkripcija nije ponovo testirana sa novim kodom.
- Ručna izmena transkripta i pojedinačnih polja nije implementirana.
- Nije implementirana istorija korisničkih korekcija.
- Još ne postoji namenski scoring/analitički servis.
- Nema multi-user/autentikacionog sloja.
- Obrada je sinhrona; nema background queue sistema.

Ova ograničenja nisu blokirajuća za kodnu implementaciju YA-01, ali zahtevaju odgovarajuće runtime testiranje pre proglašavanja milestone-a završenim.

## 9. Arhitektonske odluke

Tokom sesije usvojeni su sledeći principi:

**Original je izvor istine.** AI interpretacija nikada ne sme da zameni izvorni transkript.

**Nepoznata vrednost nije nula.** Ako nešto nije pouzdano identifikovano, ostaje nepoznato.

**Greška mora biti vidljiva.** Neuspešna ekstrakcija ne sme izgledati kao uspešno evidentirana inspekcija.

**Ekstrakcija i analitika su odvojene odgovornosti.** Budući scoring sistem koristi postojeće potvrđene zapise.

**Podaci moraju biti prenosivi.** JSON, CSV i SQLite predstavljaju osnovne formate za izvoz, backup i migraciju aplikacije.

**Automatski unos ne znači automatsku potvrdu.** Korisnik zadržava kontrolu nad konačnom evidencijom.

## 10. Zaključak

YA-01 predstavlja značajan korak od eksperimentalnog glasovnog logbook-a ka pouzdanom sistemu za prikupljanje strukturisanih pčelarskih podataka.

Prethodni tok mogao je da sakrije greške, izgubi transkript prilikom neuspešne ekstrakcije i sačuva nepotpune podatke kao da su uspešno obrađeni.

Nova implementacija uvodi očuvanje izvora, eksplicitne statuse, validaciju, sledljivost pokušaja, kontrolisanu bazu i potpunije izvoze.

**Rezultat sesije:** YA-01 implementacija je završena i prijavljeno je 92 prolazna automatizovana testa. Runtime acceptance i deployment ostaju otvoreni.

**Sledeći milestone:** YA-01 Runtime Acceptance & Deployment.

**Naredni razvojni korak nakon prihvatanja:** YA-02 — Transcript & Field Editing, sa istorijom korekcija i korisničkim potvrđivanjem finalnog zapisa.

---

**Status na kraju sesije:** CODE COMPLETE / TESTED / NOT DEPLOYED