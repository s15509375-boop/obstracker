#!/usr/bin/env python3
"""Outbound Shipping Tracker V3.2.

Offline, standard-library-only command-line prototype.
Designed for test data on a personal computer. Do not use real company data
or transfer it to a managed device without approval.
"""
from __future__ import annotations

import csv
import json
import re
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_VERSION = 32
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "outbound_tracker_data"
RZRR_DIR = DATA_DIR / "rzrr"
EXPORT_DIR = DATA_DIR / "exports"
SETTINGS_PATH = DATA_DIR / "settings.json"
STANDARD_FLOOR_POSITIONS = 24
DEFAULT_WEIGHT_WARNING_LB = 40000
DEFAULT_NEAR_FULL_FLOOR = 22

POSITIONS = [f"{side}{row:02d}" for row in range(1, 13) for side in ("L", "R")]
TYPES = {
    "box": {"label": "Plastic pallet box", "short": "BOX", "capacity": 2},
    "sleeve": {"label": "Pallet sleeve", "short": "SLV", "capacity": 2},
    "wood": {"label": "Wood pallet", "short": "WOOD", "capacity": 1},
    # "unknown" exists only for imported Asana/Issues records that still need
    # physical details completed. Unknown records cannot be trailer-laid-out.
    "unknown": {"label": "Pending type", "short": "PEND", "capacity": 1},
}
STATUSES = ("staged", "dock", "loaded")


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def clean_id(value: str) -> str:
    value = re.sub(r"\s+", " ", value.strip()).upper()
    return value[:100]


def safe_name(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("_") or "unnamed"


def pause() -> None:
    input("\nPress Enter to continue...")


def ask_yes_no(prompt: str, default: bool = False) -> bool:
    suffix = " [Y/n]: " if default else " [y/N]: "
    raw = input(prompt + suffix).strip().lower()
    if not raw:
        return default
    return raw in {"y", "yes"}


def choose(prompt: str, options: list[tuple[str, str]], allow_blank: bool = False) -> Optional[str]:
    while True:
        print(f"\n{prompt}")
        for idx, (_, label) in enumerate(options, 1):
            print(f"  {idx}. {label}")
        raw = input("> ").strip()
        if allow_blank and not raw:
            return None
        try:
            return options[int(raw) - 1][0]
        except (ValueError, IndexError):
            print("Choose a valid number.")


def get_weight(prompt: str = "Weight in whole pounds: ") -> int:
    while True:
        raw = input(prompt).strip().replace(",", "")
        try:
            value = int(raw)
            if value <= 0:
                raise ValueError
            return value
        except ValueError:
            print("Enter a positive whole number of pounds.")


def get_aisle(allow_blank: bool = True) -> Optional[int]:
    while True:
        raw = input("OBS aisle (1-4, blank for unassigned): ").strip()
        if allow_blank and not raw:
            return None
        if raw in {"1", "2", "3", "4"}:
            return int(raw)
        print("Enter 1, 2, 3, 4, or leave blank.")


def get_dock() -> Optional[int]:
    while True:
        raw = input("Dock door (1-4, blank if unknown): ").strip()
        if not raw:
            return None
        if raw in {"1", "2", "3", "4"}:
            return int(raw)
        print("Enter 1, 2, 3, 4, or leave blank.")


def default_settings() -> dict:
    return {
        "weight_warning_lb": DEFAULT_WEIGHT_WARNING_LB,
        "near_full_floor": DEFAULT_NEAR_FULL_FLOOR,
        "material_schemes": [
            {"name": "Metal", "code": "MTL", "enabled": True},
            {"name": "Foam", "code": "FM", "enabled": True},
            {"name": "Cardboard", "code": "CB", "enabled": True},
        ],
        "name_counters": {},
    }


def load_settings() -> dict:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    defaults = default_settings()
    if not SETTINGS_PATH.exists():
        save_settings(defaults)
        return defaults
    try:
        data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError
    except Exception:
        backup = SETTINGS_PATH.with_suffix(".bad.json")
        try:
            shutil.copy2(SETTINGS_PATH, backup)
        except OSError:
            pass
        save_settings(defaults)
        return defaults
    for key, value in defaults.items():
        data.setdefault(key, value)
    return data


def save_settings(settings: dict) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temp = SETTINGS_PATH.with_suffix(".tmp")
    temp.write_text(json.dumps(settings, indent=2), encoding="utf-8")
    temp.replace(SETTINGS_PATH)


def container_prefix(ctype: str) -> str:
    return "PLT" if ctype == "wood" else "PLB"


def enabled_material_schemes(settings: dict) -> list[dict]:
    return [x for x in settings.get("material_schemes", []) if x.get("enabled", True)]


def next_persistent_sequence(prefix: str, material_code: str, date_code: str, settings: dict) -> int:
    key = f"{prefix}|{clean_id(material_code).replace(' ', '')}|{date_code}"
    current = int(settings.get("name_counters", {}).get(key, 0))
    return current + 1


def commit_persistent_sequence(prefix: str, material_code: str, date_code: str, sequence: int, settings: dict) -> None:
    key = f"{prefix}|{clean_id(material_code).replace(' ', '')}|{date_code}"
    settings.setdefault("name_counters", {})[key] = max(
        int(settings.get("name_counters", {}).get(key, 0)), sequence
    )
    save_settings(settings)


def manage_naming_schemes() -> None:
    while True:
        settings = load_settings()
        schemes = settings.get("material_schemes", [])
        print("\n╔════════════════════ NAMING SCHEMES ════════════════════╗")
        if schemes:
            for i, scheme in enumerate(schemes, 1):
                state = "ON " if scheme.get("enabled", True) else "OFF"
                print(f"  [{i:>2}] {scheme.get('name',''):<24} {scheme.get('code',''):<10} {state}")
        else:
            print("  No naming schemes configured.")
        print("\n  [A] Add   [E] Edit   [T] Enable/disable   [D] Delete   [0] Back")
        action = input("> ").strip().upper()
        if action == "0":
            return
        if action == "A":
            name = input("Material name: ").strip()
            code = clean_id(input("Code (example MTL): ")).replace(" ", "")
            if not name or not re.fullmatch(r"[A-Z0-9]{1,12}", code):
                print("Name required; code must be 1-12 letters/numbers.")
                continue
            if any(clean_id(x.get("code", "")) == code for x in schemes):
                print("That code already exists.")
                continue
            schemes.append({"name": name[:40], "code": code, "enabled": True})
            save_settings(settings)
        elif action in {"E", "T", "D"}:
            raw = input("Scheme number: ").strip()
            try:
                idx = int(raw) - 1
                scheme = schemes[idx]
            except (ValueError, IndexError):
                print("Invalid scheme.")
                continue
            if action == "E":
                name = input(f"Name [{scheme['name']}]: ").strip()
                code = clean_id(input(f"Code [{scheme['code']}]: ")).replace(" ", "")
                if name:
                    scheme["name"] = name[:40]
                if code:
                    if not re.fullmatch(r"[A-Z0-9]{1,12}", code):
                        print("Invalid code.")
                        continue
                    if any(i != idx and clean_id(x.get("code","")) == code for i, x in enumerate(schemes)):
                        print("That code already exists.")
                        continue
                    scheme["code"] = code
                save_settings(settings)
            elif action == "T":
                scheme["enabled"] = not scheme.get("enabled", True)
                save_settings(settings)
            else:
                print(f"Delete {scheme['name']} ({scheme['code']})?")
                if ask_yes_no("Confirm delete"):
                    schemes.pop(idx)
                    save_settings(settings)


def trailer_capacity_info(r: "RZRRRecord") -> dict:
    counts = {k: 0 for k in TYPES}
    for b in r.bins:
        counts[b.container_type] += 1
    known_floor = counts["wood"] + (counts["box"] + 1) // 2 + (counts["sleeve"] + 1) // 2
    open_box_stack = counts["box"] % 2
    open_sleeve_stack = counts["sleeve"] % 2
    open_floor = max(0, STANDARD_FLOOR_POSITIONS - known_floor)
    return {
        "known_floor": known_floor,
        "open_floor": open_floor,
        "open_box_stack": open_box_stack,
        "open_sleeve_stack": open_sleeve_stack,
        "box_only": open_box_stack + 2 * open_floor,
        "sleeve_only": open_sleeve_stack + 2 * open_floor,
        "wood_only": open_floor,
        "existing_stack_slots": open_box_stack + open_sleeve_stack,
    }


def show_fit_options(r: "RZRRRecord", do_pause: bool = True) -> None:
    info = trailer_capacity_info(r)
    print("\n╔══════════════════ WHAT CAN STILL FIT? ══════════════════╗")
    print(f"  Standard-plan floor use : {info['known_floor']}/{STANDARD_FLOOR_POSITIONS}")
    print(f"  Open standard floor     : {info['open_floor']}")
    print(f"  Open BOX upper slots    : {info['open_box_stack']}")
    print(f"  Open SLEEVE upper slots : {info['open_sleeve_stack']}")
    if info["known_floor"] >= STANDARD_FLOOR_POSITIONS:
        print("\n  No unused standard floor positions remain.")
        if info["existing_stack_slots"]:
            print("  Existing partial stacks can still accept:")
            if info["open_box_stack"]:
                print("    +1 plastic pallet box")
            if info["open_sleeve_stack"]:
                print("    +1 pallet sleeve")
    else:
        print("\n  If all remaining standard floor is used for one type:")
        print(f"    BOXES   : up to +{info['box_only']}")
        print(f"    SLEEVES : up to +{info['sleeve_only']}")
        print(f"    WOOD    : up to +{info['wood_only']}")
        if info["existing_stack_slots"]:
            print("\n  Partial-stack room is included in those totals.")
    print("\n  Mixed loads vary by which open floor positions you dedicate")
    print("  to BOX / SLEEVE / WOOD. This is a planning aid, not a load limit.")
    if do_pause:
        pause()

@dataclass
class BinRecord:
    bin_name: str
    seal: str
    weight_lb: int
    container_type: str
    material: str = ""
    aisle: Optional[int] = None
    status: str = "staged"
    dock_order: Optional[int] = None
    truck_position: Optional[str] = None
    stack_level: Optional[int] = None
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)


@dataclass
class RZRRRecord:
    rzrr: str
    dock_door: Optional[int] = None
    state: str = "draft"
    created_at: str = field(default_factory=now_iso)
    updated_at: str = field(default_factory=now_iso)
    bins: list[BinRecord] = field(default_factory=list)
    version: int = APP_VERSION

    @property
    def locked(self) -> bool:
        return self.state in {"security_approved", "complete"}

    @property
    def path(self) -> Path:
        return RZRR_DIR / f"{safe_name(self.rzrr)}.json"

    def save(self) -> None:
        RZRR_DIR.mkdir(parents=True, exist_ok=True)
        self.updated_at = now_iso()
        payload = asdict(self)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        temp.replace(self.path)

    @classmethod
    def load(cls, path: Path) -> "RZRRRecord":
        raw = json.loads(path.read_text(encoding="utf-8"))
        saved_version = raw.get("version", 2)
        if saved_version not in {2, 3, 31, APP_VERSION}:
            raise ValueError("Unsupported save-file version")
        bins = [BinRecord(**item) for item in raw.pop("bins", [])]
        raw["version"] = APP_VERSION
        obj = cls(**raw)
        obj.bins = bins
        obj.validate()
        return obj

    def validate(self) -> None:
        if not self.rzrr or len(self.rzrr) > 100:
            raise ValueError("Invalid RZRR")
        seen_bins: set[str] = set()
        seen_seals: set[str] = set()
        for item in self.bins:
            if item.container_type not in TYPES:
                raise ValueError("Invalid container type")
            if item.status not in STATUSES:
                raise ValueError("Invalid bin status")
            if item.weight_lb < 0:
                raise ValueError("Invalid weight")
            if item.container_type != "unknown" and item.weight_lb <= 0:
                raise ValueError("Known container types require a positive weight")
            b = clean_id(item.bin_name)
            s = clean_id(item.seal)
            if not b or not s or b in seen_bins or s in seen_seals:
                raise ValueError("Duplicate or missing bin/seal")
            seen_bins.add(b)
            seen_seals.add(s)

    def find_bin(self, query: str) -> Optional[BinRecord]:
        q = clean_id(query)
        return next((b for b in self.bins if clean_id(b.bin_name) == q), None)

    def occupied(self, position: str) -> list[BinRecord]:
        return sorted(
            [b for b in self.bins if b.truck_position == position],
            key=lambda b: b.stack_level or 0,
        )

    def floor_positions_required(self) -> int:
        """Known floor positions only; imported unknown types are excluded."""
        counts = {key: 0 for key in TYPES}
        for b in self.bins:
            counts[b.container_type] += 1
        return counts["wood"] + (counts["box"] + 1) // 2 + (counts["sleeve"] + 1) // 2

    def pending_details(self) -> int:
        return sum(1 for b in self.bins if b.container_type == "unknown" or b.weight_lb <= 0)

    def estimated_floor_range(self) -> tuple[int, int]:
        """Min/max floor positions while imported container types are unknown."""
        known = self.floor_positions_required()
        unknown = sum(1 for b in self.bins if b.container_type == "unknown")
        # Best case: all pending containers are stackable two-high.
        minimum = known + (unknown + 1) // 2
        # Worst case: every pending container is a wood pallet.
        maximum = known + unknown
        return minimum, maximum

    def total_weight(self) -> int:
        return sum(b.weight_lb for b in self.bins if b.weight_lb > 0)


def list_rzrr_paths() -> list[Path]:
    RZRR_DIR.mkdir(parents=True, exist_ok=True)
    return sorted(RZRR_DIR.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True)


def create_rzrr() -> RZRRRecord:
    print("\nCREATE RZRR")
    rzrr = clean_id(input("RZRR identifier: "))
    while not rzrr:
        rzrr = clean_id(input("RZRR identifier is required: "))
    record = RZRRRecord(rzrr=rzrr)
    if record.path.exists() and not ask_yes_no("That RZRR exists. Overwrite it?"):
        raise RuntimeError("Cancelled")
    record.save()
    return record


def open_rzrr() -> Optional[RZRRRecord]:
    paths = list_rzrr_paths()
    if not paths:
        print("No saved RZRRs.")
        pause()
        return None
    print("\nSAVED RZRRs")
    loaded: list[tuple[Path, Optional[RZRRRecord]]] = []
    for i, path in enumerate(paths, 1):
        try:
            r = RZRRRecord.load(path)
            loaded.append((path, r))
            print(f"{i:>2}. {r.rzrr:<18} {r.state:<18} {len(r.bins):>3} bins | {r.floor_positions_required():>2}/24 spots")
        except Exception:
            loaded.append((path, None))
            print(f"{i:>2}. {path.name} (invalid save)")
    raw = input("Open number, or blank to cancel: ").strip()
    if not raw:
        return None
    try:
        item = loaded[int(raw) - 1][1]
        if item is None:
            raise ValueError
        return item
    except (ValueError, IndexError):
        print("Invalid selection.")
        pause()
        return None


def add_bin(r: RZRRRecord, previous: Optional[BinRecord] = None) -> Optional[BinRecord]:
    if r.locked:
        print("This RZRR is locked.")
        return None
    print("\nADD BIN (blank bin name cancels)")
    bin_name = clean_id(input("Scan/enter bin name: "))
    if not bin_name:
        return None
    if r.find_bin(bin_name):
        print("That bin already exists in this RZRR.")
        return None
    seal = clean_id(input("Scan/enter seal: "))
    if not seal:
        print("Seal is required.")
        return None
    if any(clean_id(b.seal) == seal for b in r.bins):
        print("That seal is already assigned in this RZRR.")
        return None
    weight = get_weight()

    default_type = previous.container_type if previous else None
    if default_type and ask_yes_no(f"Reuse container type: {TYPES[default_type]['label']}?", default=True):
        ctype = default_type
    else:
        ctype = choose("Container type", [(k, v["label"]) for k, v in TYPES.items()]) or "box"

    # V3 rapid intake deliberately avoids location and contents questions.
    # Legacy fields remain in the save format so V2 records still open.
    material = ""
    aisle = None
    item = BinRecord(bin_name, seal, weight, ctype, material, aisle)
    r.bins.append(item)
    r.save()
    floor = r.floor_positions_required()
    if floor > STANDARD_FLOOR_POSITIONS:
        print(f"Saved. WARNING: {floor}/{STANDARD_FLOOR_POSITIONS} standard floor positions.")
    else:
        print("Saved.")
    return item


def rapid_entry(r: RZRRRecord) -> None:
    previous: Optional[BinRecord] = r.bins[-1] if r.bins else None
    while True:
        item = add_bin(r, previous)
        if item is None:
            break
        previous = item


def progress_bar(value: int, maximum: int = STANDARD_FLOOR_POSITIONS, width: int = 34) -> str:
    if maximum <= 0:
        return "░" * width
    shown = max(0, min(value, maximum))
    filled = round((shown / maximum) * width)
    return "█" * filled + "░" * (width - filled)


def show_summary(r: RZRRRecord) -> None:
    settings = load_settings()
    counts = {k: 0 for k in TYPES}
    for b in r.bins:
        counts[b.container_type] += 1

    pending = r.pending_details()
    min_floor, max_floor = r.estimated_floor_range()
    floor = r.floor_positions_required()
    dock_verified = sum(1 for b in r.bins if b.dock_order is not None)
    weight = r.total_weight()
    weight_warn = int(settings.get("weight_warning_lb", DEFAULT_WEIGHT_WARNING_LB))
    near_full = int(settings.get("near_full_floor", DEFAULT_NEAR_FULL_FLOOR))
    fit = trailer_capacity_info(r)

    print("\n╔" + "═" * 82 + "╗")
    print(f"║  OUTBOUND TRACKER V3.2{'':<59}║")
    print("╠" + "═" * 82 + "╣")
    print(f"║  RZRR {r.rzrr[:22]:<22} STATUS {r.state.replace('_',' ').upper()[:18]:<18} DOCK {str(r.dock_door or 'UNASSIGNED'):<10} ║")
    print(f"║  BINS {len(r.bins):<22} WEIGHT {f'{weight:,} lb':<17} ORDERED {f'{dock_verified}/{len(r.bins)}':<10} ║")
    print("╠" + "═" * 82 + "╣")
    if pending:
        cap_label = f"{min_floor}-{max_floor}/{STANDARD_FLOOR_POSITIONS} EST."
        bar_value = min_floor
    else:
        cap_label = f"{floor}/{STANDARD_FLOOR_POSITIONS}"
        bar_value = floor
    print(f"║  CAPACITY {progress_bar(bar_value)}  {cap_label:<18} ║")
    print(f"║  BOX {counts['box']:<4} SLEEVE {counts['sleeve']:<4} WOOD {counts['wood']:<4} PENDING {counts['unknown']:<4}  "
          f"STACK ROOM  BOX +{fit['open_box_stack']} / SLV +{fit['open_sleeve_stack']}{'':<8}║")
    warnings = []
    if not pending and floor >= STANDARD_FLOOR_POSITIONS:
        warnings.append("OVER STANDARD PLAN" if floor > STANDARD_FLOOR_POSITIONS else "STANDARD PLAN FULL")
    elif not pending and floor >= near_full:
        warnings.append("NEAR FULL")
    if weight >= weight_warn:
        warnings.append(f"WEIGHT >= {weight_warn:,} LB")
    if pending:
        warnings.append(f"{pending} PENDING DETAIL(S)")
    warning_text = " | ".join(warnings) if warnings else "No active capacity/weight warnings"
    print(f"║  {warning_text[:78]:<78}  ║")
    print("╚" + "═" * 82 + "╝")

def list_bins(r: RZRRRecord) -> None:
    show_summary(r)
    print("\n#   BIN NAME                       SEAL                 WT    TYPE   DOCK/TRUCK")
    print("-" * 92)
    for i, b in enumerate(r.bins, 1):
        placement = (
            f"Truck {b.truck_position}/{b.stack_level}" if b.truck_position else
            f"Dock #{b.dock_order}" if b.dock_order is not None else "-"
        )
        wt = str(b.weight_lb) if b.weight_lb > 0 else "PEND"
        print(f"{i:<3} {b.bin_name[:30]:<30} {b.seal[:20]:<20} {wt:>5}  {TYPES[b.container_type]['short']:<5}  {placement}")
    pause()


def reset_aisles(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    if ask_yes_no("Clear all current-shift aisle assignments?"):
        for b in r.bins:
            if b.status == "staged":
                b.aisle = None
                b.updated_at = now_iso()
        r.save()
        print("Aisle assignments cleared.")


def assign_rzrr_aisle(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    aisle = get_aisle(allow_blank=False)
    for b in r.bins:
        if b.status == "staged":
            b.aisle = aisle
            b.updated_at = now_iso()
    r.save()
    print(f"All staged bins assigned to Aisle {aisle}.")


def edit_one_bin(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    query = input("Scan/enter bin name to edit: ").strip()
    b = r.find_bin(query)
    if not b:
        print("Bin not found.")
        return

    print("Leave a field blank to keep its value.")
    new_name = clean_id(input(f"Bin name [{b.bin_name}]: "))
    existing = r.find_bin(new_name) if new_name else None
    if new_name and existing is not None and existing is not b:
        print("That bin name already exists; edit cancelled.")
        return

    seal = clean_id(input(f"Seal [{b.seal}]: "))
    if seal and any(clean_id(x.seal) == seal and x is not b for x in r.bins):
        print("Seal already assigned; edit cancelled.")
        return

    raw_weight = input(f"Weight [{b.weight_lb if b.weight_lb else 'PENDING'}]: ").strip()
    new_weight = b.weight_lb
    if raw_weight:
        try:
            new_weight = int(raw_weight.replace(",", ""))
            if new_weight <= 0:
                raise ValueError
        except ValueError:
            print("Invalid weight; edit cancelled.")
            return

    old_type = b.container_type
    new_type = old_type
    known_type_options = [(k, v["label"]) for k, v in TYPES.items() if k != "unknown"]
    if old_type == "unknown" or ask_yes_no(f"Change container type ({TYPES[old_type]['label']})?"):
        selected = choose("Container type", known_type_options, allow_blank=(old_type != "unknown"))
        if selected:
            new_type = selected

    if new_type != "unknown" and new_weight <= 0:
        print("Enter the physical weight before completing this imported bin.")
        return

    # Validate capacity before committing.
    old_values = (b.bin_name, b.seal, b.weight_lb, b.container_type)
    if new_name:
        b.bin_name = new_name
    if seal:
        b.seal = seal
    b.weight_lb = new_weight
    b.container_type = new_type
    # More than 24 standard floor positions is allowed as an operational
    # reality; it produces a warning instead of blocking the edit.

    # Layout can become stale after a name/type edit, so rebuild it explicitly later.
    if new_type != old_type:
        for item in r.bins:
            item.truck_position = None
            item.stack_level = None
            if item.status == "loaded":
                item.status = "dock" if item.dock_order is not None else "staged"
        r.state = "dock_staged" if all(x.dock_order is not None for x in r.bins) else "draft"

    b.updated_at = now_iso()
    r.save()
    print("Updated.")

def create_named_bin(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return

    settings = load_settings()
    schemes = enabled_material_schemes(settings)
    if not schemes:
        print("No enabled material naming schemes. Add one first.")
        manage_naming_schemes()
        return

    print("\n╔════════════════ CREATE / NAME CONTAINER ════════════════╗")
    ctype = choose("Container type", [
        ("box", "Plastic pallet box  → PLB"),
        ("sleeve", "Pallet sleeve      → PLB"),
        ("wood", "Wood pallet        → PLT"),
    ]) or "box"
    prefix = container_prefix(ctype)

    options = [(str(i), f"{x['name']} ({x['code']})") for i, x in enumerate(schemes)]
    selected = choose("Material", options)
    try:
        scheme = schemes[int(selected or "0")]
    except (ValueError, IndexError):
        print("Invalid material.")
        return
    code = clean_id(scheme["code"]).replace(" ", "")
    date_code = datetime.now().strftime("%m%d%y")
    sequence = next_persistent_sequence(prefix, code, date_code, settings)
    generated = f"{prefix}/{sequence}{code}{date_code}"

    print(f"\nGenerated: {generated}")
    custom = clean_id(input("Enter = accept | or type corrected name: "))
    bin_name = custom or generated
    if r.find_bin(bin_name):
        print("That bin name already exists.")
        return

    seal = clean_id(input("Scan/enter seal: "))
    if not seal:
        print("Seal is required.")
        return
    if any(clean_id(b.seal) == seal for b in r.bins):
        print("That seal is already assigned in this RZRR.")
        return

    weight = get_weight()
    r.bins.append(BinRecord(bin_name, seal, weight, ctype))
    r.save()
    # Commit the counter only when the generated name itself was accepted.
    # A manually corrected name should not silently consume a generated number.
    if not custom:
        commit_persistent_sequence(prefix, code, date_code, sequence, settings)
    floor = r.floor_positions_required()
    print(f"Saved {bin_name}.")
    if floor > STANDARD_FLOOR_POSITIONS:
        print(f"WARNING: {floor}/{STANDARD_FLOOR_POSITIONS} standard floor positions.")

def parse_expected_line(line: str) -> Optional[tuple[str, Optional[str]]]:
    """Parse 'BIN - SEAL' and numbered '1. BIN - SEAL' lines safely."""
    line = line.strip()
    if not line:
        return None
    # Only remove a list number when punctuation is present. This preserves
    # legitimate numeric bin names such as "1234 - 43212".
    line = re.sub(r"^\s*\d+\s*[.)]\s+", "", line)
    match = re.match(r"^(.*?)\s+-\s+(.*?)$", line)
    if match:
        name, seal = clean_id(match.group(1)), clean_id(match.group(2))
        return (name, seal or None) if name else None
    name = clean_id(line)
    return (name, None) if name else None

def paste_asana_pairs() -> list[tuple[str, str]]:
    print("\nPaste the full Asana/Issues list.")
    print("Format: BIN NAME - SEAL")
    print("Numbered lines such as '1. BIN - SEAL' are accepted.")
    print("Press Enter on a blank line when the paste is complete.\n")
    pairs: list[tuple[str, str]] = []
    while True:
        line = input()
        if not line.strip():
            break
        parsed = parse_expected_line(line)
        if not parsed:
            continue
        name, seal = parsed
        if not seal:
            print(f"  ! Skipped {name}: no seal found.")
            continue
        pairs.append((clean_id(name), clean_id(seal)))
    if pairs:
        print(f"\n✓ Loaded {len(pairs)} BIN + SEAL pair(s).")
    return pairs

def import_asana_list(r: RZRRRecord) -> None:
    """Bring a previous shift's Asana/Issues bin+seal list into the RZRR."""
    if r.locked:
        print("This RZRR is locked.")
        return

    print("\n╔══════════════════ IMPORT ASANA / ISSUES ══════════════════╗")
    pairs = paste_asana_pairs()
    if not pairs:
        print("Nothing imported.")
        pause()
        return

    added = 0
    same = 0
    conflicts: list[str] = []
    seen_input: set[str] = set()

    for name, seal in pairs:
        if name in seen_input:
            conflicts.append(f"Duplicate pasted bin: {name}")
            continue
        seen_input.add(name)

        existing = r.find_bin(name)
        if existing:
            if clean_id(existing.seal) == seal:
                same += 1
            else:
                conflicts.append(
                    f"{name}: tracker seal {existing.seal} != pasted seal {seal}"
                )
            continue

        seal_owner = next((b for b in r.bins if clean_id(b.seal) == seal), None)
        if seal_owner:
            conflicts.append(f"Seal {seal} already belongs to {seal_owner.bin_name}")
            continue

        # Day-shift import knows identity, but not physical type/weight yet.
        r.bins.append(BinRecord(
            bin_name=name,
            seal=seal,
            weight_lb=0,
            container_type="unknown",
            status="staged",
        ))
        added += 1

    r.save()
    print("\n╠══════════════════════ IMPORT RESULT ══════════════════════╣")
    print(f"  Added as pending: {added}")
    print(f"  Already matched:  {same}")
    print(f"  Conflicts:        {len(conflicts)}")
    if conflicts:
        print("\n  REVIEW:")
        for conflict in conflicts:
            print(f"   ! {conflict}")
    print("\nImported bins can be completed later with Edit Bin.")
    pause()


def delete_bin(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    query = clean_id(input("Scan/enter bin name to delete: "))
    b = r.find_bin(query)
    if not b:
        print("Bin not found.")
        return
    print(f"\nDELETE: {b.bin_name} - {b.seal} | {b.weight_lb or 'PENDING'} lb | {TYPES[b.container_type]['label']}")
    if not ask_yes_no("Delete this record"):
        print("Cancelled.")
        return
    r.bins.remove(b)
    # Renumber dock order to keep output clean.
    ordered = sorted((x for x in r.bins if x.dock_order is not None), key=lambda x: x.dock_order or 0)
    for i, item in enumerate(ordered, 1):
        item.dock_order = i
    r.save()
    print("Deleted.")


def dock_parity_check(r: RZRRRecord) -> None:
    """Compare physical BIN+SEAL pairs against authoritative Asana/Issues text."""
    print("\n╔════════════════════ DOCK PARITY CHECK ════════════════════╗")
    expected_pairs = paste_asana_pairs()
    if not expected_pairs:
        print("No expected Asana/Issues pairs loaded.")
        pause()
        return

    expected: dict[str, str] = {}
    input_duplicates: list[str] = []
    for name, seal in expected_pairs:
        if name in expected:
            input_duplicates.append(name)
        expected[name] = seal

    print(f"\nExpected pairs loaded: {len(expected)}")
    print("Walk the physical dock and scan BIN then SEAL.")
    print("Blank BIN finishes the walk.\n")

    physical: list[tuple[str, str]] = []
    scan_no = 1
    while True:
        name = clean_id(input(f"BIN  {scan_no:>2}/{len(expected)} > "))
        if not name:
            break
        seal = clean_id(input(f"SEAL {scan_no:>2}/{len(expected)} > "))
        if not seal:
            print("  ! No seal scanned; pair not recorded.")
            continue
        physical.append((name, seal))

        if name not in expected:
            print(f"  ! UNEXPECTED BIN — {name}")
        elif expected[name] != seal:
            print(f"  ✗ SEAL MISMATCH — expected {expected[name]}, scanned {seal}")
        else:
            print("  ✓ MATCH")
        scan_no += 1

    physical_by_name: dict[str, list[str]] = {}
    for name, seal in physical:
        physical_by_name.setdefault(name, []).append(seal)

    expected_names = set(expected)
    physical_names = set(physical_by_name)
    missing = sorted(expected_names - physical_names)
    unexpected = sorted(physical_names - expected_names)
    duplicate_scans = sorted(name for name, seals in physical_by_name.items() if len(seals) > 1)

    wrong_seals: list[tuple[str, str, str]] = []
    matched = 0
    for name in sorted(expected_names & physical_names):
        seals = physical_by_name[name]
        if len(seals) == 1 and seals[0] == expected[name]:
            matched += 1
        elif expected[name] not in seals:
            wrong_seals.append((name, expected[name], "/".join(seals)))

    passed = (
        matched == len(expected)
        and len(physical) == len(expected)
        and not missing
        and not unexpected
        and not duplicate_scans
        and not wrong_seals
        and not input_duplicates
    )

    print("\n╔" + "═" * 62 + "╗")
    print(f"║ {'PARITY PASS' if passed else 'PARITY FAILED':^62} ║")
    print("╠" + "═" * 62 + "╣")
    print(f"║  EXPECTED {len(expected):>4}   SCANNED {len(physical):>4}   MATCHED {matched:>4}{'':<23}║")
    print(f"║  MISSING  {len(missing):>4}   EXTRA   {len(unexpected):>4}   WRONG SEAL {len(wrong_seals):>3}{'':<15}║")
    print("╚" + "═" * 62 + "╝")

    if missing:
        print("\nMISSING FROM PHYSICAL DOCK")
        for name in missing:
            print(f"  - {name} - {expected[name]}")
    if unexpected:
        print("\nON DOCK BUT NOT IN ASANA / ISSUES")
        for name in unexpected:
            for seal in physical_by_name[name]:
                print(f"  + {name} - {seal}")
    if wrong_seals:
        print("\nSEAL MISMATCHES")
        for name, exp, got in wrong_seals:
            print(f"  ✗ {name}")
            print(f"      EXPECTED: {exp}")
            print(f"      SCANNED:  {got}")
    if duplicate_scans:
        print("\nDUPLICATE PHYSICAL SCANS")
        for name in duplicate_scans:
            print(f"  ! {name} scanned {len(physical_by_name[name])} times")
    if input_duplicates:
        print("\nDUPLICATES IN PASTED ASANA / ISSUES TEXT")
        for name in sorted(set(input_duplicates)):
            print(f"  ! {name}")

    if passed:
        print(f"\n✓ {matched}/{len(expected)} BIN + SEAL pairs verified.")
    else:
        print("\nResolve the listed discrepancies before treating the dock as matched.")
    pause()



def build_dock_order(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    if not r.bins:
        print("No bins entered.")
        return
    print("\nBUILD DOCK ORDER")
    print("Scan bins in the physical order Security should verify them.")
    print("Blank input finishes. Existing dock order will be replaced.")
    for b in r.bins:
        b.dock_order = None
        if b.status == "dock":
            b.status = "staged"
    ordered: list[BinRecord] = []
    while len(ordered) < len(r.bins):
        raw = input(f"Next bin ({len(ordered)+1}/{len(r.bins)}): ").strip()
        if not raw:
            break
        b = r.find_bin(raw)
        if not b:
            print("Not found in this RZRR.")
            continue
        if b in ordered:
            print("Already scanned into dock order.")
            continue
        b.dock_order = len(ordered) + 1
        b.status = "dock"
        b.aisle = None
        b.updated_at = now_iso()
        ordered.append(b)
        print(f"Added #{b.dock_order}: {b.bin_name} - {b.seal}")
    r.state = "dock_staged" if len(ordered) == len(r.bins) else "draft"
    r.save()
    print(f"Dock order saved: {len(ordered)}/{len(r.bins)} bins.")


def issues_lines(r: RZRRRecord) -> list[str]:
    ordered = sorted(r.bins, key=lambda b: (b.dock_order is None, b.dock_order or 999999, b.created_at))
    return [f"{i}. {b.bin_name} - {b.seal}" for i, b in enumerate(ordered, 1)]


def show_issues_output(r: RZRRRecord) -> None:
    print(f"\nISSUES / MOBILITY OUTPUT — {r.rzrr}\n")
    print("\n".join(issues_lines(r)))
    if any(b.dock_order is None for b in r.bins):
        print("\nWARNING: Some bins have no dock order; they appear last.")
    pause()


def export_files(r: RZRRRecord) -> None:
    EXPORT_DIR.mkdir(parents=True, exist_ok=True)
    base = safe_name(r.rzrr)
    text_path = EXPORT_DIR / f"{base}_issues.txt"
    csv_path = EXPORT_DIR / f"{base}_records.csv"
    text_path.write_text("\n".join(issues_lines(r)) + "\n", encoding="utf-8")

    def csv_safe(value: object) -> object:
        if isinstance(value, str) and value[:1] in {"=", "+", "-", "@"}:
            return "'" + value
        return value

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["rzrr", "bin_name", "seal", "weight_lb", "container_type", "material", "aisle", "status", "dock_order", "truck_position", "stack_level"])
        for b in r.bins:
            writer.writerow([csv_safe(r.rzrr), csv_safe(b.bin_name), csv_safe(b.seal), b.weight_lb, b.container_type, csv_safe(b.material), b.aisle or "", b.status, b.dock_order or "", b.truck_position or "", b.stack_level or ""])
    print(f"Exported:\n  {text_path}\n  {csv_path}")


def layout_positions(r: RZRRRecord) -> list[str]:
    """Standard 24 positions plus as many overflow planning positions as needed."""
    required = max(STANDARD_FLOOR_POSITIONS, r.floor_positions_required())
    extra = max(0, required - STANDARD_FLOOR_POSITIONS)
    return POSITIONS + [f"O{i:02d}" for i in range(1, extra + 1)]


def next_slot(r: RZRRRecord, ctype: str) -> Optional[tuple[str, int]]:
    cap = TYPES[ctype]["capacity"]
    positions = layout_positions(r)

    if cap > 1:
        for pos in positions:
            items = r.occupied(pos)
            if items and items[0].container_type == ctype and len(items) < cap:
                used = {b.stack_level for b in items}
                for level in range(1, cap + 1):
                    if level not in used:
                        return pos, level

    for pos in positions:
        if not r.occupied(pos):
            return pos, 1
    return None

def auto_layout(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    if r.pending_details():
        print(f"{r.pending_details()} imported bin(s) still need physical weight/type details.")
        print("Complete them with Edit Bin before building the trailer layout.")
        return
    for b in r.bins:
        b.truck_position = None
        b.stack_level = None
    ordered = sorted(r.bins, key=lambda b: (b.dock_order is None, b.dock_order or 999999, b.created_at))
    for b in ordered:
        slot = next_slot(r, b.container_type)
        if slot is None:
            print("Unable to create layout.")
            return
        b.truck_position, b.stack_level = slot
        b.status = "loaded"
        b.updated_at = now_iso()
    r.state = "loaded"
    r.save()
    floor = r.floor_positions_required()
    print("Trailer layout created from dock order.")
    if floor > STANDARD_FLOOR_POSITIONS:
        print(f"WARNING: layout uses {floor}/{STANDARD_FLOOR_POSITIONS} standard-plan floor positions; overflow positions are labeled O01, O02, etc.")


def show_trailer(r: RZRRRecord) -> None:
    print(f"\n{'FRONT':^67}")
    print("                    ▲")
    print("        ┌──────────────────────────┬──────────────────────────┐")
    for row in range(1, 13):
        cells = []
        for side in ("L", "R"):
            pos = f"{side}{row:02d}"
            items = r.occupied(pos)
            if not items:
                content = "EMPTY"
            else:
                content = "/".join(
                    f"{TYPES[b.container_type]['short']}:{b.bin_name[:11]}" for b in items
                )
            cells.append(f"{pos} {content}"[:24])
        print(f"        │ {cells[0]:<24} │ {cells[1]:<24} │")
        if row != 12:
            print("        ├──────────────────────────┼──────────────────────────┤")
    print("        └──────────────────────────┴──────────────────────────┘")
    print("                    ▼")
    print(f"{'DOORS':^67}")
    if r.pending_details():
        lo, hi = r.estimated_floor_range()
        print(f"\nCapacity estimate: {lo}-{hi}/24 floor positions | {r.pending_details()} pending details")
    else:
        floor = r.floor_positions_required()
        print(f"\n{progress_bar(floor, 24, 32)}  {floor}/24 floor positions")
    overflow = [p for p in layout_positions(r) if p.startswith("O") and r.occupied(p)]
    if overflow:
        print("\nOVERFLOW / NON-STANDARD PLANNING POSITIONS")
        for pos in overflow:
            items = r.occupied(pos)
            content = " / ".join(f"{TYPES[b.container_type]['short']}:{b.bin_name}" for b in items)
            print(f"  {pos}: {content}")
    print(f"Containers: {len(r.bins)} | Known weight: {r.total_weight():,} lb")
    pause()



def mark_security_approved(r: RZRRRecord) -> None:
    if r.locked:
        print("Already locked.")
        return
    if not r.bins:
        print("No bins entered.")
        return
    if r.pending_details():
        print("Complete all imported weight/type details before Security approval.")
        return
    if any(b.dock_order is None for b in r.bins):
        print("Every bin must have a dock order before approval.")
        return
    print("\nThis permanently locks all current data in the prototype.")
    if ask_yes_no("Mark Security Approved?"):
        r.state = "security_approved"
        r.save()
        print("RZRR locked as Security Approved.")


def search_all() -> None:
    query = clean_id(input("Search RZRR or bin name: "))
    if not query:
        return
    results = []
    for path in list_rzrr_paths():
        try:
            r = RZRRRecord.load(path)
        except Exception:
            continue
        if query in clean_id(r.rzrr):
            results.append(f"{r.rzrr}: {len(r.bins)} bins, state={r.state}, dock={r.dock_door or 'unassigned'}")
        for b in r.bins:
            if query in clean_id(b.bin_name):
                loc = f"Dock order {b.dock_order}" if b.status == "dock" else f"Aisle {b.aisle}" if b.aisle else b.status
                results.append(f"{b.bin_name}: {r.rzrr}, {loc}, seal={b.seal}, {b.weight_lb} lb")
    print("\n" + ("\n".join(results) if results else "No matches."))
    pause()


def rzrr_menu(r: RZRRRecord) -> None:
    while True:
        show_summary(r)
        print("\n  INTAKE / SHIFT SYNC")
        print("   [1] Rapid scan new bins          [2] Import Asana / Issues")
        print("   [3] Create & auto-name container [4] View bins")
        print("   [5] Edit bin                     [6] Delete bin")
        print("\n  QUALITY")
        print("   [7] Dock parity — BIN + SEAL     [8] Build dock / Security order")
        print("   [9] Show Issues / Mobility text")
        print("\n  TRAILER / CAPACITY")
        print("  [10] What can still fit?         [11] Build / refresh trailer layout")
        print("  [12] View trailer")
        print("\n  ADMIN")
        print("  [13] Naming schemes              [14] Assign/change dock door")
        print("  [15] Export text and CSV         [16] Mark Security Approved (lock)")
        print("   [0] Save and return")
        raw = input("\n> ").strip()
        if raw == "1":
            rapid_entry(r)
        elif raw == "2":
            import_asana_list(r)
        elif raw == "3":
            create_named_bin(r)
        elif raw == "4":
            list_bins(r)
        elif raw == "5":
            edit_one_bin(r)
        elif raw == "6":
            delete_bin(r)
        elif raw == "7":
            dock_parity_check(r)
        elif raw == "8":
            build_dock_order(r)
        elif raw == "9":
            show_issues_output(r)
        elif raw == "10":
            show_fit_options(r)
        elif raw == "11":
            auto_layout(r)
        elif raw == "12":
            show_trailer(r)
        elif raw == "13":
            manage_naming_schemes()
        elif raw == "14":
            if r.locked:
                print("This RZRR is locked.")
            else:
                r.dock_door = get_dock()
                r.save()
        elif raw == "15":
            export_files(r)
        elif raw == "16":
            mark_security_approved(r)
        elif raw == "0":
            r.save()
            return
        else:
            print("Choose a valid option.")

def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        print("\nOUTBOUND SHIPPING TRACKER V3.2")
        print("Offline prototype — use fake/test data only")
        print("\n1. Create RZRR")
        print("2. Open RZRR")
        print("3. Search")
        print("0. Exit")
        raw = input("> ").strip()
        if raw == "1":
            try: rzrr_menu(create_rzrr())
            except RuntimeError as exc: print(exc)
        elif raw == "2":
            r = open_rzrr()
            if r: rzrr_menu(r)
        elif raw == "3": search_all()
        elif raw == "0": return
        else: print("Choose a valid option.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExited safely.")
