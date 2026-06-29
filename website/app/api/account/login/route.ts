import { exportProfile, loginUser } from "@/lib/account";
import { corsHeaders, error, json } from "@/lib/http";

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const user = await loginUser(body.email, body.password);
    return json(exportProfile(user));
  } catch {
    return error("Invalid email or password", 401);
  }
}
