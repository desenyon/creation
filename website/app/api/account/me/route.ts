import { authUserFromHeaders, exportProfile } from "@/lib/account";
import { corsHeaders, error, json } from "@/lib/http";

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function GET(req: Request) {
  const user = await authUserFromHeaders(
    req.headers.get("authorization") ?? "",
    req.headers.get("x-api-key") ?? ""
  );
  if (!user) return error("Invalid API key", 401);
  return json(exportProfile(user));
}
