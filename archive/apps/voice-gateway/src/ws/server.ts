import type { Server as HttpServer } from 'http';
import { WebSocketServer } from 'ws';
import { handleTwilioSession } from './twilio/twilioSession';

// Attaches WS handling for Twilio Media Streams to an existing HTTP server
export function createWsServer(httpServer: HttpServer) {
  const wss = new WebSocketServer({ noServer: true });

  httpServer.on('upgrade', (request, socket, head) => {
    if (!request.url?.startsWith('/twilio/stream')) {
      socket.destroy();
      return;
    }

    wss.handleUpgrade(request, socket, head, (ws) => {
      wss.emit('connection', ws, request);
    });
  });

  wss.on('connection', (ws, request) => {
    handleTwilioSession(ws, request);
  });

  return wss;
}
