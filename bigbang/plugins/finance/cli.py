import typer
from pathlib import Path
import json
from rich.console import Console
from bigbang.core.output import emit, emit_table
from bigbang.core.context import settings

app = typer.Typer(name="finance", help="Finance — Betterment/Schwab/USAA/Chase/Fidelity (manual)", no_args_is_help=True)
console = Console()

@app.command("snapshot")
def snapshot(net: bool = typer.Option(False, help="show net worth")):
    data = {
        "source": "MEMORY.md cached 2026-07-11",
        "betterment": 371255.68,
        "usaa": 66494.53,
        "schwab": 536111.42,
        "fidelity": 1274471.95,
        "chase_cc": 1455.26,
        "cap_one_cc": 5682.58,
        "emergency_fund": 136500.93,
        "monthly_burn": settings.monthly_burn,
        "emergency_target": settings.emergency_target,
        "note": "Fidelity manual Mon 9am CT, never Plaid"
    }
    if net:
        vested = data["betterment"] + data["usaa"] + data["schwab"] + data["fidelity"]
        data["vested_gross"] = vested
        data["net_after_cc"] = vested - data["chase_cc"] - data["cap_one_cc"]
    console.print(f"[bold]Vested: ${data.get('vested_gross', 2248333):,.2f} | EF: ${data['emergency_fund']:,.2f} | Burn: ${data['monthly_burn']}/mo")
    emit(data)

@app.command("emergency-tax-lift")
def emergency_tax_lift():
    base = Path.home() / "workspace" / "your_files" / "emergency-fund-tax-lift"
    pdf = base / "Emergency_Fund_Tax_Lift_Report.pdf"
    emit({"message": f"Report at {pdf}", "exists": pdf.exists(), "path": str(pdf)})

def register(root):
    root.add_typer(app, name="finance")
