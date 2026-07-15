import typer
from bigbang.core.output import emit
app = typer.Typer(name="tennis", help="Tennis DINOv3 serve coach", no_args_is_help=True)
@app.command("serve")
def serve(video: str = typer.Argument(None)):
    emit({"message": f"Tennis DINOv3 ExecuTorch ConvNeXt-Tiny 2MB ONNX WASM - analyze {video or 'live cam'}"})
def register(root):
    root.add_typer(app, name="tennis")
