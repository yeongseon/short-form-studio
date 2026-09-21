/**
 * OptimisticEditor — optimistic local editor state that reconciles with the
 * server without losing unrelated edits.
 *
 * A local command updates ``present`` immediately (optimistic prediction) and is
 * queued as a pending edit holding its pure prediction function. ``present`` is
 * always the current ``base`` (last server-confirmed timeline) with every pending
 * prediction replayed on top, so reconciliation is coherent regardless of order:
 *
 * - confirm: the edit is accepted; its server state becomes the new base and the
 *   remaining pending edits are replayed on top (rebase). A confirm for an edit
 *   already absorbed by an earlier confirm is stale.
 * - reject: the edit is dropped and the remaining pending edits replay on the
 *   current base, so unrelated edits survive a rollback.
 * - conflict: like confirm but the server's authoritative state supersedes the
 *   local prediction; the conflicting edit is dropped and unrelated pending edits
 *   replay on the new base, so no unrelated work is lost.
 * - reconnect: adopt a fresh authoritative base and replay all pending edits.
 */

export type ReconcileStatus = "confirmed" | "rolled_back" | "conflict" | "stale";

export interface ReconcileResult {
  status: ReconcileStatus;
}

interface HasRevision {
  revision: number;
}

export type Prediction<T> = (timeline: T) => T;

interface PendingEdit<T> {
  id: string;
  predict: Prediction<T>;
  baseRevision: number;
}

export interface OptimisticState {
  pendingCount: number;
  baseRevision: number;
}

export interface OptimisticEditorOptions<T> {
  initial: T;
}

type Subscriber = (state: OptimisticState) => void;

export class OptimisticEditor<T extends HasRevision> {
  private _base: T;
  private _pending: PendingEdit<T>[] = [];
  private _present: T;
  private _nextId = 0;
  private readonly _subscribers = new Set<Subscriber>();

  constructor(options: OptimisticEditorOptions<T>) {
    this._base = options.initial;
    this._present = options.initial;
  }

  get base(): T {
    return this._base;
  }

  get present(): T {
    return this._present;
  }

  get pendingCount(): number {
    return this._pending.length;
  }

  subscribe(subscriber: Subscriber): () => void {
    this._subscribers.add(subscriber);
    return () => this._subscribers.delete(subscriber);
  }

  /** Apply a validated local command optimistically; returns the edit id. */
  applyLocal(predict: Prediction<T>): string {
    const id = `edit-${this._nextId++}`;
    this._pending.push({ id, predict, baseRevision: this._base.revision });
    this._recompute();
    return id;
  }

  /** Accept an edit: its server state becomes the new base; rebase the rest.
   *
   * An edit whose confirm arrives against a server revision the editor has
   * already advanced past (via an out-of-order confirm) is already absorbed, so
   * it is dropped and reported as stale rather than re-confirmed.
   */
  confirm(id: string, serverTimeline: T): ReconcileResult {
    const index = this._pending.findIndex((edit) => edit.id === id);
    if (index === -1) {
      return { status: "stale" };
    }
    if (serverTimeline.revision <= this._base.revision) {
      this._pending.splice(index, 1);
      this._recompute();
      return { status: "stale" };
    }
    this._base = serverTimeline;
    this._pending.splice(index, 1);
    this._recompute();
    return { status: "confirmed" };
  }

  /** Reject an edit: drop it and replay the remaining edits on the base. */
  reject(id: string): ReconcileResult {
    const index = this._pending.findIndex((edit) => edit.id === id);
    if (index === -1) {
      return { status: "stale" };
    }
    this._pending.splice(index, 1);
    this._recompute();
    return { status: "rolled_back" };
  }

  /** Surface a conflict: the server state supersedes; keep unrelated edits. */
  conflict(id: string, serverTimeline: T): ReconcileResult {
    const index = this._pending.findIndex((edit) => edit.id === id);
    if (index === -1) {
      return { status: "stale" };
    }
    this._base = serverTimeline;
    this._pending.splice(index, 1);
    this._recompute();
    return { status: "conflict" };
  }

  /** Adopt a fresh authoritative base (e.g. after reconnect) and replay pending. */
  reconnect(serverTimeline: T): T {
    this._base = serverTimeline;
    this._recompute();
    return this._present;
  }

  private _recompute(): void {
    let timeline = this._base;
    for (const edit of this._pending) {
      timeline = edit.predict(timeline);
    }
    this._present = timeline;
    const state: OptimisticState = {
      pendingCount: this._pending.length,
      baseRevision: this._base.revision,
    };
    for (const subscriber of this._subscribers) {
      subscriber(state);
    }
  }
}
