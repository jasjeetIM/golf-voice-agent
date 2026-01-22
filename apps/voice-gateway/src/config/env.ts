import { z } from "zod";

export const EnvSchema = z.object({
  VOICE_GATEWAY_PORT: z.coerce.number().default(8080),
  PUBLIC_BASE_URL: z.string().default("http://localhost:8080"),

  BACKEND_URL: z.string().default("http://localhost:6060"),
  BACKEND_API_KEY: z.string().default("dev_backend_key"),

  OPENAI_API_KEY: z.string().min(1, "OPENAI_API_KEY is required"),

  LOG_LEVEL: z.string().default("info"),
});

export type Env = z.infer<typeof EnvSchema>;

export function loadEnv(processEnv: NodeJS.ProcessEnv): Env {
  return EnvSchema.parse(processEnv);
}
