import { json } from "@/lib/http";

export async function GET() {
  return json({
    ok: true,
    service: "creation-cloud",
    version: "0.6.0",
    features: ["account", "forge", "credentials"],
    kv: Boolean(process.env.KV_REST_API_URL),
    forge_backend: Boolean(process.env.OPENAI_API_KEY) ? "openai" : "heuristic",
  });
}
