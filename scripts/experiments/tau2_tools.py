"""[scripts] τ²-bench airline, retail 도메인 도구를 평가 전용으로 옮기고 공유 DB 위 덮어쓰기 층에서 실행한다."""

# 출처: sierra-research/tau2-bench v2.0.0 의 src/tau2/domains/{airline,retail}/tools.py, data_model.py,
# src/tau2/environment/environment.py(get_response, to_json_str) (MIT License, Copyright (c) 2025 Sierra Research).
# 동작(검사 순서, 오류 문구, 가격 계산, 원본의 버그까지)을 그대로 옮기고, pydantic 모델 대신 dict 로 둔다.
# 지역화(regional_settings)는 영어 기본 실행에서 꺼져 있어 옮기지 않았다

import ast
import copy
import json
import hashlib
import operator
import unicodedata
from typing import Any
from pathlib import Path
from collections.abc import Callable, Iterator, Mapping

ROOT = Path.home() / ".jarvis" / "benchmarks" / "tau2"
DOMAIN_DIR = ROOT / "src" / "tau2-bench-main" / "data" / "tau2" / "domains"
NOW = "2024-05-15T15:00:00"  # 원본 _get_datetime 의 고정 시각
CABINS = ("business", "economy", "basic_economy")
ORDER_OPTIONAL = ("cancel_reason", "exchange_items", "exchange_new_items", "exchange_payment_method_id",
                  "exchange_price_difference", "return_items", "return_payment_method_id")
_ARITH: dict[type, Callable[[Any, Any], Any]] = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv,
}

Record = dict[str, Any]


def load_base(domain: str, path: Path | None = None) -> dict[str, dict[str, Record]]:
    """db.json 을 읽고 pydantic model_dump 처럼 기본값 필드를 채운다. 프로세스에서 한 번 읽어 공유한다."""
    db: dict[str, dict[str, Record]] = json.loads((path or DOMAIN_DIR / domain / "db.json").read_text("utf-8"))
    if domain == "airline":
        for reservation in db["reservations"].values():
            reservation.setdefault("status", None)
    else:
        for order in db["orders"].values():
            for key in ORDER_OPTIONAL:
                order.setdefault(key, None)
    return db


def fold(text: str) -> str:
    """원본 utils/text_match.fold_for_match: 악센트와 대소문자를 접는다."""
    decomposed = unicodedata.normalize("NFD", text.strip())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).casefold()


def canonical(value: Any) -> str:
    """원본 get_dict_hash 의 직렬화(sort_keys, default=str)."""
    return json.dumps(value, sort_keys=True, default=str)


class OverlayDB:
    """읽기 전용 base 를 공유하고 바뀐 레코드만 복사해 둔다. 과제마다 수십 MB 를 복사하지 않으려고."""

    def __init__(self, base: dict[str, dict[str, Record]]) -> None:
        self.base = base
        self.overlay: dict[str, dict[str, Record]] = {table: {} for table in base}

    def has(self, table: str, key: str) -> bool:
        return key in self.overlay[table] or key in self.base[table]

    def get(self, table: str, key: str) -> Record:
        """읽기용. 돌려받은 레코드를 고치지 않는다(고칠 때는 mut)."""
        return self.overlay[table][key] if key in self.overlay[table] else self.base[table][key]

    def mut(self, table: str, key: str) -> Record:
        if key not in self.overlay[table]:
            self.overlay[table][key] = copy.deepcopy(self.base[table][key])
        return self.overlay[table][key]

    def put(self, table: str, key: str, record: Record) -> None:
        self.overlay[table][key] = record

    def keys(self, table: str) -> Iterator[str]:
        yield from self.base[table]
        yield from (k for k in self.overlay[table] if k not in self.base[table])

    def items(self, table: str) -> Iterator[tuple[str, Record]]:
        for key in self.keys(table):
            yield key, self.get(table, key)

    def changes(self) -> dict[str, dict[str, str]]:
        """base 와 달라진 레코드의 정규 직렬화. 같은 base 위 두 DB 는 이것이 같을 때만 전체 해시가 같다."""
        out: dict[str, dict[str, str]] = {}
        for table, rows in self.overlay.items():
            for key, record in rows.items():
                text = canonical(record)
                if key not in self.base[table] or text != canonical(self.base[table][key]):
                    out.setdefault(table, {})[key] = text
        return out

    def digest(self) -> str:
        return hashlib.sha256(canonical(self.changes()).encode()).hexdigest()


# ── pydantic 검증 흉내: 원본이 모델을 만들 때 막히는 입력은 여기서도 오류로 ──

def _str(value: Any, field: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field}: Input should be a valid string")
    return value


def _int(value: Any, field: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field}: Input should be a valid integer")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            pass
    raise ValueError(f"{field}: Input should be a valid integer")


def _float(value: Any, field: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{field}: Input should be a valid number")
    try:
        return float(value)
    except (TypeError, ValueError):
        raise ValueError(f"{field}: Input should be a valid number") from None


def _literal(value: Any, field: str, allowed: tuple[str, ...]) -> str:
    if value not in allowed:
        raise ValueError(f"{field}: Input should be {', '.join(repr(a) for a in allowed)}")
    return str(value)


def _model(value: Any, field: str, spec: Mapping[str, Callable[[Any, str], Any]]) -> Record:
    """BaseModel(**dict) 처럼 필요한 키만 검증해 남기고 나머지는 버린다."""
    if not isinstance(value, dict):
        raise ValueError(f"{field}: Input should be a valid dictionary")
    out: Record = {}
    for key, check in spec.items():
        if key not in value:
            raise ValueError(f"{field}.{key}: Field required")
        out[key] = check(value[key], f"{field}.{key}")
    return out


FLIGHT_INFO = {"flight_number": _str, "date": _str}
PASSENGER = {"first_name": _str, "last_name": _str, "dob": _str}
PAYMENT = {"payment_id": _str, "amount": _int}
ADDRESS = {k: _str for k in ("address1", "address2", "city", "country", "state", "zip")}


def calculate_expression(expression: str) -> str:
    """원본 calculate. eval 대신 사칙연산만 푸는 AST 평가로 같은 결과를 낸다."""
    if not all(char in "0123456789+-*/(). " for char in expression):
        raise ValueError("Invalid characters in expression")

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return node.value
        if isinstance(node, ast.BinOp) and type(node.op) in _ARITH:
            return float(_ARITH[type(node.op)](walk(node.left), walk(node.right)))
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = walk(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        raise ValueError("Invalid expression")

    return str(round(float(walk(ast.parse(expression, mode="eval"))), 2))


def to_json_str(resp: Any) -> str:
    """원본 Environment.to_json_str: 문자열은 그대로, 나머지는 JSON."""
    if isinstance(resp, str):
        return resp
    if isinstance(resp, (int, float, bool)):
        return str(resp)
    return json.dumps(resp, default=str)


class DomainTools:
    """도구 이름으로 메서드를 불러 원본 get_response 처럼 (글, 오류 여부)를 낸다."""

    names: tuple[str, ...] = ()
    writes: frozenset[str] = frozenset()

    def __init__(self, db: OverlayDB) -> None:
        self.db = db

    def call(self, name: str, args: dict[str, Any]) -> tuple[str, bool]:
        if name not in self.names:
            return f"Error: Tool '{name}' not found.", True
        try:
            # 인자 이름이 틀리면 원본처럼 TypeError 문구가 그대로 오류 결과가 된다
            return to_json_str(getattr(self, name)(**copy.deepcopy(args))), False
        except Exception as exc:  # noqa: BLE001 - 원본도 모든 예외를 "Error: ..." 결과로 돌려준다
            return f"Error: {exc}", True


# ── airline ──

class AirlineTools(DomainTools):
    names = ("book_reservation", "calculate", "cancel_reservation", "get_reservation_details", "get_user_details",
             "list_all_airports", "search_direct_flight", "search_onestop_flight", "send_certificate",
             "transfer_to_human_agents", "update_reservation_baggages", "update_reservation_flights",
             "update_reservation_passengers", "get_flight_status")
    writes = frozenset({"book_reservation", "cancel_reservation", "send_certificate", "update_reservation_baggages",
                        "update_reservation_flights", "update_reservation_passengers"})

    def _key(self, table: str, key: str, label: str) -> str:
        """원본 _resolve_key_folded: 정확히, 공백 제거, 접은 값이 하나만 맞을 때."""
        if self.db.has(table, key):
            return key
        stripped = key.strip()
        if self.db.has(table, stripped):
            return stripped
        folded = fold(stripped)
        matches = [k for k in self.db.keys(table) if fold(k) == folded]
        if len(matches) != 1:
            raise ValueError(f"{label} {key} not found")
        return matches[0]

    def _flight_instance(self, flight_number: str, date: str) -> tuple[str, Record]:
        key = self._key("flights", flight_number, "Flight")
        flight = self.db.get("flights", key)
        if date not in flight["dates"]:
            raise ValueError(f"Flight {flight_number} not found on date {date}")
        return key, flight["dates"][date]

    def _search_direct(self, date: str, origin: str | None = None, destination: str | None = None,
                       leave_after: str | None = None) -> list[Record]:
        results = []
        for _, flight in self.db.items("flights"):
            day = flight["dates"].get(date)
            if ((origin is None or flight["origin"] == origin)
                    and (destination is None or flight["destination"] == destination)
                    and day is not None and day["status"] == "available"
                    and (leave_after is None or flight["scheduled_departure_time_est"] >= leave_after)):
                results.append({
                    "flight_number": flight["flight_number"], "origin": flight["origin"],
                    "destination": flight["destination"], "status": "available",
                    "scheduled_departure_time_est": flight["scheduled_departure_time_est"],
                    "scheduled_arrival_time_est": flight["scheduled_arrival_time_est"], "date": None,
                    "available_seats": copy.deepcopy(day["available_seats"]), "prices": copy.deepcopy(day["prices"]),
                })
        return results

    def _payment_for_update(self, user: Record, payment_id: str, total_price: int) -> Record | None:
        if payment_id not in user["payment_methods"]:
            raise ValueError("Payment method not found")
        method = user["payment_methods"][payment_id]
        if method["source"] == "certificate":
            raise ValueError("Certificate cannot be used to update reservation")
        if method["source"] == "gift_card" and method["amount"] < total_price:
            raise ValueError("Gift card balance is not enough")
        if method["source"] == "gift_card":
            method["amount"] -= total_price
        return {"payment_id": payment_id, "amount": total_price} if total_price != 0 else None

    def book_reservation(self, user_id: str, origin: str, destination: str, flight_type: str, cabin: str,
                         flights: list[Any], passengers: list[Any], payment_methods: list[Any],
                         total_baggages: int, nonfree_baggages: int, insurance: str) -> Record:
        flight_infos = [_model(f, "flights", FLIGHT_INFO) for f in flights]
        people = [_model(p, "passengers", PASSENGER) for p in passengers]
        payments = [_model(p, "payment_methods", PAYMENT) for p in payment_methods]
        user_key = self._key("users", user_id, "User")
        user = self.db.get("users", user_key)
        reservation_id = next((r for r in ("HATHAT", "HATHAU", "HATHAV") if not self.db.has("reservations", r)), None)
        if reservation_id is None:
            raise ValueError("Too many reservations")
        reservation: Record = {
            "reservation_id": reservation_id, "user_id": user_key, "origin": _str(origin, "origin"),
            "destination": _str(destination, "destination"),
            "flight_type": _literal(flight_type, "flight_type", ("round_trip", "one_way")),
            "cabin": _literal(cabin, "cabin", CABINS), "flights": [], "passengers": copy.deepcopy(people),
            "payment_history": copy.deepcopy(payments), "created_at": NOW,
            "total_baggages": _int(total_baggages, "total_baggages"),
            "nonfree_baggages": _int(nonfree_baggages, "nonfree_baggages"),
            "insurance": _literal(insurance, "insurance", ("yes", "no")), "status": None,
        }
        total_price = 0
        touched: list[tuple[str, str]] = []
        for info in flight_infos:
            key, day = self._flight_instance(info["flight_number"], info["date"])
            flight = self.db.get("flights", key)
            if day["status"] != "available":
                raise ValueError(f"Flight {key} not available on date {info['date']}")
            if day["available_seats"][cabin] < len(people):
                raise ValueError(f"Not enough seats on flight {key}")
            price = day["prices"][cabin]
            reservation["flights"].append({"flight_number": key, "origin": flight["origin"],
                                           "destination": flight["destination"], "date": info["date"],
                                           "price": price})
            touched.append((key, info["date"]))
            total_price += price * len(people)
        if insurance == "yes":
            total_price += 30 * len(people)
        total_price += 50 * reservation["nonfree_baggages"]
        for payment in payments:
            if payment["payment_id"] not in user["payment_methods"]:
                raise ValueError(f"Payment method {payment['payment_id']} not found")
            method = user["payment_methods"][payment["payment_id"]]
            if method["source"] in {"gift_card", "certificate"} and method["amount"] < payment["amount"]:
                raise ValueError(f"Not enough balance in payment method {payment['payment_id']}")
        total_payment = sum(p["amount"] for p in payments)
        if total_payment != total_price:
            raise ValueError(f"Payment amount does not add up, total price is {total_price}, but paid {total_payment}")
        user = self.db.mut("users", user_key)
        for payment in payments:
            method = user["payment_methods"][payment["payment_id"]]
            if method["source"] == "gift_card":
                method["amount"] -= payment["amount"]
            elif method["source"] == "certificate":
                user["payment_methods"].pop(payment["payment_id"])
        for key, date in touched:
            self.db.mut("flights", key)["dates"][date]["available_seats"][cabin] -= len(people)
        self.db.put("reservations", reservation_id, reservation)
        user["reservations"].append(reservation_id)
        return reservation

    def calculate(self, expression: str) -> str:
        return calculate_expression(expression)

    def cancel_reservation(self, reservation_id: str) -> Record:
        reservation = self.db.mut("reservations", self._key("reservations", reservation_id, "Reservation"))
        refunds = [{"payment_id": p["payment_id"], "amount": -p["amount"]} for p in reservation["payment_history"]]
        reservation["payment_history"].extend(refunds)
        reservation["status"] = "cancelled"
        # 원본도 좌석을 돌려놓지 않는다("Seats release not implemented")
        return reservation

    def get_reservation_details(self, reservation_id: str) -> Record:
        return self.db.get("reservations", self._key("reservations", reservation_id, "Reservation"))

    def get_user_details(self, user_id: str) -> Record:
        return self.db.get("users", self._key("users", user_id, "User"))

    def list_all_airports(self) -> list[Record]:
        cities = (("SFO", "San Francisco"), ("JFK", "New York"), ("LAX", "Los Angeles"), ("ORD", "Chicago"),
                  ("DFW", "Dallas"), ("DEN", "Denver"), ("SEA", "Seattle"), ("ATL", "Atlanta"), ("MIA", "Miami"),
                  ("BOS", "Boston"), ("PHX", "Phoenix"), ("IAH", "Houston"), ("LAS", "Las Vegas"),
                  ("MCO", "Orlando"), ("EWR", "Newark"), ("CLT", "Charlotte"), ("MSP", "Minneapolis"),
                  ("DTW", "Detroit"), ("PHL", "Philadelphia"), ("LGA", "LaGuardia"))
        return [{"iata": iata, "city": city} for iata, city in cities]

    def search_direct_flight(self, origin: str, destination: str, date: str) -> list[Record]:
        return self._search_direct(date=date, origin=origin, destination=destination)

    def search_onestop_flight(self, origin: str, destination: str, date: str) -> list[list[Record]]:
        results = []
        for first in self._search_direct(date=date, origin=origin):
            first["date"] = date
            # 원본 그대로: 다음 날을 0 채움 없이 만든다(2024-05-10 → 2024-05-11, 2024-05-05 → 2024-05-6)
            date2 = f"2024-05-{int(date[-2:]) + 1}" if "+1" in first["scheduled_arrival_time_est"] else date
            for second in self._search_direct(date=date2, origin=first["destination"], destination=destination,
                                              leave_after=first["scheduled_arrival_time_est"]):
                second["date"] = date2
                results.append([first, second])
        return results

    def send_certificate(self, user_id: str, amount: int) -> str:
        key = self._key("users", user_id, "User")
        user = self.db.get("users", key)
        for payment_id in (f"certificate_{n}" for n in (3221322, 3221323, 3221324)):
            if payment_id not in user["payment_methods"]:
                certificate = {"source": "certificate", "id": payment_id, "amount": _float(amount, "amount")}
                self.db.mut("users", key)["payment_methods"][payment_id] = certificate
                return f"Certificate {payment_id} added to user {user_id} with amount {amount}."
        raise ValueError("Too many certificates")

    def transfer_to_human_agents(self, summary: str) -> str:
        return "Transfer successful"

    def update_reservation_baggages(self, reservation_id: str, total_baggages: int, nonfree_baggages: int,
                                    payment_id: str) -> Record:
        key = self._key("reservations", reservation_id, "Reservation")
        current = self.db.get("reservations", key)
        user_key = self._key("users", current["user_id"], "User")
        total_price = 50 * max(0, nonfree_baggages - current["nonfree_baggages"])
        payment = self._payment_for_update(self.db.mut("users", user_key), payment_id, total_price)
        reservation = self.db.mut("reservations", key)
        if payment is not None:
            reservation["payment_history"].append(payment)
        reservation["total_baggages"] = total_baggages
        reservation["nonfree_baggages"] = nonfree_baggages
        return reservation

    def update_reservation_flights(self, reservation_id: str, cabin: str, flights: list[Any],
                                   payment_id: str) -> Record:
        flight_infos = [_model(f, "flights", FLIGHT_INFO) for f in flights]
        key = self._key("reservations", reservation_id, "Reservation")
        current = self.db.get("reservations", key)
        user_key = self._key("users", current["user_id"], "User")
        total_price = 0
        new_flights = []
        for info in flight_infos:
            flight_key = self._key("flights", info["flight_number"], "Flight")
            kept = next((f for f in current["flights"] if f["flight_number"] == flight_key
                         and f["date"] == info["date"] and cabin == current["cabin"]), None)
            if kept:
                total_price += kept["price"] * len(current["passengers"])
                new_flights.append(kept)
                continue
            _, day = self._flight_instance(flight_key, info["date"])
            if day["status"] != "available":
                raise ValueError(f"Flight {flight_key} not available on date {info['date']}")
            if day["available_seats"][cabin] < len(current["passengers"]):
                raise ValueError(f"Not enough seats on flight {flight_key}")
            flight = self.db.get("flights", flight_key)
            new = {"flight_number": flight_key, "origin": flight["origin"], "destination": flight["destination"],
                   "date": info["date"], "price": day["prices"][cabin]}
            total_price += new["price"] * len(current["passengers"])
            new_flights.append(new)
        total_price -= sum(f["price"] for f in current["flights"]) * len(current["passengers"])
        payment = self._payment_for_update(self.db.mut("users", user_key), payment_id, total_price)
        reservation = self.db.mut("reservations", key)
        if payment is not None:
            reservation["payment_history"].append(payment)
        reservation["flights"] = copy.deepcopy(new_flights)
        reservation["cabin"] = cabin
        # 원본도 비행편 좌석 수를 바꾸지 않는다
        return reservation

    def update_reservation_passengers(self, reservation_id: str, passengers: list[Any]) -> Record:
        people = [_model(p, "passengers", PASSENGER) for p in passengers]
        key = self._key("reservations", reservation_id, "Reservation")
        if len(people) != len(self.db.get("reservations", key)["passengers"]):
            raise ValueError("Number of passengers does not match")
        reservation = self.db.mut("reservations", key)
        reservation["passengers"] = copy.deepcopy(people)
        return reservation

    def get_flight_status(self, flight_number: str, date: str) -> str:
        status: str = self._flight_instance(flight_number, date)[1]["status"]
        return status


# ── retail ──

class RetailTools(DomainTools):
    names = ("calculate", "cancel_pending_order", "exchange_delivered_order_items", "find_user_id_by_name_zip",
             "find_user_id_by_email", "get_order_details", "get_product_details", "get_item_details",
             "get_user_details", "list_all_product_types", "modify_pending_order_address",
             "modify_pending_order_items", "modify_pending_order_payment", "modify_user_address",
             "return_delivered_order_items", "transfer_to_human_agents")
    writes = frozenset({"cancel_pending_order", "exchange_delivered_order_items", "modify_pending_order_address",
                        "modify_pending_order_items", "modify_pending_order_payment", "modify_user_address",
                        "return_delivered_order_items"})

    def _order(self, order_id: str) -> Record:
        if not self.db.has("orders", order_id):
            raise ValueError("Order not found")
        return self.db.get("orders", order_id)

    def _user(self, user_id: str) -> Record:
        if not self.db.has("users", user_id):
            raise ValueError("User not found")
        return self.db.get("users", user_id)

    def _variant(self, product_id: str, variant_id: str) -> Record:
        if not self.db.has("products", product_id):
            raise ValueError("Product not found")
        variants = self.db.get("products", product_id)["variants"]
        if variant_id not in variants:
            raise ValueError("Variant not found")
        variant: Record = variants[variant_id]
        return variant

    def _payment_method(self, user_id: str, payment_method_id: str) -> Record:
        methods = self._user(user_id)["payment_methods"]
        if payment_method_id not in methods:
            raise ValueError("Payment method not found")
        method: Record = methods[payment_method_id]
        return method

    def _check_items(self, order: Record, item_ids: list[str], message: str) -> None:
        all_item_ids = [item["item_id"] for item in order["items"]]
        for item_id in item_ids:
            if item_ids.count(item_id) > all_item_ids.count(item_id):
                raise ValueError(message.format(item_id=item_id))

    def calculate(self, expression: str) -> str:
        return calculate_expression(expression)

    def cancel_pending_order(self, order_id: str, reason: str) -> Record:
        current = self._order(order_id)
        if current["status"] != "pending":
            raise ValueError("Non-pending order cannot be cancelled")
        if reason not in {"no longer needed", "ordered by mistake"}:
            raise ValueError("Invalid reason")
        refunds = []
        for payment in current["payment_history"]:
            refunds.append({"transaction_type": "refund", "amount": float(payment["amount"]),
                            "payment_method_id": payment["payment_method_id"]})
            self._payment_method(current["user_id"], payment["payment_method_id"])
            method = self.db.mut("users", current["user_id"])["payment_methods"][payment["payment_method_id"]]
            if method["source"] == "gift_card":
                method["balance"] = round(method["balance"] + payment["amount"], 2)
        order = self.db.mut("orders", order_id)
        order["status"] = "cancelled"
        order["cancel_reason"] = reason
        order["payment_history"].extend(refunds)
        return order

    def exchange_delivered_order_items(self, order_id: str, item_ids: list[str], new_item_ids: list[str],
                                       payment_method_id: str) -> Record:
        current = self._order(order_id)
        if current["status"] != "delivered":
            raise ValueError("Non-delivered order cannot be exchanged")
        self._check_items(current, item_ids, "Number of {item_id} not found.")
        if len(item_ids) != len(new_item_ids):
            raise ValueError("The number of items to be exchanged should match.")
        diff_price = 0.0
        for item_id, new_item_id in zip(item_ids, new_item_ids, strict=False):
            item = next((i for i in current["items"] if i["item_id"] == item_id), None)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            variant = self._variant(item["product_id"], new_item_id)
            if not variant["available"]:
                raise ValueError(f"New item {new_item_id} not found or available")
            diff_price += variant["price"] - item["price"]
        diff_price = round(diff_price, 2)
        method = self._payment_method(current["user_id"], payment_method_id)
        if method["source"] == "gift_card" and method["balance"] < diff_price:
            raise ValueError("Insufficient gift card balance to pay for the price difference")
        order = self.db.mut("orders", order_id)
        order["status"] = "exchange requested"
        order["exchange_items"] = sorted(item_ids)
        order["exchange_new_items"] = sorted(new_item_ids)
        order["exchange_payment_method_id"] = payment_method_id
        order["exchange_price_difference"] = diff_price
        return order

    def find_user_id_by_name_zip(self, first_name: str, last_name: str, zip: str) -> str:  # noqa: A002 - 원본 인자 이름
        first, last = fold(first_name), fold(last_name)
        matches = [uid for uid, user in self.db.items("users") if fold(user["name"]["first_name"]) == first
                   and fold(user["name"]["last_name"]) == last and user["address"]["zip"] == zip]
        if len(matches) == 1:
            return matches[0]
        raise ValueError("User lookup is ambiguous" if matches else "User not found")

    def find_user_id_by_email(self, email: str) -> str:
        wanted = fold(email)
        matches = [uid for uid, user in self.db.items("users") if fold(user["email"]) == wanted]
        if len(matches) == 1:
            return matches[0]
        raise ValueError("User lookup is ambiguous" if matches else "User not found")

    def get_order_details(self, order_id: str) -> Record:
        return self._order(order_id)

    def get_product_details(self, product_id: str) -> Record:
        if not self.db.has("products", product_id):
            raise ValueError("Product not found")
        return self.db.get("products", product_id)

    def get_item_details(self, item_id: str) -> Record:
        for _, product in self.db.items("products"):
            if item_id in product["variants"]:
                variant: Record = product["variants"][item_id]
                return variant
        raise ValueError("Item not found")

    def get_user_details(self, user_id: str) -> Record:
        return self._user(user_id)

    def list_all_product_types(self) -> str:
        return json.dumps({p["name"]: p["product_id"] for _, p in self.db.items("products")}, sort_keys=True)

    def modify_pending_order_address(self, order_id: str, address1: str, address2: str, city: str, state: str,
                                     country: str, zip: str) -> Record:  # noqa: A002 - 원본 인자 이름
        if "pending" not in self._order(order_id)["status"]:
            raise ValueError("Non-pending order cannot be modified")
        address = _model({"address1": address1, "address2": address2, "city": city, "country": country,
                          "state": state, "zip": zip}, "address", ADDRESS)
        order = self.db.mut("orders", order_id)
        order["address"] = address
        return order

    def modify_pending_order_items(self, order_id: str, item_ids: list[str], new_item_ids: list[str],
                                   payment_method_id: str) -> Record:
        current = self._order(order_id)
        if current["status"] != "pending":
            raise ValueError("Non-pending order cannot be modified")
        self._check_items(current, item_ids, "{item_id} not found")
        if len(item_ids) != len(new_item_ids):
            raise ValueError("The number of items to be exchanged should match")
        diff_price: float = 0
        variant: Record = {}
        for item_id, new_item_id in zip(item_ids, new_item_ids, strict=False):
            if item_id == new_item_id:
                raise ValueError("The new item id should be different from the old item id")
            item = next((i for i in current["items"] if i["item_id"] == item_id), None)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            variant = self._variant(item["product_id"], new_item_id)
            if not variant["available"]:
                raise ValueError(f"New item {new_item_id} not found or available")
            diff_price += variant["price"] - item["price"]
        method = self._payment_method(current["user_id"], payment_method_id)
        if method["source"] == "gift_card" and method["balance"] < diff_price:
            raise ValueError("Insufficient gift card balance to pay for the new item")
        order = self.db.mut("orders", order_id)
        order["payment_history"].append({"transaction_type": "payment" if diff_price > 0 else "refund",
                                         "amount": float(abs(diff_price)), "payment_method_id": payment_method_id})
        if method["source"] == "gift_card":
            live = self.db.mut("users", current["user_id"])["payment_methods"][payment_method_id]
            live["balance"] = round(live["balance"] - diff_price, 2)
        for item_id, new_item_id in zip(item_ids, new_item_ids, strict=False):
            item = next((i for i in order["items"] if i["item_id"] == item_id), None)
            if item is None:
                raise ValueError(f"Item {item_id} not found")
            item["item_id"] = new_item_id
            # 원본 그대로: 바꾼 모든 품목에 마지막 variant 의 가격과 옵션을 쓴다
            item["price"] = variant["price"]
            item["options"] = copy.deepcopy(variant["options"])
        order["status"] = "pending (item modified)"
        return order

    def modify_pending_order_payment(self, order_id: str, payment_method_id: str) -> Record:
        current = self._order(order_id)
        if "pending" not in current["status"]:
            raise ValueError("Non-pending order cannot be modified")
        method = self._payment_method(current["user_id"], payment_method_id)
        history = current["payment_history"]
        if len(history) != 1 or history[0]["transaction_type"] != "payment":
            raise ValueError("There should be exactly one payment for a pending order")
        old_id = history[0]["payment_method_id"]
        if old_id == payment_method_id:
            raise ValueError("The new payment method should be different from the current one")
        amount = history[0]["amount"]
        if method["source"] == "gift_card" and method["balance"] < amount:
            raise ValueError("Insufficient gift card balance to pay for the order")
        order = self.db.mut("orders", order_id)
        order["payment_history"].extend([
            {"transaction_type": "payment", "amount": float(amount), "payment_method_id": payment_method_id},
            {"transaction_type": "refund", "amount": float(amount), "payment_method_id": old_id},
        ])
        methods = self.db.mut("users", current["user_id"])["payment_methods"]
        if methods[payment_method_id]["source"] == "gift_card":
            methods[payment_method_id]["balance"] = round(methods[payment_method_id]["balance"] - amount, 2)
        old = self._payment_method(current["user_id"], old_id)
        if old["source"] == "gift_card":
            methods[old_id]["balance"] = round(methods[old_id]["balance"] + amount, 2)
        return order

    def modify_user_address(self, user_id: str, address1: str, address2: str, city: str, state: str, country: str,
                            zip: str) -> Record:  # noqa: A002 - 원본 인자 이름
        self._user(user_id)
        address = _model({"address1": address1, "address2": address2, "city": city, "country": country,
                          "state": state, "zip": zip}, "address", ADDRESS)
        user = self.db.mut("users", user_id)
        user["address"] = address
        return user

    def return_delivered_order_items(self, order_id: str, item_ids: list[str], payment_method_id: str) -> Record:
        current = self._order(order_id)
        if current["status"] != "delivered":
            raise ValueError("Non-delivered order cannot be returned")
        method = self._payment_method(current["user_id"], payment_method_id)
        if method["source"] != "gift_card" and payment_method_id != current["payment_history"][0]["payment_method_id"]:
            raise ValueError("Payment method should be the original payment method")
        self._check_items(current, item_ids, "Some item not found")
        order = self.db.mut("orders", order_id)
        order["status"] = "return requested"
        order["return_items"] = sorted(item_ids)
        order["return_payment_method_id"] = payment_method_id
        return order

    def transfer_to_human_agents(self, summary: str) -> str:
        return "Transfer successful"


TOOLKITS: dict[str, type[DomainTools]] = {"airline": AirlineTools, "retail": RetailTools}


# ── 도구 정의: 원본 docstring 의 설명과 인자 설명을 옮겼다. 중첩 모델은 $ref 대신 펼쳐 둔다 ──

def _s(desc: str) -> dict[str, Any]:
    return {"type": "string", "description": desc}


def _i(desc: str) -> dict[str, Any]:
    return {"type": "integer", "description": desc}


def _e(desc: str, values: tuple[str, ...]) -> dict[str, Any]:
    return {"type": "string", "enum": list(values), "description": desc}


def _obj(desc: str, props: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"type": "array", "description": desc,
            "items": {"type": "object", "properties": props, "required": list(props)}}


def _tool(name: str, desc: str, props: dict[str, dict[str, Any]]) -> dict[str, Any]:
    return {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": list(props)}}


_ORDER_ID = "The order id, such as '#W0000000'. Be careful there is a '#' symbol at the beginning of the order id."
_PAY_ID = ("The payment method id to pay or receive refund for the item price difference, such as 'gift_card_0000000' "
           "or 'credit_card_0000000'. These can be looked up from the user or order details.")
_RES_ID = "The reservation ID, such as 'ZFA04Y'."
_AIR_PAY = ("The payment id stored in user profile, such as 'credit_card_7815826', 'gift_card_7815826', "
            "'certificate_7815826'.")
_CALC = _tool("calculate", "Calculate the result of a mathematical expression.", {
    "expression": _s("The mathematical expression to calculate, such as '2 + 2'. The expression can contain numbers, "
                     "operators (+, -, *, /), parentheses, and spaces.")})
_TRANSFER = _tool("transfer_to_human_agents",
                  "Transfer the user to a human agent, with a summary of the user's issue.\nOnly transfer if\n"
                  " -  the user explicitly asks for a human agent\n -  given the policy and the "
                  "available tools, you cannot solve the user's issue.",
                  {"summary": _s("A summary of the user's issue.")})
_FLIGHT_INFO = {"flight_number": _s("Flight number, such as 'HAT001'."),
                "date": _s("The date for the flight in the format 'YYYY-MM-DD', such as '2024-05-01'.")}
_PASSENGER = {"first_name": _s("Passenger's first name"), "last_name": _s("Passenger's last name"),
              "dob": _s("Date of birth in YYYY-MM-DD format")}
_ADDRESS = {"address1": _s("The first line of the address, such as '123 Main St'."),
            "address2": _s("The second line of the address, such as 'Apt 1' or ''."),
            "city": _s("The city, such as 'San Francisco'."), "state": _s("The state, such as 'CA'."),
            "country": _s("The country, such as 'USA'."), "zip": _s("The zip code, such as '12345'.")}

SCHEMAS: dict[str, list[dict[str, Any]]] = {
    "airline": [
        _tool("book_reservation", "Book a reservation.", {
            "user_id": _s("The ID of the user to book the reservation such as 'sara_doe_496'`."),
            "origin": _s("The IATA code for the origin city such as 'SFO'."),
            "destination": _s("The IATA code for the destination city such as 'JFK'."),
            "flight_type": _e("The type of flight such as 'one_way' or 'round_trip'.", ("round_trip", "one_way")),
            "cabin": _e("The cabin class such as 'basic_economy', 'economy', or 'business'.", CABINS),
            "flights": _obj("An array of objects containing details about each piece of flight.", _FLIGHT_INFO),
            "passengers": _obj("An array of objects containing details about each passenger.", _PASSENGER),
            "payment_methods": _obj("An array of objects containing details about each payment method.", {
                "payment_id": _s("Unique identifier for the payment"), "amount": _i("Payment amount in dollars")}),
            "total_baggages": _i("The total number of baggage items to book the reservation."),
            "nonfree_baggages": _i("The number of non-free baggage items to book the reservation."),
            "insurance": _e("Whether the reservation has insurance.", ("yes", "no"))}),
        _CALC,
        _tool("cancel_reservation", "Cancel the whole reservation.", {"reservation_id": _s(_RES_ID)}),
        _tool("get_reservation_details", "Get the details of a reservation.",
              {"reservation_id": _s("The reservation ID, such as '8JX2WO'.")}),
        _tool("get_user_details", "Get the details of a user, including their reservations.",
              {"user_id": _s("The user ID, such as 'sara_doe_496'.")}),
        _tool("list_all_airports", "Returns a list of all available airports.", {}),
        _tool("search_direct_flight", "Search for direct flights between two cities on a specific date.", {
            "origin": _s("The origin city airport in three letters, such as 'JFK'."),
            "destination": _s("The destination city airport in three letters, such as 'LAX'."),
            "date": _s("The date of the flight in the format 'YYYY-MM-DD', such as '2024-01-01'.")}),
        _tool("search_onestop_flight", "Search for one-stop flights between two cities on a specific date.", {
            "origin": _s("The origin city airport in three letters, such as 'JFK'."),
            "destination": _s("The destination city airport in three letters, such as 'LAX'."),
            "date": _s("The date of the flight in the format 'YYYY-MM-DD', such as '2024-05-01'.")}),
        _tool("send_certificate", "Send a certificate to a user. Be careful!", {
            "user_id": _s("The ID of the user to book the reservation, such as 'sara_doe_496'."),
            "amount": _i("The amount of the certificate to send.")}),
        _TRANSFER,
        _tool("update_reservation_baggages", "Update the baggage information of a reservation.", {
            "reservation_id": _s(_RES_ID),
            "total_baggages": _i("The updated total number of baggage items included in the reservation."),
            "nonfree_baggages": _i("The updated number of non-free baggage items included in the reservation."),
            "payment_id": _s(_AIR_PAY)}),
        _tool("update_reservation_flights", "Update the flight information of a reservation.", {
            "reservation_id": _s(_RES_ID),
            "cabin": _e("The cabin class of the reservation", CABINS),
            "flights": _obj("An array of objects containing details about each piece of flight in the ENTIRE new "
                            "reservation. Even if the a flight segment is not changed, it should still be included "
                            "in the array.", _FLIGHT_INFO),
            "payment_id": _s(_AIR_PAY)}),
        _tool("update_reservation_passengers", "Update the passenger information of a reservation.", {
            "reservation_id": _s(_RES_ID),
            "passengers": _obj("An array of objects containing details about each passenger.", _PASSENGER)}),
        _tool("get_flight_status", "Get the status of a flight.", {
            "flight_number": _s("The flight number."), "date": _s("The date of the flight.")}),
    ],
    "retail": [
        _CALC,
        _tool("cancel_pending_order", (
            "Cancel a pending order. If the order is already processed or delivered,\nit cannot be cancelled. The "
            "agent needs to explain the cancellation detail\nand ask for explicit user confirmation (yes/no) to "
            "proceed. If the user confirms,\nthe order status will be changed to 'cancelled' and the payment will be "
            "refunded.\nThe refund will be added to the user's gift card balance immediately if the payment\nwas made "
            "using a gift card, otherwise the refund would take 5-7 business days to process.\nThe function returns "
            "the order details after the cancellation."), {
            "order_id": _s(_ORDER_ID),
            "reason": _s("The reason for cancellation, which should be either 'no longer needed' or 'ordered by "
                         "mistake'.")}),
        _tool("exchange_delivered_order_items", (
            "Exchange items in a delivered order to new items of the same product type.\nFor a delivered order, "
            "return or exchange can be only done once by the agent.\nThe agent needs to explain the exchange detail "
            "and ask for explicit user confirmation (yes/no) to proceed."), {
            "order_id": _s(_ORDER_ID),
            "item_ids": {"type": "array", "items": {"type": "string"}, "description": (
                "The item ids to be exchanged, each such as '1008292230'. There could be duplicate items in the "
                "list.")},
            "new_item_ids": {"type": "array", "items": {"type": "string"}, "description": (
                "The item ids to be exchanged for, each such as '1008292230'. There could be duplicate items in the "
                "list. Each new item id should match the item id in the same position and be of the same product.")},
            "payment_method_id": _s(_PAY_ID)}),
        _tool("find_user_id_by_name_zip", (
            "Find user id by first name, last name, and zip code. If the user is not found, the function\nwill return "
            "an error message. By default, find user id by email, and only call this function\nif the user is not "
            "found by email or cannot remember email."), {
            "first_name": _s("The first name of the customer, such as 'John'."),
            "last_name": _s("The last name of the customer, such as 'Doe'."),
            "zip": _s("The zip code of the customer, such as '12345'.")}),
        _tool("find_user_id_by_email",
              "Find user id by email. If the user is not found, the function will return an error message.",
              {"email": _s("The email of the user, such as 'something@example.com'.")}),
        _tool("get_order_details", "Get the status and details of an order.", {"order_id": _s(_ORDER_ID)}),
        _tool("get_product_details", "Get the inventory details of a product.", {"product_id": _s(
            "The product id, such as '6086499569'. Be careful the product id is different from the item id.")}),
        _tool("get_item_details", "Get the inventory details of an item.", {"item_id": _s(
            "The item id, such as '6086499569'. Be careful the item id is different from the product id.")}),
        _tool("get_user_details", "Get the details of a user, including their orders.",
              {"user_id": _s("The user id, such as 'sara_doe_496'.")}),
        _tool("list_all_product_types", (
            "List the name and product id of all product types.\nEach product type has a variety of different items "
            "with unique item ids and options.\nThere are only 50 product types in the store."), {}),
        _tool("modify_pending_order_address", (
            "Modify the shipping address of a pending order. The agent needs to explain the modification detail and "
            "ask for explicit user confirmation (yes/no) to proceed."), {"order_id": _s(_ORDER_ID), **_ADDRESS}),
        _tool("modify_pending_order_items", (
            "Modify items in a pending order to new items of the same product type. For a pending order, this "
            "function can only be called once. The agent needs to explain the exchange detail and ask for explicit "
            "user confirmation (yes/no) to proceed."), {
            "order_id": _s(_ORDER_ID),
            "item_ids": {"type": "array", "items": {"type": "string"}, "description": (
                "The item ids to be modified, each such as '1008292230'. There could be duplicate items in the "
                "list.")},
            "new_item_ids": {"type": "array", "items": {"type": "string"}, "description": (
                "The item ids to be modified for, each such as '1008292230'. There could be duplicate items in the "
                "list. Each new item id should match the item id in the same position and be of the same product.")},
            "payment_method_id": _s(_PAY_ID)}),
        _tool("modify_pending_order_payment", (
            "Modify the payment method of a pending order. The agent needs to explain the modification detail and "
            "ask for explicit user confirmation (yes/no) to proceed."), {
            "order_id": _s(_ORDER_ID), "payment_method_id": _s(_PAY_ID)}),
        _tool("modify_user_address", (
            "Modify the default address of a user. The agent needs to explain the modification detail and ask for "
            "explicit user confirmation (yes/no) to proceed."),
              {"user_id": _s("The user id, such as 'sara_doe_496'."), **_ADDRESS}),
        _tool("return_delivered_order_items", (
            "Return some items of a delivered order.\nThe order status will be changed to 'return requested'.\nThe "
            "agent needs to explain the return detail and ask for explicit user confirmation (yes/no) to proceed.\n"
            "The user will receive follow-up email for how and where to return the item."), {
            "order_id": _s(_ORDER_ID),
            "item_ids": {"type": "array", "items": {"type": "string"}, "description": (
                "The item ids to be returned, each such as '1008292230'. There could be duplicate items in the "
                "list.")},
            "payment_method_id": _s(
                "The payment method id to pay or receive refund for the item price difference, such as "
                "'gift_card_0000000' or 'credit_card_0000000'.\nThese can be looked up from the user or order "
                "details.")}),
        _TRANSFER,
    ],
}
