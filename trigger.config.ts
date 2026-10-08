import { defineConfig } from "@trigger.dev/sdk";
import { pythonExtension } from "@trigger.dev/python/extension";
import { syncEnvVars } from "@trigger.dev/build/extensions/core";

declare const process: { env: Record<string, string | undefined> };

export default defineConfig({
  project: "proj_xobepqqfeszbelrhhxju",
  dirs: ["./trigger"],
  maxDuration: 300,
  retries: { enabledInDev: false, default: { maxAttempts: 1 } },
  build: {
    extensions: [
      syncEnvVars(async () => {
        const url = process.env.SUPABASE_URL;
        const secretKey = process.env.SUPABASE_SECRET_KEY;
        if (!url || !secretKey) {
          throw new Error("SUPABASE_URL and SUPABASE_SECRET_KEY are required for deployment");
        }
        const variables = [
          { name: "SUPABASE_URL", value: url },
          { name: "SUPABASE_SECRET_KEY", value: secretKey, isSecret: true },
        ];
        for (const name of [
          "SMTP_HOST",
          "SMTP_PORT",
          "SMTP_USER",
          "REMINDER_FROM_EMAIL",
          "REMINDER_TO_EMAIL",
          "NEW_CARDS_PER_DAY",
          "MAX_REVIEWS_PER_DAY",
        ]) {
          const value = process.env[name];
          if (value) variables.push({ name, value });
        }
        if (process.env.SMTP_PASSWORD) {
          variables.push({ name: "SMTP_PASSWORD", value: process.env.SMTP_PASSWORD, isSecret: true });
        }
        return variables;
      }),
      pythonExtension({
        scripts: ["./src/**/*.py"],
        requirementsFile: "./requirements.txt",
      }),
    ],
  },
});
