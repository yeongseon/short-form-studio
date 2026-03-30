import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, it, expect } from 'vitest';
import CreatePage from '../pages/CreatePage';

describe('App', () => {
  it('renders CreatePage without crashing', () => {
    render(
      <MemoryRouter>
        <CreatePage />
      </MemoryRouter>
    );
    // Verify CreatePage renders
    expect(screen.getByText('CreatePage')).toBeTruthy();
  });

  it('App module exports default function', async () => {
    const mod = await import('../App');
    expect(typeof mod.default).toBe('function');
  });
});
