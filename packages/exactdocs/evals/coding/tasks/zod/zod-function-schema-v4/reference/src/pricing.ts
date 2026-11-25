import { z } from "zod";

/** The price of `quantity` items at `unitPrice` cents with a `discount` from 0 to 1, in cents. */
function computeTotal(unitPrice: number, quantity: number, discount: number): number {
  return Math.round(unitPrice * quantity * (1 - discount));
}

/** `computeTotal`, its arguments and result validated. */
export const total = z
  .function({
    input: [z.number().int().nonnegative(), z.number().int().positive(), z.number().min(0).max(1)],
    output: z.number().int().nonnegative(),
  })
  .implement(computeTotal);
