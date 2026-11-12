// @vitest-environment jsdom
//
// Phase 4: the Memory panel gains search + project filter, a
// direct-add form, per-fact scope controls, duplicate merging,
// and export buttons — on top of the Phase 1 confirm/reject
// flow, which must keep working unchanged.

globalThis.IS_REACT_ACT_ENVIRONMENT = true

import { act } from 'react'
import { createRoot } from 'react-dom/client'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

import {
  addMemory,
  confirmMemory,
  exportMemories,
  listDuplicates,
  listMemories,
  mergeMemories,
  setMemoryScope,
} from '../api'
import MemoryPanel from './MemoryPanel'

vi.mock('../api', () => ({
  addMemory: vi.fn(),
  confirmMemory: vi.fn(),
  deleteMemory: vi.fn(),
  exportMemories: vi.fn(),
  listDuplicates: vi.fn(),
  listMemories: vi.fn(),
  mergeMemories: vi.fn(),
  rejectMemory: vi.fn(),
  setMemoryScope: vi.fn(),
}))

let container
let root

const MEMORIES = {
  memories: [
    {
      id: 1,
      fact: 'Pawan studies at IITM',
      status: 'suggested',
      origin: 'inferred',
      project: '',
      created_at: '2026-11-12T00:00:00Z',
    },
    {
      id: 2,
      fact: 'KAI uses Django',
      status: 'confirmed',
      origin: 'stated',
      project: 'kai',
      created_at: '2026-11-12T00:00:00Z',
    },
  ],
}

const GROUPS = {
  groups: [
    {
      keeper: MEMORIES.memories[1],
      members: [
        MEMORIES.memories[1],
        {
          id: 3,
          fact: 'KAI uses Django framework',
          status: 'suggested',
          origin: 'inferred',
          project: '',
          created_at: '2026-11-12T00:00:00Z',
        },
      ],
    },
  ],
}

beforeEach(() => {
  listMemories.mockResolvedValue(MEMORIES)
  listDuplicates.mockResolvedValue(GROUPS)
  URL.createObjectURL = vi.fn(() => 'blob:fake')
  URL.revokeObjectURL = vi.fn()
  vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(
    () => {}
  )
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
  vi.resetAllMocks()
  vi.restoreAllMocks()
})

async function renderPanel() {
  container = document.createElement('div')
  document.body.appendChild(container)
  root = createRoot(container)
  await act(async () => {
    root.render(<MemoryPanel />)
  })
}

function typeText(input, value) {
  const setter = Object.getOwnPropertyDescriptor(
    window.HTMLInputElement.prototype,
    'value'
  ).set
  act(() => {
    setter.call(input, value)
    input.dispatchEvent(new Event('input', { bubbles: true }))
  })
}

function click(button) {
  act(() => {
    button.dispatchEvent(new MouseEvent('click', { bubbles: true }))
  })
}

function buttonByText(text) {
  return [...container.querySelectorAll('button')].find(
    (b) => b.textContent === text
  )
}

describe('MemoryPanel Phase 4', () => {
  it('renders facts with origin and project labels', async () => {
    await renderPanel()
    expect(container.textContent).toContain('Pawan studies at IITM')
    expect(container.textContent).toContain('inferred')
    expect(container.textContent).toContain('project: kai')
    expect(container.textContent).toContain('Possible duplicates')
  })

  it('searches with the entered query and project', async () => {
    await renderPanel()
    typeText(
      container.querySelector('input[aria-label="Search memories"]'),
      'iitm'
    )
    typeText(
      container.querySelector('input[aria-label="Filter by project"]'),
      'kai'
    )
    await act(async () => {
      container
        .querySelector('form')
        .dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
    })
    expect(listMemories).toHaveBeenLastCalledWith({
      q: 'iitm',
      project: 'kai',
    })
  })

  it('adds a fact and reloads the list', async () => {
    addMemory.mockResolvedValue({})
    await renderPanel()
    typeText(
      container.querySelector('input[aria-label="New fact"]'),
      'My exam is Friday'
    )
    typeText(
      container.querySelector('input[aria-label="New fact project"]'),
      'college'
    )
    await act(async () => {
      const forms = container.querySelectorAll('form')
      forms[1].dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true })
      )
    })
    expect(addMemory).toHaveBeenCalledWith('My exam is Friday', 'college')
  })

  it('shows the add error instead of reloading', async () => {
    addMemory.mockRejectedValue(new Error('a similar fact exists'))
    await renderPanel()
    typeText(
      container.querySelector('input[aria-label="New fact"]'),
      'Pawan studies at IITM'
    )
    await act(async () => {
      const forms = container.querySelectorAll('form')
      forms[1].dispatchEvent(
        new Event('submit', { bubbles: true, cancelable: true })
      )
    })
    expect(container.textContent).toContain('a similar fact exists')
  })

  it('merges a duplicate group keeping the keeper', async () => {
    mergeMemories.mockResolvedValue({ kept: 2, deleted: 1 })
    await renderPanel()
    await act(async () => {
      click(buttonByText('Merge'))
    })
    expect(mergeMemories).toHaveBeenCalledWith(2, [3])
  })

  it('sets a fact scope from its row', async () => {
    setMemoryScope.mockResolvedValue({
      ...MEMORIES.memories[1],
      project: 'portfolio',
    })
    await renderPanel()
    const input = container.querySelector(
      'input[aria-label="Project scope for fact 2"]'
    )
    typeText(input, 'portfolio')
    const buttons = [...container.querySelectorAll('button')].filter(
      (b) => b.textContent === 'Set scope'
    )
    await act(async () => {
      click(buttons[1])
    })
    expect(setMemoryScope).toHaveBeenCalledWith(2, 'portfolio')
  })

  it('exports JSON through a download', async () => {
    exportMemories.mockResolvedValue(new Blob(['{}']))
    await renderPanel()
    await act(async () => {
      click(buttonByText('Export JSON'))
    })
    expect(exportMemories).toHaveBeenCalledWith('json', '')
    expect(URL.createObjectURL).toHaveBeenCalled()
  })

  it('keeps the Phase 1 confirm flow working', async () => {
    confirmMemory.mockResolvedValue({})
    await renderPanel()
    await act(async () => {
      click(buttonByText('Confirm'))
    })
    expect(confirmMemory).toHaveBeenCalledWith(1)
  })
})
