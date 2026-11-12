// @vitest-environment jsdom
//
// Phase 6: the plan review shows the proposed steps with Approve
// and Cancel. Approving is the permission that lets the plan
// execute; cancelling sends nothing.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, describe, expect, it, vi } from 'vitest'

import PlanReview from './PlanReview'

const roots = []

afterEach(() => {
  act(() => {
    roots.splice(0).forEach((root) => root.unmount())
  })
  document.body.innerHTML = ''
})

function renderReview(props = {}) {
  const container = document.createElement('div')
  document.body.appendChild(container)
  const root = createRoot(container)
  roots.push(root)
  act(() => {
    root.render(
      <PlanReview
        plan={{ steps: ['Search the web', 'Read the docs'] }}
        message="Is Django 5.2 out?"
        onApprove={props.onApprove ?? (() => {})}
        onCancel={props.onCancel ?? (() => {})}
      />
    )
  })
  return container
}

describe('PlanReview', () => {
  it('lists the steps and the original request', () => {
    const container = renderReview()
    expect(container.textContent).toContain('Search the web')
    expect(container.textContent).toContain('Read the docs')
    expect(container.textContent).toContain('Is Django 5.2 out?')
    expect(container.textContent).toContain('nothing has run yet')
  })

  it('approves and cancels through the callbacks', () => {
    const onApprove = vi.fn()
    const onCancel = vi.fn()
    const container = renderReview({ onApprove, onCancel })
    const buttons = [...container.querySelectorAll('button')]
    act(() => {
      buttons
        .find((b) => b.textContent === 'Approve & run')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onApprove).toHaveBeenCalledTimes(1)
    act(() => {
      buttons
        .find((b) => b.textContent === 'Cancel')
        .dispatchEvent(new MouseEvent('click', { bubbles: true }))
    })
    expect(onCancel).toHaveBeenCalledTimes(1)
  })
})
