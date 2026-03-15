import type { Step, StepContext } from "./types.js";

export function createStep<TInput = unknown, TOutput = unknown>(
  name: string,
  run: (ctx: StepContext<TInput>) => Promise<TOutput>
): Step<TInput, TOutput> {
  return { name, run };
}
