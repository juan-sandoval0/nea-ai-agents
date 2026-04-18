import { NextRequest, NextResponse } from "next/server";

// Backend URL is env-driven so we can point at Railway today and Vercel/Databricks tomorrow.
// BACKEND_URL must be set in Vercel project settings (and in .env.local for dev).
const BACKEND_URL = process.env.BACKEND_URL ?? process.env.NEXT_PUBLIC_API_URL ?? "";
const NEA_API_KEY = process.env.NEA_API_KEY;

async function proxy(req: NextRequest, params: Promise<{ path: string[] }>, method: string) {
  if (!BACKEND_URL) {
    return NextResponse.json(
      { detail: "BACKEND_URL is not configured" },
      { status: 500 }
    );
  }

  const { path } = await params;
  const search = req.nextUrl.search;
  const target = `${BACKEND_URL}/api/${path.join("/")}${search}`;

  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  if (NEA_API_KEY) {
    headers["X-NEA-Key"] = NEA_API_KEY;
  }

  const body = method !== "GET" && method !== "DELETE"
    ? await req.text()
    : undefined;

  const upstream = await fetch(target, { method, headers, body });
  const text = await upstream.text();

  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}

export async function GET(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params, "GET");
}

export async function POST(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params, "POST");
}

export async function DELETE(req: NextRequest, { params }: { params: Promise<{ path: string[] }> }) {
  return proxy(req, params, "DELETE");
}
