#!/usr/bin/env python3
"""Outbound Shipping Tracker V2.

Offline, standard-library-only command-line prototype.
Designed for test data on a personal computer. Do not use real company data
or transfer it to a managed device without approval.
"""
from __future__ import annotations

import csv
import json
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

APP_VERSION = 2
APP_DIR = Path(__file__).resolve().parent
DATA_DIR = APP_DIR / "outbound_tracker_data"
RZRR_DIR = DATA_DIR / "rzrr"
EXPORT_DIR = DATA_DIR / "exports"

POSITIONS = [f"{side}{row:02d}" for row in range(1, 13) for side in ("L", "R")]
TYPES = {
    "box": {"label": "Plastic pallet box", "short": "BOX", "capacity": 2},
    "sleeve": {"label": "Pallet sleeve", "short": "SLV", "capacity": 2},
    "wood": {"label": "Wood pallet", "short": "WOOD", "capacity": 1},
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
        if raw.get("version") != APP_VERSION:
            raise ValueError("Unsupported save-file version")
        bins = [BinRecord(**item) for item in raw.pop("bins", [])]
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
            if item.weight_lb <= 0:
                raise ValueError("Invalid weight")
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
        counts = {key: 0 for key in TYPES}
        for b in self.bins:
            counts[b.container_type] += 1
        return counts["wood"] + (counts["box"] + 1) // 2 + (counts["sleeve"] + 1) // 2

    def total_weight(self) -> int:
        return sum(b.weight_lb for b in self.bins)


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

    default_material = previous.material if previous else ""
    if default_material and ask_yes_no(f"Reuse material: {default_material}?", default=True):
        material = default_material
    else:
        material = input("Material/contents (optional descriptive field): ").strip()[:100]

    aisle = get_aisle()
    item = BinRecord(bin_name, seal, weight, ctype, material, aisle)
    r.bins.append(item)
    if r.floor_positions_required() > 24:
        r.bins.pop()
        print("Cannot add: this RZRR would exceed 24 trailer floor positions.")
        return None
    r.save()
    print("Saved.")
    return item


def rapid_entry(r: RZRRRecord) -> None:
    previous: Optional[BinRecord] = r.bins[-1] if r.bins else None
    while True:
        item = add_bin(r, previous)
        if item is None:
            break
        previous = item


def show_summary(r: RZRRRecord) -> None:
    counts = {k: 0 for k in TYPES}
    for b in r.bins:
        counts[b.container_type] += 1
    print(f"\n{r.rzrr} — {r.state.replace('_', ' ').title()}")
    print(f"Bins: {len(r.bins)} | Weight: {r.total_weight():,} lb | Floor positions: {r.floor_positions_required()}/24")
    print(f"Boxes: {counts['box']} | Sleeves: {counts['sleeve']} | Wood pallets: {counts['wood']}")
    print(f"Dock door: {r.dock_door if r.dock_door else 'Unassigned'}")
    aisle_parts = []
    for aisle in range(1, 5):
        count = sum(1 for b in r.bins if b.aisle == aisle and b.status == "staged")
        if count:
            aisle_parts.append(f"Aisle {aisle}: {count}")
    print("Current shift staging: " + (", ".join(aisle_parts) if aisle_parts else "No aisle assignments"))


def list_bins(r: RZRRRecord) -> None:
    show_summary(r)
    print("\n#   BIN NAME                       SEAL                 WT    TYPE   LOCATION")
    print("-" * 90)
    for i, b in enumerate(r.bins, 1):
        location = (
            f"Truck {b.truck_position}/{b.stack_level}" if b.truck_position else
            f"Dock #{b.dock_order}" if b.status == "dock" else
            f"Aisle {b.aisle}" if b.aisle else "Unassigned"
        )
        print(f"{i:<3} {b.bin_name[:30]:<30} {b.seal[:20]:<20} {b.weight_lb:>5}  {TYPES[b.container_type]['short']:<5}  {location}")
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
    seal = clean_id(input(f"Seal [{b.seal}]: "))
    if seal and any(clean_id(x.seal) == seal and x is not b for x in r.bins):
        print("Seal already assigned; edit cancelled.")
        return
    raw_weight = input(f"Weight [{b.weight_lb}]: ").strip()
    if raw_weight:
        try:
            w = int(raw_weight)
            if w <= 0:
                raise ValueError
            b.weight_lb = w
        except ValueError:
            print("Invalid weight; edit cancelled.")
            return
    if seal:
        b.seal = seal
    material = input(f"Material [{b.material}]: ").strip()
    if material:
        b.material = material[:100]
    if ask_yes_no("Change container type?"):
        b.container_type = choose("Container type", [(k, v["label"]) for k, v in TYPES.items()]) or b.container_type
    if ask_yes_no("Change aisle?"):
        b.aisle = get_aisle()
    if r.floor_positions_required() > 24:
        print("Edit would exceed trailer capacity. Re-open and correct the record.")
        return
    b.updated_at = now_iso()
    r.save()
    print("Updated.")


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


def next_slot(r: RZRRRecord, ctype: str) -> Optional[tuple[str, int]]:
    cap = TYPES[ctype]["capacity"]
    for pos in POSITIONS:
        items = r.occupied(pos)
        if not items:
            return pos, 1
        if items[0].container_type == ctype and len(items) < cap:
            used = {b.stack_level for b in items}
            for level in range(1, cap + 1):
                if level not in used:
                    return pos, level
    return None


def auto_layout(r: RZRRRecord) -> None:
    if r.locked:
        print("This RZRR is locked.")
        return
    if r.floor_positions_required() > 24:
        print("This RZRR does not fit on one trailer.")
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
    print("Trailer layout created from dock order.")


def show_trailer(r: RZRRRecord) -> None:
    print(f"\nTRAILER — {r.rzrr} (FRONT AT TOP)\n")
    for row in range(1, 13):
        cells = []
        for side in ("L", "R"):
            pos = f"{side}{row:02d}"
            items = r.occupied(pos)
            if not items:
                text = "EMPTY"
            else:
                text = "/".join(f"{TYPES[b.container_type]['short']}:{b.bin_name[:10]}" for b in items)
            cells.append(f"{pos} {text:<30}")
        print(" | ".join(cells))
    print(f"\nFloor positions: {r.floor_positions_required()}/24 | Total weight: {r.total_weight():,} lb")
    pause()


def mark_security_approved(r: RZRRRecord) -> None:
    if r.locked:
        print("Already locked.")
        return
    if not r.bins:
        print("No bins entered.")
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
        print("\n1. Rapid bin entry")
        print("2. View bins")
        print("3. Edit one bin")
        print("4. Assign all staged bins to an aisle")
        print("5. Clear current-shift aisle assignments")
        print("6. Assign/change dock door")
        print("7. Build dock/Security order")
        print("8. Show Issues/Mobility text")
        print("9. Export text and CSV")
        print("10. Auto-build trailer layout")
        print("11. View trailer")
        print("12. Mark Security Approved (lock)")
        print("0. Save and return")
        raw = input("> ").strip()
        if raw == "1": rapid_entry(r)
        elif raw == "2": list_bins(r)
        elif raw == "3": edit_one_bin(r)
        elif raw == "4": assign_rzrr_aisle(r)
        elif raw == "5": reset_aisles(r)
        elif raw == "6":
            if r.locked: print("This RZRR is locked.")
            else:
                r.dock_door = get_dock(); r.save()
        elif raw == "7": build_dock_order(r)
        elif raw == "8": show_issues_output(r)
        elif raw == "9": export_files(r)
        elif raw == "10": auto_layout(r)
        elif raw == "11": show_trailer(r)
        elif raw == "12": mark_security_approved(r)
        elif raw == "0": r.save(); return
        else: print("Choose a valid option.")


def main() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    while True:
        print("\nOUTBOUND SHIPPING TRACKER V2")
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
