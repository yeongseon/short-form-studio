/**
 * Autosave — revision-aware, debounced persistence controller for accepted
 * Timeline edits.
 *
 * Edits are coalesced by a debounce window and persisted via an injected save
 * function that carries the current expected revision. The controller exposes an
 * idle → saving → saved / error / conflict status. Correctness invariants:
 *
 * - No silent concurrent overwrite: only one save is in flight at a time; an
 *   edit arriving mid-flight is queued and saved after the current one settles.
 * - Out-of-order safety: each save carries a monotonic generation; a response
 *   from a superseded generation is ignored, so a slow stale response can never
 *   clobber a newer saved revision.
 * - Preserve unsaved work: on error or conflict the pending edit is kept and the
 *   revision is NOT advanced (a 409 conflict never silently overwrites).
 */

export type AutosaveStatus = "idle" | "saving" | "saved" | "error" | "conflict";

export type SaveResult<T> =
  | { ok: true; timeline: T }
  | { ok: false; kind: "error" | "conflict"; message: string };

export type SaveTimelineFn<T> = (
  timeline: T,
  expectedRevision: number,
) => Promise<SaveResult<T>>;

interface HasRevision {
  revision: number;
}

export interface AutosaveState {
  status: AutosaveStatus;
  revision: number;
  message: string | null;
}

export interface AutosaveOptions<T> {
  save: SaveTimelineFn<T>;
  debounceMs: number;
  initialRevision: number;
}

type Subscriber = (state: AutosaveState) => void;

export class Autosave<T extends HasRevision> {
  private _status: AutosaveStatus = "idle";
  private _revision: number;
  private _message: string | null = null;
  private _pending: T | null = null;
  private _inFlight = false;
  private _generation = 0;
  private _timer: ReturnType<typeof setTimeout> | null = null;
  private readonly _save: SaveTimelineFn<T>;
  private readonly _debounceMs: number;
  private readonly _subscribers = new Set<Subscriber>();

  constructor(options: AutosaveOptions<T>) {
    this._save = options.save;
    this._debounceMs = options.debounceMs;
    this._revision = options.initialRevision;
  }

  get status(): AutosaveStatus {
    return this._status;
  }

  get revision(): number {
    return this._revision;
  }

  get pendingTimeline(): T | null {
    return this._pending;
  }

  subscribe(subscriber: Subscriber): () => void {
    this._subscribers.add(subscriber);
    return () => this._subscribers.delete(subscriber);
  }

  /** Queue an accepted edit; the latest edit within the debounce window wins. */
  schedule(timeline: T): void {
    this._pending = timeline;
    if (this._timer !== null) {
      clearTimeout(this._timer);
    }
    this._timer = setTimeout(() => {
      this._timer = null;
      void this._flush();
    }, this._debounceMs);
  }

  /**
   * Re-attempt persistence of the pending edit (e.g. after an error/conflict),
   * or supersede an in-flight save. Bumping the generation makes the previous
   * in-flight response stale, so it is ignored when it eventually arrives.
   */
  forceRetry(): void {
    if (this._pending === null) {
      return;
    }
    this._inFlight = false;
    void this._flush();
  }

  private _emit(): void {
    const state: AutosaveState = {
      status: this._status,
      revision: this._revision,
      message: this._message,
    };
    for (const subscriber of this._subscribers) {
      subscriber(state);
    }
  }

  private _set(status: AutosaveStatus, message: string | null): void {
    this._status = status;
    this._message = message;
    this._emit();
  }

  private async _flush(): Promise<void> {
    if (this._inFlight || this._pending === null) {
      return;
    }
    const timeline = this._pending;
    const generation = ++this._generation;
    this._inFlight = true;
    this._set("saving", null);

    let result: SaveResult<T>;
    try {
      result = await this._save(timeline, this._revision);
    } catch (err: unknown) {
      result = {
        ok: false,
        kind: "error",
        message: err instanceof Error ? err.message : "save failed",
      };
    }

    // Out-of-order guard: ignore a response from a superseded save.
    if (generation !== this._generation) {
      return;
    }
    this._inFlight = false;

    if (result.ok) {
      this._revision = result.timeline.revision;
      const stillPending = this._pending !== timeline ? this._pending : null;
      this._pending = stillPending;
      this._set("saved", null);
      if (stillPending !== null) {
        void this._flush();
      }
      return;
    }

    // Preserve the unsaved edit; do not advance the revision.
    this._set(result.kind, result.message);
  }
}
