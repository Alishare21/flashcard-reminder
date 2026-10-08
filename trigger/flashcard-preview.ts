import { task } from "@trigger.dev/sdk";
import { python } from "@trigger.dev/python";
import fixture from "../example_data.json" with { type: "json" };

// Development-only test. It uses synthetic fixtures and sends no email.
export const flashcardPreview = task({
  id: "flashcard-preview",
  run: async () => {
    const result = await python.runScript("./src/trigger_preview.py", [JSON.stringify(fixture)]);
    if (result.exitCode !== 0) {
      throw new Error(`Python preview failed with exit code ${result.exitCode}`);
    }
    const summary = JSON.parse(result.stdout.trim());
    return summary;
  },
});
