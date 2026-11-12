// @vitest-environment jsdom
//
// Frontend tests for the Phase 1 auth surface of api.js: the CSRF
// token must ride on every state-changing request (read fresh from
// the cookie — Django rotates it at login), GETs must not send it,
// and server error messages must reach the UI intact (the login
// form shows them verbatim).

import { beforeEach, describe, expect, it, vi } from 'vitest'

import {
  addMemory,
  confirmMemory,
  exportMemories,
  getMe,
  listConversations,
  listDuplicates,
  listMemories,
  listUsage,
  login,
  logout,
  mergeMemories,
  rejectMemory,
  sendChatStream,
  setMemoryScope,
  setupOwner,
} from './api'

function mockFetch(response) {
  const fetchMock = vi.fn(async () => response)
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function jsonResponse(status, body) {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  }
}

beforeEach(() => {
  document.cookie = 'csrftoken=fresh-token-123'
  vi.unstubAllGlobals()
})

describe('api.js auth + CSRF', () => {
  it('sends the CSRF token on POST login, with the credentials as JSON', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { ok: true }))
    await login('pawan', 'a-strong-pass-1')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/login/')
    expect(options.method).toBe('POST')
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
    expect(JSON.parse(options.body)).toEqual({
      username: 'pawan',
      password: 'a-strong-pass-1',
    })
  })

  it('does not send a CSRF token on GET requests', async () => {
    const fetchMock = mockFetch(
      jsonResponse(200, { authenticated: false, needs_setup: true })
    )
    const me = await getMe()
    expect(me.needs_setup).toBe(true)
    const [, options] = fetchMock.mock.calls[0]
    expect(options.headers['X-CSRFToken']).toBeUndefined()
  })

  it('surfaces the server error message on a failed login', async () => {
    mockFetch(jsonResponse(401, { error: 'Invalid username or password.' }))
    await expect(login('pawan', 'wrong')).rejects.toThrow(
      'Invalid username or password.'
    )
  })

  it('surfaces 401s from data endpoints so the UI can react', async () => {
    mockFetch(jsonResponse(401, { error: 'Login required.' }))
    await expect(listConversations()).rejects.toThrow('Login required.')
  })

  it('sends the bootstrap token when creating the owner', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { ok: true }))
    await setupOwner('pawan', 'a-strong-pass-1', 'boot-secret-1')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/setup/')
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
    expect(JSON.parse(options.body)).toEqual({
      username: 'pawan',
      password: 'a-strong-pass-1',
      setup_token: 'boot-secret-1',
    })
  })

  it('surfaces a rejected bootstrap token', async () => {
    mockFetch(jsonResponse(403, { error: 'Invalid setup token.' }))
    await expect(
      setupOwner('pawan', 'a-strong-pass-1', 'wrong')
    ).rejects.toThrow('Invalid setup token.')
  })

  it('surfaces an already-completed setup (permanent close)', async () => {
    mockFetch(jsonResponse(403, { error: 'Setup is already complete.' }))
    await expect(
      setupOwner('pawan', 'a-strong-pass-1', 'boot-secret-1')
    ).rejects.toThrow('Setup is already complete.')
  })

  it('logs out with a CSRF-protected POST', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { ok: true }))
    await logout()
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/auth/logout/')
    expect(options.method).toBe('POST')
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
  })

  it('throws errors carrying the HTTP status (401 = session expired)', async () => {
    mockFetch(jsonResponse(401, { error: 'Login required.' }))
    const err = await listConversations().catch((e) => e)
    expect(err).toBeInstanceOf(Error)
    expect(err.status).toBe(401)
  })

  it('confirms a suggested memory via POST to the confirm route', async () => {
    const fetchMock = mockFetch(
      jsonResponse(200, { id: 7, status: 'confirmed' })
    )
    const result = await confirmMemory(7)
    expect(result.status).toBe('confirmed')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/memories/7/confirm/')
    expect(options.method).toBe('POST')
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
  })

  it('streams chunks (even split mid-line) and resolves with done', async () => {
    const encoder = new TextEncoder()
    const pieces = [
      '{"type":"chunk","text":"Hel',
      'lo"}\n{"type":"chunk","text":" world"}\n{"type":"done","conversation_id":9,"trace":[]}\n',
    ]
    let i = 0
    const fetchMock = mockFetch({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () =>
            i < pieces.length
              ? { value: encoder.encode(pieces[i++]), done: false }
              : { value: undefined, done: true },
        }),
      },
    })
    const seen = []
    const done = await sendChatStream(
      'hi',
      null,
      'gemini::gemini-3.8-flash',
      (t) => seen.push(t)
    )
    expect(seen.join('')).toBe('Hello world')
    expect(done.conversation_id).toBe(9)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/chat/stream/')
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
  })

  it('rejects when the stream reports an error event', async () => {
    const encoder = new TextEncoder()
    let sent = false
    mockFetch({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (sent) return { value: undefined, done: true }
            sent = true
            return {
              value: encoder.encode(
                '{"type":"error","error":"AI unavailable"}\n'
              ),
              done: false,
            }
          },
        }),
      },
    })
    await expect(
      sendChatStream('hi', null, null, () => {})
    ).rejects.toThrow('AI unavailable')
  })

  // Phase 2.1: interrupted streams. The server saves the partial
  // reply flagged incomplete and ends with an error event carrying
  // "interrupted": true — the rejection must carry those flags so
  // the UI keeps and labels the partial bubble.
  function streamFetch(lines, { failAtRead = -1 } = {}) {
    const encoder = new TextEncoder()
    let i = 0
    return mockFetch({
      ok: true,
      status: 200,
      body: {
        getReader: () => ({
          read: async () => {
            if (i === failAtRead) throw new Error('network drop')
            return i < lines.length
              ? { value: encoder.encode(lines[i++]), done: false }
              : { value: undefined, done: true }
          },
        }),
      },
    })
  }

  it('flags an interrupted error event and keeps the chunks seen', async () => {
    streamFetch([
      '{"type":"chunk","text":"Partial "}\n',
      '{"type":"error","error":"AI response interrupted","interrupted":true,"conversation_id":9}\n',
    ])
    const seen = []
    const err = await sendChatStream('hi', null, null, (t) =>
      seen.push(t)
    ).catch((e) => e)
    expect(seen.join('')).toBe('Partial ')
    expect(err.message).toBe('AI response interrupted')
    expect(err.interrupted).toBe(true)
    expect(err.conversationId).toBe(9)
  })

  it('rejects when the stream ends without a done event', async () => {
    streamFetch(['{"type":"chunk","text":"Half"}\n'])
    await expect(
      sendChatStream('hi', null, null, () => {})
    ).rejects.toThrow('Stream ended unexpectedly')
  })

  it('rejects when the transport drops mid-stream', async () => {
    streamFetch(['{"type":"chunk","text":"Half"}\n'], { failAtRead: 1 })
    const seen = []
    await expect(
      sendChatStream('hi', null, null, (t) => seen.push(t))
    ).rejects.toThrow('network drop')
    expect(seen.join('')).toBe('Half')
  })

  it('rejects a suggested memory and treats the 204 as success', async () => {
    const fetchMock = mockFetch({
      ok: true,
      status: 204,
      json: async () => {
        throw new Error('no body')
      },
    })
    await expect(rejectMemory(7)).resolves.toBeNull()
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/memories/7/reject/')
    expect(options.method).toBe('POST')
  })

  it('fetches the usage ledger with a plain GET', async () => {
    const fetchMock = mockFetch(
      jsonResponse(200, { totals: { calls: 0 }, recent: [] })
    )
    const data = await listUsage()
    expect(data.totals.calls).toBe(0)
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/usage/')
    expect(options.headers['X-CSRFToken']).toBeUndefined()
  })

  it('lists memories with search and project params encoded', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { memories: [] }))
    await listMemories({ q: 'iit&m', project: 'kai', status: '' })
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/memories/?q=iit%26m&project=kai')
    expect(options.headers['X-CSRFToken']).toBeUndefined()
  })

  it('lists memories without params on the bare route', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { memories: [] }))
    await listMemories()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/memories/')
  })

  it('adds a memory via POST with fact and project', async () => {
    const fetchMock = mockFetch(jsonResponse(201, { id: 9 }))
    await addMemory('My exam is Friday', 'college')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/memories/add/')
    expect(options.method).toBe('POST')
    expect(JSON.parse(options.body)).toEqual({
      fact: 'My exam is Friday',
      project: 'college',
    })
    expect(options.headers['X-CSRFToken']).toBe('fresh-token-123')
  })

  it('sets a memory scope via POST', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { id: 9, project: 'kai' }))
    await setMemoryScope(9, 'kai')
    const [url, options] = fetchMock.mock.calls[0]
    expect(url).toBe('/api/memories/9/scope/')
    expect(JSON.parse(options.body)).toEqual({ project: 'kai' })
  })

  it('lists duplicate groups and merges with keep + drops', async () => {
    const fetchMock = mockFetch(jsonResponse(200, { groups: [] }))
    await listDuplicates()
    expect(fetchMock.mock.calls[0][0]).toBe('/api/memories/duplicates/')

    const mergeMock = mockFetch(jsonResponse(200, { kept: 2, deleted: 1 }))
    await mergeMemories(2, [3, 4])
    const [url, options] = mergeMock.mock.calls[0]
    expect(url).toBe('/api/memories/merge/')
    expect(JSON.parse(options.body)).toEqual({
      keep_id: 2,
      drop_ids: [3, 4],
    })
  })

  it('exports memories as a blob with the format param', async () => {
    const blob = new Blob(['{}'])
    const fetchMock = mockFetch({
      ok: true,
      status: 200,
      blob: async () => blob,
    })
    const result = await exportMemories('md', 'kai')
    expect(result).toBe(blob)
    expect(fetchMock.mock.calls[0][0]).toBe(
      '/api/memories/export/?format=md&project=kai'
    )
  })
})
