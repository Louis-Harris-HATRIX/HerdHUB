# BoerHUB Flask Livestock Management

## Local Run
1. Install dependencies:
   - `pip install -r requirements.txt`
2. Start app:
   - `python app.py`
3. Open:
   - `http://127.0.0.1:5000`

## Replit Deployment Notes

### Environment Variables
Set these in Replit Secrets (or `.env` for local testing):
- `SECRET_KEY`: required in production and used for session security.
- `FLASK_ENV=production`: enables production mode (`debug=False`).
- `DATABASE_URL`: optional. If not set, app uses local SQLite file `livestock.db`.

Optional seed overrides:
- `OWNER_USERNAME` (default: `owner`)
- `OWNER_PASSWORD` (default: `owner123`)
- `OWNER_FULL_NAME` (default: `Admin / Farm Owner`)

### Production Behavior
- `python app.py` runs with `debug=False` when `FLASK_ENV=production`.
- `SECRET_KEY` is loaded from environment variable.
- Protected routes still require login.
- Animal photo uploads are stored under `uploads/animals` and served through protected routes.
- Database tables initialize automatically at startup.
- Seed logic only creates owner user when `User` table is empty.

### Deploy on Replit
1. Add secrets from `.env.example`.
2. Install packages from `requirements.txt`.
3. Run command: `python app.py`.
4. Ensure persistent storage or external database if long-term file/data retention is required.
5. Default first login on a fresh database: `owner` / `owner123`.

## Import Project Into Replit (Step-by-Step)

1. Create a new Replit project:
   - Click `Create Repl`.
   - Choose `Import from GitHub` (recommended) or `Upload folder`.

2. Import code:
   - GitHub path: paste your repository URL and import.
   - Upload path: zip this project root and upload it so root contains `app.py`, `requirements.txt`, `templates`, `static`, `uploads`, and `.env.example`.

3. Configure Secrets in Replit:
   - Open `Tools -> Secrets`.
   - Add at minimum:
     - `SECRET_KEY` (long random value)
     - `FLASK_ENV` = `production`
   - Optional:
     - `DATABASE_URL` (Postgres URL) or leave empty to use SQLite.
     - `OWNER_USERNAME`, `OWNER_PASSWORD`, `OWNER_FULL_NAME` if you want custom initial admin seed values.

4. Install dependencies:
   - Run `pip install -r requirements.txt` in Replit Shell.

5. Start the app:
   - Run `python app.py`.
   - Confirm logs show `Running on http://0.0.0.0:5000`.

6. Verify first login on fresh DB:
   - Username: `owner`
   - Password: `owner123`

7. Persistence guidance:
   - SQLite and uploads work for quick testing.
   - For durable production data, use Replit persistent storage and/or Postgres via `DATABASE_URL`.

### Notes on Uploads
- Allowed image types: `jpg`, `jpeg`, `png`, `webp`.
- Maximum upload size: 5MB.
- Upload endpoints are role-protected (`admin` and `manager`).
Workflow test: 2026-06-30
