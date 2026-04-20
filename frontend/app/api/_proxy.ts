import { NextRequest, NextResponse } from "next/server";

const NEA_API_KEY = process.env.NEA_API_KEY;

function buildTarget(pyPath: string, fastApiPath: string): string {
  // On Vercel: self-call to the Python function on the same deployment
  if (process.env.VERCEL_URL) {
    return `https://${process.env.VERCEL_URL}${pyPath}`;
  }
  // Local dev: forward to the FastAPI server
  const base = process.env.BACKEND_URL ?? "";
  if (!base) return "";
  return `${base}${fastApiPath}`;
}

export async function proxyToPython(
  req: NextRequest,
  pyPath: string,
  fastApiPath: string,
  method: string,
): Promise<NextResponse> {
  const target = buildTarget(pyPath, fastApiPath);
  if (!target) {
    return NextResponse.json({ detail: "BACKEND_URL is not configured" }, { status: 500 });
  }

  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (NEA_API_KEY) headers["X-NEA-Key"] = NEA_API_KEY;

  const body = method !== "GET" && method !== "DELETE" ? await req.text() : undefined;
  const upstream = await fetch(target, { method, headers, body });
  const text = await upstream.text();
  return new NextResponse(text, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
