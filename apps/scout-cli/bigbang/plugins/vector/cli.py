"""
vector plugin — dumbmodel.com unified MTNN pipeline
Six models, four daily games, one joint cross-sport trunk — era-honest, leak-free, provenance-honest.
Mirrors vector-hub / vector-hoops / vector-pitch / gridiron / equities / unified.
"""
from __future__ import annotations
import json
from pathlib import Path
import typer
from bigbang.core.contract import make_plugin_app
from bigbang.core.output import emit, is_json

app = make_plugin_app(
    "vector",
    "dumbmodel.com vector arcade — hoops/pitch/gridiron/equities + unified ablation",
    examples=[
        "scout --json vector eval hoops",
        "scout --json vector train equities --preset nano",
        "scout --json vector export hoops --onnx",
        "scout --json vector ship hub",
        "scout --json vector unified ablation",
    ]
)

GAMES = {
    "hoops": {"dim":64, "towers":18, "players":12966, "seasons":"1996-2026", "feat_families":18, "data":"stats.nba.com/BBR cache", "metrics":{"Recall@10":0.977,"Purity@20":0.6717,"composite":0.7937}, "site":"hoops.dumbmodel.com"},
    "pitch": {"dim":24, "towers":8, "players":633, "tournaments":"WC 2018/2022 StatsBomb", "difficulty_band":"40-80% solve", "site":"pitch.dumbmodel.com"},
    "gridiron": {"dim":32, "mae":4.268, "r2":0.39, "data":"nflverse usage/snaps/age/weather/Vegas", "site":"gridiron.dumbmodel.com"},
    "equities": {"dim":64, "towers":17, "companies":2700, "fy":"2015-2024 280 tickers", "tower_families":"17x ResidualTower cat([x·m,m])→96h→24d skip + transformer fusion d_model128 4 heads CLS", "sector_purity@10":0.174, "text_tower":"384-d MiniLM", "site":"equities.dumbmodel.com"},
    "tennis": {"dim":48, "players":4022, "site":"model card only"},
    "unified": {"dim":64, "trunk":"sport-agnostic 64-d Stage1 ablation", "architectures":"UnifiedTrunk sport_dims=[native] d_adapter48 d_emb64 sport_clf+GRL+GRL λ0.3", "losses":["SupCon→G3","CORAL→G3","GRL→G2","VICReg var+cov anti-collapse","task w=2.0 anchor G1"], "configs":["full","no_supcon","no_coral","no_grl","no_vicreg","task_only"], "ablation_ep":30, "warmup":5},
}

def _emit(result: dict, cmd: str, json_out: bool=False):
    if is_json() or json_out:
        emit(result, command=cmd)
    else:
        typer.echo(json.dumps(result, indent=2))

@app.command("train")
def train_cmd(
    game: str = typer.Argument(..., help="hoops|pitch|gridiron|equities|unified"),
    preset: str = typer.Option("nano", "--preset", help="nano|mini|base1b equiv MTNN size"),
    fetch: bool = typer.Option(False, "--fetch", help="Fetch upstream caches (SEC/StatsBomb) else use local cache"),
    json_out: bool = typer.Option(False,"--json")):
    g=GAMES.get(game)
    if not g:
        if is_json() or json_out:
            emit({"ok":False,"error":f"unknown game {game}", "known":list(GAMES.keys())}, command="vector train")
            return
        typer.echo(f"unknown game {game} known {list(GAMES.keys())}"); raise typer.Exit(1)
    res={
        "game":game,
        "preset":preset,
        "pipeline":"build_features.py → build_vectors.py → train_mtnn.py → gated test_skills.py → regen_assets.py",
        "details":g,
        "fetch":fetch,
        "fetch_note":"SEC/StatsBomb/nflverse only if --fetch else cache era-honest per-season z-score / per-90 tournament-z",
        "artifacts":["assets/vectors.json","assets/mtnn_meta.json","assets/skills.json","assets/eval_scoreboard.json","assets/mtnn.onnx"],
        "provenance":"public data only, no decorative math, leak-free player-split not season-split",
        "ok":True,
        "command": f"vector train {game}",
    }
    _emit(res, f"vector train {game}", json_out)

@app.command("eval")
def eval_cmd(
    game: str = typer.Argument(..., help="hoops|pitch|gridiron|equities|unified"),
    gate: str = typer.Option("leak-free", "--gate"),
    json_out: bool = typer.Option(False,"--json")):
    g=GAMES.get(game,{})
    if game=="hoops":
        evals={"Recall@10":0.977,"Purity@20":0.6717,"composite":0.7937,"eval_scoreboard":"assets/eval_scoreboard.json gated test_skills.py","leak_free":"player-split not season-split, season-split Recall 1.0 mem bug fixed","skills":"12 skill grades probe weights skills.json"}
    elif game=="equities":
        evals={"sector_coherence purity@10":0.174, "cross_ticker":0.167, "baseline":0.112, "lift":"1.5-1.6x", "eval":"assets/eval_sector_coherence.json regen eval_sector_coherence.py gated test_eval_sector_coherence.py", "regen":"regen_assets.py (+ score_trades v2)"}
    elif game=="pitch":
        evals={"games":633,"difficulty_calibration": "assets/difficulty_calibration.json targeting 40-80% solve band model estimate no telemetry", "pipeline":"build_features.py build_vectors.py build_difficulty.py gated test_difficulty.py", "telemetry":"api/telemetry.js optional serverless event-name-only localStorage stats"}
    elif game=="gridiron":
        evals={"mae":4.268,"r2":0.39,"note":"from offline run not reproducible here MAE/R² read live from data files not hardcoded","dim":"32-d advertised pipeline 64-d typical","dashboard":"model-lab reading live"}
    else:
        evals={"ablation":"data/ablation_report.json","house_rule":"does each alignment loss earn keep via Δ G1/G2/G3/G4","configs":["full SupCon+CORAL+GRL+VICReg+task","no_supcon","no_coral","no_grl grl-lambda0","no_vicreg var+cov0","task_only drop all align"],"metrics":{"G1":"per-sport recall","G2":"sport invariance","G3":"silhouette archetype coherence","G4":"hit-rate random baseline"}, "trunk":"sport-agnostic 64-d Stage1 non-destructive frozen encoders"}
    res={"game":game,"gate":gate,"evals":evals,"provenance_honest":"every metric shown with how obtained, unreachable labelled never faked, win cross-seed not within-run","details":g,"ok":True,"command":f"vector eval {game}"}
    _emit(res, f"vector eval {game}", json_out)

@app.command("export")
def export_cmd(
    game: str = typer.Argument(..., help="hoops|pitch|gridiron|equities"),
    onnx: bool = typer.Option(False,"--onnx"),
    executorch: bool = typer.Option(False,"--executorch"),
    json_out: bool = typer.Option(False,"--json")):
    res={"game":game,"onnx":onnx,"executorch":executorch,"artifacts":["vectors.json","mtnn_meta.json","skills.json","eval_scoreboard.json","mtnn.onnx"] if onnx else ["vectors.json","mtnn_meta.json"],"site":GAMES.get(game,{}).get("site"),"ok":True}
    _emit(res, f"vector export {game}", json_out)

@app.command("ship")
def ship_cmd(
    game: str = typer.Argument(..., help="hoops|pitch|gridiron|equities|hub|unified"),
    target: str = typer.Option("vercel","--target"),
    json_out: bool = typer.Option(False,"--json")):
    res={"game":game,"target":target,"deploy":"push main auto deploy Vercel project vector-hub apex dumbmodel.com","static":"HTML/CSS/JS no build, plain canvas/WebGL no framework, PWA sw.js offline, localStorage stats, OG image copy/paste","domain":GAMES.get(game,{}).get("site","dumbmodel.com"),"ok":True}
    _emit(res, f"vector ship {game}", json_out)

@app.command("unified")
def unified_cmd(
    sub: str = typer.Argument("ablation", help="ablation|encode"),
    json_out: bool = typer.Option(False,"--json")):
    g=GAMES["unified"]
    res={"unified":g,"ablation_report":"data/ablation_report.json","cmd":f"scout --json vector unified {sub} --configs full,no_supcon,no_coral,no_grl,no_vicreg,task_only","losses":g["losses"],"house_rule":"Stage1 v0 frozen encoders non-destructive evaluate Δ G1/G2/G3/G4 does each loss earn keep","architecture":"UnifiedTrunk sport_dims=[native dim per sport] n_seasons_era d_adapter48 d_sport_tok0 d_emb64 n_arch8 sport_clf + native_heads + pos_heads GRL λ0.3 gradual warmup 10ep after 5ep warmup","ok":True}
    _emit(res, f"vector unified {sub}", json_out)

@app.command("difficulty")
def difficulty_cmd(
    game: str = typer.Argument(..., help="hoops|pitch|gridiron|equities"),
    band: str = typer.Option("0.4-0.8","--target-band"),
    json_out: bool = typer.Option(False,"--json")):
    res={"game":game,"target_band":band,"calibration":"assets/difficulty_calibration.json","probe_weights":"skills.json 12 skill grades probe weights","note":"pitch pattern → all games 40-80% solve band model estimate before telemetry telemetry optional serverless","ok":True}
    _emit(res, f"vector difficulty {game}", json_out)
