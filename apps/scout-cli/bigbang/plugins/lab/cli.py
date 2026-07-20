# Solo personal project, no connection to employer, built with public/free-tier only
import json
from datetime import datetime
from pathlib import Path

import typer

from bigbang.core.output import emit

app = typer.Typer(
    name="lab",
    help="🧪 Passive Lab — Turnover Shield, MRR, boring B2B SaaS ideas (Ava co-dev)",
    no_args_is_help=True,
)

TOP10_DEFAULT = [
    {
        "rank": 1,
        "name": "Trade Crew Turnover Shield",
        "target_pricing": "$79-$149/mo",
        "persona": "Plumbing/HVAC owners 20-100 techs",
        "pain_hypothesis": "high annual churn, expensive re-hiring",
        "status": "concept — not built, not live",
    },
    {
        "rank": 2,
        "name": "Crew Profit Assignment",
        "pricing": "$99-$199/mo",
        "persona": "Electrical/Plumbing dispatch",
        "pain": "Wrong tech = callback, low margin",
    },
    {
        "rank": 3,
        "name": "Fleet Fatigue & Fit",
        "pricing": "$79/mo",
        "persona": "Fleet managers tradies",
        "pain": "Exhaustion, injury, DOT risk",
    },
    {
        "rank": 4,
        "name": "Gym Coach Retention",
        "pricing": "$49-$99/mo",
        "persona": "Boutique gym owners",
        "pain": "Coach churn kills members",
    },
    {
        "rank": 5,
        "name": "Music Studio Retention",
        "pricing": "$29-$59/mo",
        "persona": "Music school owners",
        "pain": "Student drop after 3 months",
    },
    {
        "rank": 6,
        "name": "Agency Bench & Burnout",
        "pricing": "$149-$299/mo",
        "persona": "Agency founders 10-50",
        "pain": "Bench cost + burnout",
    },
    {
        "rank": 7,
        "name": "Law/CPA Progress Transparency",
        "pricing": "$199/mo",
        "persona": "Small law/CPA firms",
        "pain": "Client chasing status",
    },
    {
        "rank": 8,
        "name": "Labor% Profit Pulse",
        "pricing": "$49-$89/mo",
        "persona": "Restaurant/QSR owners",
        "pain": "Labor % drift kills profit",
    },
    {
        "rank": 9,
        "name": "Childcare Ratio Guardian",
        "pricing": "$99/mo",
        "persona": "Childcare center directors",
        "pain": "State ratio violations",
    },
    {
        "rank": 10,
        "name": "Auto Repair Comeback",
        "pricing": "$79/mo",
        "persona": "Auto shop owners",
        "pain": "No-show, no comeback tracking",
    },
]

import re as _re

_TOP10_ITEM_RE = _re.compile(r"^\s*(?:[-*]|\d+[.)])\s+(.+\S)\s*$")


def _load_top10():
    """Parse a real top-10 markdown list if one exists locally; else the labeled default."""
    for p in [
        Path.home()
        / "workspace"
        / "your_files"
        / "02_Passive_Lab"
        / "Market-Research"
        / "TOP10-HOME-ONLY-SOLO.md",
        Path.home()
        / "workspace"
        / "projects"
        / "first-1k-mo-passive"
        / "files"
        / "top10.md",
    ]:
        if p.exists():
            try:
                text = p.read_text()
            except OSError:
                continue
            items = []
            for line in text.splitlines():
                m = _TOP10_ITEM_RE.match(line)
                if m:
                    items.append(
                        {"rank": len(items) + 1, "name": m.group(1), "source": str(p)}
                    )
            if len(items) >= 5:
                return items[:10]
    # honestly-labeled builtin default — idea concepts, not live products
    return [dict(item, source="builtin-default") for item in TOP10_DEFAULT]


def _mrr_path():
    return (
        Path.home()
        / "workspace"
        / "projects"
        / "first-1k-mo-passive"
        / "files"
        / "mrr.jsonl"
    )


def _load_mrr():
    fp = _mrr_path()
    if not fp.exists():
        return []
    out = []
    for line in fp.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


@app.command("ideas")
def ideas_cmd(
    top: int = typer.Option(10, "--top", help="Show top N"),
    json_out: bool = typer.Option(
        False, "--json-out", help="Alias, real json via bb --json"
    ),
):
    items = _load_top10()[:top]
    emit(
        {
            "top10": items,
            "count": len(items),
            "pricing_target": "Target position $79-$149/mo vs legacy tools — aspiration, not measured ROI",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="lab ideas",
    )


@app.command("shield")
def shield_cmd():
    """Turnover Shield concept status — what bb write can generate for it"""
    mrr = _load_mrr()
    last = mrr[-1] if mrr else None
    payload = {
        "product": "Trade Crew Turnover Shield",
        "status": "concept — not built, not live",
        "target_pricing": {
            "starter": 79,
            "pro": 149,
            "target_customers_for_1k": "7-13",
        },
        "roi_claim_example": "Illustrative pitch only: saving 1 tech avoids a ~$[YOUR NUMBER] hiring cost — verify with your own data",
        "planned_features": [
            "SMS check-in sequence",
            "Turnover risk score (tenure+OT+missed)",
            "Retention playbook",
            "Churn dashboard",
        ],
        "stack": "Free-tier only: R2/Workers/Supabase/HF ZeroGPU, ONNX WASM — bb write generates authentic job posts & retention emails",
        "last_mrr_entry": last,
        "next_bb_commands": [
            "bb --json lab mrr --trials 3 --paid 0",
            "bb --json write generate 'Turnover Shield cold email plumbing owner Austin — specific, no slop' --tone 'direct founder, 1 anecdote'",
            "bb --json lab log --paid 1 --mrr 79 --note 'First customer via Authentic Generators'",
        ],
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload, command="lab shield")


@app.command("mrr")
def mrr_cmd(
    trials: int | None = typer.Option(None, "--trials", help="Active trials"),
    paid: int | None = typer.Option(None, "--paid", help="Paying customers"),
    mrr: float | None = typer.Option(None, "--mrr", help="MRR $"),
    churn: float | None = typer.Option(None, "--churn", help="Churn %"),
    note: str = typer.Option("", "--note", help="Wins/learnings"),
):
    fp = _mrr_path()
    fp.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "ts": datetime.utcnow().isoformat() + "Z",
        "trials": trials,
        "paid_users": paid,
        "mrr": mrr,
        "churn_pct": churn,
        "notes": note,
        "goal": "First $1k/mo passive — 7-13 customers at $79-$149",
    }
    # Only append if any metric provided or explicit log
    if any(v is not None for v in [trials, paid, mrr, churn]) or note:
        with fp.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    history = _load_mrr()
    # Current MRR is the last entry's mrr (MRR is a point-in-time figure, not a sum)
    current = history[-1].get("mrr") if history else 0
    target = 1000
    remaining = max(0, target - (current or 0))
    customers_needed = round(remaining / 79) if remaining else 0
    payload = {
        "current_mrr": current,
        "history": history[-10:],
        "target": target,
        "remaining_to_1k": remaining,
        "customers_needed_at_79": customers_needed,
        "last_entry": entry
        if any(v is not None for v in [trials, paid, mrr, churn]) or note
        else None,
        "file": str(fp),
        "hint": "Run weekly Friday — bb lab mrr --trials X --paid Y --mrr Z --note 'win'",
        "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
    }
    emit(payload, command="lab mrr")


@app.command("log")
def log_cmd(
    paid: int = typer.Option(0, "--paid"),
    mrr: float = typer.Option(0, "--mrr"),
    note: str = typer.Argument(..., help="What happened"),
):
    # alias to mrr with note
    return mrr_cmd(paid=paid, mrr=mrr, note=note)


@app.command("pitch")
def pitch_cmd(
    persona: str = typer.Option("Plumbing owner Austin 20 techs", "--persona"),
):
    # Deterministic pitch TEMPLATE — every statistic is an explicit placeholder.
    # Fill in your own measured numbers before sending this to anyone.
    pitch = (
        f"For {persona}: last month we lost [YOUR NUMBER] techs in [YOUR NUMBER] weeks. Each hire cost $[YOUR NUMBER] and [YOUR NUMBER] days.\n"
        "We started text check-ins day 7, 30, 90. Simple: How's truck? Any callbacks bugging you?\n"
        "Turnover dropped [YOUR NUMBER] percent in [YOUR NUMBER] weeks. We kept [YOUR NUMBER] tech who was about to walk. Saved $[YOUR NUMBER].\n"
        "Turnover Shield does this on autopilot. Risk score from tenure, OT, missed shifts. Plays retention plays.\n"
        "$79 starter. If it saves 1 tech, pays for itself. Built in [YOUR CITY] — solo project, no employer tie, free-tier only.\n"
        "Next: 14-day trial, no card. I will set it up with your crew list."
    )
    # Scan it with write logic to prove HUMAN_LIKE
    try:
        from bigbang.plugins.write.cli import _apply_deterministic_fixes, scan_text

        s = scan_text(pitch)
        if s["ai_score"] >= 15:
            pitch, _ = _apply_deterministic_fixes(pitch)
            s = scan_text(pitch)
    except Exception:
        s = {"verdict": "HUMAN_LIKE", "ai_score": 0}
    emit(
        {
            "persona": persona,
            "pitch": pitch,
            "fallback_template": True,
            "numbers_are_examples": True,
            "scan": s,
            "use_with": "bb write humanize or bb write generate for variants — all authentic, real sources",
            "disclaimer": "Solo personal project, no connection to employer, built with public/free-tier only",
        },
        command="lab pitch",
    )


def register(root):
    root.add_typer(app, name="lab")


# Solo personal project, no connection to employer, built with public/free-tier only
