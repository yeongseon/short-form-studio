import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect, vi, beforeEach } from 'vitest';
import CreatePage from '../pages/CreatePage';

describe('App', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.spyOn(globalThis, 'fetch').mockResolvedValue({
      ok: true,
      json: () => Promise.resolve({
        script_models: [], image_models: [], tts_models: [], stt_models: [],
      }),
    } as Response);
  });

  it('renders CreatePage without crashing', () => {
    render(
      <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
        <CreatePage />
      </MemoryRouter>
    );
    // Verify CreatePage renders the heading
    expect(screen.getByText('Create New Project')).toBeTruthy();
  });

  it('App module exports default function', async () => {
    const mod = await import('../App');
    expect(typeof mod.default).toBe('function');
  });
});
