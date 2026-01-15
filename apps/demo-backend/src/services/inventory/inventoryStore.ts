import { SearchTeeTimesRequest, TeeTimeOption } from "@golf/shared-schemas";

type InventoryKey = string; // `${course_id}|${date}`

export class InventoryStore {
  private byDay: Map<InventoryKey, TeeTimeOption[]> = new Map();

  constructor() {}

  seedDay(course_id: string, date: string) {
    const key: InventoryKey = `${course_id}|${date}`;

    // deterministic, demo-friendly times
    const starts = ["08:30", "09:10", "09:50", "10:30", "11:10"];
    const options: TeeTimeOption[] = starts.map((start, idx) => ({
      slot_id: `slot_${course_id}_${date}_${start.replace(":", "")}_${idx}`,
      start_local: start,
      duration_min: 240,
      players_allowed: [1, 2, 3, 4],
      price: {
        currency: "USD",
        amount_total: 0,
        amount_per_player: 0,
      },
      constraints: {
        cart_required: false,
        cancellation_policy: "Cancel >= 24h to avoid fee",
      },
    }));

    this.byDay.set(key, options);
  }

  ensureSeeded(course_id: string, date: string) {
    const key: InventoryKey = `${course_id}|${date}`;
    if (!this.byDay.has(key)) {
      this.seedDay(course_id, date);
    }
  }

  search(req: SearchTeeTimesRequest): TeeTimeOption[] {
    this.ensureSeeded(req.course_id, req.date);

    const key: InventoryKey = `${req.course_id}|${req.date}`;
    const all = this.byDay.get(key) ?? [];

    const filtered = all
      .filter((o) => o.players_allowed.includes(req.players))
      .filter((o) => o.start_local >= req.time_window.start_local && o.start_local <= req.time_window.end_local)
      .slice(0, req.max_results);

    // Fill in deterministic pricing based on time + players
    return filtered.map((o) => {
      const base = o.start_local < "10:00" ? 160 : 175;
      return {
        ...o,
        price: {
          currency: "USD",
          amount_per_player: base,
          amount_total: base * req.players,
        },
      };
    });
  }

  getSlotById(slot_id: string): { course_id: string; date: string; option: TeeTimeOption } | null {
    for (const [key, options] of this.byDay.entries()) {
      const found = options.find((o) => o.slot_id === slot_id);
      if (found) {
        const [course_id, date] = key.split("|");
        return { course_id, date, option: found };
      }
    }
    return null;
  }

  // For demo: pretend booking removes the slot
  reserveSlot(slot_id: string): boolean {
    for (const [key, options] of this.byDay.entries()) {
      const idx = options.findIndex((o) => o.slot_id === slot_id);
      if (idx >= 0) {
        options.splice(idx, 1);
        this.byDay.set(key, options);
        return true;
      }
    }
    return false;
  }
}

