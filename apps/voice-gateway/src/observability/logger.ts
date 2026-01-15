import pino from "pino";

export function createLogger(level: string) {
  return pino({
    level,
    redact: {
      // If later you log request headers/body, redact sensitive parts
      paths: ["req.headers.authorization"],
      remove: true,
    },
  });
}
