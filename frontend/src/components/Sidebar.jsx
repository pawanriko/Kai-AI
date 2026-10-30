// Left column: brand, view switch (Chat / Memory), New chat button,
// and the conversation history list. Pure presentation — all state
// lives in App and arrives via props.
export default function Sidebar({
  conversations,
  activeId,
  view,
  onSelect,
  onNew,
  onDelete,
  onView,
}) {
  return (
    <aside className="sidebar">
      <div className="brand">KAI</div>
      <div className="brand-sub">PERSONAL AI — V2</div>

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
    </aside>
  )
}
