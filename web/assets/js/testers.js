(function () {
  const form = document.querySelector("#tester-feedback-form");
  const emailButton = document.querySelector("#tester-email-btn");
  const status = document.querySelector("#tester-feedback-status");

  const contact = "arjunkshah21.work@gmail.com";
  const endpoint = "/api/testers/feedback";

  function readFeedback() {
    const data = new FormData(form);
    return {
      name: String(data.get("name") || "").trim(),
      email: String(data.get("email") || "").trim(),
      project: String(data.get("project") || "").trim(),
      feedback: String(data.get("feedback") || "").trim(),
    };
  }

  function validate(values) {
    if (!values.name || !values.email || !values.feedback) {
      if (status) status.textContent = "Name, email, and feedback are required.";
      return false;
    }

    if (!values.email.includes("@")) {
      if (status) status.textContent = "Please enter a real email address.";
      return false;
    }

    return true;
  }

  function openEmail(values) {
    const subject = `Creation tester feedback: ${values.project || values.name}`;

    const body = [
      "New Creation tester feedback",
      "",
      `Name: ${values.name || "n/a"}`,
      `Email: ${values.email || "n/a"}`,
      `Project: ${values.project || "n/a"}`,
      "",
      "Feedback:",
      values.feedback || "n/a",
      "",
      "Source: https://creation.dev/testers",
    ].join("\n");

    const url = `mailto:${contact}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
    window.location.href = url;

    if (status) status.textContent = "Opened your email app with the feedback pre-filled.";
  }

  async function submitFeedback(values) {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify(values),
    });

    const data = await response.json().catch(() => ({}));

    if (!response.ok) {
      throw new Error(data.detail || "Could not send feedback.");
    }

    return data;
  }

  form?.addEventListener("submit", async (event) => {
    event.preventDefault();

    const values = readFeedback();
    if (!validate(values)) return;

    const submitButton = form.querySelector('button[type="submit"]');

    if (submitButton) submitButton.disabled = true;
    if (status) status.textContent = "Sending feedback...";

    try {
      await submitFeedback(values);
      if (status) status.textContent = "Feedback sent. Thank you for testing Creation.";
      form.reset();
    } catch (error) {
      if (status) status.textContent = error.message || "Could not send feedback.";
    } finally {
      if (submitButton) submitButton.disabled = false;
    }
  });

  emailButton?.addEventListener("click", () => {
    const values = readFeedback();
    if (validate(values)) openEmail(values);
  });
})();