import { schedules } from "@trigger.dev/sdk";
import { python } from "@trigger.dev/python";

function dateInTimezone(timestamp: Date, timezone: string): string {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: timezone,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
  }).formatToParts(timestamp);
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]));
  return `${values.year}-${values.month}-${values.day}`;
}

// Production daily reminder. Supabase is the private source of due counts.
export const flashcardDaily = schedules.task({
  id: "flashcard-daily",
  cron: {
    pattern: "0 8 * * *",
    timezone: "Asia/Calcutta",
    window: "0m",
    environments: ["PRODUCTION"],
  },
  queue: { concurrencyLimit: 1 },
  retry: { maxAttempts: 1 },
  run: async (payload) => {
    const today = dateInTimezone(payload.timestamp, payload.timezone);
    const result = await python.runScript("./src/cloud_reminder_agent.py", [today, "--send"]);
    const output = JSON.parse(result.stdout.trim());
    if (result.exitCode !== 0 || output.status === "failed") {
      throw new Error(`Cloud reminder failed: ${output.reason ?? `exit ${result.exitCode}`}`);
    }
    return output;
  },
});
