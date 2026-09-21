/**
 * AICommandBar — controller for short-form AI editing requests.
 *
 * Accepts an editing request against the current draft and drives an
 * idle → requesting → proposal / error state machine. Its result is an
 * EditProposal that is exposed for validation and diff — the bar NEVER mutates
 * the Timeline directly. Applying a proposal is EXPLICIT: only ``apply()`` emits
 * the proposal (once) to ``onApply``, so the downstream validation/diff/apply
 * flow owns the actual change. An in-flight request is cancellable via an
 * AbortController; ``retry`` re-runs the last prompt.
 */

export interface EditProposal {
  commands: string[];
  summary: string;
}

export type AIRequestFn = (
  prompt: string,
  signal: AbortSignal,
) => Promise<EditProposal>;

export type AICommandBarStatus = "idle" | "requesting" | "proposal" | "error";

export interface AICommandBarState {
  status: AICommandBarStatus;
  proposal: EditProposal | null;
  error: string | null;
  applied: boolean;
}

export interface AICommandBarOptions {
  request: AIRequestFn;
  onApply?: (proposal: EditProposal) => void;
}

type Subscriber = (state: AICommandBarState) => void;

export class AICommandBar {
  private _status: AICommandBarStatus = "idle";
  private _proposal: EditProposal | null = null;
  private _error: string | null = null;
  private _applied = false;
  private _lastPrompt: string | null = null;
  private _controller: AbortController | null = null;
  private readonly _request: AIRequestFn;
  private readonly _onApply?: (proposal: EditProposal) => void;
  private readonly _subscribers = new Set<Subscriber>();

  constructor(options: AICommandBarOptions) {
    this._request = options.request;
    this._onApply = options.onApply;
  }

  get status(): AICommandBarStatus {
    return this._status;
  }

  get proposal(): EditProposal | null {
    return this._proposal;
  }

  get error(): string | null {
    return this._error;
  }

  get applied(): boolean {
    return this._applied;
  }

  subscribe(subscriber: Subscriber): () => void {
    this._subscribers.add(subscriber);
    return () => this._subscribers.delete(subscriber);
  }

  /** Submit an editing request; rejects an empty prompt without calling the AI. */
  async submit(prompt: string): Promise<void> {
    const trimmed = prompt.trim();
    if (trimmed.length === 0) {
      throw new Error("editing request must not be empty");
    }
    this._lastPrompt = trimmed;
    await this._run(trimmed);
  }

  /** Re-run the last submitted request (e.g. after an error). */
  async retry(): Promise<void> {
    if (this._lastPrompt === null) {
      throw new Error("nothing to retry");
    }
    await this._run(this._lastPrompt);
  }

  /** Cancel an in-flight request and return to idle. */
  cancel(): void {
    if (this._controller !== null) {
      this._controller.abort();
      this._controller = null;
    }
    this._proposal = null;
    this._error = null;
    this._set("idle");
  }

  /** Explicitly apply the current proposal exactly once via onApply. */
  apply(): void {
    if (this._proposal === null) {
      throw new Error("no proposal to apply");
    }
    if (this._applied) {
      return;
    }
    this._applied = true;
    this._onApply?.(this._proposal);
    this._emit();
  }

  /** Clear the current proposal back to idle without applying. */
  dismiss(): void {
    this._proposal = null;
    this._error = null;
    this._applied = false;
    this._set("idle");
  }

  private async _run(prompt: string): Promise<void> {
    const controller = new AbortController();
    this._controller = controller;
    this._proposal = null;
    this._error = null;
    this._applied = false;
    this._set("requesting");

    try {
      const proposal = await this._request(prompt, controller.signal);
      if (controller.signal.aborted) {
        return;
      }
      this._proposal = proposal;
      this._set("proposal");
    } catch (err: unknown) {
      if (controller.signal.aborted) {
        return;
      }
      this._error = err instanceof Error ? err.message : "AI request failed";
      this._set("error");
    } finally {
      if (this._controller === controller) {
        this._controller = null;
      }
    }
  }

  private _set(status: AICommandBarStatus): void {
    this._status = status;
    this._emit();
  }

  private _emit(): void {
    const state: AICommandBarState = {
      status: this._status,
      proposal: this._proposal,
      error: this._error,
      applied: this._applied,
    };
    for (const subscriber of this._subscribers) {
      subscriber(state);
    }
  }
}
