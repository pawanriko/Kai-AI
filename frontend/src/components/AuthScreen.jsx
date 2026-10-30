import { useState } from 'react'
import { login, register } from '../api'

export default function AuthScreen({ onAuthenticated }) {
  const [mode, setMode] = useState('login')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  async function handleSubmit(event) {
    event.preventDefault()
    setError('')
    setBusy(true)
    try {
      const result = mode === 'register'
        ? await register(username.trim(), password)
        : await login(username.trim(), password)
      onAuthenticated(result.user)
    } catch (err) {
      setError(err.message || 'Authentication failed')
    } finally {
      setBusy(false)
    }
  }

  return (
    <main className="auth-screen">
      <form className="auth-card" onSubmit={handleSubmit}>
        <div className="brand">KAI</div>
        <div className="brand-sub">PERSONAL AI — V2</div>
        <h1>{mode === 'login' ? 'SIGN IN' : 'CREATE ACCOUNT'}</h1>
        <p className="muted">Your conversations and memories are private to your account.</p>
        <label>
          Username
          <input autoComplete="username" minLength={3} maxLength={150} required value={username} onChange={(event) => setUsername(event.target.value)} />
        </label>
        <label>
          Password
          <input autoComplete={mode === 'login' ? 'current-password' : 'new-password'} type="password" required value={password} onChange={(event) => setPassword(event.target.value)} />
        </label>
        {error && <div className="error-box">{error}</div>}
        <button className="new-chat" type="submit" disabled={busy}>
          {busy ? 'PLEASE WAIT…' : mode === 'login' ? 'SIGN IN' : 'CREATE ACCOUNT'}
        </button>
        <button className="auth-switch" type="button" onClick={() => { setMode(mode === 'login' ? 'register' : 'login'); setError('') }}>
          {mode === 'login' ? 'Need an account? Register' : 'Already registered? Sign in'}
        </button>
      </form>
    </main>
  )
}
