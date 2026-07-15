import typer
from bigbang.core.output import emit
app = typer.Typer(name="tennis", help="Tennis DINOv3 serve coach", no_args_is_help=True)

@app.command("serve")
def serve(video: str = typer.Argument(None, help="video path or live")):
    emit({"action": "analyze serve", "video": video or "live cam", "model": "DINOv3 ExecuTorch ConvNeXt-Tiny 2MB ONNX WASM"})

def register(root):
    root.add_typer(app, name="tennis")
