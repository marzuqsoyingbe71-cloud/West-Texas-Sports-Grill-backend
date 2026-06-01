from fastapi import FastAPI, HTTPException, Depends, File, UploadFile, Form
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from typing import Optional, List, Dict
from pathlib import Path
from uuid import uuid4
from datetime import datetime, date
from threading import Lock
import json
import shutil

BASE_DIR = Path(__file__).parent
DB_PATH = BASE_DIR / "db.json"
UPLOAD_DIR = BASE_DIR / "static" / "uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)

security = HTTPBearer(auto_error=False)
app = FastAPI(title="West Texas Sports Grill API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.mount("/static", StaticFiles(directory=BASE_DIR / "static"), name="static")

@app.get("/", response_class=FileResponse)
async def serve_site():
    return FileResponse(Path(BASE_DIR.parent / "westnew.html"))

db_lock = Lock()
active_tokens: Dict[str, int] = {}

ALL_TIMES = [
    "15:00","15:30","16:00","16:30","17:00","17:30","18:00","18:30","19:00","19:30","20:00","20:30","21:00"
]


def load_db():
    with DB_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


def save_db(data):
    with db_lock:
        with DB_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)


def require_auth(credentials: HTTPAuthorizationCredentials = Depends(security)):
    if not credentials or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Authentication required")
    token = credentials.credentials
    user_id = active_tokens.get(token)
    if not user_id:
        raise HTTPException(status_code=401, detail="Invalid token")
    data = load_db()
    user = next((u for u in data["users"] if u["id"] == user_id), None)
    if not user:
        raise HTTPException(status_code=401, detail="User not found")
    return user


def require_admin(user=Depends(require_auth)):
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


class AuthResponse(BaseModel):
    access_token: str
    user: dict


class MenuItemCreate(BaseModel):
    name: str
    category_id: int
    price: float
    description: Optional[str] = None
    calories: Optional[int] = None
    allergens: Optional[str] = None
    is_featured: bool = False
    is_popular: bool = False
    is_spicy: bool = False
    is_available: bool = True


class OrderItemPayload(BaseModel):
    menu_item_id: int
    quantity: int


class OrderCreate(BaseModel):
    order_type: str
    items: List[OrderItemPayload]
    special_instructions: Optional[str] = None
    delivery_address: Optional[str] = None
    guest_name: Optional[str] = None
    guest_email: Optional[str] = None
    guest_phone: Optional[str] = None


class ReviewPayload(BaseModel):
    name: str
    title: Optional[str] = None
    body: str
    rating: int = Field(..., ge=1, le=5)


class ReservationPayload(BaseModel):
    name: str
    email: str
    phone: str
    party_size: int = Field(..., ge=1, le=20)
    date: str
    time: str
    special_requests: Optional[str] = None


class UserRegister(BaseModel):
    name: str
    email: str
    phone: Optional[str] = None
    password: str


@app.get("/api/menu/categories")
async def get_categories():
    data = load_db()
    return sorted(data["categories"], key=lambda x: x["sort_order"])


@app.get("/api/menu/items")
async def get_menu_items(featured: Optional[bool] = None):
    data = load_db()
    items = data["menu_items"]
    if featured is not None:
        items = [item for item in items if item.get("is_featured") == featured]
    return items


@app.post("/api/menu/items")
async def create_menu_item(payload: MenuItemCreate, user=Depends(require_admin)):
    data = load_db()
    item_id = data["next_ids"]["menu_item"]
    item = payload.dict()
    item.update({"id": item_id})
    data["menu_items"].append(item)
    data["next_ids"]["menu_item"] += 1
    save_db(data)
    return item


@app.put("/api/menu/items/{item_id}")
async def update_menu_item(item_id: int, payload: MenuItemCreate, user=Depends(require_admin)):
    data = load_db()
    item = next((i for i in data["menu_items"] if i["id"] == item_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="Item not found")
    item.update(payload.dict())
    save_db(data)
    return item


@app.delete("/api/menu/items/{item_id}")
async def delete_menu_item(item_id: int, user=Depends(require_admin)):
    data = load_db()
    data["menu_items"] = [i for i in data["menu_items"] if i["id"] != item_id]
    save_db(data)
    return {"success": True}


@app.post("/api/auth/login", response_model=AuthResponse)
async def login(username: str = Form(...), password: str = Form(...)):
    data = load_db()
    user = next((u for u in data["users"] if u["email"].lower() == username.lower() and u["password"] == password), None)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = str(uuid4())
    active_tokens[token] = user["id"]
    return {"access_token": token, "user": {k: v for k, v in user.items() if k != "password"}}


@app.post("/api/auth/register", response_model=AuthResponse)
async def register(payload: UserRegister):
    data = load_db()
    if any(u["email"].lower() == payload.email.lower() for u in data["users"]):
        raise HTTPException(status_code=400, detail="Email already registered")
    user = payload.dict()
    user_id = data["next_ids"]["user"]
    user.update({"id": user_id, "role": "member"})
    data["users"].append(user)
    data["next_ids"]["user"] += 1
    save_db(data)
    token = str(uuid4())
    active_tokens[token] = user_id
    return {"access_token": token, "user": {k: v for k, v in user.items() if k != "password"}}


@app.post("/api/orders/")
async def create_order(payload: OrderCreate):
    data = load_db()
    if not payload.items:
        raise HTTPException(status_code=400, detail="Order must include items")
    items = []
    sub_total = 0.0
    for entry in payload.items:
        menu_item = next((m for m in data["menu_items"] if m["id"] == entry.menu_item_id), None)
        if not menu_item or not menu_item.get("is_available", True):
            raise HTTPException(status_code=400, detail=f"Menu item not available: {entry.menu_item_id}")
        items.append({"menu_item_id": entry.menu_item_id, "name": menu_item["name"], "quantity": entry.quantity, "price": menu_item["price"]})
        sub_total += menu_item["price"] * entry.quantity
    tax = round(sub_total * 0.0825, 2)
    delivery = 4.99 if payload.order_type == "delivery" else 0.0
    total = round(sub_total + tax + delivery, 2)
    order_id = data["next_ids"]["order"]
    order = {
        "id": order_id,
        "order_type": payload.order_type,
        "items": items,
        "special_instructions": payload.special_instructions,
        "delivery_address": payload.delivery_address,
        "guest_name": payload.guest_name or payload.guest_email or "Guest",
        "guest_email": payload.guest_email,
        "guest_phone": payload.guest_phone,
        "status": "pending",
        "total": total,
        "tax": tax,
        "delivery_fee": delivery,
        "created_at": datetime.utcnow().isoformat(),
        "estimated_time": 20 if payload.order_type == "delivery" else 15
    }
    data["orders"].append(order)
    data["next_ids"]["order"] += 1
    save_db(data)
    return order


@app.get("/api/orders/")
async def list_orders(user=Depends(require_admin)):
    data = load_db()
    return sorted(data["orders"], key=lambda x: x["id"], reverse=True)


@app.put("/api/orders/{order_id}/status")
async def update_order_status(order_id: int, payload: dict, user=Depends(require_admin)):
    data = load_db()
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    status = payload.get("status")
    if status not in ["pending", "confirmed", "preparing", "ready", "out_for_delivery", "delivered", "cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid order status")
    order["status"] = status
    save_db(data)
    return order


@app.get("/api/orders/track/{order_id}")
async def track_order(order_id: int):
    data = load_db()
    order = next((o for o in data["orders"] if o["id"] == order_id), None)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    return order


@app.get("/api/reviews/")
async def list_reviews():
    data = load_db()
    return sorted([r for r in data["reviews"] if r.get("approved")], key=lambda x: x["id"], reverse=True)


@app.post("/api/reviews/")
async def create_review(payload: ReviewPayload):
    data = load_db()
    review_id = data["next_ids"]["review"]
    review = payload.dict()
    review.update({"id": review_id, "approved": False, "created_at": datetime.utcnow().isoformat()})
    data["reviews"].append(review)
    data["next_ids"]["review"] += 1
    save_db(data)
    return review


@app.get("/api/reviews/pending")
async def pending_reviews(user=Depends(require_admin)):
    data = load_db()
    return [r for r in data["reviews"] if not r.get("approved")]


@app.put("/api/reviews/{review_id}/approve")
async def approve_review(review_id: int, user=Depends(require_admin)):
    data = load_db()
    review = next((r for r in data["reviews"] if r["id"] == review_id), None)
    if not review:
        raise HTTPException(status_code=404, detail="Review not found")
    review["approved"] = True
    save_db(data)
    return review


@app.delete("/api/reviews/{review_id}")
async def delete_review(review_id: int, user=Depends(require_admin)):
    data = load_db()
    data["reviews"] = [r for r in data["reviews"] if r["id"] != review_id]
    save_db(data)
    return {"success": True}


@app.get("/api/reservations/available-times")
async def available_times(date: str):
    data = load_db()
    reservations = [r for r in data["reservations"] if r["date"] == date and r["status"] != "cancelled"]
    counts = {t: 0 for t in ALL_TIMES}
    for r in reservations:
        if r["time"] in counts:
            counts[r["time"]] += 1
    available = [t for t in ALL_TIMES if counts[t] < 4]
    return {"times": available}


@app.post("/api/reservations/")
async def create_reservation(payload: ReservationPayload):
    data = load_db()
    if payload.time not in ALL_TIMES:
        raise HTTPException(status_code=400, detail="Invalid time")
    if payload.date < date.today().isoformat():
        raise HTTPException(status_code=400, detail="Cannot reserve a past date")
    reservation_id = data["next_ids"]["reservation"]
    reservation = payload.dict()
    reservation.update({"id": reservation_id, "status": "pending", "created_at": datetime.utcnow().isoformat()})
    data["reservations"].append(reservation)
    data["next_ids"]["reservation"] += 1
    save_db(data)
    return reservation


@app.get("/api/reservations/")
async def list_reservations(user=Depends(require_admin)):
    data = load_db()
    return sorted(data["reservations"], key=lambda x: x["id"], reverse=True)


@app.put("/api/reservations/{reservation_id}/status")
async def update_reservation_status(reservation_id: int, payload: dict, user=Depends(require_admin)):
    data = load_db()
    reservation = next((r for r in data["reservations"] if r["id"] == reservation_id), None)
    if not reservation:
        raise HTTPException(status_code=404, detail="Reservation not found")
    if payload.get("status") not in ["pending", "confirmed", "cancelled"]:
        raise HTTPException(status_code=400, detail="Invalid status")
    reservation["status"] = payload["status"]
    save_db(data)
    return reservation


@app.get("/api/admin/dashboard")
async def admin_dashboard(user=Depends(require_admin)):
    data = load_db()
    orders = data["orders"]
    today_str = date.today().isoformat()
    today_orders = sum(1 for o in orders if o["created_at"].startswith(today_str))
    today_revenue = sum(o["total"] for o in orders if o["created_at"].startswith(today_str))
    pending_orders = sum(1 for o in orders if o["status"] in ["pending", "confirmed", "preparing"])
    total_orders = len(orders)
    total_revenue = sum(o["total"] for o in orders)
    popular_items = []
    item_counts = {}
    for o in orders:
        for i in o["items"]:
            item_counts[i["menu_item_id"]] = item_counts.get(i["menu_item_id"], 0) + i["quantity"]
    for menu_item_id, qty in sorted(item_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        menu_item = next((m for m in data["menu_items"] if m["id"] == menu_item_id), None)
        if menu_item:
            popular_items.append({"name": menu_item["name"], "quantity": qty})
    pending_reservations = sum(1 for r in data["reservations"] if r["status"] == "pending")
    pending_reviews = sum(1 for r in data["reviews"] if not r["approved"])
    total_customers = len(data["users"])
    return {
        "today_orders": today_orders,
        "today_revenue": round(today_revenue, 2),
        "pending_orders": pending_orders,
        "total_orders": total_orders,
        "total_revenue": round(total_revenue, 2),
        "total_customers": total_customers,
        "pending_reservations": pending_reservations,
        "pending_reviews": pending_reviews,
        "popular_items": popular_items,
    }


@app.get("/api/settings/")
async def get_settings():
    data = load_db()
    return data["settings"]


VALID_SLOTS = {
    "hero_image",
    "photo_strip_1",
    "photo_strip_2",
    "photo_strip_3",
    "menu_bg_image",
    "cocktail_banner_image",
}


@app.post("/api/settings/upload-image/{slot}")
async def upload_image(slot: str, file: UploadFile = File(...), user=Depends(require_admin)):
    if slot not in VALID_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid image slot")
    suffix = Path(file.filename).suffix or ".jpg"
    filename = f"{slot}{suffix}"
    dest = UPLOAD_DIR / filename
    with dest.open("wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    data = load_db()
    data["settings"][slot] = f"/static/uploads/{filename}"
    save_db(data)
    return {"path": data["settings"][slot]}


@app.delete("/api/settings/image/{slot}")
async def delete_image(slot: str, user=Depends(require_admin)):
    if slot not in VALID_SLOTS:
        raise HTTPException(status_code=400, detail="Invalid image slot")
    data = load_db()
    current = data["settings"].get(slot)
    if current and current.startswith("/static/uploads/"):
        file_path = BASE_DIR / current.lstrip("/")
        if file_path.exists():
            file_path.unlink()
    data["settings"][slot] = None
    save_db(data)
    return {"success": True}
