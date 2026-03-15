export type AgentStatus = "idle" | "running" | "completed" | "failed";

export interface AgentRun {
  id:           string;
  status:       AgentStatus;
  input:        string;
  output?:      string;
  error?:       string;
  startedAt:    Date;
  completedAt?: Date;
}

export interface AgentStep {
  id:           string;
  runId:        string;
  name:         string;
  status:       AgentStatus;
  input:        unknown;
  output?:      unknown;
  startedAt:    Date;
  completedAt?: Date;
}
