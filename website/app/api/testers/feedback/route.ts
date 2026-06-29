import { error, json } from "@/lib/http";

export async function POST(req: Request) {
  const body = await req.json();
  const { name, email, feedback, project } = body;
  if (!name?.trim() || !email?.trim() || !feedback?.trim()) {
    return error("Name, email, and feedback are required", 400);
  }

  const to = process.env.TESTER_FEEDBACK_TO || process.env.RESEND_TO;
  const resendKey = process.env.RESEND_API_KEY;

  if (resendKey && to) {
    try {
      const res = await fetch("https://api.resend.com/emails", {
        method: "POST",
        headers: {
          Authorization: `Bearer ${resendKey}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          from: process.env.RESEND_FROM || "Creation <onboarding@resend.dev>",
          to: [to],
          subject: `Creation tester feedback: ${project || name}`,
          text: [
            "New Creation tester feedback",
            "",
            `Name: ${name}`,
            `Email: ${email}`,
            `Project: ${project || "n/a"}`,
            "",
            feedback,
          ].join("\n"),
        }),
      });
      if (res.ok) return json({ ok: true, provider: "resend" });
    } catch {
      /* fall through */
    }
  }

  console.log("[tester-feedback]", { name, email, project, feedback: feedback.slice(0, 500) });
  return json({ ok: true, provider: "log" });
}
