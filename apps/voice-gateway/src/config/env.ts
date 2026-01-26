import { z } from 'zod';

const EnvSchema = z.object({
  PUBLIC_HOST: z.string().default('localhost'),
  PUBLIC_PROTOCOL: z.enum(['http', 'https']).default('http'),
  VOICE_GATEWAY_PORT: z.coerce.number().default(8080),
  BACKEND_PORT: z.coerce.number().default(8081),
  PUBLIC_BASE_URL: z.string().optional(),
  BACKEND_URL: z.string().optional(),
  OPENAI_API_KEY: z.string().default(''),
  BACKEND_API_KEY: z.string().default('be_api_key'),
  LOG_LEVEL: z.string().default('info'),
});

export type Env = z.infer<typeof EnvSchema> & {
  public_voice_url: string;
  backend_url: string;
};

export function loadEnv(processEnv: NodeJS.ProcessEnv): Env {
  const parsed = EnvSchema.parse(processEnv);
  const public_voice_url =
    parsed.PUBLIC_BASE_URL ||
    `${parsed.PUBLIC_PROTOCOL}://${parsed.PUBLIC_HOST}:${parsed.VOICE_GATEWAY_PORT}`;
  const backend_url =
    parsed.BACKEND_URL ||
    `${parsed.PUBLIC_PROTOCOL}://${parsed.PUBLIC_HOST}:${parsed.BACKEND_PORT}`;
  return { ...parsed, public_voice_url, backend_url };
}
