// @vitest-environment jsdom
//
// Phase 2.1: an interrupted assistant reply must be visibly labelled
// in the transcript — both when it arrives live (the `incomplete`
// flag App.jsx sets on the bubble) and when a saved conversation is
// reopened (the `status: 'incomplete'` the API returns). Rendered
// server-side: the label is pure markup, no interaction needed.

import { describe, expect, it } from 'vitest'
import { renderToString } from 'react-dom/server'

import MessageList from './components/MessageList'

describe('MessageList interrupted label', () => {
  it('labels a saved incomplete reply as interrupted', () => {
    const html = renderToString(
      <MessageList
        messages={[
          { id: 1, role: 'user', content: 'hi' },
          {
            id: 2,
            role: 'assistant',
            content: 'half an ans',
            status: 'incomplete',
          },
        ]}
        sending={false}
      />
    )
    expect(html).toContain('half an ans')
    expect(html).toContain('Response interrupted')
  })

  it('labels a live interrupted bubble (incomplete flag)', () => {
    const html = renderToString(
      <MessageList
        messages={[
          { role: 'assistant', content: 'partial', incomplete: true },
        ]}
        sending={false}
      />
    )
    expect(html).toContain('Response interrupted')
  })

  it('does not label a normal completed reply', () => {
    const html = renderToString(
      <MessageList
        messages={[
          {
            id: 3,
            role: 'assistant',
            content: 'full answer',
            status: 'complete',
          },
        ]}
        sending={false}
      />
    )
    expect(html).not.toContain('Response interrupted')
  })
})
