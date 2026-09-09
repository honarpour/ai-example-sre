import type {
  AskFollowUpResponse,
  CreateAlertRequest,
  Investigation,
  ScenarioSummary,
  SubmitFeedbackRequest,
} from "./types"

const BASE = "/api"

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { "Content-Type": "application/json" },
    ...init,
  })
  if (!res.ok) {
    const body = await res.text().catch(() => "")
    throw new ApiError(res.status, body || `${res.status} ${res.statusText}`)
  }
  return res.json() as Promise<T>
}

export const api = {
  health: () => request<{ status: string }>("/health"),

  listScenarios: () => request<ScenarioSummary[]>("/scenarios"),

  createAlert: (body: CreateAlertRequest) =>
    request<Investigation>("/alerts", { method: "POST", body: JSON.stringify(body) }),

  listInvestigations: () => request<Investigation[]>("/investigations"),

  getInvestigation: (id: string) => request<Investigation>(`/investigations/${id}`),

  streamUrl: (id: string) => `${BASE}/investigations/${id}/stream`,

  submitFeedback: (investigationId: string, feedback: SubmitFeedbackRequest) =>
    request<Investigation>(`/investigations/${investigationId}/feedback`, {
      method: "POST",
      body: JSON.stringify(feedback),
    }),

  askFollowUp: (investigationId: string, question: string) =>
    request<AskFollowUpResponse>(`/investigations/${investigationId}/ask`, {
      method: "POST",
      body: JSON.stringify({ question }),
    }),
}
