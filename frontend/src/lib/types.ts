import type { components } from "./api-types"

export type Alert = components["schemas"]["Alert"]
export type Investigation = components["schemas"]["Investigation"]
export type CreateAlertRequest = components["schemas"]["CreateAlertRequest"]
export type ScenarioSummary = components["schemas"]["ScenarioSummary"]
export type AgentStep = components["schemas"]["AgentStep"]
export type Evidence = components["schemas"]["Evidence"]
export type Hypothesis = components["schemas"]["Hypothesis"]
export type SuggestedAction = components["schemas"]["SuggestedAction"]
export type InvestigationFeedback = components["schemas"]["InvestigationFeedback"]
export type SubmitFeedbackRequest = components["schemas"]["SubmitFeedbackRequest"]
export type AskFollowUpRequest = components["schemas"]["AskFollowUpRequest"]
export type AskFollowUpResponse = components["schemas"]["AskFollowUpResponse"]

export type Severity = components["schemas"]["Severity"]
export type InvestigationStatus = components["schemas"]["InvestigationStatus"]
export type AgentStepStatus = components["schemas"]["AgentStepStatus"]
export type Confidence = components["schemas"]["Confidence"]
export type ActionKind = components["schemas"]["ActionKind"]
export type EvidenceKind = components["schemas"]["EvidenceKind"]

/** All our IDs are server-assigned and always present on anything the API
 * actually returns; the generated schema marks them optional only because
 * Pydantic's default_factory looks optional from the outside. */
export type WithId<T extends { id?: string }> = T & { id: string }
