export function makeConfirmationCode(prefix: string = 'DEMO'): string {
  // Simple deterministic-ish code: DEMO-XXXXXX
  const chars = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';
  let s = '';
  for (let i = 0; i < 6; i++) {
    s += chars[Math.floor(Math.random() * chars.length)];
  }
  return `${prefix}-${s}`;
}
