import json
import os
import urllib.request


TO_EMAIL = "arjunkshah21.work@gmail.com"
FROM_EMAIL = os.environ.get("TESTER_FEEDBACK_FROM", "Creation Testers <onboarding@resend.dev>")
RESEND_API_KEY = os.environ.get("RESEND_API_KEY")


def _response(status_code, payload):
    return {
        "statusCode": status_code,
        "headers": {
            "Content-Type": "application/json",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "POST, OPTIONS",
            "Access-Control-Allow-Headers": "Content-Type",
        },
        "body": json.dumps(payload),
    }


def handler(request):
    if request.get("method") == "OPTIONS":
        return _response(200, {"ok": True})

    if request.get("method") != "POST":
        return _response(405, {"detail": "Method not allowed"})

    if not RESEND_API_KEY:
        return _response(500, {"detail": "Missing RESEND_API_KEY"})

    try:
        body = json.loads(request.get("body") or "{}")
    except json.JSONDecodeError:
        return _response(400, {"detail": "Invalid JSON"})

    name = str(body.get("name") or "").strip()
    email = str(body.get("email") or "").strip()
    project = str(body.get("project") or "").strip()
    feedback = str(body.get("feedback") or "").strip()

    if not name or not email or not feedback:
        return _response(400, {"detail": "Name, email, and feedback are required."})

    subject = f"New Creation tester feedback from {name}"

    text = "\n".join(
        [
            "New Creation tester feedback",
            "",
            f"Name: {name}",
            f"Email: {email}",
            f"Project: {project or 'n/a'}",
            "",
            "Feedback:",
            feedback,
            "",
            "Source: https://creation.dev/testers",
        ]
    )

    payload = {
        "from": FROM_EMAIL,
        "to": [TO_EMAIL],
        "reply_to": email,
        "subject": subject,
        "text": text,
    }

    req = urllib.request.Request(
        "https://api.resend.com/emails",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {RESEND_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=10) as res:
            resend_response = json.loads(res.read().decode("utf-8") or "{}")
    except Exception:
        return _response(500, {"detail": "Email provider failed to send feedback."})

    return _response(200, {"ok": True, "id": resend_response.get("id")})