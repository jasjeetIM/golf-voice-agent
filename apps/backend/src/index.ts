import dotenv from "dotenv";
import { createHttpServer } from "./http/server.js";

dotenv.config();

createHttpServer().catch((e) => {
  // eslint-disable-next-line no-console
  console.error(e);
  process.exit(1);
});
