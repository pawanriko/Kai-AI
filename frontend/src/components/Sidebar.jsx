// Left column: brand, view switch (Chat / Memory), New chat button,
// and the conversation history list. Pure presentation — all state
// lives in App and arrives via props. The collapse chevron slides
// the whole column away (App owns the open state); the expand
// button lives in App, since the sidebar is off-canvas when shut.
import { ChevronLeftIcon } from './icons'

export default function Sidebar({
  conversations,
  activeId,
  view,
  onSelect,
  onNew,
  onDelete,
  onView,
  username,
  onLogout,
  onCollapse,
}) {
  return (
    <aside className="sidebar">
      <div className="brand-row">
        <div>
          <div className="brand">KAI</div>
          <div className="brand-sub">PERSONAL AI — V2</div>
        </div>
        <button
          className="collapse-btn icon-btn"
          onClick={onCollapse}
          aria-label="Close sessions panel"
          title="Close sessions panel"
        >
          <ChevronLeftIcon />
        </button>
      </div>

      <nav className="side-nav">
        <button
          className={view === 'chat' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => onView('chat')}
        >
          Chat
        </button>
        <button
          className={view === 'memory' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => onView('memory')}
        >
          Memory
        </button>
        <button
          className={view === 'usage' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => onView('usage')}
        >
          Usage
        </button>
        <button
          className={view === 'automation' ? 'nav-btn active' : 'nav-btn'}
          onClick={() => onView('automation')}
        >
          Automation
        </button>
      </nav>

      <button className="new-chat" onClick={onNew}>
        + New chat
      </button>

      <div className="history-label">RECENTS</div>
      <ul className="history">
        {conversations.map((c) => (
          <li
            key={c.id}
            className={c.id === activeId ? 'history-item active' : 'history-item'}
            onClick={() => onSelect(c.id)}
          >
            <span className="history-title">{c.title}</span>
            <button
              className="history-del"
              title="Delete conversation"
              onClick={(e) => {
                e.stopPropagation()
                onDelete(c.id)
              }}
            >
              ×
            </button>
          </li>
        ))}
        {conversations.length === 0 && (
          <li className="history-empty">No conversations yet</li>
        )}
      </ul>

      <div className="side-footer">
        <span className="side-user">{username}</span>
        <button className="nav-btn" onClick={onLogout}>
          Log out
        </button>
      </div>
    </aside>
  )
}
