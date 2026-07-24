#!/usr/bin/env python3
"""
OrgIQ fixture data generator (PRD §6.3.4).

CSV banata hai controlled distributions ke saath — fill rates, near-match
duplicates, aur staleness. Phir `sf` CLI se org mein import karna hai.

Usage:
    python3 seed_data.py --volume 2000 --out contacts.csv
"""

import argparse
import csv
import random
from datetime import datetime, timedelta

# ---------------------------------------------------------------- config
# PRD §6.3.4 wali spec. Yahi values badal ke alag-alag org profile bana sakte ho.

CONFIG = {
    "Email":          {"fill": 0.62, "shape": "power_law"},
    "Phone":          {"fill": 0.41, "shape": "uniform"},
    "Title":          {"fill": 0.28, "shape": "uniform"},
    "MailingCity":    {"fill": 0.55, "shape": "recent_only"},
    "Department":     {"fill": 0.19, "shape": "uniform"},
}
DUPLICATE_RATE = 0.07
STALE_RATIO = 0.55          # 12 mahine se purane
STALE_CUTOFF_DAYS = 365

FIRST = ["Aarav","Priya","Rahul","Neha","Vikram","Anjali","Rohan","Sneha",
         "Arjun","Kavya","Karan","Divya","Amit","Pooja","Siddharth","Meera",
         "James","Sarah","Michael","Emily","David","Laura","Chris","Anna"]
LAST  = ["Sharma","Patel","Singh","Gupta","Reddy","Nair","Iyer","Mehta",
         "Kapoor","Joshi","Verma","Rao","Smith","Johnson","Brown","Wilson"]
CITY  = ["Mumbai","Delhi","Bengaluru","Pune","Hyderabad","Chennai",
         "London","New York","Singapore","Dubai"]
TITLE = ["Manager","Senior Analyst","Director","Consultant","VP Operations",
         "Associate","Head of Delivery","Architect"]
DEPT  = ["Sales","Operations","Technology","Finance","Marketing","HR"]


def should_fill(spec, idx, total, rnd):
    """Fill hoga ya nahi — distribution shape ke hisaab se.
    Uniform random nahi, kyunki real orgs aise nahi dikhte."""
    base = spec["fill"]
    shape = spec["shape"]
    pos = idx / max(total - 1, 1)          # 0 = purana, 1 = naya

    if shape == "uniform":
        p = base
    elif shape == "power_law":
        # naye records zyada bhare hue, purane khaali
        p = base * (0.3 + 1.4 * pos ** 1.5)
    elif shape == "recent_only":
        p = base * (0.1 + 1.8 * pos ** 3)
    else:
        p = base
    return rnd.random() < min(p, 0.99)


def mutate(value, kind, rnd):
    """Near-match duplicate banata hai — exact copy nahi.
    Exact duplicates trivially detect ho jate hain, unse rule test nahi hota."""
    if not value:
        return value
    if kind == "whitespace":
        return value + " "
    if kind == "case":
        return value.upper() if rnd.random() < 0.5 else value.lower()
    if kind == "abbreviation":
        parts = value.split()
        return f"{parts[0][0]}. {' '.join(parts[1:])}" if len(parts) > 1 else value
    if kind == "transposition":
        if len(value) > 4:
            i = rnd.randrange(1, len(value) - 2)
            return value[:i] + value[i+1] + value[i] + value[i+2:]
    return value


def generate(volume, seed):
    rnd = random.Random(seed)
    today = datetime.now()
    rows = []

    for i in range(volume):
        first = rnd.choice(FIRST)
        last = rnd.choice(LAST)

        # staleness — declared ratio ke hisaab se purani date
        if rnd.random() < STALE_RATIO:
            age = rnd.randint(STALE_CUTOFF_DAYS, STALE_CUTOFF_DAYS * 4)
        else:
            age = rnd.randint(0, STALE_CUTOFF_DAYS - 1)
        created = today - timedelta(days=age)

        row = {
            "FirstName": first,
            "LastName": last,
            "Email": "", "Phone": "", "Title": "",
            "MailingCity": "", "Department": "",
            "CreatedDate": created.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

        if should_fill(CONFIG["Email"], i, volume, rnd):
            row["Email"] = f"{first.lower()}.{last.lower()}{rnd.randint(1,999)}@example.com"
        if should_fill(CONFIG["Phone"], i, volume, rnd):
            row["Phone"] = f"+91 9{rnd.randint(100000000, 999999999)}"
        if should_fill(CONFIG["Title"], i, volume, rnd):
            row["Title"] = rnd.choice(TITLE)
        if should_fill(CONFIG["MailingCity"], i, volume, rnd):
            row["MailingCity"] = rnd.choice(CITY)
        if should_fill(CONFIG["Department"], i, volume, rnd):
            row["Department"] = rnd.choice(DEPT)

        rows.append(row)

    # duplicates — mutate karke daalo, copy karke nahi
    n_dupes = int(volume * DUPLICATE_RATE)
    kinds = ["whitespace", "case", "abbreviation", "transposition"]
    for _ in range(n_dupes):
        src = dict(rnd.choice(rows))
        kind = rnd.choice(kinds)
        src["FirstName"] = mutate(src["FirstName"], kind, rnd)
        src["LastName"] = mutate(src["LastName"], kind, rnd)
        if src["Email"] and kind in ("whitespace", "case"):
            src["Email"] = mutate(src["Email"], kind, rnd)
        rows.append(src)

    rnd.shuffle(rows)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42, help="same seed = same data")
    ap.add_argument("--out", default="contacts.csv")
    a = ap.parse_args()

    rows = generate(a.volume, a.seed)
    cols = ["FirstName","LastName","Email","Phone","Title",
            "MailingCity","Department","CreatedDate"]

    with open(a.out, "w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)

    # expected values — yeh ground truth hai, D2 rules isi ke against grade honge
    total = len(rows)
    print(f"{a.out}: {total} rows\n")
    print("Expected (ground truth for D2 rules):")
    for col in ["Email","Phone","Title","MailingCity","Department"]:
        filled = sum(1 for r in rows if r[col])
        print(f"  {col:14} fill {filled/total*100:5.1f}%")
    stale = sum(1 for r in rows
                if (datetime.now() - datetime.strptime(r["CreatedDate"], "%Y-%m-%dT%H:%M:%SZ")).days
                >= STALE_CUTOFF_DAYS)
    print(f"  {'stale >12mo':14} {stale/total*100:5.1f}%")
    print(f"  {'duplicate rate':14} {DUPLICATE_RATE*100:5.1f}% (injected)")


if __name__ == "__main__":
    main()
