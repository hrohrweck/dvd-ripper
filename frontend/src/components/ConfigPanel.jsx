import React, { useState, useEffect } from 'react'
import { api } from '../App'

function ConfigPanel() {
  const [config, setConfig] = useState(null)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState('')

  useEffect(() => {
    fetchConfig()
  }, [])

  const fetchConfig = async () => {
    try {
      const response = await api.get('/config')
      setConfig(response.data)
    } catch (err) {
      console.error('Failed to fetch config:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async (e) => {
    e.preventDefault()
    setSaving(true)
    setMessage('')

    try {
      await api.post('/config', config)
      setMessage('Configuration saved successfully')
      setTimeout(() => setMessage(''), 3000)
    } catch (err) {
      setMessage('Failed to save configuration')
    } finally {
      setSaving(false)
    }
  }

  const updateConfig = (section, key, value) => {
    setConfig(prev => ({
      ...prev,
      [section]: {
        ...prev[section],
        [key]: value
      }
    }))
  }

  const updateNestedConfig = (section, subsection, key, value) => {
    setConfig(prev => ({
      ...prev,
      [section]: {
        ...prev[section],
        [subsection]: {
          ...prev[section][subsection],
          [key]: value
        }
      }
    }))
  }

  if (loading) return <div className="loading">Loading configuration...</div>
  if (!config) return <div>Error loading configuration</div>

  return (
    <div>
      <h1>Settings</h1>

      {message && (
        <div className={`badge badge-${message.includes('Failed') ? 'error' : 'success'}`} style={{ marginBottom: 16, display: 'block' }}>
          {message}
        </div>
      )}

      <form onSubmit={handleSave}>
        {/* Output Format */}
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Output Format</h2>
          </div>
          
          <div className="form-row">
            <div className="form-group">
              <label>Video Codec</label>
              <select 
                value={config.formats.video_codec}
                onChange={(e) => updateConfig('formats', 'video_codec', e.target.value)}
              >
                <option value="libx264">H.264 (x264)</option>
                <option value="libx265">H.265/HEVC (x265)</option>
                <option value="libvpx-vp9">VP9</option>
                <option value="h264_nvenc">H.264 (NVENC)</option>
                <option value="hevc_nvenc">HEVC (NVENC)</option>
              </select>
            </div>

            <div className="form-group">
              <label>Audio Codec</label>
              <select 
                value={config.formats.audio_codec}
                onChange={(e) => updateConfig('formats', 'audio_codec', e.target.value)}
              >
                <option value="aac">AAC</option>
                <option value="libmp3lame">MP3</option>
                <option value="copy">Copy (no re-encode)</option>
              </select>
            </div>

            <div className="form-group">
              <label>Container</label>
              <select 
                value={config.formats.container}
                onChange={(e) => updateConfig('formats', 'container', e.target.value)}
              >
                <option value="mp4">MP4</option>
                <option value="mkv">MKV</option>
              </select>
            </div>
          </div>

          <div className="form-row">
            <div className="form-group">
              <label>Quality (CRF) - Lower is better</label>
              <input 
                type="range"
                min="18"
                max="28"
                value={config.formats.crf}
                onChange={(e) => updateConfig('formats', 'crf', parseInt(e.target.value))}
              />
              <div style={{ textAlign: 'center' }}>{config.formats.crf}</div>
            </div>

            <div className="form-group">
              <label>Encoding Preset</label>
              <select 
                value={config.formats.preset}
                onChange={(e) => updateConfig('formats', 'preset', e.target.value)}
              >
                <option value="ultrafast">Ultrafast (larger files)</option>
                <option value="superfast">Superfast</option>
                <option value="veryfast">Veryfast</option>
                <option value="faster">Faster</option>
                <option value="fast">Fast</option>
                <option value="medium">Medium (balanced)</option>
                <option value="slow">Slow (smaller files)</option>
                <option value="slower">Slower</option>
                <option value="veryslow">Veryslow</option>
              </select>
            </div>
          </div>
        </div>

        {/* Destination */}
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Storage Destination</h2>
          </div>

          <div className="form-group">
            <label>Storage Type</label>
            <select 
              value={config.destination.type}
              onChange={(e) => updateConfig('destination', 'type', e.target.value)}
            >
              <option value="local">Local Directory</option>
              <option value="ssh">SSH/SFTP</option>
            </select>
          </div>

          {config.destination.type === 'local' && (
            <div className="form-group">
              <label>Output Path</label>
              <input 
                type="text"
                value={config.destination.local.path}
                onChange={(e) => updateNestedConfig('destination', 'local', 'path', e.target.value)}
                placeholder="/path/to/archive"
              />
            </div>
          )}

          {config.destination.type === 'ssh' && (
            <div className="form-row">
              <div className="form-group">
                <label>Host</label>
                <input 
                  type="text"
                  value={config.destination.ssh.host}
                  onChange={(e) => updateNestedConfig('destination', 'ssh', 'host', e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Username</label>
                <input 
                  type="text"
                  value={config.destination.ssh.user}
                  onChange={(e) => updateNestedConfig('destination', 'ssh', 'user', e.target.value)}
                />
              </div>
              <div className="form-group">
                <label>Remote Path</label>
                <input 
                  type="text"
                  value={config.destination.ssh.remote_path}
                  onChange={(e) => updateNestedConfig('destination', 'ssh', 'remote_path', e.target.value)}
                />
              </div>
            </div>
          )}
        </div>

        {/* API Keys */}
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Metadata Providers</h2>
          </div>

          <div className="form-group">
            <label>TMDB API Key</label>
            <input 
              type="password"
              value={config.metadata.api_keys.tmdb}
              onChange={(e) => {
                const newKeys = { ...config.metadata.api_keys, tmdb: e.target.value }
                updateConfig('metadata', 'api_keys', newKeys)
              }}
              placeholder="Get from themoviedb.org/settings/api"
            />
            <small style={{ color: 'var(--text-muted)' }}>
              Used for movie posters and metadata
            </small>
          </div>

          <div className="form-group">
            <label>OMDB API Key</label>
            <input 
              type="password"
              value={config.metadata.api_keys.omdb}
              onChange={(e) => {
                const newKeys = { ...config.metadata.api_keys, omdb: e.target.value }
                updateConfig('metadata', 'api_keys', newKeys)
              }}
              placeholder="Get from omdbapi.com/apikey.aspx"
            />
            <small style={{ color: 'var(--text-muted)' }}>
              Backup metadata provider
            </small>
          </div>
        </div>

        {/* System */}
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">System</h2>
          </div>

          <div className="form-group">
            <label>DVD Device Path</label>
            <input 
              type="text"
              value={config.dvd_device}
              onChange={(e) => setConfig({ ...config, dvd_device: e.target.value })}
              placeholder="/dev/sr0"
            />
          </div>
        </div>

        <div style={{ display: 'flex', gap: 12 }}>
          <button 
            type="submit" 
            className="btn btn-primary"
            disabled={saving}
          >
            {saving ? 'Saving...' : 'Save Configuration'}
          </button>
          <button 
            type="button" 
            className="btn btn-secondary"
            onClick={fetchConfig}
          >
            Reset
          </button>
        </div>
      </form>
    </div>
  )
}

export default ConfigPanel
