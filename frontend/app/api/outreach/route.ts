import { NextRequest } from "next/server";
import { proxyToPython } from "../_proxy";

export async function POST(req: NextRequest) {
  return proxyToPython(req, "/api/py/outreach", "/api/outreach", "POST");
}
