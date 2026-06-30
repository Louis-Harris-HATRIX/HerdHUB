# BoerHUB QA Checklist

Branding asset reference: `static/branding/boerhub-logo.png`

## Animal Photo Functionality QA

### What was tested
- Upload photo from desktop to an animal profile.
- Edit animal with a new main profile photo.
- View animal detail page with main photo and gallery.
- Set an additional photo as primary.
- Delete a photo from the gallery.
- Logged-out upload attempt to animal photo endpoint.
- Invalid file type upload rejection.
- Oversized file upload rejection (>5MB).
- Mobile camera support attribute on file inputs (`capture="environment"`).

### What passed
- Desktop upload succeeded and photo persisted.
- Animal edit with photo upload succeeded and main profile photo updated.
- Animal detail page returned 200 and rendered photo sections.
- Set primary action worked and returned to the detail page.
- Delete photo action worked and returned to the detail page.
- Logged-out users were redirected to login for upload routes.
- Invalid file types were rejected.
- Oversized uploads were rejected with redirect and flash messaging.
- Camera capture support is present on upload inputs.

### Bugs found
- Animal model did not support a main profile photo path.
- No table existed for additional animal photos.
- Animal add/edit forms had no photo upload controls.
- Animal detail page had no gallery management.
- No backend validation/storage pipeline for image uploads.
- Animal list had no thumbnail/placeholder rendering.

### What was fixed
- Added `main_photo_path` to the animal data model.
- Added `AnimalPhoto` table/model with caption, uploader, uploaded timestamp, and primary flag.
- Added secure upload validation:
	- allowed extensions and MIME checks
	- image signature verification
	- secure filenames
	- upload size cap (5MB)
- Added secure storage under uploads folder.
- Added protected image serving route scoped to the target animal.
- Added photo management routes:
	- upload additional photo
	- set primary photo
	- delete photo
- Updated animal add/edit forms with image upload + camera capture support.
- Updated animal detail page with main photo, gallery, upload form, set-primary, and delete actions.
- Updated animal list to show thumbnail or placeholder icon.

## Phase 2 (Reports and Daily Farm Diary)

### What was tested
- `/reports` as logged-out user, Admin, and Farm Manager.
- `/diary` as logged-out user, Admin, and Farm Manager.
- Diary creation flow via `POST /diary/new`.
- Diary edit flow via `POST /diary/<id>/edit`.
- Reports filters rendering: species, camp, date range, status.
- Disabled export buttons rendering with `Coming Soon` labels.

### What passed
- Logged-out user is redirected to `/login?next=/reports` and `/login?next=/diary`.
- Admin can access `/reports` and `/diary`.
- Farm Manager can access `/reports` and `/diary`.
- Diary entry creation redirects back to `/diary` and persists.
- Diary entry editing redirects back to `/diary` and updates fields.
- Reports page renders all required table-based totals:
	- Livestock Count
	- Animals by Camp
	- Births
	- Deaths / Losses
	- Health Treatments
	- Sales
	- Purchases
	- Tasks

### Bugs found
- `/reports` did not explicitly enforce Admin/Farm Manager role check.
- `/diary` listing route did not explicitly enforce Admin/Farm Manager role check.
- Reports view used summary cards without clean table sections for each required report.
- Status filter control was missing from reports filter UI.
- Diary entries did not display created/updated audit metadata.

### What was fixed
- Added explicit `require_role("admin", "manager")` checks to `/reports` and `/diary`.
- Reworked reports output into table-based report sections with relevant totals.
- Added status filter dropdown to the reports filter panel.
- Kept `Export PDF` and `Export Excel` visible and disabled with `Coming Soon` text.
- Added diary audit metadata display:
	- Created by
	- Created date
	- Updated by
	- Updated date
- Added dashboard quick links/cards for:
	- Reports
	- Daily Farm Diary
	- Add Diary Entry

## What was tested
- Authentication flow for guest, admin, and manager sessions.
- Logout behavior and post-logout access checks.
- Route protection and redirects for all requested pages:
	- /dashboard
	- /animals
	- /groups
	- /camps
	- /movements
	- /health-records
	- /breeding
	- /births
	- /deaths
	- /sales
	- /tasks
	- /users
	- /activity
- Role authorization rules for Admin and Farm Manager.
- Navigation visibility in logged-out and manager sessions.
- Friendly error responses for 403 and 404.

## What passed
- Logged-out requests to protected routes redirect to /login with next parameter.
- Admin can access all tested operational and admin routes.
- Manager can access operational routes and is blocked from /users and /activity.
- Logout clears session and protected pages redirect to login afterward.
- Cache-control headers are set to prevent protected content reuse after logout/back.
- Navigation hides operational menu for guests and hides admin links for managers.
- 403 and 404 pages return correct HTTP status codes.

## Bugs found
- Legacy plain-text passwords failed after password hashing was introduced.
- Guest UI showed an admin role label in the header.
- Admin navigation grouped links unclearly and did not expose Activity/Settings directly.
- Missing cache headers allowed a risk of browser back showing stale protected pages.

## What was fixed
- Added backward-compatible password verification and automatic hash upgrade on login.
- Changed guest header role label from Admin / Farm Owner to Guest.
- Added no-store/no-cache headers on responses.
- Refined role-aware navigation:
	- Guests only see Login.
	- Managers see operational menu only.
	- Admins see Users, Activity, and Settings links.
- Confirmed role restrictions return 403 for forbidden pages.
- Confirmed unknown pages return 404.

## Replit Deployment Readiness QA

### What was tested
- Production environment config loading (`FLASK_ENV`, `SECRET_KEY`, `DATABASE_URL`).
- App startup with `python app.py` in production mode.
- Protected-route redirect behavior for logged-out users.
- Core pages after login:
	- `/dashboard`
	- `/animals`
	- `/tasks`
	- `/reports`
	- `/diary`
- Animal photo upload pipeline (multipart image upload + DB record).
- Role restrictions for manager against admin-only route (`/users`).
- Seed behavior on an empty database.

### What passed
- App reports production mode and runs with `debug=False` when `FLASK_ENV=production`.
- Secret key is read from environment (`SECRET_KEY`) as expected.
- Default database fallback remains SQLite when `DATABASE_URL` is not set.
- `python app.py` starts successfully and binds to host/port.
- Logged-out access to `/dashboard` redirects to `/login?next=/dashboard`.
- Owner login works and all core operational pages return HTTP 200.
- Photo upload returns redirect success and creates an `AnimalPhoto` DB row with stored file path.
- Manager login works and `/users` returns HTTP 403.
- On a fresh empty DB, seed creates exactly one user (`owner`, role `admin`).

### Bugs found
- None in this deployment readiness pass.

### What was fixed
- Added production-safe environment config in app startup logic.
- Added `SECRET_KEY`/`DATABASE_URL` scaffolding via `.env.example`.
- Added Replit deployment documentation in `README.md`.
- Updated dependency manifest for deployment/runtime compatibility.
- Simplified seeding to owner-only bootstrap behavior for empty databases.
