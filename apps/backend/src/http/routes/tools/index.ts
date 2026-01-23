import type { FastifyInstance } from "fastify";
import { InventoryStore } from "../../../services/inventory/inventoryStore.js";
import { ReservationStore } from "../../../services/reservations/reservationStore.js";
import { registerSearchTeeTimes } from "./searchTeeTimes.js";
import { registerBookTeeTime } from "./bookTeeTime.js";
import { registerModifyReservation } from "./modifyReservation.js";
import { registerCancelReservation } from "./cancelReservation.js";
import { registerSendSmsConfirmation } from "./sendSmsConfirmation.js";
import { registerGetReservationDetails } from "./getReservationDetails.js";
import { registerListAvailableSlots } from "./listAvailableSlots.js";
import { registerQuoteReservationChange } from "./quoteReservationChange.js";
import { registerCheckSlotCapacity } from "./checkSlotCapacity.js";

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
  registerGetReservationDetails(app, deps);
  registerListAvailableSlots(app, deps);
  registerQuoteReservationChange(app, deps);
  registerCheckSlotCapacity(app, deps);
}
