import React, { useState, useEffect } from 'react'
import { api } from '../App'

function Dashboard() {
  const [stats, setStats] = useState(null)
  const [driveStatus, setDriveStatus] = useState(null)
  const [activeJobs, setActiveJobs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchData()
    const interval = setInterval(fetchData, 5000) // Refresh every 5 seconds
    return () => clearInterval(interval)
  }, [])

  const fetchData = async () => {
    try {
      const [statsRes, driveRes, jobsRes] = await Promise.all([
        api.get('/stats'),
        api.get('/drive/status'),
        api.get('/jobs')
      ])
      setStats(statsRes.data)
      setDriveStatus(driveRes.data)
      setActiveJobs(jobsRes.data)
    } catch (err) {
      console.error('Failed to fetch dashboard data:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleEject = async () => {
    try {
      await api.post('/drive/eject')
      fetchData()
    } catch (err) {
      const errorMsg = err.response?.data?.detail || 'Failed to eject drive'
      alert(errorMsg)
    }
  }

  const handleStartRip = async () => {
    try {
      await api.post('/jobs')
      fetchData()
    } catch (err) {
      alert('Failed to start rip job')
    }
  }

  if (loading) return <div className="loading">Loading dashboard...</div>

  return (
    <div>
      <h1>Dashboard</h1>

      {/* Stats */}
      {stats && (
        <div className="stats-grid">
          <div className="stat-card">
            <div className="stat-value">{stats.library.total_dvds}</div>
            <div className="stat-label">DVDs in Library</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{stats.library.total_size_gb}</div>
            <div className="stat-label">GB Archived</div>
          </div>
          <div className="stat-card">
            <div className="stat-value">{activeJobs.length}</div>
            <div className="stat-label">Active Jobs</div>
          </div>
        </div>
      )}

      {/* Drive Status */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">DVD Drive</h2>
          <div style={{ display: 'flex', gap: 8 }}>
            {driveStatus?.has_disc && (
              <button className="btn btn-primary" onClick={handleStartRip}>
                Start Ripping
              </button>
            )}
            <button className="btn btn-secondary" onClick={handleEject}>
              Eject
            </button>
          </div>
        </div>

        <div className="drive-status">
          <div className={`drive-status-indicator ${driveStatus?.has_disc ? 'loaded' : ''}`} />
          <div>
            <strong>
              {driveStatus?.status === 'loaded' 
                ? 'DVD Inserted' 
                : driveStatus?.status === 'empty' 
                  ? 'No Disc' 
                  : 'Unknown'}
            </strong>
            {driveStatus?.disc_info?.disc_name && (
              <div style={{ color: 'var(--text-muted)', fontSize: '0.9rem' }}>
                {driveStatus.disc_info.disc_name}
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Active Jobs */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Active Jobs</h2>
        </div>

        {activeJobs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📀</div>
            <p>No active jobs. Insert a DVD to start ripping.</p>
          </div>
        ) : (
          activeJobs.map(job => (
            <div key={job.id} style={{ marginBottom: 16 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                <span>{job.source_disc_title || 'Unknown Disc'}</span>
                <span className={`badge badge-${
                  job.status === 'error' ? 'error' : 
                  job.status === 'completed' ? 'success' : 'info'
                }`}>
                  {job.status}
                </span>
              </div>
              <div className="progress-container">
                <div 
                  className="progress-bar" 
                  style={{ width: `${job.progress_percent}%` }}
                >
                  {job.progress_percent}%
                </div>
              </div>
              <div style={{ fontSize: '0.85rem', color: 'var(--text-muted)', marginTop: 4 }}>
                {job.current_step}
              </div>
            </div>
          ))
        )}
      </div>

      {/* Recent Activity */}
      <div className="card">
        <div className="card-header">
          <h2 className="card-title">Recent Activity</h2>
        </div>
        <p style={{ color: 'var(--text-muted)' }}>
          Recent ripping activity will appear here.
        </p>
      </div>
    </div>
  )
}

export default Dashboard
