import { task } from "@trigger.dev/sdk";
import { python } from "@trigger.dev/python";

// Manual Development check only. Reads folder metadata and counts; sends no email.
export const flashcardDriveCheck = task({
  id: "flashcard-drive-check",
  run: async () => {
    const result = await python.runScript("./src/drive_probe.py");
    const output = JSON.parse(result.stdout.trim());
    if (result.exitCode !== 0 || output.status !== "passed") {
      throw new Error(`Drive check failed: ${output.reason ?? output.http_status ?? "unknown"}`);
    }
    return output;
  },
});
