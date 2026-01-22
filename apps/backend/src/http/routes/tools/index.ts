import type { FastifyInstance } from "fastify";
import { InventoryStore } from "../../../services/inventory/inventoryStore.js";
import { ReservationStore } from "../../../services/reservations/reservationStore.js";
import { registerSearchTeeTimes } from "./searchTeeTimes.js";
import { registerBookTeeTime } from "./bookTeeTime.js";
import { registerModifyReservation } from "./modifyReservation.js";
import { registerCancelReservation } from "./cancelReservation.js";
import { registerSendSmsConfirmation } from "./sendSmsConfirmation.js";

type Deps = {
  inventory: InventoryStore;
  reservations: ReservationStore;
};

export function registerToolRoutes(app: FastifyInstance, deps: Deps) {
  registerSearchTeeTimes(app, deps);
  registerBookTeeTime(app, deps);
  registerModifyReservation(app, deps);
  registerCancelReservation(app, deps);
  registerSendSmsConfirmation(app, deps);
}
