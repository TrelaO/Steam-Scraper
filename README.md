# Steam AI-ETL

Mini-hurtownia danych Steam z autogeneracją kodu ETL przez LLM (Gemini). System przyjmuje
ten sam zbiór danych Steam w trzech formatach (CSV, JSON, XLSX), wykrywa format i za każdym
razem zleca modelowi wygenerowanie kodu mapującego dane na wspólny model gwiazdy, aby
porównać, jak LLM radzi sobie z różnymi formatami wejścia.

## Model danych

Schemat gwiazdy w SQLite: `dim_date`, `dim_platform`, `dim_game`, `dim_genre`
(+ `bridge_game_genre`) jako wymiary, `fact_game` jako tabela faktów. DDL i seedy
(`dim_date`, `dim_platform`) w [backend/app/db.py](backend/app/db.py).

## Uruchomienie — Docker (zalecane, jeden port, bez instalowania Pythona/Node)

Wymaga tylko [Docker Desktop](https://www.docker.com/products/docker-desktop/). FastAPI
serwuje zbudowany frontend (statyczne pliki z `npm run build`) i API pod `/api` — jeden
proces, jeden port (`:8000`).

```bash
copy .env.example .env   # wpisz GEMINI_API_KEY z aistudio.google.com
docker compose up --build
```

Aplikacja pod http://localhost:8000.

### Jedno kliknięcie

- Windows: dwuklik na [start.bat](start.bat) — odpala `docker compose up` w tle i sam
  otwiera http://localhost:8000 w przeglądarce, gdy backend odpowie.
- Mac/Linux: `./start.sh` (lub dwuklik, jeśli ustawione jako uruchamialne w Finderze).

Oba skrypty zakładają, że Docker Desktop jest zainstalowany i uruchomiony oraz że `.env`
z `GEMINI_API_KEY` istnieje w katalogu głównym repo (patrz wyżej). `docker-compose.yml`
montuje `backend/data`, `backend/landing`, `backend/generated_etl` jako bind-mounty, więc
warehouse.db i wygenerowany kod ETL lądują bezpośrednio w repo, nie tylko w kontenerze.

## Uruchomienie — bez Dockera (dev / dwa procesy)

### Backend (FastAPI)

```bash
cd backend
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env   # wpisz GEMINI_API_KEY z aistudio.google.com
uvicorn app.main:app --reload --port 8000
```

Endpointy (wszystkie pod `/api`):
- `POST /api/upload` — przyjmuje plik, wykrywa format (csv/json/xlsx), zwraca `file_id`
- `POST /api/etl/run/{file_id}` — generuje kod ETL przez Gemini, wykonuje go w sandboxie
  (do 3 prób z samopoprawianiem na błędach), zapisuje wygenerowany kod do `generated_etl/`
- `GET /api/etl/status/{job_id}` — status/logi/kod danego uruchomienia
- `GET /api/analytics/*` — zapytania pod dashboard (cena/zniżka wg gatunku i roku, cena vs
  recenzje, wariancja ceny wg platformy)

### Frontend (React + Vite + TS)

Wymaga Node.js (nie jest zainstalowany w tym środowisku — zainstaluj lokalnie).

```bash
cd frontend
npm install
npm run dev
```

Dev server na `:5173` proxuje `/api` do backendu na `:8000` (patrz
[frontend/vite.config.ts](frontend/vite.config.ts)) — backend musi wtedy działać osobno.

Strony: `Upload` (drag&drop + wykryty format), `PipelineRun` (wygenerowany kod + logi
wykonania), `Dashboard` (wykresy trendów, recharts).

## Dane wejściowe

- CSV + JSON: [Kaggle "Steam Games Dataset"](https://www.kaggle.com/datasets/fronkongames/steam-games-dataset)
  (`games.csv`, `games.json` — ta sama treść w dwóch formatach).
- XLSX: dokładany osobno (np. tabela kursów walut / słownik gatunków), eksport przez
  `pandas.to_excel()`.

Pliki źródłowe wgrywa się przez `/upload`; nie są commitowane (`backend/landing/`
zignorowane w git). Wygenerowany kod ETL per format w `backend/generated_etl/` JEST
commitowany jako artefakt badawczy do porównania między formatami.

## Otwarte pytania

- Analiza tylko kohort rocznikowych (`release_date`) czy realny time-series ze snapshotów
  Steam Web API / IsThereAnyDeal (wymaga cyklicznego pobierania w czasie trwania projektu).
- Porównanie Gemini vs inny model jako wzmocnienie części badawczej.
