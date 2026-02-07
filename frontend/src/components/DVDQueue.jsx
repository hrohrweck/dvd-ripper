import React, { useState, useEffect } from 'react'
import { api } from '../App'

function DVDQueue() {
  const [jobs, setJobs] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    fetchJobs()
    const interval = setInterval(fetchJobs, 3000)
    return () => clearInterval(interval)
  }, [])

  const fetchJobs = async () => {
    try {
      const response = await api.get('/jobs', { params: { status: 'all' } })
      setJobs(response.data)
    } catch (err) {
      console.error('Failed to fetch jobs:', err)
    } finally {
      setLoading(false)
    }
  }

  const handleCancel = async (jobId) => {
    if (!confirm('Are you sure you want to cancel this job?')) return
    
    try {
      await api.delete(`/jobs/${jobId}`)
      fetchJobs()
    } catch (err) {
      alert('Failed to cancel job')
    }
  }

  const getStatusBadge = (status) => {
    const statusMap = {
      'queued': 'info',
      'ripping': 'warning',
      'transcoding': 'warning',
      'fetching_metadata': 'info',
      'archiving': 'warning',
      'completed': 'success',
      'error': 'error',
      'cancelled': 'error'
    }
    return statusMap[status] || 'info'
  }

  const formatDate = (isoString) => {
    if (!isoString) return '-'
    return new Date(isoString).toLocaleString()
  }

  const formatDuration = (start, end) => {
    if (!start) return '-'
    const startDate = new Date(start)
    const endDate = end ? new Date(end) : new Date()
    const diff = Math.floor((endDate - startDate) / 1000)
    
    const hours = Math.floor(diff / 3600)
    const minutes = Math.floor((diff % 3600) / 60)
    const seconds = diff % 60
    
    if (hours > 0) return `${hours}h ${minutes}m`
    if (minutes > 0) return `${minutes}m ${seconds}s`
    return `${seconds}s`
  }

  if (loading) return <div className="loading">Loading queue...</div>

  return (
    <div>
      <h1>Rip Queue</h1>

      <div className="card">
        <div className="card-header">
          <h2 className="card-title">All Jobs</h2>
          <button className="btn btn-secondary" onClick={fetchJobs}>
            Refresh
          </button>
        </div>

        {jobs.length === 0 ? (
          <div className="empty-state">
            <div className="empty-state-icon">📋</div>
            <p>No jobs in queue.</p>
          </div>
        ) : (
          <table className="table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Title</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Started</th>
                <th>Duration</th>
                <th>Actions</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map(job => (
                <tr key={job.id}>
                  <td>#{job.id}</td>
                  <td>{job.source_disc_title || 'Unknown'}</td>
                  <td>
                    <span className={`badge badge-${getStatusBadge(job.status)}`}>
                      {job.status}
                    </span>
                  </td>
                  <td>
                    {job.status === 'ripping' || job.status === 'transcoding' ? (
                      <div className="progress-container" style={{ height: 20, width: 150 }}>
                        <div 
                          className="progress-bar" 
                          style={{ width: `${job.progress_percent}%` }}
                        >
                          {job.progress_percent}%
                        </div>
                      </div>
                    ) : (
                      '-'
                    )}
                  </td>
                  <td>{formatDate(job.started_at)}</td>
                  <td>{formatDuration(job.started_at, job.completed_at)}</td>
                  <td>
                    {!['completed', 'error', 'cancelled'].includes(job.status) && (
                      <button 
                        className="btn btn-danger"
                        style={{ padding: '6px 12px', fontSize: '0.85rem' }}
                        onClick={() => handleCancel(job.id)}
                      >
                        Cancel
                      </button>
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>

      {/* Job Details */}
      {jobs.filter(j => j.error_message).length > 0 && (
        <div className="card">
          <div className="card-header">
            <h2 className="card-title">Error Log</h2>
          </div>
          {jobs
            .filter(j => j.error_message)
            .map(job => (
              <div key={job.id} style={{ marginBottom: 16, padding: 16, background: 'var(--bg)', borderRadius: 8 }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}>
                  <strong>Job #{job.id} - {job.source_disc_title || 'Unknown'}</strong>
                  <span className="badge badge-error">{job.status}</span>
                </div>
                <code style={{ color: 'var(--error)', fontSize: '0.9rem' }}>
                  {job.error_message}
                </code>
              </div>
            ))}
        </div>
      )}
    </div>
  )
}

export default DVDQueue
