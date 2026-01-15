// GET /health placeholder
export async function healthHandler(req: any, res: any) {
  res.send({ status: 'ok' });
}
