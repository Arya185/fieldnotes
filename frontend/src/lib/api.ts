import type {
  ArtifactCard,
  AskEvent,
  AskRequest,
  HealthResponse,
  IndexAcceptedResponse,
  IndexEvent,
  IndexRequest,
  NotebookResponse,
  QuizAnswerRequest,
  QuizEvent,
  QuizRequest,
  SourceResponse,
} from "../types";

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? "";

interface ErrorPayload {
  code?: string;
  message?: string;
}

export class ApiError extends Error {
  status: number;
  code?: string;
  body?: unknown;

  constructor(message: string, status: number, code?: string, body?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
    this.body = body;
  }
}

export function isWorkspaceNotFoundError(error: unknown): error is ApiError {
  return error instanceof ApiError && error.status === 404 && error.code === "WORKSPACE_NOT_FOUND";
}

async function buildApiError(response: Response): Promise<ApiError> {
  let body: unknown;
  let payload: ErrorPayload | undefined;

  try {
    body = await response.json();
    if (body && typeof body === "object") {
      payload = body as ErrorPayload;
    }
  } catch {
    try {
      body = await response.text();
    } catch {
      body = undefined;
    }
  }

  return new ApiError(
    payload?.message || `${response.status} ${response.statusText}`,
    response.status,
    payload?.code,
    body,
  );
}

async function requestJson<T>(input: RequestInfo, init?: RequestInit): Promise<T> {
  const response = await fetch(input, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return (await response.json()) as T;
}

export async function postIndex(payload: IndexRequest): Promise<IndexAcceptedResponse> {
  return requestJson<IndexAcceptedResponse>(`${API_BASE}/index`, {
    method: "POST",
    body: JSON.stringify(payload),
  });
}

export async function getHealth(): Promise<HealthResponse> {
  return requestJson<HealthResponse>(`${API_BASE}/health`);
}

export async function getNotebook(workspaceId: string): Promise<NotebookResponse> {
  return requestJson<NotebookResponse>(
    `${API_BASE}/notebook?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
}

export async function getSource(
  workspaceId: string,
  fileId: string,
  locator: string,
): Promise<SourceResponse> {
  return requestJson<SourceResponse>(
    `${API_BASE}/source/${encodeURIComponent(fileId)}/${encodeURIComponent(locator)}?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
}

export async function fetchArtifact(
  workspaceId: string,
  artifactId: string,
): Promise<Response> {
  const response = await fetch(
    `${API_BASE}/artifact/${encodeURIComponent(artifactId)}?workspace_id=${encodeURIComponent(workspaceId)}`,
  );
  if (!response.ok) {
    throw await buildApiError(response);
  }
  return response;
}

export async function openAskStream(
  payload: AskRequest,
  onEvent: (event: AskEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await consumeSse(`${API_BASE}/ask`, payload, onEvent, signal);
}

export async function openQuizStartStream(
  payload: QuizRequest,
  onEvent: (event: QuizEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await consumeSse(`${API_BASE}/quiz/start`, payload, onEvent, signal);
}

export async function openQuizAnswerStream(
  payload: QuizAnswerRequest,
  onEvent: (event: QuizEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  await consumeSse(`${API_BASE}/quiz/answer`, payload, onEvent, signal);
}

export async function openIndexEvents(
  eventsPath: string,
  onEvent: (event: IndexEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_BASE}${eventsPath}`, { signal });
  if (!response.ok || !response.body) {
    throw await buildApiError(response);
  }
  await readSse(response.body, (payload) => onEvent(payload as IndexEvent), signal);
}

async function consumeSse<TEvent>(
  endpoint: string,
  payload: unknown,
  onEvent: (event: TEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!response.ok || !response.body) {
    throw await buildApiError(response);
  }
  await readSse(response.body, (chunk) => onEvent(chunk as TEvent), signal);
}

export async function readSse(
  stream: ReadableStream<Uint8Array>,
  onPayload: (payload: unknown) => void,
  signal?: AbortSignal,
): Promise<void> {
  const reader = stream.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    if (signal?.aborted) {
      await reader.cancel();
      throw new DOMException("Aborted", "AbortError");
    }
    const { done, value } = await reader.read();
    if (done) {
      break;
    }
    buffer += decoder.decode(value, { stream: true });
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary).trim();
      buffer = buffer.slice(boundary + 2);
      if (block.startsWith("data: ")) {
        onPayload(JSON.parse(block.slice(6)));
      }
      boundary = buffer.indexOf("\n\n");
    }
  }
}

export interface ArtifactPayload {
  card: ArtifactCard;
  kind: "image" | "json" | "text";
  content: string;
}
