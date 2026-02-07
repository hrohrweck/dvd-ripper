import React, { useState } from 'react'
import { api } from '../App'

function Setup({ onComplete }) {
  const [step, setStep] = useState(1)
  const [password, setPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [tmdbKey, setTmdbKey] = useState('')
  const [omdbKey, setOmdbKey] = useState('')
  const [outputPath, setOutputPath] = useState('/archive')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const validateStep1 = () => {
    if (password.length < 8) {
      setError('Password must be at least 8 characters')
      return false
    }
    if (password !== confirmPassword) {
      setError('Passwords do not match')
      return false
    }
    return true
  }

  const handleNext = () => {
    setError('')
    if (step === 1 && validateStep1()) {
      setStep(2)
    }
  }

  const handleBack = () => {
    setError('')
    setStep(step - 1)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      const settings = {
        destination: {
          type: 'local',
          local: { path: outputPath }
        },
        metadata: {
          api_keys: {
            tmdb: tmdbKey,
            omdb: omdbKey
          }
        }
      }

      const response = await api.post('/setup', null, {
        params: { password },
        data: settings
      })

      if (response.data.status === 'setup_complete') {
        onComplete()
      }
    } catch (err) {
      setError(err.response?.data?.detail || 'Setup failed')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="auth-container">
      <div className="auth-box">
        <h2>Welcome to DVD Ripper</h2>
        <p>Let's get you set up</p>

        {error && (
          <div className="badge badge-error" style={{ marginBottom: 16, display: 'block' }}>
            {error}
          </div>
        )}

        {step === 1 && (
          <>
            <h3 style={{ marginBottom: 16 }}>Step 1: Create Admin Account</h3>
            <div className="form-group">
              <label>Admin Password</label>
              <input
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                placeholder="Min 8 characters"
              />
            </div>
            <div className="form-group">
              <label>Confirm Password</label>
              <input
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
              />
            </div>
            <button
              className="btn btn-primary"
              style={{ width: '100%' }}
              onClick={handleNext}
            >
              Next →
            </button>
          </>
        )}

        {step === 2 && (
          <form onSubmit={handleSubmit}>
            <h3 style={{ marginBottom: 16 }}>Step 2: Configuration</h3>
            
            <div className="form-group">
              <label>Output Directory</label>
              <input
                type="text"
                value={outputPath}
                onChange={(e) => setOutputPath(e.target.value)}
              />
            </div>

            <div className="form-group">
              <label>TMDB API Key (Optional)</label>
              <input
                type="text"
                value={tmdbKey}
                onChange={(e) => setTmdbKey(e.target.value)}
                placeholder="Get from themoviedb.org"
              />
            </div>

            <div className="form-group">
              <label>OMDB API Key (Optional)</label>
              <input
                type="text"
                value={omdbKey}
                onChange={(e) => setOmdbKey(e.target.value)}
                placeholder="Get from omdbapi.com"
              />
            </div>

            <div style={{ display: 'flex', gap: 12 }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ flex: 1 }}
                onClick={handleBack}
              >
                ← Back
              </button>
              <button
                type="submit"
                className="btn btn-primary"
                style={{ flex: 1 }}
                disabled={loading}
              >
                {loading ? 'Setting up...' : 'Complete Setup'}
              </button>
            </div>
          </form>
        )}
      </div>
    </div>
  )
}

export default Setup
