import type { PipelineConfig, Step } from "./types.js";

export class Pipeline {
  private readonly name: string;
  private readonly steps: Step[];

  constructor(config: PipelineConfig) {
    this.name = config.name;
    this.steps = config.steps;
  }

  async run(input: unknown): Promise<unknown> {
    const runId = crypto.randomUUID();
    let current = input;

    for (const step of this.steps) {
      current = await step.run({ input: current, runId });
    }

    return current;
  }
}
