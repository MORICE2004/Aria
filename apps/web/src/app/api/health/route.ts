import { NextResponse } from "next/server";

export const runtime = "edge";

export async function GET() {
  return NextResponse.json({
    status: "ok",
    service: "aria-web",
    tier: "vercel-edge",
    version: "0.3.0",
    timestamp: new Date().toISOString(),
  });
}
