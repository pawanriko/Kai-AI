// @vitest-environment node
//
// Final polish: the change is CSS-only, so the testable surface is
// the stylesheet itself. These assertions lock in that the polish
// exists and stays: the entry/pulse motion, the reduced-motion
// guard, styles for every control class Phases 5–7 introduced
// (they rendered as raw browser defaults before), and the narrow
// composer wrap. They say nothing about how it looks — the visual
// verdict is Pawan's, live.

import { readFileSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'

import { describe, expect, it } from 'vitest'

const css = readFileSync(
  join(dirname(fileURLToPath(import.meta.url)), 'index.css'),
  'utf-8'
)

describe('polish stylesheet', () => {
  it('animates message entry and the Thinking state', () => {
    expect(css).toContain('@keyframes kai-bubble-in')
    expect(css).toContain('@keyframes kai-pulse')
    expect(css).toContain('.bubble-row {')
    expect(css).toContain('.bubble.thinking {')
  })

  it('respects prefers-reduced-motion', () => {
    expect(css).toContain('@media (prefers-reduced-motion: reduce)')
    expect(css).toContain('animation-duration: 0.01ms')
    expect(css).toContain('transition-duration: 0.01ms')
  })

  it('styles every control class from Phases 5–7', () => {
    for (const selector of [
      '.bundle-picker',
      '.voice-lang-picker',
      '.mic-btn',
      '.mic-btn.listening',
      '.speak-btn',
      '.voice-hint',
      '.plan-review',
      '.report-row',
    ]) {
      expect(css, `missing styles for ${selector}`).toContain(selector)
    }
  })

  it('themes panel forms and keeps forget buttons compact', () => {
    expect(css).toContain('.memory-panel input')
    expect(css).toContain('.memory-panel button:not(.forget-btn)')
  })

  it('wraps the composer on narrow screens', () => {
    expect(css).toContain('@media (max-width: 720px)')
    expect(css).toContain('flex-wrap: wrap')
    expect(css).toContain('.composer-input {')
  })

  it('keeps transitions subtle and consistent', () => {
    // Every transition in the polish uses the same 120ms ease.
    const transitions = [...css.matchAll(/transition:[^;]+;/g)].map((m) => m[0])
    expect(transitions.length).toBeGreaterThan(0)
    for (const rule of transitions) {
      expect(rule).toContain('120ms')
    }
  })
})
