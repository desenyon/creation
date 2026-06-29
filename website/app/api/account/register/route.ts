import { exportProfile, registerUser } from "@/lib/account";
import { corsHeaders, error, json } from "@/lib/http";

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function POST(req: Request) {
  try {
    const body = await req.json();
    const user = await registerUser(body.email, body.password);
    return json(exportProfile(user), 201);
  } catch (e) {
    return error(e instanceof Error ? e.message : "Registration failed", 400);
  }
}
