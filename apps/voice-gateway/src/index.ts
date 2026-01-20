import dotenv from "dotenv";
import { loadEnv } from "./config/env";
import { createHttpServer } from "./http/server";
import { createWsServer } from "./ws/server";

dotenv.config();

async function main() {
  const env = loadEnv(process.env);
  const app = await createHttpServer(env);

  await app.listen({ host: "0.0.0.0", port: env.VOICE_GATEWAY_PORT });
  createWsServer(app.server);

  app.log.info(
    {
      port: env.VOICE_GATEWAY_PORT,
      inboundWebhook: "/twilio/inbound",
      mediaStream: "/twilio/stream",
    },
    "voice-gateway ready"
  );
}

main().catch((err) => {
  // eslint-disable-next-line no-console
  console.error(err);
  process.exit(1);
});
