import { useState } from 'react'

import { login, setupOwner } from '../api'

// The gate (Phase 1): KAI is a personal assistant with exactly one
// owner. On a fresh deployment (no users yet) this form CREATES the
// owner account via /api/auth/setup/ — which additionally requires
// the deployment-only bootstrap token (KAI_SETUP_TOKEN, set in the
// server's environment, never shipped to visitors in any other way)
// and closes forever once one user exists. After that it is a
// plain login.
export default function Login({ needsSetup, setupEnabled, onDone }) {
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [setupToken, setSetupToken] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function submit(e) {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      if (needsSetup) {
        await setupOwner(username, password, setupToken)
      } else {
        await login(username, password)
      }
      onDone()
    } catch (err) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="login-wrap">
      <form className="login-box" onSubmit={submit}>
        <div className="brand">KAI</div>
        <div className="brand-sub">PERSONAL AI — V2</div>
        <h2>{needsSetup ? 'Create your owner account' : 'Welcome back'}</h2>
        {needsSetup && (
          <p className="muted">
            This KAI has no owner yet. Creating the account needs the
            bootstrap token from the server's environment
            (KAI_SETUP_TOKEN) — a random visitor cannot claim this
            instance. Setup closes permanently once the owner exists.
          </p>
        )}
        {needsSetup && !setupEnabled && (
          <div className="error-box">
            ⚠️ Web setup is currently disabled: no bootstrap token is
            configured on the server. Set KAI_SETUP_TOKEN in the
            deployment's environment and redeploy, or create the owner
            with <code>python manage.py createsuperuser</code>.
          </div>
        )}
        {error && <div className="error-box">⚠️ {error}</div>}
        <input
          placeholder="Username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          autoComplete="username"
          required
        />
        <input
          type="password"
          placeholder="Password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          autoComplete={needsSetup ? 'new-password' : 'current-password'}
          required
        />
        {needsSetup && (
          <input
            type="password"
            placeholder="Bootstrap token (KAI_SETUP_TOKEN)"
            value={setupToken}
            onChange={(e) => setSetupToken(e.target.value)}
            autoComplete="off"
            required
          />
        )}
        <button type="submit" disabled={busy}>
          {busy ? '…' : needsSetup ? 'Create account & enter' : 'Log in'}
        </button>
      </form>
    </div>
  )
}
