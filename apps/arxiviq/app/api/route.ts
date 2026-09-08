import { NextResponse } from "next/server";

export async function GET() {
  return NextResponse.json(
    {
      ok: false,
      available: false,
      measured: false,
      source: "unavailable",
      provenance: "not_measured",
      error: "Model serving and parity verification are not connected on this deployment.",
    },
    { status: 503 }
  );
}
