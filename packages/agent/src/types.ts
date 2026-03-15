export interface StepContext<TInput = unknown> {
  input: TInput;
  runId: string;
}

export interface Step<TInput = unknown, TOutput = unknown> {
  name: string;
  run: (ctx: StepContext<TInput>) => Promise<TOutput>;
}

export interface PipelineConfig {
  name: string;
  steps: Step[];
}
