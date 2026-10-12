import re
from decimal import Decimal


def parse_number(raw):
    value = raw.strip().replace("\u00a0", " ")
    unit = "rupiah" if re.match(r"(?i)^rp\.?\s*", value) else ("percent" if value.endswith("%") else "number")
    value = re.sub(r"(?i)^rp\.?\s*", "", value).rstrip("%").strip()
    if re.fullmatch(r"[+-]?\d{1,3}(\.\d{3})+(,\d+)?", value):
        value = value.replace(".", "")
    elif not re.fullmatch(r"[+-]?\d+(,\d+)?", value):
        raise ValueError(f"Nilai ambigu atau bukan angka Indonesia: {raw[:80]}")
    return Decimal(value.replace(",", ".")), unit


def calculate(table, column, operation):
    rows = table["rows"]
    if not rows or column >= len(rows[0]):
        raise ValueError("Kolom tidak tersedia.")
    raw = [row[column].strip() for row in rows[1:] if column < len(row) and row[column].strip() not in ("", "-")]
    if operation == "count":
        return {"result": str(len(raw)), "unit": "cells", "count": len(raw), "values": raw}
    numbers = [parse_number(value) for value in raw]
    if not numbers:
        raise ValueError("Tidak ditemukan angka pada kolom ini.")
    if len({unit for _, unit in numbers}) != 1:
        raise ValueError("Satuan pada kolom bercampur. Koreksi tabel sebelum menghitung.")
    values = [value for value, _ in numbers]
    unit = numbers[0][1]
    if unit == "number":
        header = rows[0][column].lower()
        if "rupiah" in header or re.search(r"\brp\b", header):
            unit = "rupiah"
        elif "%" in header:
            unit = "percent"
    operations = {"sum": lambda: sum(values), "average": lambda: sum(values) / len(values),
                  "min": lambda: min(values), "max": lambda: max(values)}
    return {"result": str(operations[operation]()), "unit": unit,
            "count": len(values), "values": raw}


def display_number(result):
    integer, _, fraction = result.partition(".")
    formatted = format(int(integer), ",").replace(",", ".")
    return formatted + ("," + fraction if fraction else "")
