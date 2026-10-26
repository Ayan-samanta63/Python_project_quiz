"""
QuizMaster Pro — Auto-Generated Edition
=======================================
A desktop quiz platform (Python + Tkinter + SQLite) whose questions are
generated automatically, so it covers a very wide range of topics.

Where the questions come from
-----------------------------
1. Open Trivia DB (free, no key)  - ~24 topic areas x 3 difficulties, synced in
   the background and cached locally, so the app also works offline later.
2. Built-in generators (offline)  - maths, percentages, number systems, Python
   output, unit conversion, calendar, sequences, data structures, geometry.
   Answers are *computed*, so they are always correct and never run out.
3. Claude (optional)              - set the ANTHROPIC_API_KEY environment
   variable to type ANY topic and get fresh questions, or let the app
   discover new topics on its own.

Run:
    python quizmaster_pro.py

No third-party packages are required (standard library only).
"""

from __future__ import annotations

import calendar
import hashlib
import json
import os
import queue
import random
import sqlite3
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta
from pathlib import Path
from tkinter import messagebox, ttk
from typing import Any, Callable

APP_TITLE = "QuizMaster Pro"
APP_VERSION = "3.0"

DIFFICULTIES = ["Easy", "Medium", "Hard"]
ALL_LEVELS = "All Levels"
MIXED = "Mixed - Explore All Topics"

DEFAULT_QUESTION_SECONDS = 15
DEFAULT_QUESTION_COUNT = 10
BUCKET_TARGET = 50            # questions cached per (topic, difficulty)
USER_AGENT = f"QuizMasterPro/{APP_VERSION}"

COLORS = {
    "app_bg": "#F4F7FB", "surface": "#FFFFFF", "surface_alt": "#F8FAFC",
    "border": "#E2E8F0", "text": "#172B4D", "muted": "#64748B",
    "primary": "#2563EB", "primary_hover": "#1D4ED8", "primary_soft": "#EAF1FF",
    "success": "#15803D", "success_soft": "#DCFCE7",
    "danger": "#B91C1C", "danger_soft": "#FEE2E2",
    "warning": "#B45309", "warning_soft": "#FEF3C7",
}


def resolve_db_path() -> Path:
    """Use the script folder; fall back to the home folder if it is read-only."""
    primary = Path(__file__).resolve().with_name("quiz_history.db")
    try:
        probe = primary.parent / ".quizmaster_write_test"
        probe.write_text("ok")
        probe.unlink()
        return primary
    except OSError:
        fallback = Path.home() / ".quizmaster_pro"
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback / "quiz_history.db"


# ======================================================================
# Question model helpers
# ======================================================================

def build_question(
    category: str, difficulty: str, question: str, options: list[str],
    answer: str, explanation: str = "", source: str = "",
) -> dict[str, Any] | None:
    """Validate and normalise a question. Returns None when it is unusable."""
    clean = lambda s: " ".join(str(s).split())  # noqa: E731
    question, answer = clean(question), clean(answer)
    options = list(dict.fromkeys(clean(o) for o in options))
    if not question or len(question) > 400:
        return None
    if not 2 <= len(options) <= 6 or answer not in options:
        return None
    if any(not o or len(o) > 200 for o in options):
        return None
    difficulty = str(difficulty).strip().capitalize()
    if difficulty not in DIFFICULTIES:
        difficulty = "Medium"
    return {
        "category": clean(category)[:60] or "General",
        "difficulty": difficulty,
        "question": question,
        "options": options,
        "answer": answer,
        "explanation": clean(explanation) or f"The correct answer is {answer}.",
        "source": source,
        "id": None,
    }


def question_hash(question: str) -> str:
    return hashlib.sha1(" ".join(question.lower().split()).encode("utf-8")).hexdigest()


# ======================================================================
# Built-in seed questions (always available offline)
# ======================================================================

SEED_QUESTIONS = [
    ("Computer Basics", "Easy", "What does CPU stand for?",
     ["Central Processing Unit", "Computer Personal Unit", "Central Program Utility", "Control Processing User"],
     "Central Processing Unit", "The CPU executes instructions and coordinates many operations in a computer."),
    ("Computer Basics", "Easy", "What does RAM stand for?",
     ["Read Access Memory", "Random Access Memory", "Run Active Memory", "Remote Application Memory"],
     "Random Access Memory", "RAM temporarily stores data and programs currently being used."),
    ("Computer Basics", "Easy", "Which component supplies power to a desktop computer?",
     ["GPU", "SSD", "PSU", "CPU cooler"], "PSU",
     "PSU means Power Supply Unit and provides the required power to computer components."),
    ("Computer Basics", "Easy", "What does GPU stand for?",
     ["General Processing Utility", "Graphics Processing Unit", "Graphical Program Unit", "Global Processor Unit"],
     "Graphics Processing Unit", "A GPU specializes in graphics processing and can accelerate parallel workloads."),
    ("Computer Basics", "Medium", "Which memory is typically volatile?",
     ["SSD", "ROM", "RAM", "Blu-ray disc"], "RAM",
     "Volatile memory loses its contents when power is removed; standard RAM is volatile."),
    ("Computer Basics", "Medium", "Which unit is commonly used to measure CPU clock frequency?",
     ["Pixels", "Hertz", "Litres", "Volts per metre"], "Hertz",
     "Clock frequency is measured in hertz, often expressed as gigahertz (GHz)."),
    ("Computer Basics", "Hard", "Which cache level is usually closest to an individual CPU core?",
     ["L1 cache", "L3 cache", "Hard disk cache only", "Cloud cache"], "L1 cache",
     "L1 cache is typically the smallest and fastest CPU cache, located closest to a core."),
    ("Python", "Easy", "Which keyword defines a function in Python?",
     ["func", "define", "def", "function"], "def", "Python uses the def keyword to define a function."),
    ("Python", "Easy", "Which data type stores True or False?",
     ["str", "bool", "list", "dict"], "bool", "The bool type represents the Boolean values True and False."),
    ("Python", "Medium", "Which collection type stores key-value pairs?",
     ["tuple", "set", "dictionary", "string"], "dictionary", "A Python dictionary maps keys to values."),
    ("Python", "Hard", "What does a Python list comprehension primarily provide?",
     ["A concise way to create lists", "A way to define a class only", "Automatic database backup", "A replacement for all loops"],
     "A concise way to create lists",
     "List comprehensions create lists compactly using iteration and optional filtering."),
    ("Networking", "Easy", "What does LAN stand for?",
     ["Large Access Network", "Local Area Network", "Linked Application Node", "Long Area Network"],
     "Local Area Network", "A LAN connects devices within a limited area, such as a home, office, or campus."),
    ("Networking", "Medium", "Which protocol is commonly used to load secure websites?",
     ["HTTPS", "FTP", "SMTP", "DHCP"], "HTTPS",
     "HTTPS uses TLS to protect communication between a browser and a website."),
    ("Databases", "Easy", "What does SQL stand for?",
     ["Structured Query Language", "Simple Question List", "System Quick Link", "Sequential Queue Logic"],
     "Structured Query Language", "SQL is widely used to query and manage relational databases."),
    ("Databases", "Medium", "Which SQL command retrieves data from a table?",
     ["SELECT", "UPDATE", "DROP", "INSERT"], "SELECT", "SELECT reads data from one or more database tables."),
]


# ======================================================================
# Procedural generators (offline, answers are computed)
# ======================================================================

WEEKDAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
MONTHS = ["January", "February", "March", "April", "May", "June", "July",
          "August", "September", "October", "November", "December"]
_EVAL_ENV = {
    "__builtins__": {}, "len": len, "sum": sum, "max": max, "min": min,
    "sorted": sorted, "range": range, "list": list, "set": set, "abs": abs,
}


def _shuffled(options: list[str]) -> list[str]:
    options = list(options)
    random.shuffle(options)
    return options


def int_options(answer: int) -> list[str] | None:
    pool = [answer + d for d in (-10, -5, -3, -2, -1, 1, 2, 3, 5, 10)]
    if answer >= 0:
        non_negative = [p for p in pool if p >= 0]
        pool = non_negative if len(non_negative) >= 3 else pool
    wrong = random.sample(pool, 3)
    return _shuffled([str(answer)] + [str(w) for w in wrong])


def spread_options(answer: int, candidates: set[int]) -> list[str] | None:
    candidates = {c for c in candidates if c != answer and c > 0}
    if len(candidates) < 3:
        return None
    return _shuffled([str(answer)] + [str(c) for c in random.sample(sorted(candidates), 3)])


def value_options(answer: Any) -> tuple[str, list[str]] | None:
    """Return (display_answer, shuffled options) for ints, strings and lists."""
    if isinstance(answer, int):
        opts = int_options(answer)
        return (str(answer), opts) if opts else None
    if isinstance(answer, str):
        cands = [answer[::-1], answer[1:], answer[:-1], answer.swapcase(),
                 answer.upper(), answer.lower(), answer + answer[:1]]
    elif isinstance(answer, list):
        cands = [answer[::-1], answer[1:], answer[:-1], sorted(answer),
                 sorted(answer, reverse=True), answer + answer[:1]]
        cands.append([x + 1 for x in answer if isinstance(x, int)])
    else:
        return None
    unique: dict[str, Any] = {}
    for c in cands:
        if c != answer:
            unique.setdefault(repr(c), c)
    if len(unique) < 3:
        return None
    wrong = random.sample(sorted(unique), 3)
    shown = repr(answer)
    return shown, _shuffled([shown] + wrong)


def gen_arithmetic(diff: str) -> dict | None:
    if diff == "Easy":
        a, b, op = random.randint(10, 99), random.randint(10, 99), random.choice("+-")
        expr, ans = f"{a} {op} {b}", (a + b if op == "+" else a - b)
    elif diff == "Medium":
        a, b = random.randint(11, 35), random.randint(6, 19)
        expr, ans = f"{a} x {b}", a * b
    else:
        a, b, c = random.randint(3, 15), random.randint(3, 15), random.randint(2, 9)
        expr, ans = f"({a} + {b}) x {c} - {a}", (a + b) * c - a
    opts = int_options(ans)
    return build_question("Math: Arithmetic", diff, f"What is {expr}?", opts, str(ans),
                          f"{expr} = {ans}.", "Generated") if opts else None


def gen_percent(diff: str) -> dict | None:
    pct = random.choice([5, 10, 15, 20, 25, 40, 50, 75])
    base = random.randint(2, 50) * 20
    if diff == "Easy":
        ans, q = pct * base // 100, f"What is {pct}% of {base}?"
        exp = f"{pct}% of {base} = {base} x {pct}/100 = {ans}."
    elif diff == "Medium":
        ans = base * (100 + pct) // 100
        q = f"A price of {base} increases by {pct}%. What is the new price?"
        exp = f"{base} x {100 + pct}/100 = {ans}."
    else:
        part = pct * base // 100
        ans, q = pct, f"{part} is what percent of {base}?"
        exp = f"{part}/{base} x 100 = {pct}%."
    opts = int_options(ans)
    return build_question("Math: Percentages", diff, q, opts, str(ans), exp, "Generated") if opts else None


def gen_number_systems(diff: str) -> dict | None:
    if diff == "Easy":
        n = random.randint(3, 31)
        ans = bin(n)[2:]
        opts = _shuffled({ans} | {bin(n + d)[2:] for d in (-2, -1, 1, 2, 3)} - {ans})
        opts = _shuffled([ans] + [o for o in opts if o != ans][:3])
        return build_question("Number Systems", diff, f"Convert decimal {n} to binary.", opts, ans,
                              f"{n} in binary is {ans}.", "Generated")
    if diff == "Medium":
        n = random.randint(9, 63)
        b = bin(n)[2:]
        opts = int_options(n)
        return build_question("Number Systems", diff, f"Convert binary {b} to decimal.", opts, str(n),
                              f"{b} (base 2) = {n}.", "Generated") if opts else None
    n = random.randint(32, 255)
    if random.random() < 0.5:
        h = format(n, "X")
        opts = int_options(n)
        return build_question("Number Systems", diff, f"Convert hexadecimal {h} to decimal.", opts,
                              str(n), f"0x{h} = {n}.", "Generated") if opts else None
    ans = format(n, "X")
    wrong = {format(max(1, n + d), "X") for d in (-16, -1, 1, 16, 2)} - {ans}
    if len(wrong) < 3:
        return None
    opts = _shuffled([ans] + random.sample(sorted(wrong), 3))
    return build_question("Number Systems", diff, f"Convert decimal {n} to hexadecimal.", opts, ans,
                          f"{n} = 0x{ans}.", "Generated")


def gen_python_output(diff: str) -> dict | None:
    lst = [random.randint(1, 20) for _ in range(random.randint(3, 6))]
    word = random.choice(["python", "quiz", "network", "database", "compiler", "kernel", "script", "binary"])
    a, b, n = random.randint(10, 60), random.randint(3, 9), random.randint(4, 9)
    i, j = random.randint(0, 1), random.randint(2, len(lst))
    templates = {
        "Easy": [f"len({lst})", f"sum({lst})", f"max({lst})", f"min({lst})",
                 f"{word!r}.upper()", f"len({word!r})"],
        "Medium": [f"{lst}[{i}:{j}]", f"sorted({lst})", f"{word!r}[::-1]", f"{lst}[-1]",
                   f"{word!r}[{i}]", f"{a} // {b}", f"{a} % {b}", f"2 ** {b}"],
        "Hard": [f"[x * {b} for x in range({n}) if x % 2 == 0]", f"sum(x * x for x in range({n}))",
                 f"list(range({a}, {a + 5 * b}, {b}))", f"sorted({lst}, reverse=True)[:{i + 2}]",
                 f"len(set({lst + lst[:2]}))"],
    }
    expr = random.choice(templates[diff])
    try:
        result = eval(expr, dict(_EVAL_ENV))  # expression built only from our own literals
    except Exception:
        return None
    packed = value_options(result)
    if not packed:
        return None
    shown, opts = packed
    return build_question("Python Output Prediction", diff,
                          f"What does {expr} evaluate to in Python?", opts, shown,
                          f"{expr} evaluates to {shown}.", "Generated")


def gen_units(diff: str) -> dict | None:
    if diff == "Hard" and random.random() < 0.5:
        c = random.choice(range(-20, 105, 5))
        f = c * 9 // 5 + 32
        wrong = {c * 9 // 5, c * 2 + 30, c + 32, f + 10, f - 9} - {f}
        if len(wrong) < 3:
            return None
        opts = _shuffled([str(f)] + [str(w) for w in random.sample(sorted(wrong), 3)])
        return build_question("Unit Conversion", diff, f"Convert {c} degrees Celsius to Fahrenheit.", opts,
                              str(f), f"F = C x 9/5 + 32 = {f}.", "Generated")
    pool = {
        "Easy": [("km", "m", 1000), ("kg", "g", 1000), ("hours", "minutes", 60), ("L", "mL", 1000)],
        "Medium": [("minutes", "seconds", 60), ("days", "hours", 24), ("m", "cm", 100)],
        "Hard": [("hours", "seconds", 3600), ("days", "minutes", 1440), ("km", "cm", 100000)],
    }[diff]
    src, dst, factor = random.choice(pool)
    n = random.randint(2, 25)
    ans = n * factor
    cands = {ans * 10, ans + factor, abs(ans - factor), n + factor}
    if ans % 10 == 0:
        cands.add(ans // 10)
    opts = spread_options(ans, cands)
    return build_question("Unit Conversion", diff, f"How many {dst} are in {n} {src}?", opts, str(ans),
                          f"{n} x {factor} = {ans} {dst}.", "Generated") if opts else None


def _fmt_date(d: date) -> str:
    return f"{d.day} {MONTHS[d.month - 1]} {d.year}"


def gen_calendar(diff: str) -> dict | None:
    if diff == "Easy":
        d = date(random.randint(1995, 2035), random.randint(1, 12), random.randint(1, 28))
        ans = WEEKDAYS[d.weekday()]
        opts = _shuffled([ans] + random.sample([w for w in WEEKDAYS if w != ans], 3))
        return build_question("Calendar & Dates", diff, f"Which day of the week is {_fmt_date(d)}?",
                              opts, ans, f"{_fmt_date(d)} falls on a {ans}.", "Generated")
    if diff == "Medium":
        y = random.randint(1900, 2100)
        ans = "Yes" if calendar.isleap(y) else "No"
        exp = f"{y} is {'' if ans == 'Yes' else 'not '}a leap year."
        return build_question("Calendar & Dates", diff, f"Is {y} a leap year?", ["Yes", "No"], ans, exp, "Generated")
    d1 = date(random.randint(2000, 2030), random.randint(1, 12), random.randint(1, 28))
    gap = random.randint(10, 300)
    d2 = d1 + timedelta(days=gap)
    opts = int_options(gap)
    return build_question("Calendar & Dates", diff,
                          f"How many days are there from {_fmt_date(d1)} to {_fmt_date(d2)}?",
                          opts, str(gap), f"The gap is {gap} days.", "Generated") if opts else None


def gen_sequence(diff: str) -> dict | None:
    if diff == "Easy":
        start, step = random.randint(1, 20), random.randint(2, 9)
        terms = [start + step * k for k in range(5)]
        ans, exp = start + step * 5, f"Each term adds {step}."
    elif diff == "Medium":
        start, ratio = random.randint(2, 5), random.randint(2, 3)
        terms = [start * ratio ** k for k in range(5)]
        ans, exp = start * ratio ** 5, f"Each term is multiplied by {ratio}."
    else:
        start, d0 = random.randint(1, 10), random.randint(1, 3)
        terms = [start]
        for k in range(5):
            terms.append(terms[-1] + d0 + k)
        ans, exp = terms.pop() + d0 + 5, "The gap between terms grows by 1 each time."
        terms = terms[:5]
    opts = int_options(ans)
    seq = ", ".join(str(t) for t in terms)
    return build_question("Logic: Number Sequences", diff, f"What comes next in the sequence: {seq}, ?",
                          opts, str(ans), f"{exp} The next term is {ans}.", "Generated") if opts else None


def gen_stack_queue(diff: str) -> dict | None:
    letters = random.sample("ABCDEFGH", 6)
    if diff == "Easy":
        items = letters[:4]
        k = random.randint(1, 2)
        if random.random() < 0.5:
            ans = items[-1 - k]
            q = f"Items {', '.join(items)} are pushed onto a stack in that order, then {k} pop(s) occur. What is on top?"
            exp = f"A stack is LIFO, so the top after {k} pop(s) is {ans}."
        else:
            ans = items[k]
            q = f"Items {', '.join(items)} are enqueued in that order, then {k} dequeue(s) occur. What is at the front?"
            exp = f"A queue is FIFO, so the front after {k} dequeue(s) is {ans}."
    else:
        stack: list[str] = []
        ops: list[str] = []
        pool = iter(letters)
        steps = 6 if diff == "Medium" else 9
        for _ in range(steps):
            if stack and (random.random() < 0.4 or len(ops) >= steps - 1 and len(stack) > 1):
                stack.pop()
                ops.append("pop")
            else:
                item = next(pool, None)
                if item is None:
                    break
                stack.append(item)
                ops.append(f"push {item}")
        if not stack:
            return None
        ans = stack[-1]
        q = f"Starting with an empty stack, apply: {', '.join(ops)}. What is on top now?"
        exp = f"Following the operations leaves {ans} on top."
    opts = _shuffled([ans] + random.sample([x for x in "ABCDEFGH" if x != ans], 3))
    return build_question("Data Structures Simulation", diff, q, opts, ans, exp, "Generated")


def gen_geometry(diff: str) -> dict | None:
    if diff == "Easy":
        a, b = random.randint(3, 20), random.randint(3, 20)
        if random.random() < 0.5:
            ans, q, exp = a * b, f"What is the area of a rectangle {a} by {b}?", f"{a} x {b} = {a * b}."
        else:
            ans, q = 2 * (a + b), f"What is the perimeter of a rectangle {a} by {b}?"
            exp = f"2 x ({a} + {b}) = {ans}."
    elif diff == "Medium":
        base, h = random.randint(2, 15) * 2, random.randint(3, 20)
        ans, q = base * h // 2, f"What is the area of a triangle with base {base} and height {h}?"
        exp = f"{base} x {h} / 2 = {ans}."
    else:
        a, b, c = random.choice([(3, 4, 5), (5, 12, 13), (8, 15, 17), (7, 24, 25), (20, 21, 29)])
        k = random.randint(1, 3)
        a, b, c = a * k, b * k, c * k
        ans, q = c, f"A right triangle has legs {a} and {b}. What is the hypotenuse?"
        exp = f"sqrt({a}^2 + {b}^2) = {c}."
    opts = int_options(ans)
    return build_question("Geometry", diff, q, opts, str(ans), exp, "Generated") if opts else None


PROCEDURAL: dict[str, Callable[[str], dict | None]] = {
    "Math: Arithmetic": gen_arithmetic,
    "Math: Percentages": gen_percent,
    "Number Systems": gen_number_systems,
    "Python Output Prediction": gen_python_output,
    "Unit Conversion": gen_units,
    "Calendar & Dates": gen_calendar,
    "Logic: Number Sequences": gen_sequence,
    "Data Structures Simulation": gen_stack_queue,
    "Geometry": gen_geometry,
}


def generate_procedural(category: str, difficulty: str | None, count: int) -> list[dict]:
    out: list[dict] = []
    seen: set[str] = set()
    attempts = 0
    while len(out) < count and attempts < count * 25:
        attempts += 1
        diff = difficulty if difficulty in DIFFICULTIES else random.choice(DIFFICULTIES)
        try:
            q = PROCEDURAL[category](diff)
        except (ValueError, IndexError, KeyError):
            q = None
        if q and q["question"] not in seen:
            seen.add(q["question"])
            out.append(q)
    return out


# ======================================================================
# Online providers
# ======================================================================

def http_json(url: str, data: bytes | None = None, headers: dict | None = None, timeout: int = 15) -> Any:
    req = urllib.request.Request(url, data=data, headers={"User-Agent": USER_AGENT, **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


FALLBACK_TDB_CATEGORIES = {
    "General Knowledge": 9, "Entertainment: Books": 10, "Entertainment: Film": 11,
    "Entertainment: Music": 12, "Entertainment: Musicals & Theatres": 13,
    "Entertainment: Television": 14, "Entertainment: Video Games": 15,
    "Entertainment: Board Games": 16, "Science & Nature": 17, "Science: Computers": 18,
    "Science: Mathematics": 19, "Mythology": 20, "Sports": 21, "Geography": 22,
    "History": 23, "Politics": 24, "Art": 25, "Celebrities": 26, "Animals": 27,
    "Vehicles": 28, "Entertainment: Comics": 29, "Science: Gadgets": 30,
    "Entertainment: Japanese Anime & Manga": 31, "Entertainment: Cartoon & Animations": 32,
}


class OpenTriviaProvider:
    """Open Trivia DB client. Free, no key; allows one request per ~5 seconds."""

    BASE = "https://opentdb.com"

    def __init__(self, stop: threading.Event | None = None) -> None:
        self.token: str | None = None
        self.last_call = 0.0
        self.stop = stop or threading.Event()

    def _get(self, path: str, **params: Any) -> dict:
        wait = 5.3 - (time.monotonic() - self.last_call)
        if wait > 0:
            self.stop.wait(wait)
        self.last_call = time.monotonic()
        return http_json(f"{self.BASE}{path}?{urllib.parse.urlencode(params)}")

    def fetch_categories(self) -> dict[str, int]:
        try:
            data = self._get("/api_category.php")
            cats = {c["name"]: int(c["id"]) for c in data.get("trivia_categories", [])}
            return cats or dict(FALLBACK_TDB_CATEGORIES)
        except (KeyError, TypeError, ValueError):
            return dict(FALLBACK_TDB_CATEGORIES)

    def _ensure_token(self) -> None:
        if self.token is None:
            try:
                self.token = self._get("/api_token.php", command="request").get("token")
            except (urllib.error.URLError, ValueError):
                self.token = None

    def fetch_questions(self, category_id: int, category_name: str, difficulty: str, amount: int = 50) -> list[dict]:
        self._ensure_token()
        for _ in range(4):
            if self.stop.is_set():
                return []
            params: dict[str, Any] = {
                "amount": amount, "category": category_id, "difficulty": difficulty.lower(),
                "type": "multiple", "encode": "url3986",
            }
            if self.token:
                params["token"] = self.token
            data = self._get("/api.php", **params)
            code = data.get("response_code", 0)
            if code == 0:
                return self._parse(data.get("results", []), category_name)
            if code == 5:                       # rate limited
                self.stop.wait(6)
            elif code == 1 and amount > 5:      # fewer questions exist than requested
                amount = max(5, amount // 2)
            elif code == 3:                     # token expired
                self.token = None
                self._ensure_token()
            elif code == 4:                     # token exhausted: reset it for next time
                if self.token:
                    self._get("/api_token.php", command="reset", token=self.token)
                return []
            else:
                return []
        return []

    @staticmethod
    def _parse(items: list[dict], category_name: str) -> list[dict]:
        unq = urllib.parse.unquote
        out = []
        for item in items:
            try:
                correct = unq(item["correct_answer"])
                options = [unq(x) for x in item["incorrect_answers"]] + [correct]
                q = build_question(category_name, unq(item["difficulty"]), unq(item["question"]), options,
                                   correct, f"The correct answer is {correct}.", "Open Trivia DB")
            except (KeyError, TypeError):
                continue
            if q:
                out.append(q)
        return out


class ClaudeProvider:
    """Optional: generate questions on any topic with the Claude API."""

    URL = "https://api.anthropic.com/v1/messages"

    def __init__(self) -> None:
        self.model = os.environ.get("QUIZMASTER_MODEL", "claude-sonnet-5-5")

    @staticmethod
    def available() -> bool:
        return bool(os.environ.get("ANTHROPIC_API_KEY", "").strip())

    def _call(self, prompt: str, max_tokens: int = 4000) -> str:
        body = json.dumps({
            "model": self.model, "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": prompt}],
        }).encode("utf-8")
        data = http_json(self.URL, data=body, timeout=90, headers={
            "content-type": "application/json",
            "x-api-key": os.environ.get("ANTHROPIC_API_KEY", "").strip(),
            "anthropic-version": "2023-06-01",
        })
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")

    @staticmethod
    def _extract_json(text: str) -> Any:
        start, end = text.find("["), text.rfind("]")
        if start == -1 or end <= start:
            raise ValueError("No JSON array in model reply")
        return json.loads(text[start:end + 1])

    def generate(self, topic: str, amount: int = 12) -> list[dict]:
        topic = " ".join(topic.split())[:80]
        prompt = (
            f'Write {amount} multiple-choice quiz questions about "{topic}" for a general learner. '
            "Spread difficulty across Easy, Medium and Hard. Each question has exactly 4 options, one correct "
            "answer, and a one-sentence explanation. Only include facts you are confident are accurate.\n"
            "Reply with ONLY a JSON array (no markdown). Each item: "
            '{"question": "...", "options": ["...","...","...","..."], '
            '"answer": "<must equal one option exactly>", "difficulty": "Easy|Medium|Hard", "explanation": "..."}'
        )
        category = topic[:1].upper() + topic[1:]
        out = []
        for item in self._extract_json(self._call(prompt)):
            try:
                q = build_question(category, item.get("difficulty", "Medium"), item["question"],
                                   item["options"], item["answer"], item.get("explanation", ""), "Claude")
            except (KeyError, TypeError, AttributeError):
                continue
            if q and len(q["options"]) == 4:
                out.append(q)
        return out

    def discover_topics(self, count: int, existing: list[str]) -> list[str]:
        prompt = (
            f"List {count} distinct quiz topics spanning very different fields of knowledge (science, "
            "humanities, technology, arts, health, business, nature, society, etc.). "
            f"Do not repeat any of these existing topics: {', '.join(existing[:80]) or 'none'}.\n"
            "Reply with ONLY a JSON array of short topic names (max 4 words each)."
        )
        topics = self._extract_json(self._call(prompt, 600))
        return [" ".join(str(t).split())[:60] for t in topics if str(t).strip()][:count]


# ======================================================================
# Database
# ======================================================================

class Database:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, timeout=10)
        self.conn.execute("PRAGMA busy_timeout = 5000")
        try:
            self.conn.execute("PRAGMA journal_mode = WAL")
        except sqlite3.Error:
            pass
        self._schema()

    def _schema(self) -> None:
        with self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS quiz_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    player_name TEXT NOT NULL, category TEXT NOT NULL, difficulty TEXT NOT NULL,
                    score INTEGER NOT NULL CHECK(score >= 0), total INTEGER NOT NULL CHECK(total > 0),
                    percentage REAL NOT NULL, duration_seconds INTEGER NOT NULL CHECK(duration_seconds >= 0),
                    completed_at TEXT NOT NULL)""")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS question_bank (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    qhash TEXT NOT NULL UNIQUE, source TEXT NOT NULL,
                    category TEXT NOT NULL, difficulty TEXT NOT NULL,
                    question TEXT NOT NULL, options_json TEXT NOT NULL,
                    answer TEXT NOT NULL, explanation TEXT NOT NULL,
                    times_seen INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL)""")
            self.conn.execute("CREATE INDEX IF NOT EXISTS idx_bank_cat ON question_bank(category, difficulty)")
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS answer_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    category TEXT NOT NULL, difficulty TEXT NOT NULL,
                    is_correct INTEGER NOT NULL, answered_at TEXT NOT NULL)""")

    # ----- question bank -----
    def add_questions(self, questions: list[dict]) -> int:
        added = 0
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with self.conn:
            for q in questions:
                cur = self.conn.execute(
                    """INSERT OR IGNORE INTO question_bank
                       (qhash, source, category, difficulty, question, options_json, answer, explanation, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (question_hash(q["question"]), q.get("source") or "Built-in", q["category"], q["difficulty"],
                     q["question"], json.dumps(q["options"]), q["answer"], q["explanation"], now))
                added += cur.rowcount
        return added

    def seed_builtin(self) -> None:
        self.add_questions([q for q in (build_question(c, d, qu, o, a, e, "Built-in")
                                        for c, d, qu, o, a, e in SEED_QUESTIONS) if q])

    def fetch_questions(self, category: str | None = None, difficulty: str | None = None,
                        limit: int = 10, exclude_ids: set[int] | None = None) -> list[dict]:
        sql = ("SELECT id, category, difficulty, question, options_json, answer, explanation, source "
               "FROM question_bank WHERE 1=1")
        params: list[Any] = []
        if category:
            sql += " AND category = ?"
            params.append(category)
        if difficulty:
            sql += " AND difficulty = ?"
            params.append(difficulty)
        if exclude_ids:
            sql += f" AND id NOT IN ({','.join('?' * len(exclude_ids))})"
            params.extend(exclude_ids)
        sql += " ORDER BY times_seen ASC, RANDOM() LIMIT ?"
        params.append(limit)
        return [{"id": r[0], "category": r[1], "difficulty": r[2], "question": r[3],
                 "options": json.loads(r[4]), "answer": r[5], "explanation": r[6], "source": r[7]}
                for r in self.conn.execute(sql, params)]

    def mark_seen(self, qid: int) -> None:
        with self.conn:
            self.conn.execute("UPDATE question_bank SET times_seen = times_seen + 1 WHERE id = ?", (qid,))

    def categories(self, difficulty: str | None = None) -> list[str]:
        if difficulty:
            rows = self.conn.execute("SELECT DISTINCT category FROM question_bank WHERE difficulty = ?", (difficulty,))
        else:
            rows = self.conn.execute("SELECT DISTINCT category FROM question_bank")
        return sorted(r[0] for r in rows)

    def bucket_count(self, category: str, difficulty: str) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM question_bank WHERE category = ? AND difficulty = ?",
                                 (category, difficulty)).fetchone()[0]

    def total_questions(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM question_bank").fetchone()[0]

    def coverage(self) -> dict[str, dict[str, Any]]:
        cov: dict[str, dict[str, Any]] = {}
        rows = self.conn.execute("SELECT category, source, difficulty, COUNT(*) FROM question_bank "
                                 "GROUP BY category, source, difficulty")
        for cat, src, diff, n in rows:
            entry = cov.setdefault(cat, {"sources": set(), "Easy": 0, "Medium": 0, "Hard": 0})
            entry["sources"].add(src)
            entry[diff] = entry.get(diff, 0) + n
        return cov

    # ----- progress -----
    def log_answer(self, category: str, difficulty: str, correct: bool) -> None:
        with self.conn:
            self.conn.execute("INSERT INTO answer_log (category, difficulty, is_correct, answered_at) VALUES (?,?,?,?)",
                              (category, difficulty, int(correct), datetime.now().strftime("%Y-%m-%d %H:%M:%S")))

    def accuracy_by_category(self) -> dict[str, tuple[int, int]]:
        rows = self.conn.execute("SELECT category, SUM(is_correct), COUNT(*) FROM answer_log GROUP BY category")
        return {r[0]: (int(r[1]), int(r[2])) for r in rows}

    def save_result(self, player: str, category: str, difficulty: str, score: int, total: int,
                    duration: int, completed_at: str) -> None:
        pct = round(score / total * 100, 1) if total else 0.0
        with self.conn:
            self.conn.execute(
                """INSERT INTO quiz_results (player_name, category, difficulty, score, total, percentage,
                   duration_seconds, completed_at) VALUES (?,?,?,?,?,?,?,?)""",
                (player, category, difficulty, score, total, pct, duration, completed_at))

    def get_history(self, limit: int = 100) -> list[tuple[Any, ...]]:
        return self.conn.execute(
            """SELECT completed_at, player_name, category, difficulty, score, total, percentage, duration_seconds
               FROM quiz_results ORDER BY id DESC LIMIT ?""", (limit,)).fetchall()

    def get_summary(self) -> tuple[int, int, float]:
        row = self.conn.execute("SELECT COUNT(*), COALESCE(SUM(score),0), COALESCE(AVG(percentage),0) "
                                "FROM quiz_results").fetchone()
        return int(row[0]), int(row[1]), float(row[2])

    def close(self) -> None:
        self.conn.close()


# ======================================================================
# Question picking (UI independent)
# ======================================================================

class QuestionPicker:
    def __init__(self, db: Database) -> None:
        self.db = db

    def all_categories(self, difficulty: str | None = None) -> list[str]:
        return sorted(set(self.db.categories(difficulty)) | set(PROCEDURAL))

    def _from_category(self, category: str, difficulty: str | None, n: int,
                       used_ids: set[int], seen_text: set[str]) -> list[dict]:
        if n <= 0:
            return []
        if category in PROCEDURAL:
            batch = generate_procedural(category, difficulty, n + 3)
        else:
            batch = self.db.fetch_questions(category, difficulty, n, used_ids)
        out = []
        for q in batch:
            if q["question"] in seen_text:
                continue
            seen_text.add(q["question"])
            if q.get("id"):
                used_ids.add(q["id"])
            out.append(q)
            if len(out) == n:
                break
        return out

    def pick(self, category: str, difficulty: str, count: int) -> list[dict]:
        diff = None if difficulty == ALL_LEVELS else difficulty
        used_ids: set[int] = set()
        seen_text: set[str] = set()
        if category != MIXED:
            picked = self._from_category(category, diff, count, used_ids, seen_text)
        else:
            cats = self.all_categories(diff)
            random.shuffle(cats)
            quotas: dict[str, int] = {}
            for i in range(count):
                c = cats[i % len(cats)]
                quotas[c] = quotas.get(c, 0) + 1
            picked = []
            for c, q in quotas.items():
                picked += self._from_category(c, diff, q, used_ids, seen_text)
            for _ in range(12):                  # top up if some topics ran short
                if len(picked) >= count:
                    break
                picked += self._from_category(random.choice(cats), diff, count - len(picked), used_ids, seen_text)
        picked = picked[:count]
        random.shuffle(picked)
        return picked


# ======================================================================
# Background workers (automation)
# ======================================================================

def sync_worker(db_path: Path, events: queue.Queue, stop: threading.Event) -> None:
    """Walk every Open Trivia DB topic x difficulty and cache any that are not full."""
    db = Database(db_path)
    provider = OpenTriviaProvider(stop)
    added = 0
    try:
        events.put(("status", "Library sync: connecting to Open Trivia DB..."))
        cats = provider.fetch_categories()
        todo = [(n, i, d) for n, i in cats.items() for d in DIFFICULTIES
                if db.bucket_count(n, d) < BUCKET_TARGET * 0.8]
        random.shuffle(todo)
        if not todo:
            events.put(("library_updated", "Library is already full - nothing to sync."))
            return
        for k, (name, cid, diff) in enumerate(todo, 1):
            if stop.is_set():
                return
            events.put(("status", f"Library sync {k}/{len(todo)}: {name} ({diff})  -  {added} new so far"))
            added += db.add_questions(provider.fetch_questions(cid, name, diff, BUCKET_TARGET))
        events.put(("library_updated", f"Library sync finished: {added} new questions added."))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        events.put(("library_updated", f"Library sync paused ({exc}). {added} questions added; offline play still works."))
    finally:
        db.close()


def claude_topic_worker(db_path: Path, events: queue.Queue, topic: str) -> None:
    db = Database(db_path)
    try:
        qs = ClaudeProvider().generate(topic, 12)
        if not qs:
            events.put(("topic_error", "Claude returned no usable questions. Try a different topic."))
            return
        db.add_questions(qs)
        events.put(("topic_ready", qs[0]["category"]))
    except urllib.error.HTTPError as exc:
        hint = " (check your ANTHROPIC_API_KEY)" if exc.code in (401, 403) else ""
        events.put(("topic_error", f"Claude API error {exc.code}{hint}."))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        events.put(("topic_error", f"Could not generate questions: {exc}"))
    finally:
        db.close()


def claude_explore_worker(db_path: Path, events: queue.Queue, stop: threading.Event, topic_count: int = 10) -> None:
    """Let Claude invent new topic areas, then write questions for each one."""
    db = Database(db_path)
    claude = ClaudeProvider()
    added = 0
    try:
        events.put(("status", "Claude is choosing new topics to explore..."))
        topics = claude.discover_topics(topic_count, db.categories() + list(PROCEDURAL))
        for k, topic in enumerate(topics, 1):
            if stop.is_set():
                return
            events.put(("status", f"Claude topic {k}/{len(topics)}: {topic}"))
            added += db.add_questions(claude.generate(topic, 12))
        events.put(("library_updated", f"Claude added {added} questions across {len(topics)} new topics."))
    except urllib.error.HTTPError as exc:
        events.put(("library_updated", f"Claude API error {exc.code}. {added} questions added."))
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        events.put(("library_updated", f"Claude exploration stopped ({exc}). {added} questions added."))
    finally:
        db.close()


# ======================================================================
# Custom widgets (Labels, so colours work on every OS including macOS)
# ======================================================================

class FlatButton(tk.Label):
    def __init__(self, parent: tk.Widget, text: str, command: Callable[[], None],
                 primary: bool = False, **kw: Any) -> None:
        self._normal = COLORS["primary"] if primary else COLORS["surface"]
        self._hover = COLORS["primary_hover"] if primary else COLORS["primary_soft"]
        self._fg = "#FFFFFF" if primary else COLORS["text"]
        self._command = command
        self.enabled = True
        super().__init__(parent, text=text, bg=self._normal, fg=self._fg, font=("Segoe UI", 10, "bold"),
                         padx=18, pady=10, cursor="hand2", highlightthickness=0 if primary else 1,
                         highlightbackground=COLORS["border"], **kw)
        self.bind("<Button-1>", self._click)
        self.bind("<Enter>", lambda _e: self.enabled and self.configure(bg=self._hover))
        self.bind("<Leave>", lambda _e: self.enabled and self.configure(bg=self._normal))

    def _click(self, _event: Any) -> None:
        if self.enabled:
            self._command()

    def set_command(self, text: str, command: Callable[[], None]) -> None:
        self.configure(text=text)
        self._command = command

    def set_enabled(self, enabled: bool) -> None:
        self.enabled = enabled
        if enabled:
            self.configure(bg=self._normal, fg=self._fg, cursor="hand2")
        else:
            self.configure(bg=COLORS["border"], fg=COLORS["muted"], cursor="arrow")


class OptionRow(tk.Label):
    STATES = {
        "normal": (COLORS["surface_alt"], COLORS["text"], COLORS["border"]),
        "selected": (COLORS["primary_soft"], COLORS["text"], COLORS["primary"]),
        "correct": (COLORS["success_soft"], COLORS["success"], COLORS["success"]),
        "wrong": (COLORS["danger_soft"], COLORS["danger"], COLORS["danger"]),
        "dim": (COLORS["surface_alt"], COLORS["muted"], COLORS["border"]),
    }

    def __init__(self, parent: tk.Widget, letter: str, value: str, on_click: Callable[["OptionRow"], None]) -> None:
        self.value = value
        super().__init__(parent, text=f"  {letter}.   {value}", anchor="w", justify="left",
                         font=("Segoe UI", 11), padx=14, pady=12, cursor="hand2", highlightthickness=1)
        self.set_state("normal")
        self.bind("<Button-1>", lambda _e: on_click(self))

    def set_state(self, state: str) -> None:
        bg, fg, border = self.STATES[state]
        self.configure(bg=bg, fg=fg, highlightbackground=border)


# ======================================================================
# Application
# ======================================================================

class QuizMasterPro:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(f"{APP_TITLE} {APP_VERSION} | Auto-Generated Quiz Platform")
        self.root.geometry("1080x780")
        self.root.minsize(880, 660)
        self.root.configure(bg=COLORS["app_bg"])

        self.db_path = resolve_db_path()
        self.db = Database(self.db_path)
        self.db.seed_builtin()
        self.picker = QuestionPicker(self.db)
        self.claude = ClaudeProvider()
        self.events: queue.Queue = queue.Queue()
        self.stop_event = threading.Event()
        self.sync_thread: threading.Thread | None = None
        self.claude_thread: threading.Thread | None = None

        self.style = ttk.Style()
        self._configure_styles()

        # persistent status bar + replaceable content area
        self.status_var = tk.StringVar(value="Ready.")
        bar = tk.Frame(self.root, bg=COLORS["surface"], highlightbackground=COLORS["border"], highlightthickness=1)
        bar.pack(side="bottom", fill="x")
        tk.Label(bar, textvariable=self.status_var, bg=COLORS["surface"], fg=COLORS["muted"],
                 font=("Segoe UI", 9), anchor="w", padx=14, pady=6).pack(fill="x")
        self.content = tk.Frame(self.root, bg=COLORS["app_bg"])
        self.content.pack(fill="both", expand=True)

        self.mode = "home"
        self.timer_job: str | None = None
        self.scroll_canvas: tk.Canvas | None = None
        self.option_rows: list[OptionRow] = []
        self.pending_quiz: dict[str, Any] | None = None
        self.last_config: dict[str, Any] | None = None
        self.questions: list[dict] = []
        self.question_index = 0
        self.score = 0
        self.answers: list[dict] = []
        self.answer_locked = False
        self.selected_value = ""
        self.active_seconds = 0.0
        self.question_started = 0.0
        self.question_time = DEFAULT_QUESTION_SECONDS
        self.player_name = "Player"
        self.selected_category = MIXED
        self.selected_difficulty = ALL_LEVELS

        self.root.bind("<Key>", self.on_key)
        for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
            self.root.bind_all(seq, self.on_wheel)

        self.build_home()
        self.poll_events()
        self.root.after(1200, lambda: self.start_sync(auto=True))

    # ---------- styling & helpers ----------

    def _configure_styles(self) -> None:
        try:
            self.style.theme_use("clam")
        except tk.TclError:
            pass
        self.style.configure("Light.TCombobox", fieldbackground=COLORS["surface"], background=COLORS["surface"],
                             foreground=COLORS["text"], arrowcolor=COLORS["primary"], padding=8)
        self.style.map("Light.TCombobox", fieldbackground=[("readonly", COLORS["surface"])],
                       selectbackground=[("readonly", COLORS["surface"])],
                       selectforeground=[("readonly", COLORS["text"])])
        self.style.configure("Light.Horizontal.TProgressbar", troughcolor=COLORS["border"],
                             background=COLORS["primary"], bordercolor=COLORS["border"],
                             lightcolor=COLORS["primary"], darkcolor=COLORS["primary"], thickness=10)
        self.style.configure("Light.Treeview", background=COLORS["surface"], fieldbackground=COLORS["surface"],
                             foreground=COLORS["text"], rowheight=32, borderwidth=0, font=("Segoe UI", 10))
        self.style.configure("Light.Treeview.Heading", background=COLORS["primary_soft"], foreground=COLORS["text"],
                             font=("Segoe UI", 10, "bold"), padding=(8, 10), relief="flat")
        self.style.map("Light.Treeview", background=[("selected", COLORS["primary_soft"])],
                       foreground=[("selected", COLORS["text"])])

    def set_status(self, text: str) -> None:
        self.status_var.set(text)

    def clear_screen(self) -> None:
        self.cancel_timer()
        self.scroll_canvas = None
        self.option_rows = []
        for widget in self.content.winfo_children():
            widget.destroy()

    @staticmethod
    def label(parent: tk.Widget, text: str, size: int = 11, color: str | None = None,
              bold: bool = False, **kw: Any) -> tk.Label:
        bg = kw.pop("bg", COLORS["surface"])
        return tk.Label(parent, text=text, bg=bg, fg=color or COLORS["text"],
                        font=("Segoe UI", size, "bold" if bold else "normal"), **kw)

    @staticmethod
    def card(parent: tk.Widget, **kw: Any) -> tk.Frame:
        return tk.Frame(parent, bg=COLORS["surface"], highlightbackground=COLORS["border"],
                        highlightthickness=1, **kw)

    @staticmethod
    def autowrap(container: tk.Widget, widgets: list[tk.Label], pad: int = 70) -> None:
        def resize(event: Any) -> None:
            width = max(220, event.width - pad)
            for w in widgets:
                try:
                    w.configure(wraplength=width)
                except tk.TclError:
                    pass
        container.bind("<Configure>", resize, add="+")

    def on_wheel(self, event: Any) -> None:
        canvas = self.scroll_canvas
        if canvas is None:
            return
        if getattr(event, "num", 0) == 4:
            canvas.yview_scroll(-1, "units")
        elif getattr(event, "num", 0) == 5:
            canvas.yview_scroll(1, "units")
        elif event.delta:
            steps = max(1, abs(event.delta) // 120)
            canvas.yview_scroll((-1 if event.delta > 0 else 1) * steps, "units")

    # ---------- background events ----------

    def poll_events(self) -> None:
        try:
            while True:
                kind, *rest = self.events.get_nowait()
                if kind == "status":
                    self.set_status(rest[0])
                elif kind == "library_updated":
                    self.set_status(rest[0])
                    if self.mode == "library":
                        self.show_library()
                    elif self.mode == "home":
                        self.refresh_topic_choices()
                elif kind == "topic_ready":
                    self.set_status(f"Questions ready for '{rest[0]}'.")
                    pending, self.pending_quiz = self.pending_quiz, None
                    if pending and self.mode == "home":
                        pending["category"] = rest[0]
                        self.launch_quiz(**pending)
                elif kind == "topic_error":
                    self.pending_quiz = None
                    self.set_status("Topic generation failed.")
                    messagebox.showerror("Claude generation", rest[0], parent=self.root)
        except queue.Empty:
            pass
        self.root.after(200, self.poll_events)

    def start_sync(self, auto: bool = False) -> None:
        if self.sync_thread and self.sync_thread.is_alive():
            if not auto:
                messagebox.showinfo("Sync running", "A library sync is already running. Progress is in the status bar.",
                                    parent=self.root)
            return
        self.sync_thread = threading.Thread(target=sync_worker, args=(self.db_path, self.events, self.stop_event),
                                            daemon=True)
        self.sync_thread.start()
        if not auto:
            self.set_status("Library sync started. This runs in the background (about 5 s per request).")

    def start_claude_explore(self) -> None:
        if not self.claude.available():
            self.explain_missing_key()
            return
        if self.claude_thread and self.claude_thread.is_alive():
            messagebox.showinfo("Already running", "Claude is already exploring topics.", parent=self.root)
            return
        self.claude_thread = threading.Thread(target=claude_explore_worker,
                                              args=(self.db_path, self.events, self.stop_event), daemon=True)
        self.claude_thread.start()
        self.set_status("Claude is exploring new topics in the background...")

    def explain_missing_key(self) -> None:
        messagebox.showinfo(
            "Claude API key needed",
            "This feature uses the Claude API.\n\nSet the ANTHROPIC_API_KEY environment variable, then restart "
            "the app.\n\nWindows (PowerShell):  $env:ANTHROPIC_API_KEY=\"your-key\"\n"
            "macOS/Linux:  export ANTHROPIC_API_KEY=\"your-key\"\n\n"
            "Everything else (Open Trivia DB sync and built-in generators) works without a key.",
            parent=self.root)

    # ---------- home ----------

    def topic_choices(self) -> list[str]:
        return [MIXED] + self.picker.all_categories()

    def refresh_topic_choices(self) -> None:
        combo = getattr(self, "category_combo", None)
        if combo is not None and combo.winfo_exists():
            combo.configure(values=self.topic_choices())

    def build_home(self) -> None:
        self.clear_screen()
        self.mode = "home"
        shell = tk.Frame(self.content, bg=COLORS["app_bg"], padx=28, pady=20)
        shell.pack(fill="both", expand=True)

        top = tk.Frame(shell, bg=COLORS["app_bg"])
        top.pack(fill="x", pady=(0, 14))
        self.label(top, "QM", 13, "#FFFFFF", True, bg=COLORS["primary"], width=4, height=2).pack(side="left", padx=(0, 10))
        brand = tk.Frame(top, bg=COLORS["app_bg"])
        brand.pack(side="left")
        self.label(brand, "QuizMaster Pro", 15, bold=True, bg=COLORS["app_bg"]).pack(anchor="w")
        self.label(brand, "AUTO-GENERATED QUIZ PLATFORM", 8, COLORS["muted"], True, bg=COLORS["app_bg"]).pack(anchor="w")
        FlatButton(top, "History", self.show_history).pack(side="right")
        FlatButton(top, "Topic library", self.show_library).pack(side="right", padx=(0, 8))

        self.label(shell, "Explore every topic. Questions write themselves.", 26, bold=True,
                   bg=COLORS["app_bg"]).pack(anchor="w")
        sub = self.label(shell, "Questions are pulled and generated automatically from many sources, so each quiz "
                         "can cover a different area of knowledge.", 11, COLORS["muted"], bg=COLORS["app_bg"],
                         justify="left")
        sub.pack(anchor="w", pady=(6, 14))
        self.autowrap(shell, [sub], 56)

        attempts, _correct, avg = self.db.get_summary()
        stats = tk.Frame(shell, bg=COLORS["app_bg"])
        stats.pack(fill="x", pady=(0, 14))
        topic_total = len(self.picker.all_categories())
        for i, (head, val, det) in enumerate([
            ("QUESTIONS CACHED", f"{self.db.total_questions():,}", "Plus unlimited generated maths/logic"),
            ("TOPIC AREAS", str(topic_total), "Trivia, science, code, maths and more"),
            ("QUIZ ATTEMPTS", str(attempts), f"Average accuracy {avg:.1f}%"),
        ]):
            c = self.card(stats, padx=16, pady=12)
            c.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 10, 0))
            self.label(c, head, 8, COLORS["muted"], True).pack(anchor="w")
            self.label(c, val, 21, COLORS["primary"], True).pack(anchor="w", pady=(4, 0))
            self.label(c, det, 9, COLORS["muted"]).pack(anchor="w")

        setup = self.card(shell, padx=24, pady=18)
        setup.pack(fill="x")
        self.label(setup, "Set up your quiz", 16, bold=True).pack(anchor="w", pady=(0, 10))

        row1 = tk.Frame(setup, bg=COLORS["surface"])
        row1.pack(fill="x")
        left = tk.Frame(row1, bg=COLORS["surface"])
        left.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.label(left, "PLAYER NAME", 9, COLORS["muted"], True).pack(anchor="w")
        self.name_var = tk.StringVar(value=self.player_name)
        entry = tk.Entry(left, textvariable=self.name_var, bg=COLORS["surface_alt"], fg=COLORS["text"],
                         insertbackground=COLORS["text"], relief="flat", highlightthickness=1,
                         highlightbackground=COLORS["border"], highlightcolor=COLORS["primary"], font=("Segoe UI", 11))
        entry.pack(fill="x", ipady=8, pady=(5, 0))
        entry.bind("<Return>", lambda _e: self.start_quiz())
        right = tk.Frame(row1, bg=COLORS["surface"])
        right.pack(side="left", fill="x", expand=True, padx=(10, 0))
        self.label(right, "TOPIC", 9, COLORS["muted"], True).pack(anchor="w")
        self.category_var = tk.StringVar(value=MIXED)
        self.category_combo = ttk.Combobox(right, textvariable=self.category_var, values=self.topic_choices(),
                                           state="readonly", style="Light.TCombobox")
        self.category_combo.pack(fill="x", pady=(5, 0))

        row2 = tk.Frame(setup, bg=COLORS["surface"])
        row2.pack(fill="x", pady=(12, 0))
        self.difficulty_var = tk.StringVar(value=ALL_LEVELS)
        self.count_var = tk.StringVar(value=str(DEFAULT_QUESTION_COUNT))
        self.seconds_var = tk.StringVar(value=str(DEFAULT_QUESTION_SECONDS))
        for idx, (title, widget_factory) in enumerate([
            ("DIFFICULTY", lambda p: ttk.Combobox(p, textvariable=self.difficulty_var,
                                                  values=[ALL_LEVELS] + DIFFICULTIES, state="readonly",
                                                  style="Light.TCombobox")),
            ("QUESTIONS", lambda p: tk.Spinbox(p, from_=5, to=30, textvariable=self.count_var, width=6,
                                               font=("Segoe UI", 11), relief="flat", highlightthickness=1,
                                               highlightbackground=COLORS["border"])),
            ("SECONDS PER QUESTION", lambda p: ttk.Combobox(p, textvariable=self.seconds_var,
                                                            values=["10", "15", "20", "30", "45", "60"],
                                                            state="readonly", style="Light.TCombobox")),
        ]):
            col = tk.Frame(row2, bg=COLORS["surface"])
            col.pack(side="left", fill="x", expand=True, padx=(0 if idx == 0 else 10, 0))
            self.label(col, title, 9, COLORS["muted"], True).pack(anchor="w")
            widget_factory(col).pack(fill="x", pady=(5, 0), ipady=3)

        self.label(setup, "OR TYPE ANY TOPIC  (Claude writes fresh questions - needs ANTHROPIC_API_KEY)", 9,
                   COLORS["muted"], True).pack(anchor="w", pady=(14, 0))
        self.custom_var = tk.StringVar()
        custom = tk.Entry(setup, textvariable=self.custom_var, bg=COLORS["surface_alt"], fg=COLORS["text"],
                          insertbackground=COLORS["text"], relief="flat", highlightthickness=1,
                          highlightbackground=COLORS["border"], highlightcolor=COLORS["primary"], font=("Segoe UI", 11))
        custom.pack(fill="x", ipady=8, pady=(5, 0))
        custom.bind("<Return>", lambda _e: self.start_quiz())

        footer = tk.Frame(shell, bg=COLORS["app_bg"])
        footer.pack(fill="x", pady=(14, 0))
        self.label(footer, "Mixed mode spreads your questions across as many different topics as possible.",
                   9, COLORS["muted"], bg=COLORS["app_bg"]).pack(side="left")
        FlatButton(footer, "Start quiz  >", self.start_quiz, primary=True).pack(side="right")

    def start_quiz(self) -> None:
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("Name required", "Please enter your name before starting.", parent=self.root)
            return
        try:
            count = max(5, min(30, int(self.count_var.get())))
            seconds = int(self.seconds_var.get())
        except ValueError:
            messagebox.showwarning("Invalid settings", "Question count must be a number.", parent=self.root)
            return
        config = {"category": self.category_var.get(), "difficulty": self.difficulty_var.get(),
                  "count": count, "seconds": seconds, "name": name[:60]}
        topic = " ".join(self.custom_var.get().split())
        if topic:
            if not self.claude.available():
                self.explain_missing_key()
                return
            if self.pending_quiz:
                return
            self.pending_quiz = config
            self.set_status(f"Claude is writing questions about '{topic[:50]}'...")
            threading.Thread(target=claude_topic_worker, args=(self.db_path, self.events, topic),
                             daemon=True).start()
            return
        self.launch_quiz(**config)

    def launch_quiz(self, category: str, difficulty: str, count: int, seconds: int, name: str) -> None:
        questions = self.picker.pick(category, difficulty, count)
        if not questions:
            messagebox.showinfo(
                "No questions yet",
                "No questions match these filters yet. Try 'Mixed', another difficulty, or open the Topic library "
                "and run a sync while online.", parent=self.root)
            return
        self.last_config = {"category": category, "difficulty": difficulty, "count": count,
                            "seconds": seconds, "name": name}
        self.player_name, self.selected_category, self.selected_difficulty = name, category, difficulty
        self.question_time = seconds
        self.questions, self.question_index, self.score = questions, 0, 0
        self.answers, self.active_seconds = [], 0.0
        self.show_question()

    # ---------- quiz ----------

    def show_question(self) -> None:
        self.clear_screen()
        self.mode = "quiz"
        self.answer_locked = False
        self.selected_value = ""
        self.seconds_left = self.question_time
        q = self.questions[self.question_index]
        total = len(self.questions)

        shell = tk.Frame(self.content, bg=COLORS["app_bg"], padx=28, pady=18)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=COLORS["app_bg"])
        header.pack(fill="x", pady=(0, 14))
        self.label(header, "QUIZMASTER PRO", 10, COLORS["primary"], True, bg=COLORS["app_bg"]).pack(side="left")
        self.timer_label = self.label(header, "", 10, COLORS["warning"], True, bg=COLORS["warning_soft"], padx=12, pady=7)
        self.timer_label.pack(side="right")

        card = self.card(shell, padx=24, pady=20)
        card.pack(fill="both", expand=True)
        top = tk.Frame(card, bg=COLORS["surface"])
        top.pack(fill="x")
        self.label(top, f"QUESTION {self.question_index + 1:02d} / {total:02d}", 9, COLORS["muted"], True).pack(side="left")
        badges = tk.Frame(top, bg=COLORS["surface"])
        badges.pack(side="right")
        self.label(badges, q["category"], 9, COLORS["primary"], True, bg=COLORS["primary_soft"], padx=9, pady=5).pack(side="left", padx=(0, 6))
        diff_color = {"Easy": COLORS["success"], "Medium": COLORS["warning"], "Hard": COLORS["danger"]}[q["difficulty"]]
        self.label(badges, q["difficulty"], 9, diff_color, True, bg=COLORS["surface_alt"], padx=9, pady=5).pack(side="left")

        ttk.Progressbar(card, style="Light.Horizontal.TProgressbar", maximum=total,
                        value=self.question_index).pack(fill="x", pady=(14, 20))
        qlabel = self.label(card, q["question"], 18, bold=True, justify="left", anchor="w")
        qlabel.pack(fill="x", pady=(0, 16))

        options = q["options"][:]
        random.shuffle(options)
        wrap_targets = [qlabel]
        area = tk.Frame(card, bg=COLORS["surface"])
        area.pack(fill="x")
        for i, opt in enumerate(options):
            row = OptionRow(area, chr(65 + i), opt, self.select_option)
            row.pack(fill="x", pady=4)
            self.option_rows.append(row)
            wrap_targets.append(row)
        self.feedback_label = self.label(card, "Tip: press A-D (or 1-4) to choose and Enter to submit.", 10,
                                         COLORS["muted"], justify="left", anchor="w")
        self.feedback_label.pack(fill="x", pady=(12, 0))
        wrap_targets.append(self.feedback_label)
        self.autowrap(card, wrap_targets, 80)

        controls = tk.Frame(shell, bg=COLORS["app_bg"])
        controls.pack(fill="x", pady=(14, 0))
        FlatButton(controls, "< Quit quiz", self.confirm_quit).pack(side="left")
        self.submit_button = FlatButton(controls, "Submit answer  >", self.submit_answer, primary=True)
        self.submit_button.pack(side="right")
        self.question_started = time.monotonic()
        self.update_timer()

    def select_option(self, chosen: OptionRow) -> None:
        if self.answer_locked:
            return
        self.selected_value = chosen.value
        for row in self.option_rows:
            row.set_state("selected" if row is chosen else "normal")

    def on_key(self, event: Any) -> None:
        if self.mode != "quiz" or not self.option_rows:
            return
        key = event.keysym.lower()
        if key in ("return", "kp_enter"):
            if self.answer_locked:
                self.next_question()
            else:
                self.submit_answer()
            return
        index = {"1": 0, "2": 1, "3": 2, "4": 3, "a": 0, "b": 1, "c": 2, "d": 3, "e": 4, "f": 5}.get(key)
        if index is not None and index < len(self.option_rows):
            self.select_option(self.option_rows[index])

    def update_timer(self) -> None:
        if self.answer_locked or self.mode != "quiz":
            return
        self.timer_label.configure(text=f"Time left: {self.seconds_left:02d}s")
        if self.seconds_left <= 0:
            self.submit_answer(timed_out=True)
            return
        if self.seconds_left <= 5:
            self.timer_label.configure(bg=COLORS["danger_soft"], fg=COLORS["danger"])
        self.seconds_left -= 1
        self.timer_job = self.root.after(1000, self.update_timer)

    def cancel_timer(self) -> None:
        if self.timer_job is not None:
            try:
                self.root.after_cancel(self.timer_job)
            except (tk.TclError, ValueError):
                pass
            self.timer_job = None

    def submit_answer(self, timed_out: bool = False) -> None:
        if self.answer_locked:
            return
        if not self.selected_value and not timed_out:
            self.feedback_label.configure(text="Select an answer first.", fg=COLORS["warning"])
            return
        self.answer_locked = True
        self.cancel_timer()
        self.active_seconds += min(time.monotonic() - self.question_started, self.question_time)

        q = self.questions[self.question_index]
        correct = self.selected_value == q["answer"]
        if correct:
            self.score += 1
            text, color, bg = f"Correct!  {q['explanation']}", COLORS["success"], COLORS["success_soft"]
        elif timed_out and not self.selected_value:
            text = f"Time is up. Correct answer: {q['answer']}.  {q['explanation']}"
            color, bg = COLORS["danger"], COLORS["danger_soft"]
        else:
            text = f"Not quite. Correct answer: {q['answer']}.  {q['explanation']}"
            color, bg = COLORS["danger"], COLORS["danger_soft"]

        for row in self.option_rows:
            if row.value == q["answer"]:
                row.set_state("correct")
            elif row.value == self.selected_value:
                row.set_state("wrong")
            else:
                row.set_state("dim")
        self.feedback_label.configure(text=text, fg=color, bg=bg, padx=12, pady=10)

        self.answers.append({"question": q["question"], "selected": self.selected_value or "No answer",
                             "correct_answer": q["answer"], "is_correct": correct,
                             "explanation": q["explanation"], "category": q["category"]})
        try:
            self.db.log_answer(q["category"], q["difficulty"], correct)
            if q.get("id"):
                self.db.mark_seen(q["id"])
        except sqlite3.Error:
            pass
        last = self.question_index == len(self.questions) - 1
        self.submit_button.set_command("View results  >" if last else "Next question  >", self.next_question)

    def next_question(self) -> None:
        if not self.answer_locked:
            self.submit_answer()
            return
        if self.question_index + 1 < len(self.questions):
            self.question_index += 1
            self.show_question()
        else:
            self.show_results()

    def confirm_quit(self) -> None:
        if messagebox.askyesno("Quit quiz", "End this quiz attempt? Its result will not be saved.", parent=self.root):
            self.build_home()

    # ---------- results ----------

    def show_results(self) -> None:
        self.clear_screen()
        self.mode = "results"
        total = len(self.questions)
        pct = self.score / total * 100 if total else 0.0
        duration = int(self.active_seconds)
        try:
            self.db.save_result(self.player_name, self.selected_category, self.selected_difficulty, self.score,
                                total, duration, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        except sqlite3.Error as exc:
            messagebox.showerror("Save error", f"The result could not be saved.\n\n{exc}", parent=self.root)

        shell = tk.Frame(self.content, bg=COLORS["app_bg"], padx=28, pady=18)
        shell.pack(fill="both", expand=True)
        head = tk.Frame(shell, bg=COLORS["app_bg"])
        head.pack(fill="x", pady=(0, 12))
        self.label(head, "QUIZ SUMMARY", 10, COLORS["primary"], True, bg=COLORS["app_bg"]).pack(side="left")
        FlatButton(head, "Home", self.build_home).pack(side="right")

        if pct >= 80:
            msg, color, bg = "Excellent work - you have a strong grasp of these topics.", COLORS["success"], COLORS["success_soft"]
        elif pct >= 50:
            msg, color, bg = "Good effort - review the missed answers to improve.", COLORS["warning"], COLORS["warning_soft"]
        else:
            msg, color, bg = "Keep practising - every attempt helps you improve.", COLORS["danger"], COLORS["danger_soft"]
        hero = self.card(shell, padx=22, pady=16)
        hero.pack(fill="x")
        self.label(hero, f"Well done, {self.player_name}!", 22, bold=True).pack(anchor="w")
        self.label(hero, msg, 10, color, bg=bg, padx=10, pady=6).pack(anchor="w", pady=(8, 0))

        stats = tk.Frame(shell, bg=COLORS["app_bg"])
        stats.pack(fill="x", pady=12)
        for i, (head_t, val, det) in enumerate([
            ("YOUR SCORE", f"{self.score}/{total}", "Correct answers"),
            ("ACCURACY", f"{pct:.1f}%", "Overall performance"),
            ("ANSWERING TIME", f"{duration // 60:02d}:{duration % 60:02d}", "Time spent on questions"),
        ]):
            box = self.card(stats, padx=16, pady=12)
            box.pack(side="left", fill="both", expand=True, padx=(0 if i == 0 else 10, 0))
            self.label(box, head_t, 8, COLORS["muted"], True).pack(anchor="w")
            self.label(box, val, 21, COLORS["primary"], True).pack(anchor="w", pady=(4, 0))
            self.label(box, det, 9, COLORS["muted"]).pack(anchor="w")

        self.label(shell, "Answer review", 14, bold=True, bg=COLORS["app_bg"]).pack(anchor="w", pady=(0, 6))
        outer = self.card(shell)
        outer.pack(fill="both", expand=True)
        canvas = tk.Canvas(outer, bg=COLORS["surface"], highlightthickness=0)
        bar = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        inner = tk.Frame(canvas, bg=COLORS["surface"], padx=14, pady=8)
        win = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind("<Configure>", lambda _e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.configure(yscrollcommand=bar.set)
        canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.scroll_canvas = canvas

        wrap_targets: list[tk.Label] = []
        for i, item in enumerate(self.answers, 1):
            ok = item["is_correct"]
            cbg = COLORS["success_soft"] if ok else COLORS["danger_soft"]
            box = tk.Frame(inner, bg=cbg, padx=12, pady=9)
            box.pack(fill="x", pady=4)
            parts = [
                self.label(box, f"{i}. {item['question']}", 10, bold=True, bg=cbg, justify="left", anchor="w"),
                self.label(box, f"[{item['category']}]  Your answer: {item['selected']}   |   Correct: "
                           f"{item['correct_answer']}   -   {'CORRECT' if ok else 'REVIEW'}", 9,
                           COLORS["success"] if ok else COLORS["danger"], True, bg=cbg, justify="left", anchor="w"),
                self.label(box, item["explanation"], 9, COLORS["muted"], bg=cbg, justify="left", anchor="w"),
            ]
            for p in parts:
                p.pack(fill="x", pady=1)
            wrap_targets += parts

        def on_canvas_resize(event: Any) -> None:
            canvas.itemconfigure(win, width=event.width)
            for w in wrap_targets:
                w.configure(wraplength=max(220, event.width - 70))
        canvas.bind("<Configure>", on_canvas_resize)

        actions = tk.Frame(shell, bg=COLORS["app_bg"])
        actions.pack(fill="x", pady=(12, 0))
        FlatButton(actions, "< Home", self.build_home).pack(side="left")
        FlatButton(actions, "History", self.show_history).pack(side="left", padx=8)
        if self.last_config:
            FlatButton(actions, "Play again with new questions  >", lambda: self.launch_quiz(**self.last_config),
                       primary=True).pack(side="right")

    # ---------- history ----------

    def show_history(self) -> None:
        self.clear_screen()
        self.mode = "history"
        shell = tk.Frame(self.content, bg=COLORS["app_bg"], padx=28, pady=20)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=COLORS["app_bg"])
        header.pack(fill="x", pady=(0, 14))
        titles = tk.Frame(header, bg=COLORS["app_bg"])
        titles.pack(side="left")
        self.label(titles, "Quiz history", 22, bold=True, bg=COLORS["app_bg"]).pack(anchor="w")
        self.label(titles, "Recent attempts saved on this computer.", 10, COLORS["muted"], bg=COLORS["app_bg"]).pack(anchor="w")
        FlatButton(header, "< Home", self.build_home).pack(side="right")

        holder = self.card(shell, padx=12, pady=12)
        holder.pack(fill="both", expand=True)
        cols = ("date", "player", "category", "difficulty", "score", "accuracy", "duration")
        table = ttk.Treeview(holder, columns=cols, show="headings", style="Light.Treeview", height=14)
        names = {"date": ("COMPLETED AT", 150), "player": ("PLAYER", 110), "category": ("TOPIC", 190),
                 "difficulty": ("LEVEL", 85), "score": ("SCORE", 70), "accuracy": ("ACCURACY", 85),
                 "duration": ("TIME", 80)}
        for col in cols:
            table.heading(col, text=names[col][0])
            table.column(col, width=names[col][1], anchor="center", stretch=True)
        rows = self.db.get_history()
        for when, player, cat, diff, score, total, pct, secs in rows:
            table.insert("", "end", values=(when, player, cat, diff, f"{score}/{total}", f"{pct:.1f}%",
                                            f"{secs // 60:02d}:{secs % 60:02d}"))
        sb = ttk.Scrollbar(holder, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=sb.set)
        table.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        if not rows:
            self.set_status("No quiz attempts yet - complete a quiz to see your history.")

    # ---------- topic library ----------

    def show_library(self) -> None:
        self.clear_screen()
        self.mode = "library"
        shell = tk.Frame(self.content, bg=COLORS["app_bg"], padx=28, pady=20)
        shell.pack(fill="both", expand=True)
        header = tk.Frame(shell, bg=COLORS["app_bg"])
        header.pack(fill="x", pady=(0, 10))
        titles = tk.Frame(header, bg=COLORS["app_bg"])
        titles.pack(side="left")
        self.label(titles, "Topic library", 22, bold=True, bg=COLORS["app_bg"]).pack(anchor="w")
        self.label(titles, "Everything the automation has collected, and how well you do in each topic.", 10,
                   COLORS["muted"], bg=COLORS["app_bg"]).pack(anchor="w")
        FlatButton(header, "< Home", self.build_home).pack(side="right")

        actions = tk.Frame(shell, bg=COLORS["app_bg"])
        actions.pack(fill="x", pady=(0, 6))
        FlatButton(actions, "Sync free trivia library", lambda: self.start_sync(False), primary=True).pack(side="left")
        FlatButton(actions, "Explore new topics with Claude", self.start_claude_explore).pack(side="left", padx=8)
        key_text = "Claude API key: detected" if self.claude.available() else "Claude API key: not set (optional)"
        self.label(actions, key_text, 9, COLORS["success"] if self.claude.available() else COLORS["muted"],
                   bg=COLORS["app_bg"]).pack(side="left", padx=8)

        holder = self.card(shell, padx=12, pady=12)
        holder.pack(fill="both", expand=True, pady=(6, 0))
        cols = ("topic", "source", "easy", "medium", "hard", "total", "acc")
        table = ttk.Treeview(holder, columns=cols, show="headings", style="Light.Treeview", height=16)
        spec = {"topic": ("TOPIC", 250, "w"), "source": ("SOURCE", 150, "center"), "easy": ("EASY", 60, "center"),
                "medium": ("MEDIUM", 70, "center"), "hard": ("HARD", 60, "center"),
                "total": ("TOTAL", 70, "center"), "acc": ("YOUR ACCURACY", 120, "center")}
        for col in cols:
            table.heading(col, text=spec[col][0])
            table.column(col, width=spec[col][1], anchor=spec[col][2], stretch=True)

        accuracy = self.db.accuracy_by_category()

        def acc_text(cat: str) -> str:
            ok, tot = accuracy.get(cat, (0, 0))
            return f"{ok / tot * 100:.0f}%  ({tot} answered)" if tot else "-"

        for cat, info in sorted(self.db.coverage().items()):
            total = info["Easy"] + info["Medium"] + info["Hard"]
            table.insert("", "end", values=(cat, ", ".join(sorted(info["sources"])), info["Easy"],
                                            info["Medium"], info["Hard"], total, acc_text(cat)))
        for cat in sorted(PROCEDURAL):
            table.insert("", "end", values=(cat, "Generated (offline)", "inf", "inf", "inf", "inf", acc_text(cat)))
        sb = ttk.Scrollbar(holder, orient="vertical", command=table.yview)
        table.configure(yscrollcommand=sb.set)
        table.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    # ---------- shutdown ----------

    def close(self) -> None:
        self.stop_event.set()
        self.cancel_timer()
        try:
            self.db.close()
        finally:
            self.root.destroy()


def main() -> None:
    root = tk.Tk()
    try:
        app = QuizMasterPro(root)
    except (sqlite3.Error, tk.TclError, OSError) as exc:
        messagebox.showerror("Application startup error", f"QuizMaster Pro could not start.\n\n{exc}")
        root.destroy()
        return
    root.protocol("WM_DELETE_WINDOW", app.close)
    root.mainloop()


if __name__ == "__main__":
    main()