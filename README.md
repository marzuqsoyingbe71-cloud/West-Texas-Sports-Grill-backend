# West Texas Sports Grill Backend

This backend supports the `westnew.html` frontend with menu, orders, reservations, reviews, admin management, and image uploads.

## Setup

1. Create a Python virtual environment:

```powershell
cd c:\Users\user\Documents\westnew\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

2. Install dependencies:

```powershell
pip install -r requirements.txt
```

## Run

```powershell
uvicorn main:app --reload --host 127.0.0.1 --port 8000
```

Then open the site in your browser at:

```text
http://127.0.0.1:8000/
```

Do not open `westnew.html` directly from `file://` if you want the API to work.

## Default admin login

- Email: `admin@wtsg.local`
- Password: `admin123`

## Notes

- The data is stored in `db.json`.
- Uploaded images are saved to `static/uploads/`.
- If the frontend is served locally in the same workspace, it will connect to `http://localhost:8000/api`.
