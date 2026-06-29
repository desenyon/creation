import { authUserFromHeaders, deductCredits } from "@/lib/account";
import { forgeCompletion } from "@/lib/forge";
import { corsHeaders, error, json } from "@/lib/http";

export async function OPTIONS() {
  return new Response(null, { status: 204, headers: corsHeaders() });
}

export async function POST(req: Request) {
  const user = await authUserFromHeaders(
    req.headers.get("authorization") ?? "",
    req.headers.get("x-api-key") ?? ""
  );
  if (!user) return error("Invalid API key — run creation login", 401);

  const body = await req.json();
  const messages = body.messages ?? [];
  const maxTokens = body.max_tokens ?? 800;
  const model = body.model ?? "creation-forge-v1";
  const units = Math.max(25, JSON.stringify(messages).length / 8);
  await deductCredits(user.id, Math.floor(units), "forge");

  const content = await forgeCompletion(messages, maxTokens);
  return json({
    id: "forge-cloud",
    object: "chat.completion",
    model,
    choices: [{ index: 0, message: { role: "assistant", content }, finish_reason: "stop" }],
  });
}
