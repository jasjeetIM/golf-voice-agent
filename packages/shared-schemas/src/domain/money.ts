// Domain types placeholder
import { z } from "zod";

export const MoneySchema = z.object({
    currency: z.string().min(3).max(3), // USD
    amount_total: z.number().nonnegative(),
    amount_per_player: z.number().nonnegative(),
});

export type Money = z.infer<typeof MoneySchema>;
