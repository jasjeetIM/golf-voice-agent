import { z } from "zod";

export const EnvSchema = z.object({
  VOICE_GATEWAY_PORT: z.coerce.number().default(8080),
  PUBLIC_BASE_URL: z.string().default("http://localhost:8080"),

  DEMO_BACKEND_URL: z.string().default("http://localhost:8081"),
  DEMO_API_KEY: z.string().default("dev_demo_key"),

  LOG_LEVEL: z.string().default("info"),
});

export type Env = z.infer<typeof EnvSchema>;

export function loadEnv(processEnv: NodeJS.ProcessEnv): Env {
  return EnvSchema.parse(processEnv);
}
