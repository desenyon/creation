export function heuristicPlan(idea: string, turns = 8): string {
  const steps = [
    "Scaffold project layout and README",
    "Implement core feature path",
    "Add unit tests for critical paths",
    "Wire CLI or API entrypoint",
    "Polish error handling and docs",
    "Run QA and fix failures",
    "Prepare ship receipt and changelog",
  ];
  return steps
    .slice(0, Math.min(turns, steps.length))
    .map((s, i) => `${i + 1}. ${s} — ${idea.slice(0, 80)}`)
    .join("\n");
}

export function heuristicResponse(system: string, user: string): string {
  const sl = system.toLowerCase();
  if (sl.includes("json") && sl.includes("brand")) {
    const slug = user
      .toLowerCase()
      .replace(/[^a-z0-9]+/g, "-")
      .replace(/^-|-$/g, "")
      .slice(0, 18) || "creation-app";
    const name = slug
      .split("-")
      .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
      .join(" ");
    return JSON.stringify({
      product_name: name,
      repo_slug: slug,
      tagline: "Built with Creation",
      linear_project_name: name.slice(0, 48),
    });
  }
  if (sl.includes("json") && (sl.includes("turn") || sl.includes("follow"))) {
    return JSON.stringify({
      done: false,
      refresh_research: false,
      run_agent: true,
      run_qa: true,
      follow_up: "Continue the build — fix failing tests first.",
      subtasks: [],
      reason: "Forge heuristic route",
    });
  }
  if (sl.includes("json") && sl.includes("linear")) {
    return JSON.stringify({
      active_step_index: 1,
      step_states: [{ index: 1, state: "in_progress" }],
      new_issues: [],
      board_summary: "Forge board sync.",
    });
  }
  if (sl.includes("plan") || sl.includes("numbered")) {
    return heuristicPlan(user.slice(0, 500), 12);
  }
  if (sl.includes("email")) {
    return `Creation progress update\n\n${user.slice(-1200)}`;
  }
  return heuristicPlan(user.slice(0, 500), 8);
}

export async function forgeCompletion(
  messages: { role: string; content: string }[],
  maxTokens: number
): Promise<string> {
  const system = messages.find((m) => m.role === "system")?.content ?? "";
  const user = [...messages].reverse().find((m) => m.role === "user")?.content ?? "";
  const openaiKey = process.env.OPENAI_API_KEY?.trim();
  if (openaiKey) {
    try {
      const res = await fetch("https://api.openai.com/v1/chat/completions", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${openaiKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          model: process.env.CREATION_FORGE_MODEL || "gpt-4o-mini",
          messages,
          max_tokens: maxTokens,
        }),
      });
      if (res.ok) {
        const data = await res.json();
        return data.choices?.[0]?.message?.content ?? "";
      }
    } catch {
      /* fall through to heuristic */
    }
  }
  return heuristicResponse(system, user);
}
