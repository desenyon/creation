import { authUserFromHeaders, exportProfile, updateCredentials } from "@/lib/account";
import { corsHeaders, error, json } from "@/lib/http";

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function PUT(req: Request) {
  const user = await authUserFromHeaders(
    req.headers.get("authorization") ?? "",
    req.headers.get("x-api-key") ?? ""
  );
  if (!user) return error("Invalid API key", 401);
  const body = await req.json();
  const updated = await updateCredentials(user, {
    github_token: body.github_token ?? user.github_token,
    linear_api_key: body.linear_api_key ?? user.linear_api_key,
    linear_team_id: body.linear_team_id ?? user.linear_team_id,
    notify_email: body.notify_email ?? user.notify_email,
  });
  return json(exportProfile(updated));
}
